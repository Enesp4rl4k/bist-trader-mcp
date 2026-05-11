"""Takasbank — VIOP daily aggregate margin snapshot.

What we publish
---------------
Takasbank renders a public VIOP statistics dashboard at
`https://www.takasbank.com.tr/tr/istatistikler/
 vadeli-islem-ve-opsiyon-piyasasi-viop/vadeli-islem-ve-opsiyon-piyasasi`
that shows the marketwide aggregate margin state of the day:
    - Teminatlı Hesap Sayısı   (# of margined accounts)
    - İşlem Teminatı           (transaction margin, cash + non-cash)
    - Garanti Fonu Teminatı    (guarantee fund, cash + non-cash)
    - Teminat Tamamlama Çağrısı  ← marketwide margin call total
    - Bulunması Gereken Teminat  ← required margin

This is the actual stress signal a desk monitors: a jump in the margin
call total / required margin ratio means brokers are pulling collateral
from their clients in size.

Per-contract SPAN parameters (initial / maintenance margin per VIOP
contract) live in a separate ZIP/Excel file pipeline that this v0.1
release does not yet automate — that's tracked for v0.3.

Why this code is so defensive
-----------------------------
Takasbank serves the dashboard behind an F5 BIG-IP TSPD WAF that:
    1. Rejects naive HTTP requests with a "Request Rejected" page.
    2. Detects headless Chromium fingerprints (we counter with
       `playwright-stealth`).
    3. Rate-limits per IP after ~5-10 probes within a short window.
The data updates only once per trading day, so we cache the parsed
snapshot for 6 hours by default. With cache hits the WAF never sees
a request.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from ._browser import BrowserCallError, extract_page_data, playwright_available
from ._cache import cache_get, cache_set
from ._wip import wip_error
from .http_utils import SourceError

TAKASBANK_HOME_URL = "https://www.takasbank.com.tr/tr"
TAKASBANK_VIOP_DASHBOARD_URL = (
    "https://www.takasbank.com.tr/tr/istatistikler/"
    "vadeli-islem-ve-opsiyon-piyasasi-viop/"
    "vadeli-islem-ve-opsiyon-piyasasi"
)

# Daily data — refresh at most every 6 hours.
DEFAULT_CACHE_TTL_SECONDS = 6 * 3600

# Anchor text used to confirm the page rendered before we extract.
_RENDER_ANCHOR_TEXT = "Teminat Tamamlama Çağrısı"


# JS extractor: find each label element by exact innerText match, then
# take its nextElementSibling — that's where Takasbank's React layout
# puts the numeric value. Confirmed empirically against the live DOM.
_EXTRACTOR_JS = r"""
const SIMPLE_LABELS = [
  ['teminatli_hesap_sayisi',         'Teminatlı Hesap Sayısı'],
  ['teminat_tamamlama_cagrisi',      'Teminat Tamamlama Çağrısı'],
  ['bulunmasi_gereken_teminat',      'Bulunması Gereken Teminat'],
  ['kar_zarar_tutari',               'Kar / Zarar Tutarı (TL)'],
  ['futures_islem_hacmi',            'Vadeli İşlem Sözleşmesi İşlem Hacmi (TL)'],
  ['opsiyon_islem_hacmi',            'Opsiyon İşlem Hacmi (TL)'],
  ['opsiyon_prim_hacmi',             'Opsiyon Prim Hacmi (TL)'],
  ['futures_acik_pozisyon_adet',     'Vadeli İşlem Sözleşmesi Açık Pozisyon (Adet)'],
  ['futures_acik_pozisyon_deger',    'Vadeli İşlem Sözleşmesi Açık Pozisyon Değeri (TL)'],
  ['opsiyon_acik_pozisyon_adet',     'Opsiyon Açık Pozisyon (Adet)'],
  ['opsiyon_acik_pozisyon_deger',    'Opsiyon Açık Pozisyon Değeri (TL)'],
];

// Compound labels whose sibling cell holds tab-separated key:value pairs
// (e.g. "Yerli:\\n110.702\\tYabancı:\\n577\\tToplam:\\n111.279").
const COMPOUND_LABELS = [
  ['teminatli_hesap_bireysel',  'Teminatlı Hesap Sayısı - Bireysel'],
  ['teminatli_hesap_kurumsal',  'Teminatlı Hesap Sayısı - Kurumsal'],
  ['islem_teminati',            'İşlem Teminatı (TL)'],
  ['garanti_fonu_teminati',     'Garanti Fonu Teminatı (TL)'],
];

const allEls = Array.from(document.body.querySelectorAll('*'));

function findLabelEl(label) {
  return allEls.find(e => (e.innerText || '').trim() === label);
}

function siblingText(el) {
  const s = el && el.nextElementSibling;
  return s ? (s.innerText || '').trim() : null;
}

function parseCompound(txt) {
  // Input: "Yerli:\n110.702\tYabancı:\n577\tToplam:\n111.279"
  //     or "Nakit:\n171.946.126.497,75\tNakit Dışı:\n20.231.162.015,57"
  if (!txt) return null;
  const out = {};
  // Split on tabs, then within each chunk split on first \\n to get key/value.
  const chunks = txt.split(/\t/);
  for (const chunk of chunks) {
    const idx = chunk.indexOf('\n');
    if (idx < 0) continue;
    let key = chunk.slice(0, idx).trim().replace(/:$/, '');
    const value = chunk.slice(idx + 1).trim();
    // Slugify the Turkish keys.
    key = key
      .toLowerCase()
      .replace(/ş/g, 's').replace(/ı/g, 'i').replace(/ç/g, 'c')
      .replace(/ğ/g, 'g').replace(/ü/g, 'u').replace(/ö/g, 'o')
      .replace(/[^a-z0-9]+/g, '_').replace(/^_|_$/g, '');
    if (key) out[key] = value;
  }
  return Object.keys(out).length ? out : null;
}

const result = {};
for (const [key, label] of SIMPLE_LABELS) {
  const el = findLabelEl(label);
  result[key] = el ? siblingText(el) : null;
}
for (const [key, label] of COMPOUND_LABELS) {
  const el = findLabelEl(label);
  const sib = siblingText(el);
  result[key] = sib ? parseCompound(sib) : null;
}
result['_as_of'] = new Date().toISOString();
return result;
"""


@dataclass
class VIOPMarginSnapshot:
    """One day's marketwide VIOP margin + activity snapshot from Takasbank.

    Numeric fields are in TL unless noted. Account counts are integers.
    Compound fields preserve the bireysel/kurumsal × yerli/yabancı break-
    down because that's how Takasbank publishes it.
    """
    as_of: str

    # Margin call & risk
    margined_account_count: int | None
    margined_account_bireysel: dict[str, float | None] | None
    margined_account_kurumsal: dict[str, float | None] | None
    transaction_margin: dict[str, float | None] | None      # nakit / nakit_disi
    guarantee_fund_margin: dict[str, float | None] | None   # nakit / nakit_disi
    margin_call_total: float | None
    required_margin_total: float | None
    profit_loss_total: float | None

    # VIOP activity
    futures_volume_tl: float | None
    options_volume_tl: float | None
    options_premium_volume_tl: float | None
    futures_oi_count: int | None
    futures_oi_value_tl: float | None
    options_oi_count: int | None
    options_oi_value_tl: float | None


def _to_number(raw: str | None) -> float | None:
    """Parse Turkish-formatted numbers (1.234.567,89) into float."""
    if not raw:
        return None
    clean = raw.strip().replace(".", "").replace(",", ".")
    try:
        return float(clean)
    except (TypeError, ValueError):
        return None


def _to_int(raw: str | None) -> int | None:
    f = _to_number(raw)
    if f is None:
        return None
    try:
        return int(f)
    except (TypeError, ValueError):
        return None


async def fetch_viop_margin_snapshot(
    *,
    use_cache: bool = True,
    cache_ttl_seconds: int = DEFAULT_CACHE_TTL_SECONDS,
    headless: bool = True,
) -> VIOPMarginSnapshot:
    """Scrape the live VIOP aggregate margin snapshot from Takasbank.

    Args:
        use_cache: If True (default), serve from disk cache when fresh.
        cache_ttl_seconds: TTL for cache hits (default 6 hours).
        headless: Set False only to debug WAF challenges manually.
    """
    if not playwright_available():
        raise wip_error(
            "takasbank",
            "Playwright not installed — `pip install bist-trader-mcp[browser]` "
            "+ `python -m playwright install chromium`.",
        )

    cache_key = "takasbank.viop_margin_snapshot"
    if use_cache:
        cached = cache_get(cache_key, ttl_seconds=cache_ttl_seconds)
        if cached:
            return _snapshot_from_dict(cached)

    try:
        raw = await extract_page_data(
            page_url=TAKASBANK_VIOP_DASHBOARD_URL,
            extractor_js=_EXTRACTOR_JS,
            warmup_url=TAKASBANK_HOME_URL,
            wait_for_text=_RENDER_ANCHOR_TEXT,
            wait_after_nav_ms=2_500,
            use_stealth=True,
            headless=headless,
        )
    except BrowserCallError as e:
        raise SourceError("takasbank", str(e)) from e

    if not isinstance(raw, dict):
        raise SourceError("takasbank", f"unexpected extractor output: {type(raw)}")

    def _compound(raw_d: Any) -> dict[str, float | None] | None:
        if not isinstance(raw_d, dict):
            return None
        return {k: _to_number(v) for k, v in raw_d.items()}

    snap = VIOPMarginSnapshot(
        as_of=str(raw.get("_as_of") or datetime.utcnow().isoformat()),
        margined_account_count=_to_int(raw.get("teminatli_hesap_sayisi")),
        margined_account_bireysel=_compound(raw.get("teminatli_hesap_bireysel")),
        margined_account_kurumsal=_compound(raw.get("teminatli_hesap_kurumsal")),
        transaction_margin=_compound(raw.get("islem_teminati")),
        guarantee_fund_margin=_compound(raw.get("garanti_fonu_teminati")),
        margin_call_total=_to_number(raw.get("teminat_tamamlama_cagrisi")),
        required_margin_total=_to_number(raw.get("bulunmasi_gereken_teminat")),
        profit_loss_total=_to_number(raw.get("kar_zarar_tutari")),
        futures_volume_tl=_to_number(raw.get("futures_islem_hacmi")),
        options_volume_tl=_to_number(raw.get("opsiyon_islem_hacmi")),
        options_premium_volume_tl=_to_number(raw.get("opsiyon_prim_hacmi")),
        futures_oi_count=_to_int(raw.get("futures_acik_pozisyon_adet")),
        futures_oi_value_tl=_to_number(raw.get("futures_acik_pozisyon_deger")),
        options_oi_count=_to_int(raw.get("opsiyon_acik_pozisyon_adet")),
        options_oi_value_tl=_to_number(raw.get("opsiyon_acik_pozisyon_deger")),
    )
    cache_set(cache_key, _snapshot_to_dict(snap), ttl_seconds=cache_ttl_seconds)
    return snap


def _snapshot_to_dict(snap: VIOPMarginSnapshot) -> dict[str, Any]:
    return {
        "as_of": snap.as_of,
        "margined_account_count": snap.margined_account_count,
        "margined_account_bireysel": snap.margined_account_bireysel,
        "margined_account_kurumsal": snap.margined_account_kurumsal,
        "transaction_margin": snap.transaction_margin,
        "guarantee_fund_margin": snap.guarantee_fund_margin,
        "margin_call_total": snap.margin_call_total,
        "required_margin_total": snap.required_margin_total,
        "profit_loss_total": snap.profit_loss_total,
        "futures_volume_tl": snap.futures_volume_tl,
        "options_volume_tl": snap.options_volume_tl,
        "options_premium_volume_tl": snap.options_premium_volume_tl,
        "futures_oi_count": snap.futures_oi_count,
        "futures_oi_value_tl": snap.futures_oi_value_tl,
        "options_oi_count": snap.options_oi_count,
        "options_oi_value_tl": snap.options_oi_value_tl,
    }


def _snapshot_from_dict(d: dict[str, Any]) -> VIOPMarginSnapshot:
    def _f(k: str) -> float | None:
        return _to_float_safe(d.get(k))

    def _i(k: str) -> int | None:
        return _to_int_safe(d.get(k))

    def _c(k: str) -> dict[str, float | None] | None:
        v = d.get(k)
        if not isinstance(v, dict):
            return None
        return {key: _to_float_safe(val) for key, val in v.items()}

    return VIOPMarginSnapshot(
        as_of=str(d.get("as_of", "")),
        margined_account_count=_i("margined_account_count"),
        margined_account_bireysel=_c("margined_account_bireysel"),
        margined_account_kurumsal=_c("margined_account_kurumsal"),
        transaction_margin=_c("transaction_margin"),
        guarantee_fund_margin=_c("guarantee_fund_margin"),
        margin_call_total=_f("margin_call_total"),
        required_margin_total=_f("required_margin_total"),
        profit_loss_total=_f("profit_loss_total"),
        futures_volume_tl=_f("futures_volume_tl"),
        options_volume_tl=_f("options_volume_tl"),
        options_premium_volume_tl=_f("options_premium_volume_tl"),
        futures_oi_count=_i("futures_oi_count"),
        futures_oi_value_tl=_f("futures_oi_value_tl"),
        options_oi_count=_i("options_oi_count"),
        options_oi_value_tl=_f("options_oi_value_tl"),
    )


def _to_float_safe(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _to_int_safe(v: Any) -> int | None:
    f = _to_float_safe(v)
    return int(f) if f is not None else None


# ---------------------------------------------------------------------------
# Legacy per-contract surface — still WIP (SPAN parameter files not wired).
# ---------------------------------------------------------------------------

@dataclass
class MarginParameter:
    contract_code: str
    underlying: str | None
    trade_date: str
    initial_margin: float | None
    maintenance_margin: float | None
    price_scan_range: float | None
    spread_credit: float | None
    initial_margin_prev: float | None
    pct_change_initial: float | None


async def fetch_margin_parameters(
    trade_date: date | str | None = None,
    underlying_filter: str | None = None,
    only_changed: bool = False,
) -> list[MarginParameter]:
    """Per-contract initial/maintenance margin per VIOP product.

    v0.1.2 STATUS: still WIP. Per-contract SPAN parameters are published
    by Takasbank as a separate downloadable Excel/ZIP file pipeline that
    we have not yet automated (the dashboard above is aggregated only).
    The high-level `fetch_viop_margin_snapshot` covers the marketwide
    margin-call signal that most users actually want; per-contract
    parameters will land in v0.3 once we identify the SPAN file URL.
    """
    raise wip_error(
        "takasbank",
        f"per-contract SPAN parameters: trade_date={trade_date} "
        f"underlying={underlying_filter} only_changed={only_changed} "
        "(aggregate snapshot is available via get_viop_dashboard / "
        "get_viop_margin_call_alerts)",
    )


async def fetch_margin_change_alerts(
    trade_date: date | str | None = None,
    threshold_pct: float = 5.0,
) -> list[MarginParameter]:
    """v0.1.2 STATUS: still WIP for per-contract; see fetch_margin_parameters."""
    raise wip_error(
        "takasbank",
        f"per-contract change alerts: trade_date={trade_date} "
        f"threshold={threshold_pct} (use get_viop_dashboard for the "
        "marketwide margin-call total instead)",
    )


def _coerce(value: date | str) -> date:
    if isinstance(value, date):
        return value
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d.%m.%Y"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    raise SourceError("takasbank", f"bad date: {value!r}")


__all__ = [
    "VIOPMarginSnapshot",
    "fetch_viop_margin_snapshot",
    "MarginParameter",
    "fetch_margin_parameters",
    "fetch_margin_change_alerts",
]

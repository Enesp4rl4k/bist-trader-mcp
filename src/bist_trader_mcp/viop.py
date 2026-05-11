"""VIOP (Vadeli İşlem ve Opsiyon Piyasası) live snapshot fetcher.

Source: İş Yatırım's `viop.aspx` page, which is a publicly accessible
HTML page that lists every actively trading VIOP contract along with
its last price, daily % change, absolute change, TL volume and open
interest. No auth, no WAF — a clean plain HTTP scrape.

Why this source and not the official Borsa İstanbul or Takasbank pages:
    - BIST's `datastore.borsaistanbul.com` data is paid (subscription).
    - Takasbank's per-contract margin file is gated behind their portal.
    - The Borsa derivatives bulletin page (`turev-piyasasi-...`) doesn't
      render contract-level data for anonymous clients (no XHR fires).
    - İş Yatırım renders the full 480+ contract table server-side and
      community libraries (borsapy, isyatirimhisse) already validate
      it as the de-facto free source for Turkish derivatives quotes.

Schema (verified live 2026-05-11, 484 contracts):
    <td title="<CODE> | <description>">
        td[0]: contract name (e.g. "CIMSA Haziran 2026 Vadeli")
        td[1]: last price            (Turkish-formatted, e.g. "60,1700")
        td[2]: percent change        (e.g. "-1,55")
        td[3]: absolute change       (e.g. "-0,9500")
        td[4]: volume TL             (e.g. "3.932.186")
        td[5]: open interest / count (e.g. "646")

Contract code format on İş Yatırım: `F_<UNDERLYING><MM><YY>` for futures
and `O_<UNDERLYING><MM><YY>_<C|P><STRIKE>` for options. This is the same
canonical VIOP code used elsewhere.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

import httpx

from ._cache import cache_get, cache_set
from .http_utils import USER_AGENT, SourceError

VIOP_PAGE_URL = "https://www.isyatirim.com.tr/tr-tr/analiz/Sayfalar/viop.aspx"
DEFAULT_CACHE_TTL_SECONDS = 60 * 60   # snapshot data, 1 h is plenty


@dataclass
class VIOPContract:
    contract_code: str       # e.g. F_XU0300625
    underlying: str          # e.g. XU030
    contract_type: str       # "future" | "option"
    expiry_year: int
    expiry_month: int
    option_strike: float | None
    option_right: str | None  # "C" | "P" | None


@dataclass
class VIOPSettlement:
    """One row from the live İş Yatırım VIOP snapshot."""
    contract: VIOPContract
    trade_date: str           # YYYY-MM-DD (date of the snapshot)
    name: str
    last_price: float | None
    percent_change: float | None
    absolute_change: float | None
    volume_tl: float | None
    open_interest: int | None
    # Settlement / reference price aren't exposed by this source. They are
    # surfaced by Takasbank's overnight feed (separate pipeline); we leave
    # them as None here.
    settle_price: float | None = None
    reference_price: float | None = None
    volume: int | None = None
    high: float | None = None
    low: float | None = None


# Match both futures and options at the start of an İş Yatırım title attr.
CONTRACT_RX = re.compile(
    r"^(?P<kind>[FO])_(?P<underlying>[A-Z0-9]+?)(?P<month>\d{2})(?P<year>\d{2})"
    r"(?:_(?P<right>[CP])(?P<strike>\d+(?:[.,]\d+)?))?$"
)


def parse_contract_code(code: str) -> VIOPContract:
    """Parse a VIOP contract code into its structured form.

    Raises SourceError when the code doesn't match the F_/O_ pattern.
    """
    m = CONTRACT_RX.match(code.strip().upper())
    if not m:
        raise SourceError("viop", f"unparseable contract code: {code}")

    kind = "future" if m.group("kind") == "F" else "option"
    underlying = m.group("underlying")
    month = int(m.group("month"))
    year_yy = int(m.group("year"))
    expiry_year = 2000 + year_yy if year_yy < 70 else 1900 + year_yy
    raw_strike = m.group("strike")
    strike: float | None = None
    if raw_strike:
        try:
            strike = float(raw_strike.replace(",", "."))
        except ValueError:
            strike = None
    right = m.group("right") or None
    return VIOPContract(
        contract_code=code.strip().upper(),
        underlying=underlying,
        contract_type=kind,
        expiry_year=expiry_year,
        expiry_month=month,
        option_strike=strike,
        option_right=right,
    )


def _to_float(raw: str | None) -> float | None:
    """Parse Turkish-formatted numbers (`1.234,56` → `1234.56`)."""
    if raw is None:
        return None
    s = raw.strip()
    if not s or s in {"-", "—", "n/a"}:
        return None
    cleaned = s.replace(".", "").replace(",", ".")
    try:
        return float(cleaned)
    except ValueError:
        return None


def _to_int(raw: str | None) -> int | None:
    val = _to_float(raw)
    if val is None:
        return None
    try:
        return int(val)
    except (TypeError, ValueError):
        return None


def _parse_html(html: str, trade_date: str) -> list[VIOPSettlement]:
    """Extract VIOPSettlement rows from the rendered İş Yatırım page.

    The page uses one `<td title="CODE | description">` cell per row
    followed by numeric td cells with Turkish-formatted values. We use
    BeautifulSoup with lxml backend for speed.
    """
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "lxml")
    out: list[VIOPSettlement] = []
    for tr in soup.select("tr"):
        first_td = tr.find("td", title=True)
        if first_td is None:
            continue
        title = (first_td.get("title") or "").strip()
        if not title or "|" not in title:
            continue
        code = title.split("|", 1)[0].strip()
        try:
            contract = parse_contract_code(code)
        except SourceError:
            continue
        tds = tr.find_all("td")
        if len(tds) < 5:
            continue

        def cell(idx: int, _tds: list = tds) -> str | None:
            if idx >= len(_tds):
                return None
            return _tds[idx].get_text(strip=True) or None

        out.append(
            VIOPSettlement(
                contract=contract,
                trade_date=trade_date,
                name=cell(0) or contract.contract_code,
                last_price=_to_float(cell(1)),
                percent_change=_to_float(cell(2)),
                absolute_change=_to_float(cell(3)),
                volume_tl=_to_float(cell(4)),
                open_interest=_to_int(cell(5)),
            )
        )
    return out


def _fetch_html() -> str:
    try:
        with httpx.Client(
            timeout=30.0,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "tr,en;q=0.7",
            },
            follow_redirects=True,
        ) as client:
            resp = client.get(VIOP_PAGE_URL)
            resp.raise_for_status()
            return resp.text
    except httpx.HTTPError as e:
        raise SourceError("viop", f"İş Yatırım fetch failed: {e}") from e


def _serialise(rows: list[VIOPSettlement]) -> list[dict[str, Any]]:
    return [
        {
            "contract_code": r.contract.contract_code,
            "underlying": r.contract.underlying,
            "contract_type": r.contract.contract_type,
            "expiry_year": r.contract.expiry_year,
            "expiry_month": r.contract.expiry_month,
            "option_strike": r.contract.option_strike,
            "option_right": r.contract.option_right,
            "trade_date": r.trade_date,
            "name": r.name,
            "last_price": r.last_price,
            "percent_change": r.percent_change,
            "absolute_change": r.absolute_change,
            "volume_tl": r.volume_tl,
            "open_interest": r.open_interest,
        }
        for r in rows
    ]


def _deserialise(rows: list[dict[str, Any]]) -> list[VIOPSettlement]:
    out: list[VIOPSettlement] = []
    for r in rows:
        try:
            contract = VIOPContract(
                contract_code=str(r.get("contract_code", "")),
                underlying=str(r.get("underlying", "")),
                contract_type=str(r.get("contract_type", "future")),
                expiry_year=int(r.get("expiry_year", 0)),
                expiry_month=int(r.get("expiry_month", 0)),
                option_strike=(
                    None if r.get("option_strike") is None else float(r["option_strike"])
                ),
                option_right=r.get("option_right"),
            )
        except (TypeError, ValueError):
            continue
        out.append(
            VIOPSettlement(
                contract=contract,
                trade_date=str(r.get("trade_date", "")),
                name=str(r.get("name", "")),
                last_price=r.get("last_price"),
                percent_change=r.get("percent_change"),
                absolute_change=r.get("absolute_change"),
                volume_tl=r.get("volume_tl"),
                open_interest=r.get("open_interest"),
            )
        )
    return out


async def fetch_daily_settlement(
    trade_date: date | str | None = None,
    underlying_filter: str | None = None,
    use_cache: bool = True,
    cache_ttl_seconds: int = DEFAULT_CACHE_TTL_SECONDS,
) -> list[VIOPSettlement]:
    """Fetch all active VIOP contracts as a live snapshot.

    Note: This returns the **live** quote tape from İş Yatırım — last
    price, percent change, volume — not the official Takasbank end-of-
    day settle. Use `get_viop_dashboard` (Takasbank) for the marketwide
    aggregate margin / volume / OI totals.

    Args:
        trade_date: Cosmetic only — used as the `trade_date` stamp on
            each row. Pass None to use today.
        underlying_filter: Limit to one underlying (e.g. "XU030", "USD").
        use_cache: Serve from disk cache if fresh.
        cache_ttl_seconds: Cache lifetime (default 1 h).
    """
    if trade_date is None:
        td = date.today()
    elif isinstance(trade_date, date):
        td = trade_date
    else:
        td = _coerce_date(trade_date)
    iso_date = td.isoformat()

    cache_key = "viop.snapshot"
    payload: list[dict[str, Any]] | None = None
    if use_cache:
        cached = cache_get(cache_key, ttl_seconds=cache_ttl_seconds)
        if isinstance(cached, list):
            payload = cached

    if payload is None:
        html = _fetch_html()
        rows = _parse_html(html, trade_date=iso_date)
        if not rows:
            raise SourceError("viop", "0 rows parsed from İş Yatırım page")
        payload = _serialise(rows)
        cache_set(cache_key, payload, ttl_seconds=cache_ttl_seconds)

    rows = _deserialise(payload)
    if underlying_filter:
        uf = underlying_filter.upper().strip()
        rows = [r for r in rows if r.contract.underlying == uf]
    return rows


async def fetch_term_structure(
    underlying: str,
    as_of: date | str | None = None,
    use_cache: bool = True,
    cache_ttl_seconds: int = DEFAULT_CACHE_TTL_SECONDS,
) -> list[VIOPSettlement]:
    """Futures-only term structure for one underlying, sorted by expiry."""
    settlements = await fetch_daily_settlement(
        trade_date=as_of,
        underlying_filter=underlying,
        use_cache=use_cache,
        cache_ttl_seconds=cache_ttl_seconds,
    )
    futs = [s for s in settlements if s.contract.contract_type == "future"]
    futs.sort(key=lambda s: (s.contract.expiry_year, s.contract.expiry_month))
    return futs


def _coerce_date(value: date | str) -> date:
    if isinstance(value, date):
        return value
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d.%m.%Y"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    raise SourceError("viop", f"bad date: {value!r}")


__all__ = [
    "VIOPContract",
    "VIOPSettlement",
    "VIOP_PAGE_URL",
    "parse_contract_code",
    "fetch_daily_settlement",
    "fetch_term_structure",
]

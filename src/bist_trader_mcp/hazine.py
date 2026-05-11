"""Hazine — DİBS auction calendar via the quarterly strategy PDF.

The Turkish Treasury publishes a quarterly "İç Borçlanma Stratejisi"
PDF that contains, per month, every scheduled DİBS auction with:

    İhale Tarihi (auction date)  |  Valör Tarihi (settlement)
    İtfa Tarihi  (maturity)      |  Senet Türü   (instrument)
    Vadesi       (tenor)         |  İhraç Yöntemi (method)

The PDF is a stable, well-formatted Treasury document — no WAF, no JS.
We download it via httpx, extract page text with pdfplumber, and parse
each auction row with a tight regex.

URL discovery
-------------
The current quarterly PDF lives at:
    https://ms.hmb.gov.tr/uploads/<YYYY>/<MM>/Tr<NN>-<Month1>-<Year>
    -<Month2>-<Year>-Ic-Borclanma-Stratejisi-<hash>.pdf

The trailing hash is unpredictable and the public navigation pages don't
expose the strategy PDFs reliably. v0.1 ships a small manual registry of
known URLs and lets callers override `pdf_url=` to point at a fresher
file once one is published; v0.3 will add a discovery scraper.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

import httpx

from ._cache import cache_get, cache_set
from .http_utils import USER_AGENT, SourceError


# v0.1 registry — append the latest known strategy URL on each release.
# Indexed by the calendar starting month so we can pick the most recent
# document covering the user's date window.
QUARTERLY_STRATEGY_URLS: dict[str, str] = {
    "2026-01": (
        "https://ms.hmb.gov.tr/uploads/2025/12/"
        "Tr01-Ocak-Mart-2026-Ic-Borclanma-Stratejisi-"
        "f3a8bbd23a879490.pdf"
    ),
}

DEFAULT_CACHE_TTL_SECONDS = 24 * 3600   # the PDF changes at most monthly


@dataclass
class DIBSAuction:
    auction_id: str | None
    auction_date: str            # YYYY-MM-DD
    settlement_date: str | None
    maturity_date: str | None
    instrument: str
    tenor_days: int | None
    tenor_label: str | None
    issuance_method: str | None
    status: str                  # "scheduled" | "completed" | "cancelled"
    coupon_frequency: str | None
    avg_yield_pct: float | None
    cut_off_yield_pct: float | None
    bid_amount: float | None
    accepted_amount: float | None
    bid_to_cover: float | None


# Regex tuned against the Ocak-Mart 2026 PDF. Each scheduled auction line
# looks like (text-extracted):
#   "DD.MM.YYYY DD.MM.YYYY DD.MM.YYYY <Instrument …> <N>Yıl/Ay / <N> Gün <Method>"
# where the three dates are auction / settlement / maturity, and the
# remaining tokens form the instrument label + tenor + method.
_AUCTION_LINE_RX = re.compile(
    r"""^
    \s*(?P<auction>\d{1,2}\.\d{1,2}\.\d{4})\s+
    (?P<settlement>\d{1,2}\.\d{1,2}\.\d{4})\s+
    (?P<maturity>\d{1,2}\.\d{1,2}\.\d{4})\s+
    (?P<rest>.+)$
    """,
    re.VERBOSE,
)

_TENOR_RX = re.compile(
    r"""
    (?P<tenor_label>\d+\s*(?:Yıl|Ay|Hafta|Gün))
    \s*/\s*
    (?P<days>\d+)\s*Gün
    """,
    re.VERBOSE,
)


def _iso(date_tr: str) -> str | None:
    try:
        return datetime.strptime(date_tr.strip(), "%d.%m.%Y").date().isoformat()
    except ValueError:
        return None


def _parse_pdf_text(text: str) -> list[DIBSAuction]:
    """Walk text line by line, emit DIBSAuction per matching auction row.

    The strategy PDF wraps an auction across two visual lines when a
    coupon-frequency note follows. We attach trailing coupon notes to
    the prior auction's `coupon_frequency` field.
    """
    auctions: list[DIBSAuction] = []
    last: DIBSAuction | None = None

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        m = _AUCTION_LINE_RX.match(line)
        if not m:
            if last and (
                ("kupon" in line.lower())
                or ("kira" in line.lower() and "ödemeli" in line.lower())
            ):
                last.coupon_frequency = line
            continue

        auction_iso = _iso(m.group("auction"))
        if auction_iso is None:
            continue

        rest = m.group("rest").strip()
        tenor_match = _TENOR_RX.search(rest)
        tenor_days: int | None = None
        tenor_label: str | None = None
        method: str | None = None

        if tenor_match:
            tenor_days = int(tenor_match.group("days"))
            tenor_label = tenor_match.group("tenor_label").replace(" ", "")
            instrument = rest[: tenor_match.start()].strip()
            method = rest[tenor_match.end():].strip() or None
        else:
            instrument = rest

        last = DIBSAuction(
            auction_id=None,
            auction_date=auction_iso,
            settlement_date=_iso(m.group("settlement")),
            maturity_date=_iso(m.group("maturity")),
            instrument=instrument,
            tenor_days=tenor_days,
            tenor_label=tenor_label,
            issuance_method=method,
            status="scheduled",
            coupon_frequency=None,
            avg_yield_pct=None,
            cut_off_yield_pct=None,
            bid_amount=None,
            accepted_amount=None,
            bid_to_cover=None,
        )
        auctions.append(last)

    return auctions


def _pick_strategy_url(reference: date) -> str:
    """Return the strategy URL covering `reference`, falling back to the
    nearest earlier published quarter."""
    if not QUARTERLY_STRATEGY_URLS:
        raise SourceError("hazine", "no strategy URL registered in registry")

    ref_key = reference.strftime("%Y-%m")
    sorted_keys = sorted(QUARTERLY_STRATEGY_URLS.keys())
    chosen = sorted_keys[0]
    for k in sorted_keys:
        if k <= ref_key:
            chosen = k
        else:
            break
    return QUARTERLY_STRATEGY_URLS[chosen]


def _download_pdf(url: str) -> bytes:
    try:
        with httpx.Client(
            timeout=30.0, headers={"User-Agent": USER_AGENT, "Accept": "*/*"}
        ) as client:
            resp = client.get(url, follow_redirects=True)
            resp.raise_for_status()
            return resp.content
    except httpx.HTTPError as e:
        raise SourceError("hazine", f"PDF download failed: {e}") from e


def _extract_pdf_text(content: bytes) -> str:
    import pdfplumber  # lazy import — keeps `import bist_trader_mcp` fast

    out: list[str] = []
    with pdfplumber.open(io.BytesIO(content)) as pdf:
        for page in pdf.pages:
            t = page.extract_text() or ""
            if t:
                out.append(t)
    return "\n".join(out)


async def fetch_auctions(
    since: date | str | None = None,
    until: date | str | None = None,
    status: str | None = None,
    pdf_url: str | None = None,
    use_cache: bool = True,
    cache_ttl_seconds: int = DEFAULT_CACHE_TTL_SECONDS,
) -> list[DIBSAuction]:
    """Return the DİBS auction calendar within a date window.

    Args:
        since: lower bound for auction_date (default 30 days ago).
        until: upper bound (default +90 days).
        status: optional filter — "scheduled" | "completed" | "cancelled".
        pdf_url: override which strategy PDF to parse. Falls back to the
            registered current quarter.
        use_cache: serve from disk cache when fresh.
        cache_ttl_seconds: cache lifetime (default 24h).
    """
    since_date = _coerce(since) if since else date.today() - timedelta(days=30)
    until_date = _coerce(until) if until else date.today() + timedelta(days=90)

    url = pdf_url or _pick_strategy_url(reference=date.today())
    cache_key = f"hazine.strategy_pdf:{url}"

    payload: list[dict[str, Any]] | None = None
    if use_cache:
        cached = cache_get(cache_key, ttl_seconds=cache_ttl_seconds)
        if isinstance(cached, list):
            payload = cached

    if payload is None:
        pdf_bytes = _download_pdf(url)
        try:
            text = _extract_pdf_text(pdf_bytes)
        except Exception as e:
            raise SourceError("hazine", f"PDF parse failed: {e}") from e
        parsed = _parse_pdf_text(text)
        payload = [
            {
                "auction_date": a.auction_date,
                "settlement_date": a.settlement_date,
                "maturity_date": a.maturity_date,
                "instrument": a.instrument,
                "tenor_days": a.tenor_days,
                "tenor_label": a.tenor_label,
                "issuance_method": a.issuance_method,
                "status": a.status,
                "coupon_frequency": a.coupon_frequency,
            }
            for a in parsed
        ]
        cache_set(cache_key, payload, ttl_seconds=cache_ttl_seconds)

    out: list[DIBSAuction] = []
    for row in payload:
        try:
            row_date = date.fromisoformat(row["auction_date"])
        except (ValueError, KeyError, TypeError):
            continue
        if row_date < since_date or row_date > until_date:
            continue
        a = DIBSAuction(
            auction_id=None,
            auction_date=row.get("auction_date", ""),
            settlement_date=row.get("settlement_date"),
            maturity_date=row.get("maturity_date"),
            instrument=row.get("instrument", ""),
            tenor_days=row.get("tenor_days"),
            tenor_label=row.get("tenor_label"),
            issuance_method=row.get("issuance_method"),
            status=row.get("status", "scheduled"),
            coupon_frequency=row.get("coupon_frequency"),
            avg_yield_pct=None,
            cut_off_yield_pct=None,
            bid_amount=None,
            accepted_amount=None,
            bid_to_cover=None,
        )
        if status and a.status != status.lower():
            continue
        out.append(a)

    out.sort(key=lambda a: a.auction_date)
    return out


def _coerce(value: date | str) -> date:
    if isinstance(value, date):
        return value
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d.%m.%Y"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    raise SourceError("hazine", f"bad date: {value!r}")


__all__ = [
    "DIBSAuction",
    "QUARTERLY_STRATEGY_URLS",
    "fetch_auctions",
]

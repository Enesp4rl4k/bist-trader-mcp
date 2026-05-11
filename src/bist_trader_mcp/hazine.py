"""Hazine — DİBS auction calendar & results fetcher.

The Turkish Treasury (Hazine ve Maliye Bakanlığı) publishes both:
    1. A forward-looking borrowing / auction calendar — typically updated
       at the start of each month with that month's planned issues.
    2. Auction results — the day after each tender (cut-off rate, demand,
       bid-to-cover, average yield).

We expose both via a single normalised structure and let the caller filter
by date / status. Endpoint pattern follows the JSON used by hazine.gov.tr's
own UI; URLs occasionally move so this module fails defensively.

Caveat: When the API is briefly offline, the canonical fallback is the
monthly borrowing strategy PDF. Parsing that PDF is out of scope for v0.2.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from ._wip import wip_error
from .http_utils import SourceError, fetch_json  # noqa: F401  retained for v0.3

HAZINE_AUCTION_URL = (
    "https://www.hmb.gov.tr/data/dibs/auction-calendar"
)


@dataclass
class DIBSAuction:
    auction_id: str | None
    auction_date: str            # YYYY-MM-DD
    settlement_date: str | None
    instrument: str              # "TL_BOND" | "TL_BILL" | "INFLATION_LINKED" | "SUKUK" | "FX"
    tenor_months: int | None
    coupon_pct: float | None
    status: str                  # "scheduled" | "completed" | "cancelled"
    avg_yield_pct: float | None
    cut_off_yield_pct: float | None
    bid_amount: float | None
    accepted_amount: float | None
    bid_to_cover: float | None


def _to_float(v: Any) -> float | None:
    if v in (None, "", "-"):
        return None
    try:
        return float(str(v).replace(",", "."))
    except (TypeError, ValueError):
        return None


def _to_int(v: Any) -> int | None:
    f = _to_float(v)
    if f is None:
        return None
    try:
        return int(f)
    except (TypeError, ValueError):
        return None


def _iso(value: Any) -> str | None:
    if not value:
        return None
    s = str(value)
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d-%m-%Y", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            continue
    return s[:10] if len(s) >= 10 else s


def _parse(row: dict[str, Any]) -> DIBSAuction | None:
    auction_date = _iso(
        row.get("auctionDate") or row.get("ihaleTarihi")
    )
    if not auction_date:
        return None

    status = (row.get("status") or row.get("durum") or "scheduled").lower()
    if status not in {"scheduled", "completed", "cancelled"}:
        # Map TR labels.
        if "tamam" in status:
            status = "completed"
        elif "iptal" in status:
            status = "cancelled"
        else:
            status = "scheduled"

    bid = _to_float(row.get("bidAmount") or row.get("teklifTutari"))
    accepted = _to_float(row.get("acceptedAmount") or row.get("kabulTutari"))
    btc = (bid / accepted) if (bid and accepted) else None

    return DIBSAuction(
        auction_id=str(row.get("auctionId") or row.get("ihaleId") or "") or None,
        auction_date=auction_date,
        settlement_date=_iso(row.get("settlementDate") or row.get("valor")),
        instrument=str(row.get("instrument") or row.get("kiymet") or "TL_BOND"),
        tenor_months=_to_int(row.get("tenorMonths") or row.get("vade")),
        coupon_pct=_to_float(row.get("couponRate") or row.get("kuponOrani")),
        status=status,
        avg_yield_pct=_to_float(row.get("averageYield") or row.get("ortalamaFaiz")),
        cut_off_yield_pct=_to_float(row.get("cutOffYield") or row.get("kesinFaiz")),
        bid_amount=bid,
        accepted_amount=accepted,
        bid_to_cover=btc,
    )


async def fetch_auctions(
    since: date | str | None = None,
    until: date | str | None = None,
    status: str | None = None,
) -> list[DIBSAuction]:
    """Fetch DİBS auctions in a date window.

    v0.2 STATUS: hmb.gov.tr returns HTML (not JSON) on the URL pattern
    observed; the auction calendar lives as a rendered table or
    downloadable Excel/PDF rather than as a public JSON endpoint.
    Discovery for v0.3 will likely involve parsing the monthly
    borrowing strategy PDF. Parser + dataclass are ready.
    """
    raise wip_error(
        "hazine",
        f"since={since} until={until} status={status}",
    )


def _coerce(value: date | str) -> date:
    if isinstance(value, date):
        return value
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d.%m.%Y"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    raise SourceError("hazine", f"bad date: {value!r}")

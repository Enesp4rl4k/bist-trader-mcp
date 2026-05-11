"""MKK (Merkezi Kayıt Kuruluşu) foreign-ownership fetcher.

MKK publishes a daily breakdown of foreign vs domestic equity ownership for
each BIST-listed company. The historic page exposes per-company free-float
distribution by investor type (resident/foreign, retail/corporate, fund).

This module hits the public "Yatırımcı Profili" / "Pay Sahipliği Yapısı"
JSON used by their UI. Endpoint stability is the main caveat — MKK
periodically reorganises their portal.

Tool surface:
    - fetch_foreign_ownership(ticker, since, until) -> [Daily ratio]
    - fetch_latest_snapshot(tickers) -> dict[ticker -> ratio]

What we return is the **foreign holding ratio of free-float** in percent
(0..100). Total foreign / total shares is also computed when MKK supplies
the underlying counts.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from ._wip import wip_error
from .http_utils import SourceError, fetch_json  # noqa: F401  retained for v0.3

MKK_OWNERSHIP_URL = (
    "https://www.mkk.com.tr/data/foreign-ownership/daily"
)


@dataclass
class ForeignOwnershipPoint:
    ticker: str
    date: str  # YYYY-MM-DD
    foreign_pct_of_freefloat: float | None
    foreign_pct_of_total: float | None
    foreign_investor_count: int | None


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


def _parse_point(ticker: str, row: dict[str, Any]) -> ForeignOwnershipPoint | None:
    d = row.get("date") or row.get("tarih")
    if not d:
        return None
    iso_date: str
    try:
        # Accept either ISO or DD.MM.YYYY.
        if "." in str(d):
            iso_date = datetime.strptime(str(d), "%d.%m.%Y").date().isoformat()
        else:
            iso_date = datetime.fromisoformat(str(d)[:10]).date().isoformat()
    except ValueError:
        return None

    return ForeignOwnershipPoint(
        ticker=ticker,
        date=iso_date,
        foreign_pct_of_freefloat=_to_float(
            row.get("foreignFreeFloatPct") or row.get("yabanciDolasimdakiOran")
        ),
        foreign_pct_of_total=_to_float(
            row.get("foreignTotalPct") or row.get("yabanciToplamOran")
        ),
        foreign_investor_count=_to_int(
            row.get("foreignInvestorCount") or row.get("yabanciYatirimciSayisi")
        ),
    )


async def fetch_foreign_ownership(
    ticker: str,
    since: date | str | None = None,
    until: date | str | None = None,
) -> list[ForeignOwnershipPoint]:
    """Daily foreign-ownership series for one BIST ticker.

    v0.2 STATUS: mkk.com.tr returns HTML rather than JSON on the URL
    pattern observed and probably requires session/captcha for direct
    access. Endpoint discovery is tracked for v0.3 (browser-automated
    fallback). Parser and dataclass are ready.
    """
    raise wip_error(
        "mkk", f"ticker={ticker} since={since} until={until}"
    )


async def fetch_latest_snapshot(
    tickers: list[str],
) -> dict[str, ForeignOwnershipPoint | None]:
    """v0.2 STATUS: blocked on `fetch_foreign_ownership` endpoint discovery."""
    raise wip_error("mkk", f"tickers={tickers}")


def _coerce(value: date | str) -> date:
    if isinstance(value, date):
        return value
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d.%m.%Y"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    raise SourceError("mkk", f"bad date: {value!r}")

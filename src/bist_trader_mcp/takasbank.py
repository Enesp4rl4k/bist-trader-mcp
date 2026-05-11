"""Takasbank — VIOP daily margin / collateral parameters.

Takasbank, as the central counterparty (CCP) for BIST derivatives, publishes
daily risk parameters used to compute initial and maintenance margin for
every active VIOP contract. These drive **margin calls** (teminat tamamlama
çağrısı) when a position's value moves enough that posted collateral falls
below the maintenance level.

What's published daily (public, free):
    - Per-contract `initial_margin` (başlangıç teminatı)
    - Per-contract `maintenance_margin` (sürdürme teminatı)
    - Price scan range (fiyat tarama aralığı)
    - Spread credit / inter-month offset values
    - Cross-margin parameters between underlying pairs

Endpoint stability: Takasbank periodically reorganises their portal; the
exact URL has moved between `takasbank.com.tr/risk-parameters/...` patterns.
This module tries the current observed JSON pattern and surfaces a
structured `SourceError` if the schema drifts so the LLM can react.

Caveat: True "margin call events" (specific traders being called) are NOT
public — that's broker-confidential. What we expose is the **parameter
side**: yesterday's vs today's parameter changes, which is the actual
signal traders watch. A jump in initial margin = the exchange tightened.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from ._wip import wip_error
from .http_utils import SourceError, fetch_json  # noqa: F401  retained for v0.3

TAKASBANK_MARGIN_URL = (
    "https://www.takasbank.com.tr/data/risk-parameters/viop-daily"
)


@dataclass
class MarginParameter:
    contract_code: str
    underlying: str | None
    trade_date: str
    initial_margin: float | None       # başlangıç teminatı (TL)
    maintenance_margin: float | None   # sürdürme teminatı (TL)
    price_scan_range: float | None     # fiyat tarama aralığı
    spread_credit: float | None        # vade içi indirim
    initial_margin_prev: float | None  # önceki günkü, varsa
    pct_change_initial: float | None   # gün-içi değişim %


def _to_float(v: Any) -> float | None:
    if v in (None, "", "-"):
        return None
    try:
        return float(str(v).replace(",", "."))
    except (TypeError, ValueError):
        return None


def _parse_row(row: dict[str, Any], trade_date: str) -> MarginParameter | None:
    code = (
        row.get("contractCode")
        or row.get("kontratKodu")
        or row.get("contract")
        or row.get("KONTRAT_KODU")
    )
    if not code:
        return None

    initial = _to_float(
        row.get("initialMargin")
        or row.get("baslangicTeminati")
        or row.get("BASLANGIC_TEMINATI")
    )
    initial_prev = _to_float(
        row.get("initialMarginPrev")
        or row.get("oncekiBaslangicTeminati")
    )
    if initial is not None and initial_prev not in (None, 0):
        pct_change = (initial - initial_prev) / initial_prev * 100.0
    else:
        pct_change = None

    underlying = row.get("underlying") or row.get("dayanak") or None

    return MarginParameter(
        contract_code=str(code),
        underlying=underlying,
        trade_date=trade_date,
        initial_margin=initial,
        maintenance_margin=_to_float(
            row.get("maintenanceMargin") or row.get("surdurmeTeminati")
        ),
        price_scan_range=_to_float(
            row.get("priceScanRange") or row.get("fiyatTaramaAraligi")
        ),
        spread_credit=_to_float(
            row.get("spreadCredit") or row.get("vadeIciIndirim")
        ),
        initial_margin_prev=initial_prev,
        pct_change_initial=pct_change,
    )


async def fetch_margin_parameters(
    trade_date: date | str | None = None,
    underlying_filter: str | None = None,
    only_changed: bool = False,
) -> list[MarginParameter]:
    """Pull Takasbank's daily VIOP margin parameter snapshot.

    v0.2 STATUS: Takasbank's portal returns 404 for direct fetches on
    the URL pattern observed; the data lives behind their UI's auth/
    session layer. Endpoint discovery is tracked for v0.3 (likely needs
    Excel bulletin scraping rather than a JSON endpoint). The parameter
    dataclass and change-detection logic in this module are ready.
    """
    raise wip_error(
        "takasbank",
        f"trade_date={trade_date} underlying_filter={underlying_filter} "
        f"only_changed={only_changed}",
    )


async def fetch_margin_change_alerts(
    trade_date: date | str | None = None,
    threshold_pct: float = 5.0,
) -> list[MarginParameter]:
    """v0.2 STATUS: blocked on `fetch_margin_parameters` endpoint discovery."""
    raise wip_error(
        "takasbank",
        f"trade_date={trade_date} threshold_pct={threshold_pct}",
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


# Re-export for convenience
__all__ = [
    "MarginParameter",
    "fetch_margin_parameters",
    "fetch_margin_change_alerts",
]

# Silence the unused import warning when consumers don't need timedelta
_ = timedelta

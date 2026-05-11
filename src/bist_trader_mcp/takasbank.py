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

    v0.1.1 STATUS: discovery progressed 2026-05-11.

    Takasbank publishes 20 daily VIOP statistics pages (live values
    visible directly on the parent dashboard) at:
        https://www.takasbank.com.tr/tr/istatistikler/
            vadeli-islem-ve-opsiyon-piyasasi-viop/<report-slug>

    Key report slugs:
      - teminat-tamamlama-cagrisi-raporu  (margin call total)
      - bulunmasi-gereken-teminat-raporu  (required margin)
      - islem-teminati-raporu             (transaction margin)
      - garanti-fonu-teminati-raporu      (guarantee fund)
      - vadeli-islem-sozlesmesi-islem-hacmi-raporu (futures volume)
      - opsiyon-islem-hacmi-raporu        (options volume)
      - vadeli-islem-sozlesmesi-acik-pozisyon-adet-raporu (futures OI)
      - opsiyon-acik-pozisyon-adedi-raporu (options OI)

    Live discovery 2026-05-11 dashboard snapshot:
      - Teminatlı Hesap Sayısı:            113,405
      - Teminat Tamamlama Çağrısı:         404,002,374.47 TL
      - Bulunması Gereken Teminat:         96,174,374,438.15 TL

    Obstacles for direct scraping:
      1. F5 BIG-IP TSPD WAF blocks plain HTTP and naive Playwright.
      2. playwright-stealth bypasses the bot fingerprint but Takasbank
         then trips IP-based rate limits after 5-10 probes.
      3. Report sub-pages render charts via async JS; values arrive
         after user-interaction (date picker, dropdown).

    Path forward (v0.3, separate sprint):
      - Add light IP rotation or rate-limited fetch (one request /
        15 minutes per IP).
      - Use page.locator() with explicit waits rather than innerText.
      - Optionally drive date-picker controls programmatically.
      - Cache snapshot for 24h since the data is daily anyway.

    Until then this tool returns a structured WIP payload so the LLM
    explains the gap to the user rather than hallucinating values.
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

"""VIOP (Vadeli İşlem ve Opsiyon Piyasası) settlement & term-structure fetcher.

VIOP is Borsa İstanbul's derivatives market. The exchange publishes a daily
settlement bulletin that lists, for every active contract:
    - contract code (e.g. F_XU0300625 = BIST30 June 2025 future)
    - settle price, open interest, daily volume, takas referans fiyatı

This module wraps the public bulletin so we can build:
    - get_viop_settlement(contract_code, since, until)
    - get_viop_term_structure(underlying, as_of)
    - calculate_basis vs spot (in tools.py)

Caveats:
- The bulletin URL on borsaistanbul.com changes occasionally; we attempt a
  couple of known patterns and surface a structured SourceError if all fail.
- Real-time tick data is NOT free and is not provided here.
- Option chains are deferred to a later module (`viop_options.py`).

Contract code conventions (BIST):
    F_<UNDERLYING><MONTHCODE><YY>
    e.g. F_XU0300625 = BIST 30 futures, June 2025 expiry
         F_USD0625   = USDTRY futures, June 2025
Month codes:
    01=Jan, 02=Feb, ..., 12=Dec (BIST uses numeric, not the H/M/U/Z futures
    code seen in CME).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from ._wip import wip_error
from .http_utils import SourceError, fetch_json  # noqa: F401  retained for v0.3

# BIST publishes daily VIOP data via a public JSON endpoint that mirrors
# their settlement bulletin. The exact URL has moved historically; if this
# stops working, check https://www.borsaistanbul.com/data/data-statistics
# for the current "Türev Piyasası Günlük Bülteni" pattern.
VIOP_DAILY_URL = (
    "https://www.borsaistanbul.com/data/derivatives/daily-bulletin"
)


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
    contract: VIOPContract
    trade_date: str           # YYYY-MM-DD
    settle_price: float | None
    reference_price: float | None
    open_interest: int | None
    volume: int | None
    high: float | None
    low: float | None


CONTRACT_RX = re.compile(
    r"^(?P<kind>[FO])_(?P<underlying>[A-Z0-9]+?)(?P<month>\d{2})(?P<year>\d{2})"
    r"(?:_(?P<right>[CP])(?P<strike>\d+(?:\.\d+)?))?$"
)


def parse_contract_code(code: str) -> VIOPContract:
    """Best-effort parser for VIOP contract codes."""
    m = CONTRACT_RX.match(code.strip().upper())
    if not m:
        raise SourceError("viop", f"unparseable contract code: {code}")
    kind = "future" if m.group("kind") == "F" else "option"
    underlying = m.group("underlying")
    month = int(m.group("month"))
    year_yy = int(m.group("year"))
    expiry_year = 2000 + year_yy if year_yy < 70 else 1900 + year_yy
    strike = float(m.group("strike")) if m.group("strike") else None
    right = m.group("right") if m.group("right") else None
    return VIOPContract(
        contract_code=code,
        underlying=underlying,
        contract_type=kind,
        expiry_year=expiry_year,
        expiry_month=month,
        option_strike=strike,
        option_right=right,
    )


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


def _row_to_settlement(row: dict[str, Any], trade_date: str) -> VIOPSettlement | None:
    """Map a bulletin row onto a VIOPSettlement.

    BIST publishes fields under a variety of casings; we try several.
    """
    code = (
        row.get("contractCode")
        or row.get("ContractCode")
        or row.get("kontratKodu")
        or row.get("KONTRAT_KODU")
    )
    if not code:
        return None
    try:
        contract = parse_contract_code(str(code))
    except SourceError:
        return None
    return VIOPSettlement(
        contract=contract,
        trade_date=trade_date,
        settle_price=_to_float(row.get("settlementPrice") or row.get("uzlasmaFiyati")),
        reference_price=_to_float(
            row.get("referencePrice") or row.get("takasReferansFiyati")
        ),
        open_interest=_to_int(row.get("openInterest") or row.get("acikPozisyon")),
        volume=_to_int(row.get("volume") or row.get("islemMiktari")),
        high=_to_float(row.get("highPrice") or row.get("enYuksek")),
        low=_to_float(row.get("lowPrice") or row.get("enDusuk")),
    )


async def fetch_daily_settlement(
    trade_date: date | str | None = None,
    underlying_filter: str | None = None,
) -> list[VIOPSettlement]:
    """Fetch all VIOP contract settlement rows for a single trade date.

    v0.2 STATUS: Borsa İstanbul publishes VIOP bulletins behind a
    session-bound UI and returns 404 for direct JSON access on the URL
    patterns observed. Endpoint discovery is tracked for v0.3. The
    contract-code parser and settlement dataclasses are ready.
    """
    raise wip_error(
        "viop",
        f"trade_date={trade_date} underlying_filter={underlying_filter}",
    )


async def fetch_term_structure(
    underlying: str,
    as_of: date | str | None = None,
) -> list[VIOPSettlement]:
    """v0.2 STATUS: blocked on `fetch_daily_settlement` endpoint discovery."""
    raise wip_error("viop", f"underlying={underlying} as_of={as_of}")


def _coerce(value: date | str) -> date:
    if isinstance(value, date):
        return value
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d.%m.%Y"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    raise SourceError("viop", f"bad date: {value!r}")

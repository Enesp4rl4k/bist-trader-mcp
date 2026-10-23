"""Annual financial history for valuation auto-fill (Yahoo fundamentals timeseries).

Best effort and **never authoritative**: the figures seed the valuation drivers
(revenue, EBIT margin, D&A / capex / working capital intensity, debt, cash,
shares…) and every value the caller passes explicitly wins. For BIST, check
them against the KAP statements — Yahoo may lag, and TMS 29 (inflation
accounting) restatements can make old years non-comparable.
"""

from __future__ import annotations

import time
from typing import Any

from ._cache import cache_get, cache_set
from .http_utils import fetch_json

TIMESERIES_URL = (
    "https://query2.finance.yahoo.com/ws/fundamentals-timeseries/v1/finance/timeseries/{symbol}"
)
CACHE_TTL = 24 * 3600

FIELDS = {
    "revenue": "annualTotalRevenue",
    "ebit": "annualEBIT",
    "ebitda": "annualEBITDA",
    "net_income": "annualNetIncome",
    "da": "annualReconciledDepreciation",
    "capex": "annualCapitalExpenditure",
    "fcf": "annualFreeCashFlow",
    "total_debt": "annualTotalDebt",
    "cash": "annualCashAndCashEquivalents",
    "equity": "annualStockholdersEquity",
    "minority_interest": "annualMinorityInterest",
    "shares": "annualOrdinarySharesNumber",
    "working_capital": "annualWorkingCapital",
    "tax_rate": "annualTaxRateForCalcs",
    "dividends_paid": "annualCashDividendsPaid",
}


def _yahoo_symbol(ticker: str) -> str:
    t = ticker.strip().upper().split(":")[-1]
    return t if "." in t or "-" in t or "=" in t else f"{t}.IS"


def parse_timeseries(payload: Any) -> dict[str, list[tuple[str, float]]]:
    """{field: [(asOfDate, value), …] oldest first} from a timeseries payload."""
    by_type = {v: k for k, v in FIELDS.items()}
    out: dict[str, list[tuple[str, float]]] = {}
    for res in ((payload or {}).get("timeseries") or {}).get("result") or []:
        types = (res.get("meta") or {}).get("type") or []
        if not types or types[0] not in by_type:
            continue
        rows = []
        for item in res.get(types[0]) or []:
            if not item:
                continue
            raw = (item.get("reportedValue") or {}).get("raw")
            if isinstance(raw, (int, float)) and item.get("asOfDate"):
                rows.append((item["asOfDate"], float(raw)))
        if rows:
            out[by_type[types[0]]] = sorted(rows)
    return out


async def fetch_financial_history(ticker: str, years: int = 6) -> dict[str, Any]:
    symbol = _yahoo_symbol(ticker)
    key = f"yahoo.timeseries:{symbol}"
    payload = cache_get(key, ttl_seconds=CACHE_TTL)
    if payload is None:
        now = int(time.time())
        payload = await fetch_json(
            TIMESERIES_URL.format(symbol=symbol),
            params={"type": ",".join(FIELDS.values()),
                    "period1": now - (years + 1) * 366 * 86400, "period2": now},
            source="yahoo",
        )
        cache_set(key, payload, ttl_seconds=CACHE_TTL)
    return {"symbol": symbol, "history": parse_timeseries(payload)}


def _last(h: dict[str, list[tuple[str, float]]], f: str) -> float | None:
    rows = h.get(f) or []
    return rows[-1][1] if rows else None


def derive_drivers(history: dict[str, list[tuple[str, float]]]) -> dict[str, Any]:
    """Valuation inputs from annual history (intensities as % of revenue, averaged)."""
    rev = history.get("revenue") or []
    if not rev:
        return {"available": False, "reason": "no revenue history"}
    rev_by = dict(rev)
    years = [d for d, _ in rev]

    def ratio(field: str, absolute: bool = False) -> float | None:
        vals = []
        for d, v in history.get(field) or []:
            r = rev_by.get(d)
            if r and r > 0:
                vals.append((abs(v) if absolute else v) / r)
        return sum(vals) / len(vals) if vals else None

    cagr = None
    if len(rev) >= 2 and rev[0][1] > 0 and rev[-1][1] > 0:
        n = len(rev) - 1
        cagr = (rev[-1][1] / rev[0][1]) ** (1 / n) - 1
    ebit_last = _last(history, "ebit")
    tax = _last(history, "tax_rate")
    equity = _last(history, "equity")
    ni = _last(history, "net_income")
    divs = _last(history, "dividends_paid")
    shares = _last(history, "shares")
    return {
        "available": True,
        "fiscal_years": years,
        "revenue0": rev[-1][1],
        "revenue_cagr": None if cagr is None else round(cagr, 4),
        "ebit_margin_last": None if ebit_last is None else round(ebit_last / rev[-1][1], 4),
        "ebit_margin_avg": None if ratio("ebit") is None else round(ratio("ebit"), 4),
        "da_pct_revenue": None if ratio("da") is None else round(ratio("da"), 4),
        "capex_pct_revenue": None if ratio("capex", True) is None
        else round(ratio("capex", True), 4),
        "nwc_pct_revenue": None if ratio("working_capital") is None
        else round(ratio("working_capital"), 4),
        "tax_rate": None if tax is None else round(min(max(tax, 0.0), 0.5), 4),
        "debt": _last(history, "total_debt") or 0.0,
        "cash": _last(history, "cash") or 0.0,
        "minority_interest": _last(history, "minority_interest") or 0.0,
        "shares_outstanding": shares,
        "book_value": equity,
        "net_income": ni,
        "ebitda": _last(history, "ebitda"),
        "roe": round(ni / equity, 4) if ni is not None and equity else None,
        "dividend_per_share": round(abs(divs) / shares, 4) if divs and shares else None,
        "payout": round(abs(divs) / ni, 4) if divs and ni and ni > 0 else None,
    }


__all__ = ["derive_drivers", "fetch_financial_history", "parse_timeseries"]

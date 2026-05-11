"""BIST equity EOD (end-of-day) OHLCV fetcher.

Backed by Yahoo Finance's `/v8/finance/chart` JSON endpoint, which remains
free and unauthenticated as of 2026-05. (The older `/v7/finance/download`
CSV endpoint started returning 401 in mid-2024 — do not use it.)

Design notes:
- We do NOT ship real-time tick data. Intraday licensing is not free in TR;
  trader workflows that need real-time still belong to Matriks/Foreks.
- Yahoo Finance returns BIST tickers with a ".IS" suffix (e.g. "THYAO.IS").
- Index symbols use a "^" prefix on Yahoo (^XU100, ^XU030).
- A single call returns OHLCV for one symbol over a date window.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from .http_utils import SourceError, fetch_json


@dataclass
class OHLCVBar:
    date: str  # YYYY-MM-DD
    open: float | None
    high: float | None
    low: float | None
    close: float | None
    volume: float | None
    ticker: str


YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"


def _bist_to_yahoo(ticker: str) -> str:
    """Normalise BIST tickers to Yahoo's expected symbol form."""
    t = ticker.upper().strip()
    if t.endswith(".IS"):
        return t
    if t.startswith("^"):
        return t
    return f"{t}.IS"


def _epoch(d: date) -> int:
    return int(datetime(d.year, d.month, d.day).timestamp())


async def fetch_eod_ohlcv(
    ticker: str,
    since: date | str | None = None,
    until: date | str | None = None,
) -> list[OHLCVBar]:
    """Fetch daily OHLCV bars for a BIST symbol."""
    since_date = _coerce(since) if since else date.today() - timedelta(days=365)
    until_date = _coerce(until) if until else date.today()
    if until_date <= since_date:
        raise SourceError("bist_eod", "until must be after since")

    symbol = _bist_to_yahoo(ticker)
    url = YAHOO_CHART_URL.format(symbol=symbol)
    params = {
        "period1": _epoch(since_date),
        "period2": _epoch(until_date + timedelta(days=1)),
        "interval": "1d",
        "events": "history",
        "includeAdjustedClose": "true",
    }
    payload = await fetch_json(url, params=params, source="yahoo")
    return _parse_yahoo_chart(payload, ticker=symbol)


def _parse_yahoo_chart(payload: Any, ticker: str) -> list[OHLCVBar]:
    """Yahoo /v8/finance/chart returns:
        chart.result[0].timestamp -> [epoch_sec, ...]
        chart.result[0].indicators.quote[0].{open,high,low,close,volume}
    """
    if not isinstance(payload, dict):
        raise SourceError("yahoo", f"unexpected payload type: {type(payload)}")
    chart = payload.get("chart") or {}
    if chart.get("error"):
        raise SourceError("yahoo", f"chart error: {chart['error']}")
    results = chart.get("result") or []
    if not results:
        return []

    r0 = results[0]
    timestamps: list[int] = r0.get("timestamp") or []
    quote = ((r0.get("indicators") or {}).get("quote") or [{}])[0]
    opens = quote.get("open") or []
    highs = quote.get("high") or []
    lows = quote.get("low") or []
    closes = quote.get("close") or []
    volumes = quote.get("volume") or []

    bars: list[OHLCVBar] = []
    for i, ts in enumerate(timestamps):
        try:
            bar_date = datetime.fromtimestamp(int(ts)).date().isoformat()
        except (OverflowError, OSError, ValueError):
            continue
        bars.append(
            OHLCVBar(
                date=bar_date,
                open=_safe_float(_at(opens, i)),
                high=_safe_float(_at(highs, i)),
                low=_safe_float(_at(lows, i)),
                close=_safe_float(_at(closes, i)),
                volume=_safe_float(_at(volumes, i)),
                ticker=ticker,
            )
        )
    return bars


def _at(seq: list[Any], i: int) -> Any:
    return seq[i] if 0 <= i < len(seq) else None


def _safe_float(v: Any) -> float | None:
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if f != f else f  # NaN guard


def _coerce(value: date | str) -> date:
    if isinstance(value, date):
        return value
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d.%m.%Y"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    raise SourceError("bist_eod", f"bad date: {value!r}")

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

from ._cache import cache_get, cache_set
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


EOD_HISTORY_TTL = 7 * 24 * 3600
EOD_LIVE_TTL = 15 * 60

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
    period: str | None = None,
    adjusted: bool = False,
) -> list[OHLCVBar]:
    """Fetch daily OHLCV bars for a BIST symbol.

    ``adjusted=True`` back-adjusts OHLC for splits/bonus issues/dividends using
    Yahoo's ``adjclose`` — use it for technical analysis so capital increases
    (bedelsiz) don't print fake crash candles. Default keeps official prices.
    """
    until_date = _coerce(until) if until else date.today()
    since_date = (
        _coerce(since)
        if since
        else _period_start(until_date, period or "1y")
    )
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
    # Closed history never changes → cache for a week; a window that includes
    # today can still print a new bar → 15 minutes.
    key = f"yahoo.eod:{symbol}:{since_date}:{until_date}"
    ttl = EOD_HISTORY_TTL if until_date < date.today() else EOD_LIVE_TTL
    payload = cache_get(key, ttl_seconds=ttl)
    if payload is None:
        payload = await fetch_json(url, params=params, source="yahoo")
        cache_set(key, payload, ttl_seconds=ttl)
    return _parse_yahoo_chart(payload, ticker=symbol, adjusted=adjusted)


def _parse_yahoo_chart(payload: Any, ticker: str, adjusted: bool = False) -> list[OHLCVBar]:
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
    adjcloses: list[Any] = []
    if adjusted:
        adj_block = (r0.get("indicators") or {}).get("adjclose") or [{}]
        adjcloses = adj_block[0].get("adjclose") or []

    bars: list[OHLCVBar] = []
    for i, ts in enumerate(timestamps):
        close = _safe_float(_at(closes, i))
        if close is None:
            continue
        try:
            bar_date = datetime.fromtimestamp(int(ts)).date().isoformat()
        except (OverflowError, OSError, ValueError):
            continue
        o = _safe_float(_at(opens, i))
        h = _safe_float(_at(highs, i))
        lo = _safe_float(_at(lows, i))
        vol = _safe_float(_at(volumes, i))
        adj = _safe_float(_at(adjcloses, i))
        if adj is not None and adj > 0 and close > 0:
            f = adj / close
            o = o * f if o is not None else None
            h = h * f if h is not None else None
            lo = lo * f if lo is not None else None
            vol = vol / f if vol is not None else None
            close = adj
        bars.append(
            OHLCVBar(
                date=bar_date,
                open=o,
                high=h,
                low=lo,
                close=close,
                volume=vol,
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


def _period_start(end: date, period: str) -> date:
    value = period.strip().lower()
    if value.endswith("mo"):
        try:
            months = int(value[:-2])
        except ValueError as exc:
            raise SourceError("bist_eod", f"bad period: {period!r}") from exc
        return end - timedelta(days=max(1, months) * 31)
    if value.endswith("y"):
        try:
            years = int(value[:-1])
        except ValueError as exc:
            raise SourceError("bist_eod", f"bad period: {period!r}") from exc
        return end - timedelta(days=max(1, years) * 365)
    if value.endswith("d"):
        try:
            days = int(value[:-1])
        except ValueError as exc:
            raise SourceError("bist_eod", f"bad period: {period!r}") from exc
        return end - timedelta(days=max(1, days))
    raise SourceError("bist_eod", f"unsupported period: {period!r}")

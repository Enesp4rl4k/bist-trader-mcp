"""BIST real-time(ish) price snapshot + market summary.

Provides two high-level primitives:
    - `fetch_snapshot(tickers)` — latest price / change / volume for 1-10
      tickers. 15-min delayed (Yahoo Finance), but covers the "what's my
      stock doing right now?" question that EOD bars can't answer.
    - `fetch_market_summary()` — single-call overview of TR market pulse:
      XU100, XU030, XBANK, USDTRY, EURTRY, gold, plus BIST summary stats.

Both use Yahoo Finance's `/v8/finance/chart?range=1d&interval=1m` which
returns the latest available intraday point plus daily open/high/low and
prior-close for % change calculation.

Design notes:
    - NOT real-time. Yahoo Finance BIST data is ~15 min delayed. This is
      explicitly documented in every response. Traders needing true L1 or
      L2 should still use Matriks / Foreks.
    - The module does NOT store or cache — snapshots are inherently time-
      sensitive and caching stale prices defeats the purpose. The shared
      httpx connection pool handles efficiency.
    - Batch calls issue parallel tasks with asyncio.gather for speed.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .http_utils import SourceError, fetch_json

YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"


@dataclass
class PriceSnapshot:
    """A single ticker's latest price snapshot."""
    ticker: str
    last_price: float | None
    previous_close: float | None
    open: float | None
    day_high: float | None
    day_low: float | None
    change: float | None
    change_pct: float | None
    volume: float | None
    market_state: str | None     # "REGULAR", "PRE", "POST", "CLOSED"
    currency: str | None
    as_of: str                   # ISO timestamp of the data point


# Market summary symbols — covers the core TR market pulse
MARKET_SUMMARY_SYMBOLS = {
    # BIST indices
    "XU100": "^XU100",       # BIST 100
    "XU030": "^XU030",       # BIST 30
    "XBANK": "^XBANK",      # BIST Banka
    # FX
    "USDTRY": "USDTRY=X",   # Dolar/TL
    "EURTRY": "EURTRY=X",   # Euro/TL
    "GBPTRY": "GBPTRY=X",   # Sterlin/TL
    # Commodities
    "GOLD_USD": "GC=F",     # Altın (USD/oz)
    "BRENT": "BZ=F",        # Brent Petrol
    # Crypto
    "BTCUSD": "BTC-USD",    # Bitcoin
}


def _to_yahoo(ticker: str) -> str:
    """Convert BIST/common tickers to Yahoo symbol format."""
    t = ticker.upper().strip()

    # Already a Yahoo symbol?
    if "=" in t or "-" in t or t.startswith("^"):
        return t
    if t.endswith(".IS"):
        return t

    # Check if it's a known market summary alias
    if t in MARKET_SUMMARY_SYMBOLS:
        return MARKET_SUMMARY_SYMBOLS[t]

    # Default: BIST equity
    return f"{t}.IS"


async def _fetch_one_snapshot(ticker: str, yahoo_symbol: str) -> PriceSnapshot:
    """Fetch the latest intraday snapshot for one symbol."""
    url = YAHOO_CHART_URL.format(symbol=yahoo_symbol)
    params = {
        "range": "1d",
        "interval": "1m",
        "includePrePost": "false",
    }

    try:
        payload = await fetch_json(url, params=params, source="yahoo")
    except SourceError:
        return PriceSnapshot(
            ticker=ticker,
            last_price=None, previous_close=None, open=None,
            day_high=None, day_low=None,
            change=None, change_pct=None, volume=None,
            market_state=None, currency=None,
            as_of=datetime.now().isoformat(timespec="seconds"),
        )

    if not isinstance(payload, dict):
        return _empty_snapshot(ticker)

    chart = payload.get("chart") or {}
    results = chart.get("result") or []
    if not results:
        return _empty_snapshot(ticker)

    r0 = results[0]
    meta = r0.get("meta") or {}

    # Extract latest price from meta (most reliable)
    last_price = _sf(meta.get("regularMarketPrice"))
    prev_close = _sf(meta.get("chartPreviousClose") or meta.get("previousClose"))
    currency = meta.get("currency")
    market_state = meta.get("marketState")

    # Day OHLV from indicators
    quote = ((r0.get("indicators") or {}).get("quote") or [{}])[0]
    opens = quote.get("open") or []
    highs = quote.get("high") or []
    lows = quote.get("low") or []
    volumes = quote.get("volume") or []

    day_open = _sf(opens[0]) if opens else None
    day_high = max((_sf(h) for h in highs if _sf(h) is not None), default=None)
    day_low_vals = [_sf(low) for low in lows if _sf(low) is not None]
    day_low = min(day_low_vals) if day_low_vals else None
    total_volume = sum(_sf(v) or 0 for v in volumes)

    # Calculate change
    change: float | None = None
    change_pct: float | None = None
    if last_price is not None and prev_close is not None and prev_close != 0:
        change = last_price - prev_close
        change_pct = (change / prev_close) * 100.0

    # Timestamp
    timestamps = r0.get("timestamp") or []
    if timestamps:
        try:
            as_of = datetime.fromtimestamp(int(timestamps[-1])).isoformat(timespec="seconds")
        except (OverflowError, OSError, ValueError):
            as_of = datetime.now().isoformat(timespec="seconds")
    else:
        as_of = datetime.now().isoformat(timespec="seconds")

    return PriceSnapshot(
        ticker=ticker,
        last_price=last_price,
        previous_close=prev_close,
        open=day_open,
        day_high=day_high,
        day_low=day_low,
        change=_round(change),
        change_pct=_round(change_pct),
        volume=total_volume if total_volume else None,
        market_state=market_state,
        currency=currency,
        as_of=as_of,
    )


def _sf(v: Any) -> float | None:
    """Safe float conversion with NaN guard."""
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if f != f else f  # NaN guard


def _round(v: float | None, digits: int = 4) -> float | None:
    if v is None:
        return None
    return round(v, digits)


def _empty_snapshot(ticker: str) -> PriceSnapshot:
    return PriceSnapshot(
        ticker=ticker,
        last_price=None, previous_close=None, open=None,
        day_high=None, day_low=None,
        change=None, change_pct=None, volume=None,
        market_state=None, currency=None,
        as_of=datetime.now().isoformat(timespec="seconds"),
    )


async def fetch_snapshot(
    tickers: list[str],
) -> list[PriceSnapshot]:
    """Fetch latest price snapshots for 1-10 tickers in parallel.

    Args:
        tickers: BIST tickers (e.g. ["THYAO", "GARAN"]) or Yahoo symbols.
            Max 10 per call to keep latency reasonable.

    Returns:
        List of PriceSnapshot dataclass instances.
    """
    if not tickers:
        raise SourceError("snapshot", "tickers list is empty")
    if len(tickers) > 10:
        tickers = tickers[:10]  # hard cap

    tasks = [
        _fetch_one_snapshot(t, _to_yahoo(t))
        for t in tickers
    ]
    return list(await asyncio.gather(*tasks))


async def fetch_market_summary() -> dict[str, PriceSnapshot]:
    """Fetch a one-shot overview of the Turkish market.

    Returns a dict keyed by human-friendly aliases:
        XU100, XU030, XBANK, USDTRY, EURTRY, GBPTRY, GOLD_USD, BRENT, BTCUSD
    """
    aliases = list(MARKET_SUMMARY_SYMBOLS.keys())
    yahoo_symbols = list(MARKET_SUMMARY_SYMBOLS.values())

    tasks = [
        _fetch_one_snapshot(alias, ysym)
        for alias, ysym in zip(aliases, yahoo_symbols, strict=True)
    ]
    results = await asyncio.gather(*tasks)
    return dict(zip(aliases, results, strict=True))


__all__ = [
    "PriceSnapshot",
    "MARKET_SUMMARY_SYMBOLS",
    "fetch_snapshot",
    "fetch_market_summary",
]

"""Crypto data fetchers — CoinGecko (spot + market cap) + Binance (klines,
funding rates, open interest).

Both sources are free, public, and CORS-friendly. CoinGecko rate-limits to
~30 calls/min on the free tier; Binance public endpoints have no auth
requirement and ~1200 req/min weight budget. We cache 60s for spot tickers
and 5 min for klines.

Why two sources:
- CoinGecko is the canonical multi-exchange aggregator (median spot, market
  cap rank, total volume). Best for "which coin, how big".
- Binance provides USDT-pair klines + perp funding rates + open interest,
  which are the proxies traders use for sentiment / leverage stress.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ._cache import cache_get, cache_set
from .http_utils import SourceError, fetch_json

COINGECKO_BASE = "https://api.coingecko.com/api/v3"
BINANCE_BASE = "https://api.binance.com"
BINANCE_FAPI = "https://fapi.binance.com"

DEFAULT_SPOT_TTL = 60       # seconds
DEFAULT_KLINES_TTL = 300    # 5 min
DEFAULT_FUNDING_TTL = 600   # 10 min


@dataclass
class CryptoSpot:
    """One coin's aggregated spot snapshot from CoinGecko."""
    coin_id: str
    symbol: str
    name: str
    price_usd: float | None
    market_cap_usd: float | None
    market_cap_rank: int | None
    volume_24h_usd: float | None
    change_24h_pct: float | None
    change_7d_pct: float | None
    high_24h_usd: float | None
    low_24h_usd: float | None
    ath_usd: float | None
    ath_date: str | None
    as_of: str


async def fetch_coin_spots(
    coin_ids: list[str],
    vs_currency: str = "usd",
    use_cache: bool = True,
) -> list[CryptoSpot]:
    """Fetch spot snapshots for a list of coins via CoinGecko /coins/markets.

    Args:
        coin_ids: CoinGecko slugs (e.g. "bitcoin", "ethereum", "solana").
        vs_currency: usually "usd"; CoinGecko supports tl as well.
        use_cache: serve from 60s cache when fresh.
    """
    if not coin_ids:
        return []
    key = f"crypto.coingecko.spots:{vs_currency}:{','.join(sorted(coin_ids))}"
    if use_cache:
        cached = cache_get(key, ttl_seconds=DEFAULT_SPOT_TTL)
        if isinstance(cached, list):
            return [_spot_from_dict(d) for d in cached]

    params = {
        "vs_currency": vs_currency,
        "ids": ",".join(coin_ids),
        "price_change_percentage": "24h,7d",
        "order": "market_cap_desc",
        "per_page": str(len(coin_ids)),
        "page": "1",
        "sparkline": "false",
    }
    try:
        data = await fetch_json(
            f"{COINGECKO_BASE}/coins/markets",
            source="coingecko",
            params=params,
        )
    except SourceError:
        raise

    if not isinstance(data, list):
        raise SourceError("coingecko", f"unexpected response: {type(data)}")

    out = [_spot_from_api(d) for d in data]
    cache_set(key, [_spot_to_dict(s) for s in out], ttl_seconds=DEFAULT_SPOT_TTL)
    return out


def _spot_from_api(d: dict[str, Any]) -> CryptoSpot:
    return CryptoSpot(
        coin_id=str(d.get("id") or ""),
        symbol=str(d.get("symbol") or "").upper(),
        name=str(d.get("name") or ""),
        price_usd=_f(d.get("current_price")),
        market_cap_usd=_f(d.get("market_cap")),
        market_cap_rank=_i(d.get("market_cap_rank")),
        volume_24h_usd=_f(d.get("total_volume")),
        change_24h_pct=_f(d.get("price_change_percentage_24h_in_currency")
                          or d.get("price_change_percentage_24h")),
        change_7d_pct=_f(d.get("price_change_percentage_7d_in_currency")),
        high_24h_usd=_f(d.get("high_24h")),
        low_24h_usd=_f(d.get("low_24h")),
        ath_usd=_f(d.get("ath")),
        ath_date=str(d.get("ath_date") or "") or None,
        as_of=str(d.get("last_updated") or ""),
    )


def _spot_to_dict(s: CryptoSpot) -> dict[str, Any]:
    return s.__dict__.copy()


def _spot_from_dict(d: dict[str, Any]) -> CryptoSpot:
    return CryptoSpot(**{k: d.get(k) for k in CryptoSpot.__dataclass_fields__})


def _f(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _i(v: Any) -> int | None:
    f = _f(v)
    return int(f) if f is not None else None


# ---------------------------------------------------------------------------
# Binance klines + funding + OI
# ---------------------------------------------------------------------------

@dataclass
class Kline:
    open_time_ms: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    close_time_ms: int
    trades: int


async def fetch_binance_klines(
    symbol: str,
    interval: str = "1d",
    limit: int = 200,
    use_cache: bool = True,
) -> list[Kline]:
    """Fetch OHLCV klines from Binance spot.

    Args:
        symbol: trading pair, e.g. "BTCUSDT", "ETHUSDT".
        interval: "1m","5m","15m","1h","4h","1d","1w".
        limit: max 1000.
    """
    sym = symbol.upper().replace("/", "")
    key = f"crypto.binance.klines:{sym}:{interval}:{limit}"
    if use_cache:
        cached = cache_get(key, ttl_seconds=DEFAULT_KLINES_TTL)
        if isinstance(cached, list):
            return [_kline_from_dict(d) for d in cached]

    params = {"symbol": sym, "interval": interval, "limit": str(min(limit, 1000))}
    try:
        data = await fetch_json(
            f"{BINANCE_BASE}/api/v3/klines",
            source="binance",
            params=params,
        )
    except SourceError:
        raise

    if not isinstance(data, list):
        raise SourceError("binance", f"unexpected klines response: {type(data)}")

    out: list[Kline] = []
    for row in data:
        if len(row) < 9:
            continue
        out.append(Kline(
            open_time_ms=int(row[0]),
            open=float(row[1]),
            high=float(row[2]),
            low=float(row[3]),
            close=float(row[4]),
            volume=float(row[5]),
            close_time_ms=int(row[6]),
            trades=int(row[8]),
        ))
    cache_set(key, [_kline_to_dict(k) for k in out], ttl_seconds=DEFAULT_KLINES_TTL)
    return out


def _kline_to_dict(k: Kline) -> dict[str, Any]:
    return k.__dict__.copy()


def _kline_from_dict(d: dict[str, Any]) -> Kline:
    return Kline(**{k: d[k] for k in Kline.__dataclass_fields__})


@dataclass
class FundingPoint:
    symbol: str
    funding_time_ms: int
    funding_rate: float   # decimal per 8h (0.0001 = 0.01%)
    mark_price: float | None


async def fetch_funding_rates(
    symbol: str,
    limit: int = 30,
    use_cache: bool = True,
) -> list[FundingPoint]:
    """Recent funding rate history for a Binance perp.

    Args:
        symbol: e.g. "BTCUSDT" (USD-M perp).
        limit: max 1000; default 30 (last 10 days at 8h intervals).
    """
    sym = symbol.upper().replace("/", "")
    key = f"crypto.binance.funding:{sym}:{limit}"
    if use_cache:
        cached = cache_get(key, ttl_seconds=DEFAULT_FUNDING_TTL)
        if isinstance(cached, list):
            return [FundingPoint(**d) for d in cached]

    params = {"symbol": sym, "limit": str(min(limit, 1000))}
    try:
        data = await fetch_json(
            f"{BINANCE_FAPI}/fapi/v1/fundingRate",
            source="binance-fapi",
            params=params,
        )
    except SourceError:
        raise

    if not isinstance(data, list):
        raise SourceError("binance-fapi", f"unexpected funding response: {type(data)}")

    out: list[FundingPoint] = []
    for row in data:
        try:
            out.append(FundingPoint(
                symbol=str(row.get("symbol", sym)),
                funding_time_ms=int(row.get("fundingTime", 0)),
                funding_rate=float(row.get("fundingRate", 0.0)),
                mark_price=_f(row.get("markPrice")),
            ))
        except (TypeError, ValueError):
            continue
    cache_set(key, [fp.__dict__ for fp in out], ttl_seconds=DEFAULT_FUNDING_TTL)
    return out


async def fetch_open_interest_history(
    symbol: str,
    period: str = "1h",
    limit: int = 30,
    use_cache: bool = True,
) -> list[dict[str, Any]]:
    """Open interest history for a Binance perp."""
    sym = symbol.upper().replace("/", "")
    key = f"crypto.binance.oi:{sym}:{period}:{limit}"
    if use_cache:
        cached = cache_get(key, ttl_seconds=DEFAULT_FUNDING_TTL)
        if isinstance(cached, list):
            return cached

    params = {"symbol": sym, "period": period, "limit": str(min(limit, 500))}
    try:
        data = await fetch_json(
            f"{BINANCE_FAPI}/futures/data/openInterestHist",
            source="binance-fapi",
            params=params,
        )
    except SourceError:
        raise

    if not isinstance(data, list):
        return []
    out = [
        {
            "timestamp_ms": int(r.get("timestamp", 0)),
            "open_interest": _f(r.get("sumOpenInterest")),
            "open_interest_value_usd": _f(r.get("sumOpenInterestValue")),
        }
        for r in data
    ]
    cache_set(key, out, ttl_seconds=DEFAULT_FUNDING_TTL)
    return out


__all__ = [
    "CryptoSpot",
    "fetch_coin_spots",
    "Kline",
    "fetch_binance_klines",
    "FundingPoint",
    "fetch_funding_rates",
    "fetch_open_interest_history",
]

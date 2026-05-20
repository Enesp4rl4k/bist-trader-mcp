"""Crypto Fear & Greed Index via alternative.me.

A composite 0-100 sentiment score derived from price momentum, volume,
social signals, dominance, and Google Trends. Updated daily.

- 0-25: Extreme Fear (contrarian bullish)
- 25-45: Fear
- 45-55: Neutral
- 55-75: Greed
- 75-100: Extreme Greed (contrarian bearish)

Free, no auth, no rate limit at light usage.
"""

from __future__ import annotations

from dataclasses import dataclass

from ._cache import cache_get, cache_set
from .http_utils import SourceError, fetch_json

ALTERNATIVE_ME_API = "https://api.alternative.me/fng/"
DEFAULT_TTL = 6 * 3600


@dataclass
class FearGreedPoint:
    timestamp_unix: int
    value: int                # 0-100
    classification: str       # e.g. "Extreme Fear"
    date: str | None = None   # ISO date if derivable


async def fetch_fear_greed(
    limit: int = 30,
    use_cache: bool = True,
) -> list[FearGreedPoint]:
    """Fetch the most recent N daily F&G values (newest first)."""
    key = f"crypto.fng.limit{limit}"
    if use_cache:
        cached = cache_get(key, ttl_seconds=DEFAULT_TTL)
        if isinstance(cached, list):
            return [FearGreedPoint(**d) for d in cached]

    params = {"limit": str(limit), "format": "json"}
    try:
        data = await fetch_json(ALTERNATIVE_ME_API, source="alternative.me",
                                 params=params)
    except SourceError:
        raise

    if not isinstance(data, dict) or "data" not in data:
        raise SourceError("alternative.me", f"unexpected response: {data}")

    from datetime import datetime, timezone
    out: list[FearGreedPoint] = []
    for r in data.get("data") or []:
        try:
            ts = int(r.get("timestamp", 0))
            iso = datetime.fromtimestamp(ts, tz=timezone.utc).date().isoformat()
            out.append(FearGreedPoint(
                timestamp_unix=ts,
                value=int(r.get("value", 0)),
                classification=str(r.get("value_classification", "")),
                date=iso,
            ))
        except (TypeError, ValueError):
            continue
    cache_set(key, [p.__dict__ for p in out], ttl_seconds=DEFAULT_TTL)
    return out


__all__ = ["FearGreedPoint", "fetch_fear_greed"]

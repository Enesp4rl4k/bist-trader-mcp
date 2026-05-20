"""Global spot FX rates via Frankfurter (ECB reference rates) + Yahoo Finance.

Frankfurter is a free, no-key API that re-publishes ECB Euro reference
rates and computes cross-pairs on the fly. Updated daily ~16:00 CET.
Best for "what's EURUSD doing this week" reports, not intraday.

For intraday spot we fall back to Yahoo Finance via bist_snapshot
(already integrated).

Coverage: 30+ major currencies. Examples used in this MCP:
    EUR USD JPY GBP CHF AUD CAD NZD CNY HKD SGD MXN BRL ZAR INR TRY ...

Pair construction:
- Frankfurter natively quotes vs a base (default EUR). For any pair
  X/Y we fetch ?from=X with `to=Y` and read the rate.
- Cross rates (e.g. JPY/CHF) are computed by Frankfurter on the server,
  no need to triangulate locally.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ._cache import cache_get, cache_set
from .http_utils import SourceError, fetch_json

FRANKFURTER_BASE = "https://api.frankfurter.app"
DEFAULT_TTL = 6 * 3600   # daily-updated; 6h is plenty


@dataclass
class FXSpot:
    base: str
    quote: str
    rate: float
    as_of: str   # ISO date


async def fetch_fx_spot(
    pair: str,
    use_cache: bool = True,
) -> FXSpot:
    """Fetch the latest ECB reference rate for `pair` (e.g. 'EURUSD').

    The pair string can be 6 chars (EURUSD) or with a slash (EUR/USD).
    """
    base, quote = _split_pair(pair)
    key = f"fx.frankfurter.{base}{quote}.latest"
    if use_cache:
        cached = cache_get(key, ttl_seconds=DEFAULT_TTL)
        if isinstance(cached, dict) and "rate" in cached:
            return FXSpot(**cached)

    try:
        data = await fetch_json(
            f"{FRANKFURTER_BASE}/latest",
            source="frankfurter",
            params={"from": base, "to": quote},
        )
    except SourceError:
        raise

    if not isinstance(data, dict) or "rates" not in data:
        raise SourceError("frankfurter", f"unexpected response: {data}")
    rates = data.get("rates") or {}
    rate = rates.get(quote)
    if rate is None:
        raise SourceError("frankfurter", f"no rate for {pair}: {data}")
    spot = FXSpot(base=base, quote=quote, rate=float(rate),
                   as_of=str(data.get("date") or ""))
    cache_set(key, spot.__dict__, ttl_seconds=DEFAULT_TTL)
    return spot


async def fetch_fx_history(
    pair: str,
    days: int = 30,
    use_cache: bool = True,
) -> list[dict[str, Any]]:
    """Daily ECB reference rates for the last `days` business days."""
    from datetime import date, timedelta
    base, quote = _split_pair(pair)
    end = date.today()
    start = end - timedelta(days=days * 2)  # over-fetch to absorb weekends
    key = f"fx.frankfurter.{base}{quote}.history.{days}"
    if use_cache:
        cached = cache_get(key, ttl_seconds=DEFAULT_TTL)
        if isinstance(cached, list):
            return cached

    try:
        data = await fetch_json(
            f"{FRANKFURTER_BASE}/{start.isoformat()}..{end.isoformat()}",
            source="frankfurter",
            params={"from": base, "to": quote},
        )
    except SourceError:
        raise

    rows = []
    if isinstance(data, dict):
        for d, vals in (data.get("rates") or {}).items():
            if isinstance(vals, dict) and quote in vals:
                rows.append({"date": d, "rate": float(vals[quote])})
    rows.sort(key=lambda r: r["date"])
    if len(rows) > days:
        rows = rows[-days:]
    cache_set(key, rows, ttl_seconds=DEFAULT_TTL)
    return rows


async def fetch_fx_matrix(
    bases: list[str],
    quotes: list[str],
) -> dict[str, dict[str, float]]:
    """Build an N×M rate matrix in one call per base. Useful for
    constructing G10 cross-rate snapshots."""
    out: dict[str, dict[str, float]] = {}
    for b in bases:
        try:
            data = await fetch_json(
                f"{FRANKFURTER_BASE}/latest",
                source="frankfurter",
                params={"from": b, "to": ",".join(quotes)},
            )
        except SourceError:
            out[b] = {}
            continue
        if not isinstance(data, dict):
            out[b] = {}
            continue
        rates = data.get("rates") or {}
        out[b] = {q: float(v) for q, v in rates.items() if v is not None}
    return out


def _split_pair(pair: str) -> tuple[str, str]:
    p = pair.upper().strip().replace("/", "").replace("-", "")
    if len(p) != 6:
        raise SourceError("frankfurter", f"invalid pair: {pair} (need 6 chars)")
    return p[:3], p[3:]


# G10 + EM majors — sensible default basket for screening
G10_BASES = ["EUR", "USD", "GBP", "JPY", "CHF", "AUD", "CAD", "NZD"]
EM_QUOTES = ["TRY", "CNY", "HKD", "SGD", "MXN", "BRL", "ZAR", "INR", "PLN"]


__all__ = [
    "FXSpot",
    "fetch_fx_spot",
    "fetch_fx_history",
    "fetch_fx_matrix",
    "G10_BASES",
    "EM_QUOTES",
]

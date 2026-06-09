"""Replace weak TV HTF series with Yahoo EOD when bar count or quality is low."""

from __future__ import annotations

import asyncio
from typing import Any

from .bist_eod import fetch_eod_ohlcv
from .data_quality import assess_ohlcv_quality, merge_mtf_data_quality
from .market_profiles import get_market_profile


def _bars_to_ohlcv(bars: list[dict[str, Any]]) -> dict[str, list]:
    closes, highs, lows, times, volumes = [], [], [], [], []
    for b in bars:
        if not isinstance(b, dict):
            continue
        c = b.get("close")
        if c is None:
            continue
        closes.append(float(c))
        highs.append(float(b.get("high") or c))
        lows.append(float(b.get("low") or c))
        ts = b.get("date") or b.get("timestamp")
        if ts is not None:
            if hasattr(ts, "timestamp"):
                times.append(int(ts.timestamp()))
            else:
                times.append(int(ts))
        vol = b.get("volume")
        if vol is not None:
            volumes.append(float(vol))
    out: dict[str, list] = {
        "closes": closes,
        "highs": highs,
        "lows": lows,
        "times": times,
    }
    if volumes:
        out["volumes"] = volumes
    return out


async def apply_eod_htf_fallback_async(
    ohlcv: dict[str, Any],
    *,
    symbol: str,
    market: str | None = None,
    min_htf_bars: int = 40,
) -> dict[str, Any]:
    """If HTF TV data is thin, pull EOD OHLCV for the equity ticker."""
    prof = get_market_profile(symbol, market=market)
    if prof.get("asset_class") != "bist_equity":
        return ohlcv

    htf = ohlcv.get("htf") or {}
    n = len(htf.get("closes") or [])
    dq = ohlcv.get("data_quality") or {}
    flag = dq.get("flag")
    need = n < min_htf_bars or flag in ("insufficient", "thin", "stale")
    if not need:
        return ohlcv

    core = symbol.split(":")[-1].upper()
    try:
        bars = await fetch_eod_ohlcv(core, period="6mo")
    except Exception:
        return ohlcv
    if not bars or len(bars) < min_htf_bars:
        return ohlcv

    eod = _bars_to_ohlcv(bars)
    if len(eod["closes"]) < min_htf_bars:
        return ohlcv

    ac = prof.get("asset_class") or "bist_equity"
    htf_q = assess_ohlcv_quality(
        eod["closes"],
        eod["highs"],
        eod["lows"],
        times=eod.get("times"),
        volumes=eod.get("volumes"),
        asset_class=ac,
    )
    ltf_q = ohlcv.get("data_quality_ltf") or ohlcv.get("data_quality") or {}
    out = dict(ohlcv)
    out["htf"] = eod
    out["htf_bar_count"] = len(eod["closes"])
    out["htf_eod_fallback"] = True
    out["data_quality_htf"] = htf_q
    out["data_quality"] = merge_mtf_data_quality(htf_q, ltf_q)
    return out


def apply_eod_htf_fallback(
    ohlcv: dict[str, Any],
    *,
    symbol: str,
    market: str | None = None,
) -> dict[str, Any]:
    return asyncio.run(
        apply_eod_htf_fallback_async(ohlcv, symbol=symbol, market=market)
    )


__all__ = ["apply_eod_htf_fallback", "apply_eod_htf_fallback_async"]

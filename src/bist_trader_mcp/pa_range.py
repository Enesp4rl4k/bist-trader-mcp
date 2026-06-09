"""Range trade engine — box detection, premium/discount, liquidity sweeps, fade/breakout."""

from __future__ import annotations

from typing import Any, Literal

RangeZone = Literal["discount", "equilibrium", "premium"]
RangePlay = Literal[
    "fade_long",
    "fade_short",
    "breakout_long",
    "breakout_short",
    "sweep_fade_long",
    "sweep_fade_short",
    "wait_mid",
    "no_range",
]


def _count_touches(
    highs: list[float],
    lows: list[float],
    level: float,
    *,
    side: Literal["high", "low"],
    tolerance_pct: float = 0.006,
) -> int:
    """Bars that tested range boundary (wick reached level band)."""
    touches = 0
    if level <= 0:
        return 0
    band = level * tolerance_pct
    for i in range(len(highs)):
        if side == "high" and highs[i] >= level - band:
            touches += 1
        elif side == "low" and lows[i] <= level + band:
            touches += 1
    return touches


def _find_equal_liquidity(
    swing_prices: list[float],
    tolerance_pct: float = 0.003,
) -> list[dict[str, Any]]:
    """Equal highs/lows clusters — liquidity pools."""
    if len(swing_prices) < 2:
        return []
    pools: list[dict[str, Any]] = []
    used: set[int] = set()
    for i, p in enumerate(swing_prices):
        if i in used:
            continue
        cluster = [p]
        idxs = [i]
        for j in range(i + 1, len(swing_prices)):
            if j in used:
                continue
            centre = sum(cluster) / len(cluster)
            if centre > 0 and abs(swing_prices[j] - centre) / centre <= tolerance_pct:
                cluster.append(swing_prices[j])
                idxs.append(j)
        if len(cluster) >= 2:
            for k in idxs:
                used.add(k)
            pools.append({
                "price": sum(cluster) / len(cluster),
                "touches": len(cluster),
                "prices": cluster,
            })
    return pools


def detect_trading_range(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    *,
    atr_val: float | None = None,
    window: int = 48,
    max_width_atr: float = 4.0,
    min_touches_each_side: int = 2,
) -> dict[str, Any]:
    """Identify horizontal range box and quality metrics."""
    n = len(closes)
    if n < max(window, 20):
        return {"active": False, "reason": "insufficient_bars"}

    w = min(window, n)
    seg_h = highs[-w:]
    seg_l = lows[-w:]
    seg_c = closes[-w:]

    range_high = max(seg_h)
    range_low = min(seg_l)
    close = closes[-1]
    width = range_high - range_low
    if width <= 0:
        return {"active": False, "reason": "zero_width"}

    mid = (range_high + range_low) / 2
    width_atr = width / atr_val if atr_val and atr_val > 0 else None

    touches_h = _count_touches(seg_h, seg_l, range_high, side="high")
    touches_l = _count_touches(seg_h, seg_l, range_low, side="low")

    inside_ratio = sum(1 for c in seg_c if range_low <= c <= range_high) / len(seg_c)
    position_pct = (close - range_low) / width if width else 0.5
    position_pct = max(0.0, min(1.0, position_pct))

    if position_pct <= 0.33:
        zone: RangeZone = "discount"
    elif position_pct >= 0.67:
        zone: RangeZone = "premium"
    else:
        zone = "equilibrium"

    width_ok = width_atr is None or width_atr <= max_width_atr
    touch_ok = touches_h >= min_touches_each_side and touches_l >= min_touches_each_side
    active = width_ok and touch_ok and inside_ratio >= 0.72

    quality = 0.0
    if active:
        quality = 40.0
        quality += min(25, touches_h * 5 + touches_l * 5)
        quality += inside_ratio * 20
        if width_atr and width_atr <= 2.5:
            quality += 15
        quality = min(100.0, quality)

    return {
        "active": active,
        "range_high": round(range_high, 8),
        "range_low": round(range_low, 8),
        "range_mid": round(mid, 8),
        "range_width": round(width, 8),
        "width_atr_ratio": round(width_atr, 3) if width_atr else None,
        "touches_high": touches_h,
        "touches_low": touches_l,
        "inside_ratio": round(inside_ratio, 3),
        "position_pct": round(position_pct, 4),
        "zone": zone,
        "quality_score": round(quality, 1),
        "window_bars": w,
    }


def detect_liquidity_sweep(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    range_box: dict[str, Any],
    *,
    lookback: int = 8,
) -> dict[str, Any] | None:
    """Recent sweep above range high or below range low with close back inside."""
    if not range_box.get("active"):
        return None
    rh = float(range_box["range_high"])
    rl = float(range_box["range_low"])
    n = len(closes)
    if n < lookback + 1:
        return None

    for j in range(n - lookback, n):
        if highs[j] > rh * 1.0008 and closes[j] < rh * 0.9995:
            return {
                "kind": "sweep_high",
                "bar": j,
                "wick": highs[j],
                "level": rh,
                "close": closes[j],
                "play": "sweep_fade_short",
            }
        if lows[j] < rl * 0.9992 and closes[j] > rl * 1.0005:
            return {
                "kind": "sweep_low",
                "bar": j,
                "wick": lows[j],
                "level": rl,
                "close": closes[j],
                "play": "sweep_fade_long",
            }
    return None


def recommend_range_play(
    range_box: dict[str, Any],
    sweep: dict[str, Any] | None,
    *,
    close: float,
    structure: str,
) -> dict[str, Any]:
    """Primary range trade idea (fade vs breakout vs wait)."""
    if not range_box.get("active"):
        return {"play": "no_range", "direction": None, "confidence": 0}

    zone = range_box.get("zone")
    rh = float(range_box["range_high"])
    rl = float(range_box["range_low"])
    mid = float(range_box["range_mid"])
    q = float(range_box.get("quality_score") or 0)

    if sweep:
        play = sweep.get("play")
        direction = "short" if play == "sweep_fade_short" else "long"
        return {
            "play": play,
            "direction": direction,
            "confidence": min(95.0, q + 20),
            "entry_hint": rh if direction == "short" else rl,
            "stop_hint": sweep.get("wick"),
            "target_hint": mid,
            "reason": f"Liquidity {sweep.get('kind')} — fade back into range.",
        }

    if zone == "discount":
        return {
            "play": "fade_long",
            "direction": "long",
            "confidence": q + (10 if structure in ("ranging", "bullish", "transition") else -5),
            "entry_hint": rl,
            "stop_hint": rl - (rh - rl) * 0.08,
            "target_hint": mid,
            "reason": "Discount zone — buy range low / mid target.",
        }
    if zone == "premium":
        return {
            "play": "fade_short",
            "direction": "short",
            "confidence": q + (10 if structure in ("ranging", "bearish", "transition") else -5),
            "entry_hint": rh,
            "stop_hint": rh + (rh - rl) * 0.08,
            "target_hint": mid,
            "reason": "Premium zone — sell range high / mid target.",
        }
    if close > rh * 1.001:
        return {
            "play": "breakout_long",
            "direction": "long",
            "confidence": q,
            "entry_hint": rh,
            "stop_hint": mid,
            "target_hint": rh + (rh - rl),
            "reason": "Close above range — breakout long.",
        }
    if close < rl * 0.999:
        return {
            "play": "breakout_short",
            "direction": "short",
            "confidence": q,
            "entry_hint": rl,
            "stop_hint": mid,
            "target_hint": rl - (rh - rl),
            "reason": "Close below range — breakout short.",
        }
    return {
        "play": "wait_mid",
        "direction": None,
        "confidence": max(0, q - 25),
        "reason": "Equilibrium — wait for edge or sweep.",
    }


def build_range_panel(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    *,
    atr_val: float | None = None,
    swing_high_prices: list[float] | None = None,
    swing_low_prices: list[float] | None = None,
    structure: str = "ranging",
    window: int = 48,
) -> dict[str, Any]:
    """Full range + liquidity context for PA / MCP."""
    box = detect_trading_range(
        highs, lows, closes, atr_val=atr_val, window=window
    )
    sweep = detect_liquidity_sweep(highs, lows, closes, box) if box.get("active") else None
    play = recommend_range_play(box, sweep, close=closes[-1], structure=structure)

    eq_highs = _find_equal_liquidity(swing_high_prices or [])
    eq_lows = _find_equal_liquidity(swing_low_prices or [])

    return {
        "box": box,
        "liquidity_pools": {
            "equal_highs": eq_highs[:3],
            "equal_lows": eq_lows[:3],
        },
        "sweep": sweep,
        "recommended_play": play,
        "range_trade_mode": box.get("active", False),
    }


__all__ = [
    "detect_trading_range",
    "detect_liquidity_sweep",
    "recommend_range_play",
    "build_range_panel",
]

"""Price action analysis — swing structure, S/R clusters, setup hints.

Pure math on OHLCV lists. Market-agnostic: works for any asset once bars
are supplied (from TradingView data_get_ohlcv, get_crypto_klines, etc.).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from .technicals import atr

Direction = Literal["long", "short", "neutral"]
Structure = Literal["bullish", "bearish", "ranging", "transition"]


@dataclass(frozen=True)
class SwingPoint:
    index: int
    price: float
    kind: Literal["high", "low"]


def find_swings(
    highs: list[float],
    lows: list[float],
    lookback: int = 5,
) -> tuple[list[SwingPoint], list[SwingPoint]]:
    """Fractal swing highs/lows: extrema within ±lookback bars."""
    if lookback <= 0:
        raise ValueError("lookback must be > 0")
    n = min(len(highs), len(lows))
    if n == 0:
        return [], []

    swing_highs: list[SwingPoint] = []
    swing_lows: list[SwingPoint] = []
    for i in range(lookback, n - lookback):
        window_h = highs[i - lookback : i + lookback + 1]
        window_l = lows[i - lookback : i + lookback + 1]
        if highs[i] == max(window_h):
            swing_highs.append(SwingPoint(index=i, price=highs[i], kind="high"))
        if lows[i] == min(window_l):
            swing_lows.append(SwingPoint(index=i, price=lows[i], kind="low"))
    return swing_highs, swing_lows


def _compare_sequence(values: list[float]) -> str:
    if len(values) < 2:
        return "flat"
    higher = sum(1 for a, b in zip(values, values[1:], strict=False) if b > a)
    lower = sum(1 for a, b in zip(values, values[1:], strict=False) if b < a)
    if higher > lower:
        return "rising"
    if lower > higher:
        return "falling"
    return "flat"


def infer_market_structure(
    swing_highs: list[SwingPoint],
    swing_lows: list[SwingPoint],
    *,
    closes: list[float] | None = None,
    highs: list[float] | None = None,
    lows: list[float] | None = None,
) -> dict[str, Any]:
    """Classify HH/HL/LH/LL, BOS/CHoCH; bar fallback when swings are sparse."""
    from .pa_structure import infer_market_structure_enhanced

    return infer_market_structure_enhanced(
        swing_highs,
        swing_lows,
        closes=closes,
        highs=highs,
        lows=lows,
    )


def cluster_levels(
    prices: list[float],
    tolerance_pct: float = 0.003,
    min_touches: int = 1,
) -> list[dict[str, Any]]:
    """Group nearby price levels; rank by touch count."""
    if not prices:
        return []
    sorted_prices = sorted(prices)
    clusters: list[list[float]] = [[sorted_prices[0]]]
    for p in sorted_prices[1:]:
        centre = sum(clusters[-1]) / len(clusters[-1])
        if centre == 0 or abs(p - centre) / centre <= tolerance_pct:
            clusters[-1].append(p)
        else:
            clusters.append([p])

    out: list[dict[str, Any]] = []
    for group in clusters:
        if len(group) < min_touches:
            continue
        level = sum(group) / len(group)
        out.append({"price": level, "touches": len(group)})
    out.sort(key=lambda x: (-x["touches"], x["price"]))
    return out


def _buffer(price: float, pct: float, side: Literal["below", "above"]) -> float:
    delta = price * pct
    return price - delta if side == "below" else price + delta


def _suggest_setup(
    direction: Direction,
    close: float,
    atr_val: float | None,
    structure: Structure,
    supports: list[dict[str, Any]],
    resistances: list[dict[str, Any]],
    last_swing_high: float | None,
    last_swing_low: float | None,
    stop_buffer_pct: float = 0.001,
) -> dict[str, Any] | None:
    buffer = stop_buffer_pct
    atr_stop = (atr_val or 0.0) * 0.5

    if direction == "long":
        if structure == "bearish":
            return None
        stop_ref = last_swing_low
        if stop_ref is None:
            below = [s["price"] for s in supports if s["price"] < close]
            stop_ref = max(below) if below else close - (atr_val or close * 0.01)
        stop = _buffer(stop_ref, buffer, "below") - atr_stop * 0.25
        if stop >= close:
            stop = close - max(atr_val or close * 0.005, close * 0.003)
        targets = [r["price"] for r in resistances if r["price"] > close][:2]
        if not targets and last_swing_high and last_swing_high > close:
            targets = [last_swing_high]
        if not targets:
            risk = close - stop
            targets = [close + risk * 2.0, close + risk * 3.0]
        entry = close
        entry_style = "market"
        if supports:
            sup = supports[0]["price"]
            if sup < close and (close - sup) / close <= 0.02:
                entry = sup
                entry_style = "limit_retest_support"
        return {
            "direction": "long",
            "entry": round(entry, 8),
            "entry_style": entry_style,
            "stop": round(stop, 8),
            "targets": [round(t, 8) for t in targets],
            "rationale": (
                f"Long bias ({structure} structure): {entry_style} entry, "
                f"stop below swing low {stop_ref:.4f}, targets at resistance cluster(s)."
            ),
        }

    if direction == "short":
        if structure == "bullish":
            return None
        stop_ref = last_swing_high
        if stop_ref is None:
            above = [r["price"] for r in resistances if r["price"] > close]
            stop_ref = min(above) if above else close + (atr_val or close * 0.01)
        stop = _buffer(stop_ref, buffer, "above") + atr_stop * 0.25
        if stop <= close:
            stop = close + max(atr_val or close * 0.005, close * 0.003)
        targets = [s["price"] for s in supports if s["price"] < close][:2]
        if not targets and last_swing_low and last_swing_low < close:
            targets = [last_swing_low]
        if not targets:
            risk = stop - close
            targets = [close - risk * 2.0, close - risk * 3.0]
        entry = close
        entry_style = "market"
        if resistances:
            res = resistances[0]["price"]
            if res > close and (res - close) / close <= 0.02:
                entry = res
                entry_style = "limit_retest_resistance"
        return {
            "direction": "short",
            "entry": round(entry, 8),
            "entry_style": entry_style,
            "stop": round(stop, 8),
            "targets": [round(t, 8) for t in targets],
            "rationale": (
                f"Short bias ({structure} structure): {entry_style} entry, "
                f"stop above swing high {stop_ref:.4f}, targets at support cluster(s)."
            ),
        }
    return None


def analyze_price_action(
    closes: list[float],
    highs: list[float],
    lows: list[float],
    *,
    volumes: list[float] | None = None,
    swing_lookback: int = 5,
    sr_tolerance_pct: float = 0.003,
    stop_buffer_pct: float = 0.001,
    max_entry_chase_atr: float = 1.5,
    min_confluence: float = 40.0,
) -> dict[str, Any]:
    """Full PA panel: swings, structure, S/R, bias, suggested setups."""
    if not (len(closes) == len(highs) == len(lows)):
        raise ValueError("closes, highs, lows must be equal length")
    if len(closes) < swing_lookback * 2 + 1:
        raise ValueError("need more bars for swing detection")

    swing_highs, swing_lows = find_swings(highs, lows, lookback=swing_lookback)
    close = closes[-1]

    atr_series = atr(highs, lows, closes, 14)
    atr_val = next((v for v in reversed(atr_series) if v is not None), None)

    structure_info = infer_market_structure(
        swing_highs, swing_lows, closes=closes, highs=highs, lows=lows
    )
    structure = structure_info["structure"]

    from .pa_imbalances import build_imbalance_panel, detect_fvgs, update_fvg_lifecycle
    from .pa_range import build_range_panel

    range_panel = build_range_panel(
        highs,
        lows,
        closes,
        atr_val=atr_val,
        swing_high_prices=[s.price for s in swing_highs],
        swing_low_prices=[s.price for s in swing_lows],
        structure=structure,
    )
    box = range_panel.get("box") or {}
    if box.get("active") and float(box.get("quality_score") or 0) >= 55:
        structure = "ranging"
        structure_info = {
            **structure_info,
            "structure": "ranging",
            "range_override": True,
            "range_quality": box.get("quality_score"),
        }

    fvg_objs = update_fvg_lifecycle(
        detect_fvgs(highs, lows, closes, atr_val=atr_val),
        highs,
        lows,
        closes,
    )
    imbalance_panel = build_imbalance_panel(
        highs, lows, closes, atr_val=atr_val, range_box=box
    )
    fvg_panel = imbalance_panel

    range_ctx = {
        "box": box,
        "recommended_play": range_panel.get("recommended_play"),
        "sweep": range_panel.get("sweep"),
        "liquidity_pools": range_panel.get("liquidity_pools"),
        "stacks": imbalance_panel.get("stacks"),
        "range_aligned": imbalance_panel.get("range_aligned"),
    }

    all_highs = [s.price for s in swing_highs]
    all_lows = [s.price for s in swing_lows]
    resistances = cluster_levels(
        [p for p in all_highs if p > close],
        tolerance_pct=sr_tolerance_pct,
    )
    supports = cluster_levels(
        [p for p in all_lows if p < close],
        tolerance_pct=sr_tolerance_pct,
    )

    if structure == "bullish":
        bias: Direction = "long"
    elif structure == "bearish":
        bias = "short"
    else:
        bias = "neutral"

    from .pa_setups import build_setup_candidates, pick_best_setup, score_confluence
    from .technical_signals import compute_indicator_signals

    recent_h = structure_info.get("recent_highs") or []
    recent_l = structure_info.get("recent_lows") or []

    indicator_signals = compute_indicator_signals(
        closes,
        highs,
        lows,
        swing_highs=[{"index": s.index, "price": s.price} for s in swing_highs],
        swing_lows=[{"index": s.index, "price": s.price} for s in swing_lows],
    )

    conf_long = score_confluence(
        direction="long",
        close=close,
        supports=supports,
        resistances=resistances,
        structure=structure,
        atr_val=atr_val,
        volumes=volumes,
        fvg_objs=fvg_objs,
        structure_events=structure_info.get("structure_events"),
        range_ctx=range_ctx,
        indicator_signals=indicator_signals,
    )
    conf_short = score_confluence(
        direction="short",
        close=close,
        supports=supports,
        resistances=resistances,
        structure=structure,
        atr_val=atr_val,
        volumes=volumes,
        fvg_objs=fvg_objs,
        structure_events=structure_info.get("structure_events"),
        range_ctx=range_ctx,
        indicator_signals=indicator_signals,
    )

    long_setup = pick_best_setup(
        build_setup_candidates(
            direction="long",
            close=close,
            atr_val=atr_val,
            structure=structure,
            supports=supports,
            resistances=resistances,
            last_swing_high=structure_info.get("last_swing_high"),
            last_swing_low=structure_info.get("last_swing_low"),
            recent_highs=recent_h,
            recent_lows=recent_l,
            stop_buffer_pct=stop_buffer_pct,
            max_entry_chase_atr=max_entry_chase_atr,
            fvg_objs=fvg_objs,
            range_ctx=range_ctx,
        ),
        conf_long,
        min_confluence=min_confluence,
    )
    short_setup = pick_best_setup(
        build_setup_candidates(
            direction="short",
            close=close,
            atr_val=atr_val,
            structure=structure,
            supports=supports,
            resistances=resistances,
            last_swing_high=structure_info.get("last_swing_high"),
            last_swing_low=structure_info.get("last_swing_low"),
            recent_highs=recent_h,
            recent_lows=recent_l,
            stop_buffer_pct=stop_buffer_pct,
            max_entry_chase_atr=max_entry_chase_atr,
            fvg_objs=fvg_objs,
            range_ctx=range_ctx,
        ),
        conf_short,
        min_confluence=min_confluence,
    )

    return {
        "bars_analyzed": len(closes),
        "current_price": close,
        "atr_14": atr_val,
        "market_structure": structure,
        "structure_detail": structure_info,
        "bias": bias,
        "swing_highs": [
            {"index": s.index, "price": s.price} for s in swing_highs[-10:]
        ],
        "swing_lows": [
            {"index": s.index, "price": s.price} for s in swing_lows[-10:]
        ],
        "resistance_levels": resistances[:5],
        "support_levels": supports[:5],
        "suggested_long_setup": long_setup,
        "suggested_short_setup": short_setup,
        "confluence_long": conf_long,
        "confluence_short": conf_short,
        "fvg": fvg_panel,
        "imbalances": fvg_panel,
        "range": range_panel,
        "range_trade": range_panel.get("recommended_play"),
        "structure_events": structure_info.get("structure_events") or [],
        "bias_strength": structure_info.get("bias_strength"),
        "indicator_signals": indicator_signals,
    }


__all__ = [
    "SwingPoint",
    "find_swings",
    "infer_market_structure",
    "cluster_levels",
    "analyze_price_action",
]

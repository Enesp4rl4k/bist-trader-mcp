"""Market structure — HH/HL/LH/LL, BOS, CHoCH, bar-based fallback."""

from __future__ import annotations

from typing import Any, Literal

from .price_action import Structure, SwingPoint, _compare_sequence, find_swings

EventKind = Literal["bos_bull", "bos_bear", "choch_bull", "choch_bear"]


def _label_pivot_sequence(
    swing_highs: list[SwingPoint],
    swing_lows: list[SwingPoint],
) -> tuple[list[str], list[str], list[str]]:
    """Time-ordered HH/LH and HL/LL labels."""
    events: list[tuple[int, float, str]] = []
    for s in swing_highs:
        events.append((s.index, s.price, "H"))
    for s in swing_lows:
        events.append((s.index, s.price, "L"))
    events.sort(key=lambda x: x[0])

    high_labels: list[str] = []
    low_labels: list[str] = []
    timeline: list[str] = []
    last_h: float | None = None
    last_l: float | None = None

    for _idx, price, kind in events:
        if kind == "H":
            if last_h is not None:
                lab = "HH" if price > last_h else "LH"
                high_labels.append(lab)
                timeline.append(lab)
            last_h = price
        else:
            if last_l is not None:
                lab = "HL" if price > last_l else "LL"
                low_labels.append(lab)
                timeline.append(lab)
            last_l = price

    return high_labels, low_labels, timeline


def _structure_from_labels(
    high_labels: list[str],
    low_labels: list[str],
) -> Structure:
    recent_h = high_labels[-2:] if high_labels else []
    recent_l = low_labels[-2:] if low_labels else []
    bull_pts = sum(1 for x in recent_h + recent_l if x in ("HH", "HL"))
    bear_pts = sum(1 for x in recent_h + recent_l if x in ("LH", "LL"))
    hh = "HH" in recent_h
    hl = "HL" in recent_l
    lh = "LH" in recent_h
    ll = "LL" in recent_l

    if (hh and hl) or (bull_pts >= 2 and bear_pts == 0):
        return "bullish"
    if (lh and ll) or (bear_pts >= 2 and bull_pts == 0):
        return "bearish"
    if (hh and ll) or (lh and hl) or (bull_pts > 0 and bear_pts > 0):
        return "transition"
    return "ranging"


def detect_structure_events(
    swing_highs: list[SwingPoint],
    swing_lows: list[SwingPoint],
    closes: list[float],
    *,
    high_labels: list[str],
    low_labels: list[str],
) -> list[dict[str, Any]]:
    """BOS = continuation break; CHoCH = first break against prior bias."""
    events: list[dict[str, Any]] = []
    if not closes:
        return events
    close = closes[-1]
    last_h = swing_highs[-1].price if swing_highs else None
    last_l = swing_lows[-1].price if swing_lows else None
    if last_h is None or last_l is None:
        return events

    bias = _structure_from_labels(high_labels, low_labels)
    if bias == "bullish":
        if close > last_h * 1.0005:
            events.append({"kind": "bos_bull", "level": last_h, "detail": "Close above last swing high"})
        if close < last_l * 0.9995 and low_labels and low_labels[-1] == "LL":
            events.append({"kind": "choch_bear", "level": last_l, "detail": "Close below last swing low (LL)"})
    elif bias == "bearish":
        if close < last_l * 0.9995:
            events.append({"kind": "bos_bear", "level": last_l, "detail": "Close below last swing low"})
        if close > last_h * 1.0005 and high_labels and high_labels[-1] == "HH":
            events.append({"kind": "choch_bull", "level": last_h, "detail": "Close above last swing high (HH)"})
    return events


def infer_bar_market_structure(
    closes: list[float],
    highs: list[float],
    lows: list[float],
    *,
    window: int = 24,
    micro_lookback: int = 2,
) -> dict[str, Any] | None:
    """Fallback when fractal swings are sparse (smooth trends)."""
    n = len(closes)
    if n < window:
        return None

    seg_c = closes[-window:]
    seg_h = highs[-window:]
    seg_l = lows[-window:]
    slope_pct = (seg_c[-1] - seg_c[0]) / seg_c[0] if seg_c[0] else 0.0

    sh, sl = find_swings(seg_h, seg_l, lookback=micro_lookback)
    if len(sh) >= 2 and len(sl) >= 2:
        hi = [s.price for s in sh[-3:]]
        lo = [s.price for s in sl[-3:]]
        seq_h = _compare_sequence(hi)
        seq_l = _compare_sequence(lo)
        if seq_h == "rising" and seq_l == "rising":
            structure: Structure = "bullish"
        elif seq_h == "falling" and seq_l == "falling":
            structure = "bearish"
        elif seq_h == "rising" or seq_l == "rising":
            structure = "transition"
        else:
            structure = "ranging"
        return {
            "structure": structure,
            "source": "bar_micro_swings",
            "slope_pct": round(slope_pct, 6),
            "recent_highs": hi,
            "recent_lows": lo,
        }

    if slope_pct > 0.012:
        return {
            "structure": "bullish",
            "source": "bar_slope",
            "slope_pct": round(slope_pct, 6),
            "recent_highs": [max(seg_h)],
            "recent_lows": [min(seg_l)],
        }
    if slope_pct < -0.012:
        return {
            "structure": "bearish",
            "source": "bar_slope",
            "slope_pct": round(slope_pct, 6),
            "recent_highs": [max(seg_h)],
            "recent_lows": [min(seg_l)],
        }
    return {
        "structure": "ranging",
        "source": "bar_flat",
        "slope_pct": round(slope_pct, 6),
        "recent_highs": [max(seg_h[-12:])],
        "recent_lows": [min(seg_l[-12:])],
    }


def infer_market_structure_enhanced(
    swing_highs: list[SwingPoint],
    swing_lows: list[SwingPoint],
    *,
    closes: list[float] | None = None,
    highs: list[float] | None = None,
    lows: list[float] | None = None,
) -> dict[str, Any]:
    """HH/HL/LH/LL + BOS/CHoCH; bar fallback when pivots are thin."""
    high_labels, low_labels, timeline = _label_pivot_sequence(swing_highs, swing_lows)
    high_prices = [s.price for s in swing_highs[-4:]]
    low_prices = [s.price for s in swing_lows[-4:]]

    structure = _structure_from_labels(high_labels, low_labels)
    source = "swing_pivots"

    if len(swing_highs) < 2 or len(swing_lows) < 2:
        if closes and highs and lows:
            bar_info = infer_bar_market_structure(closes, highs, lows)
            if bar_info:
                structure = bar_info["structure"]
                source = bar_info["source"]
                high_prices = bar_info.get("recent_highs") or high_prices
                low_prices = bar_info.get("recent_lows") or low_prices

    events: list[dict[str, Any]] = []
    if closes:
        events = detect_structure_events(
            swing_highs, swing_lows, closes,
            high_labels=high_labels, low_labels=low_labels,
        )

    return {
        "structure": structure,
        "structure_source": source,
        "swing_labels": timeline,
        "high_swing_labels": high_labels,
        "low_swing_labels": low_labels,
        "last_swing_high": high_prices[-1] if high_prices else None,
        "last_swing_low": low_prices[-1] if low_prices else None,
        "recent_highs": high_prices,
        "recent_lows": low_prices,
        "structure_events": events,
        "bias_strength": _bias_strength(high_labels, low_labels, structure),
    }


def _bias_strength(
    high_labels: list[str],
    low_labels: list[str],
    structure: Structure,
) -> float:
    """0–1 clarity of structural bias."""
    if structure in ("ranging", "transition"):
        return 0.35
    tags = high_labels[-3:] + low_labels[-3:]
    if not tags:
        return 0.4
    if structure == "bullish":
        hits = sum(1 for t in tags if t in ("HH", "HL"))
    else:
        hits = sum(1 for t in tags if t in ("LH", "LL"))
    return round(min(1.0, 0.5 + hits * 0.15), 2)


__all__ = [
    "infer_market_structure_enhanced",
    "infer_bar_market_structure",
    "detect_structure_events",
    "_label_pivot_sequence",
]

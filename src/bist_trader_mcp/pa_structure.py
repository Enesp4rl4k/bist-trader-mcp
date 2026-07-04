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
    opens: list[float] | None = None,
    atr_val: float | None = None,
) -> list[dict[str, Any]]:
    """BOS = continuation break; CHoCH = first break; MSS = break with displacement."""
    events: list[dict[str, Any]] = []
    if not closes:
        return events
    close = closes[-1]
    last_h = swing_highs[-1].price if swing_highs else None
    last_l = swing_lows[-1].price if swing_lows else None
    if last_h is None or last_l is None:
        return events

    atr_threshold = atr_val if atr_val and atr_val > 0 else close * 0.01
    has_displacement = False
    if opens and len(opens) == len(closes):
        body = abs(close - opens[-1])
        has_displacement = body >= atr_threshold * 0.50

    bias = _structure_from_labels(high_labels, low_labels)
    if bias == "bullish":
        if close > last_h * 1.0005:
            kind = "mss_bull" if has_displacement else "bos_bull"
            events.append({"kind": kind, "level": last_h, "detail": f"Close above last swing high ({'with displacement' if has_displacement else 'normal'})"})
        if close < last_l * 0.9995 and low_labels and low_labels[-1] == "LL":
            kind = "mss_bear" if has_displacement else "choch_bear"
            events.append({"kind": kind, "level": last_l, "detail": "Close below last swing low (LL)"})
    elif bias == "bearish":
        if close < last_l * 0.9995:
            kind = "mss_bear" if has_displacement else "bos_bear"
            events.append({"kind": kind, "level": last_l, "detail": f"Close below last swing low ({'with displacement' if has_displacement else 'normal'})"})
        if close > last_h * 1.0005 and high_labels and high_labels[-1] == "HH":
            kind = "mss_bull" if has_displacement else "choch_bull"
            events.append({"kind": kind, "level": last_h, "detail": "Close above last swing high (HH)"})
    elif bias in ("transition", "ranging"):
        if close > last_h * 1.0005:
            kind = "mss_bull" if has_displacement else "choch_bull"
            events.append({"kind": kind, "level": last_h, "detail": "Bullish breakout from range/transition"})
        elif close < last_l * 0.9995:
            kind = "mss_bear" if has_displacement else "choch_bear"
            events.append({"kind": kind, "level": last_l, "detail": "Bearish breakout from range/transition"})
    return events


def classify_strong_weak_pivots(
    swing_highs: list[SwingPoint],
    swing_lows: list[SwingPoint],
    closes: list[float],
) -> dict[str, list[dict[str, Any]]]:
    """Identify Strong/Weak Highs and Lows based on SMC principles.

    - Strong Low: Swept a previous low or caused a bullish breakout (BOS/CHoCH/MSS).
    - Weak Low: Failed to break a swing high.
    - Strong High: Swept a previous high or caused a bearish breakout.
    - Weak High: Failed to break a swing low.
    """
    sh_classified = []
    sl_classified = []

    # Classify swing highs
    for i, sh in enumerate(swing_highs):
        is_strong = False
        reason = "normal"
        # 1. Sweep check
        if i > 0 and sh.price > swing_highs[i - 1].price:
            is_strong = True
            reason = "liquidity_sweep"
        # 2. Break check (did it lead to a break of a swing low)
        sh_idx = sh.index
        for sl in swing_lows:
            if sl.index < sh_idx:
                for c in closes[sh_idx:]:
                    if c < sl.price:
                        is_strong = True
                        reason = "caused_breakout"
                        break
            if is_strong:
                break
        sh_classified.append({
            "index": sh.index,
            "price": sh.price,
            "strength": "strong" if is_strong else "weak",
            "reason": reason,
        })

    # Classify swing lows
    for i, sl in enumerate(swing_lows):
        is_strong = False
        reason = "normal"
        # 1. Sweep check
        if i > 0 and sl.price < swing_lows[i - 1].price:
            is_strong = True
            reason = "liquidity_sweep"
        # 2. Break check (did it lead to a break of a swing high)
        sl_idx = sl.index
        for sh in swing_highs:
            if sh.index < sl_idx:
                for c in closes[sl_idx:]:
                    if c > sh.price:
                        is_strong = True
                        reason = "caused_breakout"
                        break
            if is_strong:
                break
        sl_classified.append({
            "index": sl.index,
            "price": sl.price,
            "strength": "strong" if is_strong else "weak",
            "reason": reason,
        })

    return {"swing_highs": sh_classified, "swing_lows": sl_classified}


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


def detect_pivot_sweeps(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    swing_highs: list[SwingPoint],
    swing_lows: list[SwingPoint],
    *,
    lookback: int = 8,
) -> dict[str, Any | None]:
    """Detect general BSL/SSL sweeps of recent swing high/low pivots."""
    n = len(closes)
    if n < lookback + 1 or not swing_highs or not swing_lows:
        return {"bsl_sweep": None, "ssl_sweep": None}

    recent_sh = sorted(swing_highs[-3:], key=lambda s: s.index)
    recent_sl = sorted(swing_lows[-3:], key=lambda s: s.index)

    bsl = None
    ssl = None
    current_close = closes[-1]

    # BSL Sweep check (sweep of recent swing highs)
    for sh in reversed(recent_sh):
        level = sh.price
        for j in range(n - lookback, n):
            if highs[j] > level * 1.0005 and closes[j] < level * 0.9995:
                if current_close < level:
                    bsl = {
                        "kind": "bsl_sweep",
                        "bar": j,
                        "level": level,
                        "extreme": highs[j],
                        "close": current_close,
                        "play": "sweep_fade_short",
                    }
                    break
        if bsl:
            break

    # SSL Sweep check (sweep of recent swing lows)
    for sl in reversed(recent_sl):
        level = sl.price
        for j in range(n - lookback, n):
            if lows[j] < level * 0.9995 and closes[j] > level * 1.0005:
                if current_close > level:
                    ssl = {
                        "kind": "ssl_sweep",
                        "bar": j,
                        "level": level,
                        "extreme": lows[j],
                        "close": current_close,
                        "play": "sweep_fade_long",
                    }
                    break
        if ssl:
            break

    return {"bsl_sweep": bsl, "ssl_sweep": ssl}


def infer_market_structure_enhanced(
    swing_highs: list[SwingPoint],
    swing_lows: list[SwingPoint],
    *,
    closes: list[float] | None = None,
    highs: list[float] | None = None,
    lows: list[float] | None = None,
    opens: list[float] | None = None,
    atr_val: float | None = None,
) -> dict[str, Any]:
    """HH/HL/LH/LL + BOS/CHoCH/MSS; bar fallback when pivots are thin."""
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
            opens=opens, atr_val=atr_val,
        )

    classified = {}
    if closes:
        classified = classify_strong_weak_pivots(swing_highs, swing_lows, closes)

    swing_leg = {}
    if high_prices and low_prices:
        last_h = high_prices[-1]
        last_l = low_prices[-1]
        width = abs(last_h - last_l)
        if width > 0:
            mid = (last_h + last_l) / 2
            current_close = closes[-1] if closes else mid
            position_pct = (current_close - last_l) / width
            zone = "discount" if position_pct < 0.50 else "premium"
            
            swing_leg = {
                "active": True,
                "high": last_h,
                "low": last_l,
                "mid": mid,
                "width": width,
                "position_pct": round(position_pct, 4),
                "zone": zone,
                "fib_levels": {
                    "0.0": round(last_l, 8),
                    "0.25": round(last_l + width * 0.25, 8),
                    "0.50": round(mid, 8),
                    "0.75": round(last_l + width * 0.75, 8),
                    "1.0": round(last_h, 8),
                    "ote_long_low": round(last_l + width * 0.214, 8),
                    "ote_long_high": round(last_l + width * 0.382, 8),
                    "ote_short_low": round(last_l + width * 0.618, 8),
                    "ote_short_high": round(last_l + width * 0.786, 8),
                }
            }

    sweeps = {"bsl_sweep": None, "ssl_sweep": None}
    if closes and highs and lows:
        sweeps = detect_pivot_sweeps(highs, lows, closes, swing_highs, swing_lows)

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
        "classified_pivots": classified,
        "swing_leg": swing_leg,
        "sweeps": sweeps,
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
    "classify_strong_weak_pivots",
    "detect_pivot_sweeps",
    "_label_pivot_sequence",
]

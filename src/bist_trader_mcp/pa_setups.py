"""Price Action setup builders — retest, breakout, range fade + confluence."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

Direction = Literal["long", "short"]
Structure = Literal["bullish", "bearish", "ranging", "transition"]

if TYPE_CHECKING:
    pass


def _buffer(price: float, pct: float, side: Literal["below", "above"]) -> float:
    delta = price * pct
    return price - delta if side == "below" else price + delta


def _near_level(close: float, level: float, pct: float) -> bool:
    if level <= 0:
        return False
    return abs(close - level) / level <= pct


def score_confluence(
    *,
    direction: Direction,
    close: float,
    supports: list[dict[str, Any]],
    resistances: list[dict[str, Any]],
    structure: Structure,
    atr_val: float | None,
    volumes: list[float] | None,
    fvg_objs: list[Any] | None = None,
    structure_events: list[dict[str, Any]] | None = None,
    range_ctx: dict[str, Any] | None = None,
    indicator_signals: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """0–100 confluence for a direction."""
    score = 40.0
    factors: list[str] = []

    if direction == "long":
        if structure == "bullish":
            score += 22
            factors.append("bullish_structure")
        elif structure == "transition":
            score += 8
        elif structure == "bearish":
            score -= 25
        if supports and _near_level(close, float(supports[0]["price"]), 0.015):
            score += 18
            factors.append("near_support")
        if resistances:
            room = float(resistances[0]["price"]) - close
            if close > 0 and room / close > 0.01:
                score += 10
                factors.append("room_to_resistance")
    else:
        if structure == "bearish":
            score += 22
            factors.append("bearish_structure")
        elif structure == "transition":
            score += 8
        elif structure == "bullish":
            score -= 25
        if resistances and _near_level(close, float(resistances[0]["price"]), 0.015):
            score += 18
            factors.append("near_resistance")
        if supports:
            room = close - float(supports[0]["price"])
            if close > 0 and room / close > 0.01:
                score += 10
                factors.append("room_to_support")

    if volumes and len(volumes) >= 5:
        avg = sum(float(v) for v in volumes[-20:]) / min(20, len(volumes))
        last = float(volumes[-1])
        if avg > 0 and last >= avg * 1.15:
            score += 8
            factors.append("volume_expansion")

    if fvg_objs:
        from .pa_imbalances import nearest_fvg_for_direction

        zone = nearest_fvg_for_direction(fvg_objs, close, direction)
        if zone:
            if zone.status in ("open", "partial"):
                score += 14
                factors.append(f"fvg_{zone.direction}_in_zone")
            elif zone.status == "inverted":
                score += 12
                factors.append(f"ifvg_{zone.ifvg_side}")

    for ev in structure_events or []:
        kind = ev.get("kind")
        if direction == "long" and kind in ("bos_bull", "choch_bull"):
            score += 10
            factors.append(kind)
        if direction == "short" and kind in ("bos_bear", "choch_bear"):
            score += 10
            factors.append(kind)
        if direction == "long" and kind == "choch_bear":
            score -= 15
            factors.append("choch_against_long")
        if direction == "short" and kind == "choch_bull":
            score -= 15
            factors.append("choch_against_short")

    box = (range_ctx or {}).get("box") or {}
    play = (range_ctx or {}).get("recommended_play") or {}
    if box.get("active"):
        zone = box.get("zone")
        q = float(box.get("quality_score") or 0)
        if direction == "long" and zone == "discount":
            score += 16 + min(10, q / 10)
            factors.append("range_discount_long")
        if direction == "short" and zone == "premium":
            score += 16 + min(10, q / 10)
            factors.append("range_premium_short")
        if direction == "long" and play.get("play") in ("sweep_fade_long", "fade_long"):
            score += 12
            factors.append(play.get("play", "range_play"))
        if direction == "short" and play.get("play") in ("sweep_fade_short", "fade_short"):
            score += 12
            factors.append(play.get("play", "range_play"))
        if zone == "equilibrium" and structure == "ranging":
            score -= 8
            factors.append("range_mid_avoid")
        align = (range_ctx or {}).get("range_aligned") or {}
        if direction == "long" and align.get("aligned_long"):
            score += 10
            factors.append("imbalance_stack_range_long")
        if direction == "short" and align.get("aligned_short"):
            score += 10
            factors.append("imbalance_stack_range_short")
        stacks = (range_ctx or {}).get("stacks") or []
        for st in stacks:
            if direction == "long" and st.get("direction") == "bullish":
                score += 6
                factors.append("bullish_imbalance_stack")
            if direction == "short" and st.get("direction") == "bearish":
                score += 6
                factors.append("bearish_imbalance_stack")

    if indicator_signals is not None:
        from .technical_signals import confluence_adjustment

        delta, ind_factors = confluence_adjustment(indicator_signals, direction)
        score += delta
        factors.extend(ind_factors)

    return {
        "score": round(min(100.0, max(0.0, score)), 1),
        "factors": factors,
    }


def build_setup_candidates(
    *,
    direction: Direction,
    close: float,
    atr_val: float | None,
    structure: Structure,
    supports: list[dict[str, Any]],
    resistances: list[dict[str, Any]],
    last_swing_high: float | None,
    last_swing_low: float | None,
    recent_highs: list[float],
    recent_lows: list[float],
    stop_buffer_pct: float = 0.001,
    max_entry_chase_atr: float = 1.5,
    fvg_objs: list[Any] | None = None,
    range_ctx: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Ranked setup candidates for one direction."""
    box = (range_ctx or {}).get("box") or {}
    range_active = bool(box.get("active"))
    if direction == "long" and structure == "bearish" and not range_active:
        return []
    if direction == "short" and structure == "bullish" and not range_active:
        return []

    buffer = stop_buffer_pct
    atr_stop = (atr_val or 0.0) * 0.5
    candidates: list[dict[str, Any]] = []

    def _chase_ok(entry: float) -> bool:
        if not atr_val or atr_val <= 0:
            return True
        return abs(entry - close) / atr_val <= max_entry_chase_atr

    # 1) Trend retest
    if direction == "long" and supports:
        sup = float(supports[0]["price"])
        stop_ref = last_swing_low or sup
        stop = _buffer(stop_ref, buffer, "below") - atr_stop * 0.25
        if stop >= close:
            stop = close - max(atr_val or close * 0.005, close * 0.003)
        entry = sup if _near_level(close, sup, 0.02) else close
        if _chase_ok(entry):
            targets = [r["price"] for r in resistances if r["price"] > entry][:2]
            if not targets and last_swing_high:
                targets = [last_swing_high]
            if not targets:
                risk = entry - stop
                targets = [entry + risk * 2.0]
            candidates.append({
                "setup_type": "trend_retest_long",
                "direction": "long",
                "entry": round(entry, 8),
                "entry_style": "limit_retest_support",
                "stop": round(stop, 8),
                "targets": [round(t, 8) for t in targets],
                "priority": 90 if structure == "bullish" else 65,
                "rationale": "Trend retest long at support cluster / HL context.",
            })

    if direction == "short" and resistances:
        res = float(resistances[0]["price"])
        stop_ref = last_swing_high or res
        stop = _buffer(stop_ref, buffer, "above") + atr_stop * 0.25
        if stop <= close:
            stop = close + max(atr_val or close * 0.005, close * 0.003)
        entry = res if _near_level(close, res, 0.02) else close
        if _chase_ok(entry):
            targets = [s["price"] for s in supports if s["price"] < entry][:2]
            if not targets and last_swing_low:
                targets = [last_swing_low]
            if not targets:
                risk = stop - entry
                targets = [entry - risk * 2.0]
            candidates.append({
                "setup_type": "trend_retest_short",
                "direction": "short",
                "entry": round(entry, 8),
                "entry_style": "limit_retest_resistance",
                "stop": round(stop, 8),
                "targets": [round(t, 8) for t in targets],
                "priority": 90 if structure == "bearish" else 65,
                "rationale": "Trend retest short at resistance cluster / LH context.",
            })

    # 2) Breakout + retest (recent range break)
    if len(recent_highs) >= 2 and len(recent_lows) >= 2:
        rh, rl = recent_highs[-1], recent_lows[-1]
        if direction == "long" and close > rh * 1.001:
            entry = rh
            stop = _buffer(rl, buffer, "below")
            if _chase_ok(entry) and stop < entry:
                risk = entry - stop
                candidates.append({
                    "setup_type": "breakout_retest_long",
                    "direction": "long",
                    "entry": round(entry, 8),
                    "entry_style": "breakout_retest",
                    "stop": round(stop, 8),
                    "targets": [round(entry + risk * 2.0, 8)],
                    "priority": 75,
                    "rationale": "Break above recent swing high — retest entry.",
                })
        if direction == "short" and close < rl * 0.999:
            entry = rl
            stop = _buffer(rh, buffer, "above")
            if _chase_ok(entry) and stop > entry:
                risk = stop - entry
                candidates.append({
                    "setup_type": "breakout_retest_short",
                    "direction": "short",
                    "entry": round(entry, 8),
                    "entry_style": "breakout_retest",
                    "stop": round(stop, 8),
                    "targets": [round(entry - risk * 2.0, 8)],
                    "priority": 75,
                    "rationale": "Break below recent swing low — retest entry.",
                })

    # 3) FVG / IFVG retest
    if fvg_objs:
        from .pa_imbalances import nearest_fvg_for_direction, price_in_zone

        zone = nearest_fvg_for_direction(fvg_objs, close, direction)
        if zone and (price_in_zone(close, zone) or abs(close - zone.mid) / max(zone.mid, 1e-9) <= 0.02):
            if direction == "long":
                entry = round(zone.mid, 8)
                stop = round(zone.bottom - max(atr_val or entry * 0.004, entry * 0.003), 8)
                if stop < entry:
                    tgt = resistances[0]["price"] if resistances else entry + (entry - stop) * 2
                    st = "fvg_retest_long" if zone.status in ("open", "partial") else "ifvg_support_long"
                    candidates.append({
                        "setup_type": st,
                        "direction": "long",
                        "entry": entry,
                        "entry_style": "fvg_mid",
                        "stop": stop,
                        "targets": [round(float(tgt), 8)],
                        "priority": 88 if zone.status in ("open", "partial") else 82,
                        "rationale": f"Long at {'FVG' if 'fvg' in st else 'IFVG'} zone {zone.bottom:.4f}-{zone.top:.4f}.",
                        "fvg_zone": zone.to_dict(),
                    })
            else:
                entry = round(zone.mid, 8)
                stop = round(zone.top + max(atr_val or entry * 0.004, entry * 0.003), 8)
                if stop > entry:
                    tgt = supports[0]["price"] if supports else entry - (stop - entry) * 2
                    st = "fvg_retest_short" if zone.status in ("open", "partial") else "ifvg_resistance_short"
                    candidates.append({
                        "setup_type": st,
                        "direction": "short",
                        "entry": entry,
                        "entry_style": "fvg_mid",
                        "stop": stop,
                        "targets": [round(float(tgt), 8)],
                        "priority": 88 if zone.status in ("open", "partial") else 82,
                        "rationale": f"Short at {'FVG' if 'fvg' in st else 'IFVG'} zone {zone.bottom:.4f}-{zone.top:.4f}.",
                        "fvg_zone": zone.to_dict(),
                    })

    # 4) Range trade (box + imbalance confluence)
    if range_active or structure == "ranging":
        rh = float(box.get("range_high") or (resistances[0]["price"] if resistances else close * 1.02))
        rl = float(box.get("range_low") or (supports[0]["price"] if supports else close * 0.98))
        rmid = float(box.get("range_mid") or (rh + rl) / 2)
        zone = box.get("zone")
        sweep = (range_ctx or {}).get("sweep")
        pad = max(atr_val or close * 0.004, (rh - rl) * 0.06)

        if direction == "long" and sweep and sweep.get("play") == "sweep_fade_long":
            entry = rl
            stop = float(sweep.get("wick") or rl) - pad * 0.5
            if stop < entry and _chase_ok(entry):
                candidates.append({
                    "setup_type": "range_sweep_fade_long",
                    "direction": "long",
                    "entry": round(entry, 8),
                    "entry_style": "liquidity_sweep",
                    "stop": round(stop, 8),
                    "targets": [round(rmid, 8), round(rh, 8)],
                    "priority": 95,
                    "rationale": "Sweep below range low — fade long to mid/upper range.",
                    "range_zone": zone,
                })

        if direction == "short" and sweep and sweep.get("play") == "sweep_fade_short":
            entry = rh
            stop = float(sweep.get("wick") or rh) + pad * 0.5
            if stop > entry and _chase_ok(entry):
                candidates.append({
                    "setup_type": "range_sweep_fade_short",
                    "direction": "short",
                    "entry": round(entry, 8),
                    "entry_style": "liquidity_sweep",
                    "stop": round(stop, 8),
                    "targets": [round(rmid, 8), round(rl, 8)],
                    "priority": 95,
                    "rationale": "Sweep above range high — fade short to mid/lower range.",
                    "range_zone": zone,
                })

        if direction == "long" and (zone == "discount" or structure == "ranging"):
            entry = rl if range_active else float(supports[0]["price"] if supports else rl)
            stop = entry - pad
            if _chase_ok(entry) and stop < entry:
                tgt = rmid if range_active else entry + (entry - stop) * 1.5
                pri = 92 if zone == "discount" and range_active else 70
                candidates.append({
                    "setup_type": "range_fade_long",
                    "direction": "long",
                    "entry": round(entry, 8),
                    "entry_style": "range_discount",
                    "stop": round(stop, 8),
                    "targets": [round(tgt, 8)],
                    "priority": pri,
                    "rationale": "Range discount — long edge targeting equilibrium.",
                    "range_zone": zone,
                })

        if direction == "short" and (zone == "premium" or structure == "ranging"):
            entry = rh if range_active else float(resistances[0]["price"] if resistances else rh)
            stop = entry + pad
            if _chase_ok(entry) and stop > entry:
                tgt = rmid if range_active else entry - (stop - entry) * 1.5
                pri = 92 if zone == "premium" and range_active else 70
                candidates.append({
                    "setup_type": "range_fade_short",
                    "direction": "short",
                    "entry": round(entry, 8),
                    "entry_style": "range_premium",
                    "stop": round(stop, 8),
                    "targets": [round(tgt, 8)],
                    "priority": pri,
                    "rationale": "Range premium — short edge targeting equilibrium.",
                    "range_zone": zone,
                })

        if direction == "long" and close > rh * 1.001 and range_active:
            entry = rh
            stop = rmid
            if _chase_ok(entry) and stop < entry:
                candidates.append({
                    "setup_type": "range_breakout_long",
                    "direction": "long",
                    "entry": round(entry, 8),
                    "entry_style": "range_break",
                    "stop": round(stop, 8),
                    "targets": [round(rh + (rh - rl), 8)],
                    "priority": 78,
                    "rationale": "Breakout above range high — retest long.",
                })
        if direction == "short" and close < rl * 0.999 and range_active:
            entry = rl
            stop = rmid
            if _chase_ok(entry) and stop > entry:
                candidates.append({
                    "setup_type": "range_breakout_short",
                    "direction": "short",
                    "entry": round(entry, 8),
                    "entry_style": "range_break",
                    "stop": round(stop, 8),
                    "targets": [round(rl - (rh - rl), 8)],
                    "priority": 78,
                    "rationale": "Breakout below range low — retest short.",
                })

    # Fallback market
    if not candidates:
        if direction == "long" and structure != "bearish":
            stop_ref = last_swing_low or (supports[0]["price"] if supports else close * 0.99)
            stop = _buffer(float(stop_ref), buffer, "below")
            targets = [r["price"] for r in resistances[:1]] or [close * 1.02]
            candidates.append({
                "setup_type": "market_long",
                "direction": "long",
                "entry": round(close, 8),
                "entry_style": "market",
                "stop": round(stop, 8),
                "targets": [round(float(targets[0]), 8)],
                "priority": 40,
                "rationale": "Fallback market long.",
            })
        if direction == "short" and structure != "bullish":
            stop_ref = last_swing_high or (resistances[0]["price"] if resistances else close * 1.01)
            stop = _buffer(float(stop_ref), buffer, "above")
            targets = [s["price"] for s in supports[:1]] or [close * 0.98]
            candidates.append({
                "setup_type": "market_short",
                "direction": "short",
                "entry": round(close, 8),
                "entry_style": "market",
                "stop": round(stop, 8),
                "targets": [round(float(targets[0]), 8)],
                "priority": 40,
                "rationale": "Fallback market short.",
            })

    return sorted(candidates, key=lambda x: -int(x.get("priority") or 0))


def pick_best_setup(
    candidates: list[dict[str, Any]],
    confluence: dict[str, Any],
    *,
    min_confluence: float = 50.0,
) -> dict[str, Any] | None:
    if not candidates:
        return None
    if float(confluence.get("score") or 0) < min_confluence:
        return None
    best = candidates[0]
    return {**best, "confluence": confluence}


__all__ = [
    "score_confluence",
    "build_setup_candidates",
    "pick_best_setup",
]

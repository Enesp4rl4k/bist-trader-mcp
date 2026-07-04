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
    block_ctx: dict[str, Any] | None = None,
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
        if direction == "long" and kind in ("bos_bull", "choch_bull", "mss_bull"):
            score += 15 if kind == "mss_bull" else 10
            factors.append(kind)
        if direction == "short" and kind in ("bos_bear", "choch_bear", "mss_bear"):
            score += 15 if kind == "mss_bear" else 10
            factors.append(kind)
        if direction == "long" and kind in ("choch_bear", "mss_bear"):
            score -= 20 if kind == "mss_bear" else 15
            factors.append("mss_against_long" if kind == "mss_bear" else "choch_against_long")
        if direction == "short" and kind in ("choch_bull", "mss_bull"):
            score -= 20 if kind == "mss_bull" else 15
            factors.append("mss_against_short" if kind == "mss_bull" else "choch_against_short")

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

        # Range deviation factor
        deviation = (range_ctx or {}).get("deviation")
        if deviation:
            if direction == "long" and deviation.get("play") == "sweep_fade_long":
                score += 18
                factors.append("range_deviation_long")
            elif direction == "short" and deviation.get("play") == "sweep_fade_short":
                score += 18
                factors.append("range_deviation_short")

    # Swing leg Premium / Discount & OTE checks
    swing_leg = (range_ctx or {}).get("swing_leg")
    if swing_leg and swing_leg.get("active"):
        zone = swing_leg.get("zone")
        if direction == "long" and zone == "premium":
            score -= 20.0
            factors.append("chasing_in_premium")
        elif direction == "short" and zone == "discount":
            score -= 20.0
            factors.append("chasing_in_discount")
            
        fibs = swing_leg.get("fib_levels") or {}
        if fibs:
            if direction == "long":
                ote_low = float(fibs.get("ote_long_low", 0))
                ote_high = float(fibs.get("ote_long_high", 0))
                if ote_low <= close <= ote_high:
                    score += 15.0
                    factors.append("swing_ote_discount_long")
            else:
                ote_low = float(fibs.get("ote_short_low", 0))
                ote_high = float(fibs.get("ote_short_high", 0))
                if ote_low <= close <= ote_high:
                    score += 15.0
                    factors.append("swing_ote_premium_short")

    # General BSL/SSL Sweep rewards
    sweeps = (range_ctx or {}).get("sweeps")
    if sweeps:
        if direction == "long" and sweeps.get("ssl_sweep"):
            score += 18.0
            factors.append("ssl_liquidity_sweep")
        elif direction == "short" and sweeps.get("bsl_sweep"):
            score += 18.0
            factors.append("bsl_liquidity_sweep")

    if block_ctx:
        obs = block_ctx.get("order_blocks") or {}
        bbs = block_ctx.get("breaker_blocks") or {}
        if direction == "long":
            for ob in obs.get("bullish") or []:
                if _near_level(close, float(ob["mid"]), 0.015):
                    score += 15
                    factors.append("near_bullish_ob")
                    break
            for bb in bbs.get("bullish") or []:
                if _near_level(close, float(bb["mid"]), 0.015):
                    score += 12
                    factors.append("near_bullish_breaker")
                    break
        else:
            for ob in obs.get("bearish") or []:
                if _near_level(close, float(ob["mid"]), 0.015):
                    score += 15
                    factors.append("near_bearish_ob")
                    break
            for bb in bbs.get("bearish") or []:
                if _near_level(close, float(bb["mid"]), 0.015):
                    score += 12
                    factors.append("near_bearish_breaker")
                    break

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
    block_ctx: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Ranked setup candidates for one direction, incorporating OBs, Breakers, and Range Deviations."""
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

    # 5) Order Block & Breaker Block setups
    if block_ctx:
        obs = block_ctx.get("order_blocks") or {}
        bbs = block_ctx.get("breaker_blocks") or {}

        if direction == "long":
            for ob in obs.get("bullish") or []:
                ob_mid = float(ob["mid"])
                ob_bot = float(ob["bottom"])
                if _near_level(close, ob_mid, 0.025) and ob_bot < close:
                    stop = ob_bot - atr_stop * 0.5
                    if _chase_ok(ob_mid) and stop < ob_mid:
                        candidates.append({
                            "setup_type": "ob_retest_long",
                            "direction": "long",
                            "entry": round(ob_mid, 8),
                            "entry_style": "limit_ob_mid",
                            "stop": round(stop, 8),
                            "targets": [round(r["price"], 8) for r in resistances[:2]] or [round(close + (ob_mid - stop) * 2.0, 8)],
                            "priority": 92,
                            "rationale": f"Bullish OB retest at {ob_mid:.4f} (OB formed at bar {ob['index']}).",
                        })
            for bb in bbs.get("bullish") or []:
                bb_mid = float(bb["mid"])
                bb_bot = float(bb["bottom"])
                if _near_level(close, bb_mid, 0.025) and bb_bot < close:
                    stop = bb_bot - atr_stop * 0.5
                    if _chase_ok(bb_mid) and stop < bb_mid:
                        candidates.append({
                            "setup_type": "breaker_retest_long",
                            "direction": "long",
                            "entry": round(bb_mid, 8),
                            "entry_style": "limit_breaker_mid",
                            "stop": round(stop, 8),
                            "targets": [round(r["price"], 8) for r in resistances[:2]] or [round(close + (bb_mid - stop) * 2.0, 8)],
                            "priority": 88,
                            "rationale": f"Bullish Breaker retest support at {bb_mid:.4f}.",
                        })
        else:
            for ob in obs.get("bearish") or []:
                ob_mid = float(ob["mid"])
                ob_top = float(ob["top"])
                if _near_level(close, ob_mid, 0.025) and ob_top > close:
                    stop = ob_top + atr_stop * 0.5
                    if _chase_ok(ob_mid) and stop > ob_mid:
                        candidates.append({
                            "setup_type": "ob_retest_short",
                            "direction": "short",
                            "entry": round(ob_mid, 8),
                            "entry_style": "limit_ob_mid",
                            "stop": round(stop, 8),
                            "targets": [round(s["price"], 8) for s in supports[:2]] or [round(close - (stop - ob_mid) * 2.0, 8)],
                            "priority": 92,
                            "rationale": f"Bearish OB retest at {ob_mid:.4f} (OB formed at bar {ob['index']}).",
                        })
            for bb in bbs.get("bearish") or []:
                bb_mid = float(bb["mid"])
                bb_top = float(bb["top"])
                if _near_level(close, bb_mid, 0.025) and bb_top > close:
                    stop = bb_top + atr_stop * 0.5
                    if _chase_ok(bb_mid) and stop > bb_mid:
                        candidates.append({
                            "setup_type": "breaker_retest_short",
                            "direction": "short",
                            "entry": round(bb_mid, 8),
                            "entry_style": "limit_breaker_mid",
                            "stop": round(stop, 8),
                            "targets": [round(s["price"], 8) for s in supports[:2]] or [round(close - (stop - bb_mid) * 2.0, 8)],
                            "priority": 88,
                            "rationale": f"Bearish Breaker retest resistance at {bb_mid:.4f}.",
                        })

    # 6) Market Structure Shift Setup
    struct_evs = range_ctx.get("structure_events") if range_ctx else []
    for ev in struct_evs or []:
        kind = ev.get("kind")
        level = float(ev.get("level") or 0)
        if direction == "long" and kind == "mss_bull":
            stop = last_swing_low or (close - (atr_val or close * 0.01) * 2.0)
            candidates.append({
                "setup_type": "mss_retest_long",
                "direction": "long",
                "entry": round(close, 8),
                "entry_style": "market_mss",
                "stop": round(stop, 8),
                "targets": [round(r["price"], 8) for r in resistances[:2]] or [round(close + (close - stop) * 2.0, 8)],
                "priority": 90,
                "rationale": f"Bullish Market Structure Shift (MSS) above {level:.4f} with displacement.",
            })
        if direction == "short" and kind == "mss_bear":
            stop = last_swing_high or (close + (atr_val or close * 0.01) * 2.0)
            candidates.append({
                "setup_type": "mss_retest_short",
                "direction": "short",
                "entry": round(close, 8),
                "entry_style": "market_mss",
                "stop": round(stop, 8),
                "targets": [round(s["price"], 8) for s in supports[:2]] or [round(close - (stop - close) * 2.0, 8)],
                "priority": 90,
                "rationale": f"Bearish Market Structure Shift (MSS) below {level:.4f} with displacement.",
            })

    # 7) Swing Leg Fibonacci OTE Setup
    swing_leg = (range_ctx or {}).get("swing_leg")
    if swing_leg and swing_leg.get("active"):
        fibs = swing_leg.get("fib_levels") or {}
        if fibs:
            if direction == "long":
                entry = float(fibs["ote_long_high"])
                stop = float(fibs["0.0"]) - atr_stop * 0.5
                if _chase_ok(entry) and stop < entry:
                    candidates.append({
                        "setup_type": "ote_retest_long",
                        "direction": "long",
                        "entry": round(entry, 8),
                        "entry_style": "limit_ote_high",
                        "stop": round(stop, 8),
                        "targets": [round(float(fibs["1.0"]), 8)],
                        "priority": 93,
                        "rationale": f"Bullish OTE Fibonacci Retracement at {entry:.4f}.",
                    })
            else:
                entry = float(fibs["ote_short_low"])
                stop = float(fibs["1.0"]) + atr_stop * 0.5
                if _chase_ok(entry) and stop > entry:
                    candidates.append({
                        "setup_type": "ote_retest_short",
                        "direction": "short",
                        "entry": round(entry, 8),
                        "entry_style": "limit_ote_low",
                        "stop": round(stop, 8),
                        "targets": [round(float(fibs["0.0"]), 8)],
                        "priority": 93,
                        "rationale": f"Bearish OTE Fibonacci Retracement at {entry:.4f}.",
                    })

    # 8) General BSL/SSL Sweep Reversal Setup
    sweeps = (range_ctx or {}).get("sweeps")
    if sweeps:
        if direction == "long" and sweeps.get("ssl_sweep"):
            sw = sweeps["ssl_sweep"]
            entry = close
            stop = float(sw["extreme"]) - atr_stop * 0.5
            if stop < entry:
                candidates.append({
                    "setup_type": "ssl_sweep_long",
                    "direction": "long",
                    "entry": round(entry, 8),
                    "entry_style": "market_sweep",
                    "stop": round(stop, 8),
                    "targets": [round(float(last_swing_high or entry * 1.02), 8)],
                    "priority": 94,
                    "rationale": f"SSL Liquidity Sweep detected at {sw['level']:.4f} (extreme {sw['extreme']:.4f}). Reversal long.",
                })
        if direction == "short" and sweeps.get("bsl_sweep"):
            sw = sweeps["bsl_sweep"]
            entry = close
            stop = float(sw["extreme"]) + atr_stop * 0.5
            if stop > entry:
                candidates.append({
                    "setup_type": "bsl_sweep_short",
                    "direction": "short",
                    "entry": round(entry, 8),
                    "entry_style": "market_sweep",
                    "stop": round(stop, 8),
                    "targets": [round(float(last_swing_low or entry * 0.98), 8)],
                    "priority": 94,
                    "rationale": f"BSL Liquidity Sweep detected at {sw['level']:.4f} (extreme {sw['extreme']:.4f}). Reversal short.",
                })

    # 9) Range Deviation Setup
    deviation = (range_ctx or {}).get("deviation")
    if deviation:
        rh = float(box.get("range_high") or close)
        rl = float(box.get("range_low") or close)
        rmid = float(box.get("range_mid") or close)
        pad = max(atr_val or close * 0.004, (rh - rl) * 0.06)

        if direction == "long" and deviation.get("play") == "sweep_fade_long":
            entry = rl
            stop = float(deviation.get("extreme_price") or rl) - pad * 0.5
            if stop < entry:
                candidates.append({
                    "setup_type": "range_deviation_long",
                    "direction": "long",
                    "entry": round(entry, 8),
                    "entry_style": "liquidity_sweep",
                    "stop": round(stop, 8),
                    "targets": [round(rmid, 8), round(rh, 8)],
                    "priority": 96,
                    "rationale": f"Range deviation low reclaimed {rl:.4f}. Fading back inside range.",
                })
        if direction == "short" and deviation.get("play") == "sweep_fade_short":
            entry = rh
            stop = float(deviation.get("extreme_price") or rh) + pad * 0.5
            if stop > entry:
                candidates.append({
                    "setup_type": "range_deviation_short",
                    "direction": "short",
                    "entry": round(entry, 8),
                    "entry_style": "liquidity_sweep",
                    "stop": round(stop, 8),
                    "targets": [round(rmid, 8), round(rl, 8)],
                    "priority": 96,
                    "rationale": f"Range deviation high rejected above {rh:.4f}. Fading back inside range.",
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

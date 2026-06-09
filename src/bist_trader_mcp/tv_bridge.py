"""TradingView Desktop bridge — subprocess wrapper for tradingview-mcp CLI."""

from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any

DEFAULT_TV_MCP = Path(r"C:\Users\parlak\Downloads\tradingview-mcp")


def tv_mcp_root() -> Path:
    env = os.environ.get("TRADINGVIEW_MCP_PATH")
    if env:
        return Path(env)
    return DEFAULT_TV_MCP


def tv_call(*args: str, timeout: int = 90) -> dict[str, Any]:
    root = tv_mcp_root()
    proc = subprocess.run(
        ["node", "src/cli/index.js", *args],
        cwd=str(root),
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    raw = (proc.stdout or proc.stderr or "").strip()
    if not raw:
        return {
            "success": False,
            "error": "empty_output",
            "detail": f"exit={proc.returncode} args={' '.join(args)}",
        }
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"success": False, "error": "invalid_json", "detail": raw[:300]}


def fetch_ohlcv_from_chart(count: int = 150) -> dict[str, Any]:
    return tv_call("ohlcv", "-n", str(count))


def chart_bar_time(fallback_bars: list[dict[str, Any]] | None = None) -> int:
    vr = tv_call("range")
    t = int((vr.get("bars_range") or {}).get("to") or (vr.get("visible_range") or {}).get("to") or 0)
    if t:
        return t
    if fallback_bars:
        return int(fallback_bars[-1].get("time") or 0)
    return int(time.time())


def _ltf_position_bar_times(ltf_times: list[int] | None) -> tuple[int, int]:
    """Place Long/Short tool on the right edge of the chart (readable box)."""
    if ltf_times and len(ltf_times) >= 12:
        t1 = int(ltf_times[-12])
        t2 = int(ltf_times[-2])
        if t2 > t1:
            return t1, t2
    bar_time = chart_bar_time()
    vr = tv_call("range")
    bar_from = int((vr.get("bars_range") or {}).get("from") or (vr.get("visible_range") or {}).get("from") or 0)
    if bar_from and bar_time > bar_from:
        span = bar_time - bar_from
        return bar_time - max(span // 6, 3600), bar_time + max(span // 12, 1800)
    return bar_time - 86400, bar_time + 86400


def _pa_context(mtf: dict[str, Any] | None, plan: dict[str, Any] | None) -> dict[str, Any]:
    if mtf and mtf.get("ltf_analysis"):
        return mtf["ltf_analysis"]
    if plan:
        pa = plan.get("price_action_context") or plan.get("price_action")
        if isinstance(pa, dict):
            return pa
    return {}


def _nearest_level(levels: list[dict[str, Any]], close: float, side: str) -> float | None:
    prices = [float(x["price"]) for x in levels if x.get("price") is not None]
    if not prices:
        return None
    if side == "below":
        below = [p for p in prices if p <= close * 1.002]
        return max(below) if below else None
    above = [p for p in prices if p >= close * 0.998]
    return min(above) if above else None


def refine_chart_trade_plan(
    plan: dict[str, Any],
    *,
    ltf_closes: list[float],
    ltf_highs: list[float],
    ltf_lows: list[float],
    mtf: dict[str, Any] | None = None,
    max_entry_chase_atr: float = 2.0,
    min_risk_reward: float = 1.8,
) -> dict[str, Any]:
    """Tune entry/stop/target for a readable TV Long/Short box (display-only copy)."""
    if plan.get("error") or plan.get("entry") is None or plan.get("stop") is None:
        return plan

    out = dict(plan)
    direction = str(plan.get("direction") or "long")
    close = float(ltf_closes[-1])
    pa = _pa_context(mtf, plan)
    atr = float(pa.get("atr_14") or 0.0)
    if atr <= 0 and len(ltf_closes) >= 15:
        trs = [
            max(ltf_highs[i] - ltf_lows[i], abs(ltf_highs[i] - ltf_closes[i - 1]))
            for i in range(1, len(ltf_closes))
        ]
        atr = sum(trs[-14:]) / min(14, len(trs))

    supports = pa.get("support_levels") or []
    resistances = pa.get("resistance_levels") or []
    entry = float(plan["entry"])
    stop = float(plan["stop"])

    swing_low = pa.get("last_swing_low")
    if swing_low is None:
        swing_low = (pa.get("structure_detail") or {}).get("last_swing_low")
    if direction == "long":
        retest = _nearest_level(supports, close, "below")
        if retest is not None:
            entry = retest
        elif atr > 0 and entry > close + atr * max_entry_chase_atr:
            entry = close
        if isinstance(swing_low, (int, float)):
            stop = min(stop, float(swing_low) * 0.998)
        elif retest is not None:
            stop = min(stop, retest * 0.995)
        if stop >= entry:
            stop = entry - max(atr * 0.8, entry * 0.008)
        target_px = _nearest_level(resistances, entry, "above")
        if target_px is None:
            risk = entry - stop
            target_px = entry + risk * min_risk_reward
    else:
        retest = _nearest_level(resistances, close, "above")
        if retest is not None:
            entry = retest
        elif atr > 0 and entry < close - atr * max_entry_chase_atr:
            entry = close
        swing_high = pa.get("last_swing_high")
        if swing_high is None:
            swing_high = (pa.get("structure_detail") or {}).get("last_swing_high")
        if isinstance(swing_high, (int, float)):
            stop = max(stop, float(swing_high) * 1.002)
        elif retest is not None:
            stop = max(stop, retest * 1.005)
        if stop <= entry:
            stop = entry + max(atr * 0.8, entry * 0.008)
        target_px = _nearest_level(supports, entry, "below")
        if target_px is None:
            risk = stop - entry
            target_px = entry - risk * min_risk_reward

    risk = abs(entry - stop)
    reward = abs(target_px - entry)
    rr = reward / risk if risk > 0 else 0.0
    if rr < min_risk_reward:
        if direction == "long":
            target_px = entry + risk * min_risk_reward
        else:
            target_px = entry - risk * min_risk_reward
        rr = min_risk_reward

    out["entry"] = round(entry, 8)
    out["stop"] = round(stop, 8)
    out["targets"] = [{"label": "TP1", "price": round(target_px, 8), "risk_reward": round(rr, 2)}]
    out["best_risk_reward"] = round(max(rr, min_risk_reward), 2)
    out["chart_refined"] = True
    return out


def plan_has_trade_levels(plan: dict[str, Any] | None) -> bool:
    if not plan or plan.get("error"):
        return False
    return plan.get("entry") is not None and plan.get("stop") is not None


def build_demo_position_plan(
    *,
    symbol: str,
    mtf: dict[str, Any],
    ltf_closes: list[float],
    ltf_highs: list[float],
    ltf_lows: list[float],
    equity: float = 100_000.0,
    risk_per_trade_pct: float = 1.0,
    min_risk_reward: float = 1.2,
    min_trade_quality: str = "a",
) -> dict[str, Any] | None:
    """Produce a chart-friendly plan when MTF setup is aligned (screenshots / demos)."""
    from .position_design import design_trade_setup
    from .trade_playbook import _quality_rank

    if mtf.get("conflict") or mtf.get("trade_quality") in ("conflict", "no_trade"):
        return None
    if _quality_rank(str(mtf.get("trade_quality") or "no_trade")) < _quality_rank(min_trade_quality):
        return None

    setup = mtf.get("recommended_setup")
    direction = mtf.get("aligned_direction")
    if not setup or direction not in ("long", "short"):
        return None

    raw_targets = setup.get("targets") or []
    target_prices: list[float] = []
    for t in raw_targets:
        if isinstance(t, dict):
            target_prices.append(float(t["price"]))
        else:
            target_prices.append(float(t))

    plan = design_trade_setup(
        symbol=symbol,
        direction=direction,  # type: ignore[arg-type]
        entry_price=float(setup["entry"]),
        stop_price=float(setup["stop"]),
        target_prices=target_prices,
        equity=equity,
        risk_per_trade_pct=risk_per_trade_pct,
        min_risk_reward=min_risk_reward,
        closes=ltf_closes,
        highs=ltf_highs,
        lows=ltf_lows,
    )
    if plan.get("error"):
        return None
    plan["demo_for_screenshot"] = True
    plan["price_action"] = mtf.get("ltf_analysis")
    return refine_chart_trade_plan(
        plan,
        ltf_closes=ltf_closes,
        ltf_highs=ltf_highs,
        ltf_lows=ltf_lows,
        mtf=mtf,
        min_risk_reward=min_risk_reward,
    )


def _profit_level(plan: dict[str, Any]) -> float:
    targets = plan.get("targets") or []
    prices = [float(t["price"]) for t in targets if t.get("price") is not None]
    if not prices:
        entry = float(plan["entry"])
        stop = float(plan["stop"])
        risk = abs(entry - stop)
        if plan.get("direction") == "short":
            return entry - risk * 2
        return entry + risk * 2
    if plan.get("direction") == "short":
        return min(prices)
    return max(prices)


def apply_trade_plan_to_chart(
    plan: dict[str, Any],
    *,
    symbol: str | None = None,
    timeframe: str | None = None,
    ltf_times: list[int] | None = None,
    ltf_closes: list[float] | None = None,
    ltf_highs: list[float] | None = None,
    ltf_lows: list[float] | None = None,
    mtf: dict[str, Any] | None = None,
    skip_chart_nav: bool = False,
    clear_drawings: bool = True,
    inject_pine: bool = False,
    draw_levels: bool = True,
    pine_path: Path | None = None,
    render_pine: Any | None = None,
    pine_payload_fn: Any | None = None,
) -> dict[str, Any]:
    """Apply trade plan via TradingView native Long/Short position forecasting tool."""
    from .chart_drawing_styles import position_tool_overrides
    from .tv_tools import tv_draw_position

    if plan.get("error"):
        return {"success": False, "error": "invalid_plan", "detail": plan.get("detail")}

    chart_plan = plan
    if ltf_closes and ltf_highs and ltf_lows:
        chart_plan = refine_chart_trade_plan(
            plan,
            ltf_closes=ltf_closes,
            ltf_highs=ltf_highs,
            ltf_lows=ltf_lows,
            mtf=mtf,
        )

    sym = symbol or plan.get("symbol")
    direction = str(chart_plan.get("direction") or "long")
    results: dict[str, Any] = {"success": True, "steps": []}

    if sym:
        results["steps"].append(tv_call("symbol", str(sym)))
    if timeframe:
        results["steps"].append(tv_call("timeframe", str(timeframe)))
        time.sleep(1.5)

    if clear_drawings:
        results["steps"].append(tv_call("draw", "clear"))

    bar_time, bar_time2 = _ltf_position_bar_times(ltf_times)

    position_draw: dict[str, Any] | None = None
    if draw_levels:
        sizing = plan.get("sizing") or {}
        equity = float(sizing.get("equity") or sizing.get("account_equity") or 100_000)
        risk_pct = float(sizing.get("risk_per_trade_pct") or 1.0)
        units = sizing.get("units")
        position_draw = tv_draw_position(
            direction,
            float(chart_plan["entry"]),
            float(chart_plan["stop"]),
            _profit_level(chart_plan),
            bar_time,
            time2=bar_time2,
            account_size=equity,
            risk_pct=risk_pct,
            qty=float(units) if units is not None else None,
            overrides=position_tool_overrides(direction),
        )
        results["position_tool"] = position_draw
        results["position_shape"] = position_draw.get("shape")

    if inject_pine and render_pine and pine_payload_fn:
        payload = pine_payload_fn(plan)
        body = render_pine("pa_trade_overlay", payload)
        out = pine_path or Path.home() / ".bist-trader" / "_last_overlay.pine"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(body, encoding="utf-8")
        results["steps"].append(tv_call("ui", "panel", "pine-editor", "open"))
        time.sleep(1.5)
        results["steps"].append(tv_call("pine", "set", "-f", str(out.resolve())))
        time.sleep(1)
        results["pine_compile"] = tv_call("pine", "compile")

    results["position_drawn"] = bool(position_draw and position_draw.get("success"))
    results["shape"] = position_draw.get("shape") if position_draw else None
    results["entity_id"] = position_draw.get("entity_id") if position_draw else None
    results["symbol"] = sym
    results["bar_time"] = bar_time
    if not results["position_drawn"] and draw_levels:
        results["success"] = False
        results["error"] = position_draw.get("error") if position_draw else "position_draw_failed"
    return results


def _ew_segment_ok(
    t1: int,
    p1: float,
    t2: int,
    p2: float,
    *,
    max_move_pct: float = 0.22,
    min_dt_sec: int = 300,
) -> bool:
    """Skip trend segments that would render as vertical 'spikes' on the chart."""
    dt = abs(int(t2) - int(t1))
    if dt < min_dt_sec:
        return False
    # Guard: if both points collapsed to the same time, skip
    if int(t1) == int(t2):
        return False
    base = max(abs(p1), 1e-9)
    move = abs(p2 - p1) / base
    if move > max_move_pct and dt < 86400 * 3:
        return False
    return True


def _resolve_point_time(
    pt: dict[str, Any],
    bar_times: list[int] | None,
) -> int | None:
    if pt.get("time") is not None:
        return int(pt["time"])
    idx = pt.get("index")
    if bar_times and idx is not None and 0 <= int(idx) < len(bar_times):
        return int(bar_times[int(idx)])
    return None


def _map_channel_point(
    pt: dict[str, Any],
    bar_times: list[int] | None,
    ltf_times: list[int] | None,
    draw_on_ltf: bool,
) -> dict[str, Any]:
    if not draw_on_ltf or not ltf_times or not bar_times:
        return pt
    from .chart_draw_coords import map_points_to_chart_times

    mapped = map_points_to_chart_times([pt], bar_times, ltf_times)
    return mapped[0] if mapped else pt


def _draw_elliott_channel(
    channel: dict[str, Any],
    *,
    chart_times: list[int] | None,
    bar_times: list[int] | None,
    ltf_times: list[int] | None,
    draw_on_ltf: bool,
    style: dict[str, Any],
) -> dict[str, Any]:
    """Draw impulse parallel channel (waves 2–4 baseline + 3 parallel)."""
    from .tv_tools import tv_draw_trend_line

    out: dict[str, Any] = {"lines": []}
    if not chart_times:
        return out

    base = channel.get("support_line") or channel.get("resistance_line")
    if not base:
        return out
    p_from = _map_channel_point(base["from"], bar_times, ltf_times, draw_on_ltf)
    p_to = _map_channel_point(base["to"], bar_times, ltf_times, draw_on_ltf)
    t1 = _resolve_point_time(p_from, chart_times)
    t2 = _resolve_point_time(p_to, chart_times)
    if t1 is None or t2 is None:
        return out
    out["lines"].append(
        tv_draw_trend_line(
            t1, float(p_from["price"]), t2, float(p_to["price"]), overrides=style
        )
    )

    parallel = channel.get("resistance_parallel") or channel.get("support_parallel")
    if parallel:
        anchor = _map_channel_point(parallel["anchor"], bar_times, ltf_times, draw_on_ltf)
        end_idx = int((base["to"] or {}).get("index") or anchor.get("index") or 0)
        end_pt = {
            "index": end_idx,
            "price": float(parallel["end_price"]),
            "time": (base["to"] or {}).get("time"),
        }
        end_pt = _map_channel_point(end_pt, bar_times, ltf_times, draw_on_ltf)
        ta = _resolve_point_time(anchor, chart_times)
        te = _resolve_point_time(end_pt, chart_times)
        if ta is not None and te is not None:
            out["lines"].append(
                tv_draw_trend_line(
                    ta,
                    float(anchor["price"]),
                    te,
                    float(end_pt["price"]),
                    overrides=style,
                )
            )
    return out


def _banner_anchor_price(
    ltf_highs: list[float] | None,
    ltf_closes: list[float] | None,
) -> float:
    if ltf_highs:
        window = ltf_highs[-30:]
        return max(window) * 1.004
    if ltf_closes:
        return float(ltf_closes[-1]) * 1.01
    return 0.0


def _closest_levels(
    levels: list[dict[str, Any]],
    close: float,
    *,
    side: str,
    limit: int,
) -> list[dict[str, Any]]:
    rows = [x for x in levels if x.get("price") is not None]
    if side == "support":
        rows = sorted(
            [x for x in rows if float(x["price"]) <= close * 1.01],
            key=lambda x: close - float(x["price"]),
        )
    else:
        rows = sorted(
            [x for x in rows if float(x["price"]) >= close * 0.99],
            key=lambda x: float(x["price"]) - close,
        )
    return rows[:limit]


def apply_pa_overlay_to_chart(
    mtf: dict[str, Any],
    *,
    ltf_times: list[int] | None = None,
    ltf_closes: list[float] | None = None,
    ltf_highs: list[float] | None = None,
    minimal: bool = False,
) -> dict[str, Any]:
    """Draw PA on chart: S/R horizontals + HTF/LTF structure label (LTF timeframe)."""
    from .chart_drawing_styles import (
        PA_BANNER_TEXT,
        PA_FVG_LINE,
        PA_RANGE_HIGH,
        PA_RANGE_LOW,
        PA_RANGE_MID,
        PA_RESIST_LINE,
        PA_SUPPORT_LINE,
        overrides_json,
    )
    from .tv_tools import tv_draw_horizontal_line, tv_draw_text

    ltf_pa = mtf.get("ltf_analysis") or {}
    if not ltf_times and not ltf_closes:
        return {"success": False, "error": "no_ltf_series"}

    t_anchor = int(ltf_times[-1]) if ltf_times else int(time.time())
    close = float(ltf_closes[-1]) if ltf_closes else 0.0
    banner_y = _banner_anchor_price(ltf_highs, ltf_closes)

    out: dict[str, Any] = {"success": True, "levels": [], "labels": []}

    resistances = ltf_pa.get("resistance_levels") or []
    supports = ltf_pa.get("support_levels") or []
    if minimal:
        resistances = _closest_levels(resistances, close, side="resistance", limit=1)
        supports = _closest_levels(supports, close, side="support", limit=1)
    else:
        resistances = resistances[:2]
        supports = supports[:2]

    for r in resistances:
        px = float(r["price"])
        line = tv_draw_horizontal_line(
            t_anchor, px, text="Res", overrides=overrides_json(PA_RESIST_LINE)
        )
        out["levels"].append(line)
        time.sleep(0.08)

    for s in supports:
        px = float(s["price"])
        line = tv_draw_horizontal_line(
            t_anchor, px, text="Sup", overrides=overrides_json(PA_SUPPORT_LINE)
        )
        out["levels"].append(line)
        time.sleep(0.08)

    range_box = (ltf_pa.get("range") or {}).get("box") or {}
    if range_box.get("active") and not minimal:
        rh = float(range_box["range_high"])
        rl = float(range_box["range_low"])
        rm = float(range_box.get("range_mid") or (rh + rl) / 2)
        for px, lbl, style in (
            (rh, "RNG H", PA_RANGE_HIGH),
            (rl, "RNG L", PA_RANGE_LOW),
            (rm, "EQ", PA_RANGE_MID),
        ):
            out["levels"].append(
                tv_draw_horizontal_line(
                    t_anchor, px, text=lbl, overrides=overrides_json(style)
                )
            )
            time.sleep(0.06)
        zone = range_box.get("zone", "")
        out["range_zone"] = zone

    fvg_sum = (ltf_pa.get("fvg") or ltf_pa.get("imbalances") or {}).get("summary") or {}
    fvg_note = ""
    rp = ltf_pa.get("range_trade") or {}
    if not minimal:
        if range_box.get("active"):
            fvg_note = f" · RNG {range_box.get('zone')} Q{int(range_box.get('quality_score', 0))}"
            if rp.get("play") and rp.get("play") != "no_range":
                fvg_note += f" · {rp.get('play')}"
        elif fvg_sum.get("open_bullish") or fvg_sum.get("open_bearish"):
            fvg_note = f" · FVG↑{fvg_sum.get('open_bullish', 0)}↓{fvg_sum.get('open_bearish', 0)}"
        ifvg_n = fvg_sum.get("inverted", 0)
        if ifvg_n:
            fvg_note += f" · IFVG{ifvg_n}"

    def _draw_fvg_zone(top: float, bot: float, label: str) -> None:
        mid = (top + bot) / 2
        for px, lbl in ((top, f"{label} top"), (bot, f"{label} bot")):
            out["levels"].append(
                tv_draw_horizontal_line(
                    t_anchor, px, overrides=overrides_json(PA_FVG_LINE)
                )
            )
            time.sleep(0.06)
        out["labels"].append(
            tv_draw_text(
                t_anchor,
                mid,
                f"{label} ZONE",
                overrides=overrides_json(PA_FVG_LINE),
            )
        )

    if not minimal:
        for z in (fvg_sum.get("open_bullish_zones") or [])[:1]:
            _draw_fvg_zone(float(z["top"]), float(z["bottom"]), "FVG↑")
        for z in (fvg_sum.get("open_bearish_zones") or [])[:1]:
            _draw_fvg_zone(float(z["top"]), float(z["bottom"]), "FVG↓")

    if minimal:
        banner = (
            f"PA · {mtf.get('htf_structure')} → {mtf.get('ltf_structure')} "
            f"· {mtf.get('aligned_direction')} · {mtf.get('trade_quality')}"
        )
    else:
        banner = (
            f"PA · HTF {mtf.get('htf_structure')} · LTF {mtf.get('ltf_structure')} "
            f"· {mtf.get('trade_quality')} · {mtf.get('aligned_direction')}{fvg_note}"
        )
    # Disabled text banner rendering to prevent UI clutter and overlapping text in screenshots
    # out["labels"].append(
    #     tv_draw_text(t_anchor, banner_y, banner, overrides=overrides_json(PA_BANNER_TEXT))
    # )
    out["banner"] = banner
    return out


def _ew_points_for_chart(
    points: list[dict[str, Any]],
    ew_times: list[int] | None,
    ltf_times: list[int] | None,
    *,
    chart_style: str,
) -> list[dict[str, Any]]:
    if chart_style != "clean" or not points:
        return points
    if ltf_times and ew_times:
        t_min = int(ltf_times[max(0, len(ltf_times) - 120)])
        filtered = [
            p for p in points
            if (t := _resolve_point_time(p, ew_times)) is not None and t >= t_min
        ]
        if len(filtered) >= 3:
            return filtered
    return points[-6:] if len(points) > 6 else points


def apply_scenario_to_chart(
    scenario: dict[str, Any],
    *,
    symbol: str | None = None,
    timeframe: str | None = None,
    htf_timeframe: str | None = None,
    ltf_timeframe: str | None = None,
    bar_times: list[int] | None = None,
    ltf_times: list[int] | None = None,
    ltf_closes: list[float] | None = None,
    ltf_highs: list[float] | None = None,
    ltf_lows: list[float] | None = None,
    mtf: dict[str, Any] | None = None,
    plan: dict[str, Any] | None = None,
    clear_drawings: bool = True,
    draw_position: bool = True,
    draw_pa: bool = True,
    draw_ew: bool = True,
    draw_on_ltf: bool = True,
    fundamental_banner: str | None = None,
    chart_style: str = "full",
) -> dict[str, Any]:
    """Draw on LTF chart: EW (mapped from HTF indices) + PA + Long/Short position tool."""
    from .chart_draw_coords import map_points_to_chart_times, points_drawable_on_chart
    from .chart_drawing_styles import EW_POINT_LABEL, EW_TREND_LINE, overrides_json
    from .tv_tools import (
        tv_chart_set_candles,
        tv_chart_set_timeframe,
        tv_draw_text,
        tv_draw_trend_line,
    )

    ew_style = overrides_json(EW_TREND_LINE)
    ew_lbl_style = overrides_json(EW_POINT_LABEL)

    results: dict[str, Any] = {"success": True, "steps": [], "wave_lines": [], "pa": None}
    chart_tf = ltf_timeframe or timeframe or htf_timeframe

    if symbol:
        results["steps"].append(tv_call("symbol", str(symbol)))
        time.sleep(1.0)

    if clear_drawings:
        results["steps"].append(tv_call("draw", "clear"))

    if chart_tf:
        results["steps"].append(tv_chart_set_timeframe(str(chart_tf)))
        time.sleep(2.0)
        results["steps"].append(tv_chart_set_candles())
        time.sleep(0.5)

    chart_times = ltf_times if (draw_on_ltf and ltf_times) else bar_times

    # --- Elliott Wave: always use HTF coordinates (no LTF mapping) ---
    # EW is computed on HTF data, so HTF timestamps are the correct
    # coordinate system.  TradingView drawings use absolute time/price,
    # so HTF timestamps render correctly even when the chart is on LTF.
    ew_times = bar_times  # HTF times — native EW coordinate system
    raw_points = scenario.get("draw_points") or scenario.get("elliott_primary", {}).get("points")
    if not raw_points and scenario.get("elliott_alternate"):
        raw_points = scenario["elliott_alternate"].get("points")

    points = _ew_points_for_chart(raw_points or [], ew_times, ltf_times, chart_style=chart_style)

    if draw_ew and points and ew_times and points_drawable_on_chart(points, ew_times):
        for i in range(len(points) - 1):
            p1, p2 = points[i], points[i + 1]
            t1 = _resolve_point_time(p1, ew_times)
            t2 = _resolve_point_time(p2, ew_times)
            if t1 is None or t2 is None:
                continue
            if not _ew_segment_ok(t1, float(p1["price"]), t2, float(p2["price"])):
                continue
            line = tv_draw_trend_line(
                t1, float(p1["price"]), t2, float(p2["price"]), overrides=ew_style
            )
            results["wave_lines"].append(line)
            time.sleep(0.12)
        for p in points:
            t = _resolve_point_time(p, ew_times)
            lbl = p.get("label")
            if t is not None and lbl:
                results["steps"].append(
                    tv_draw_text(t, float(p["price"]), str(lbl), overrides=ew_lbl_style)
                )
                time.sleep(0.08)
    elif draw_ew and raw_points:
        results["ew_skipped"] = "points_not_on_visible_htf_range"

    ew_primary = scenario.get("elliott_primary") or {}
    channel = ew_primary.get("channel") or scenario.get("channel")
    if draw_ew and channel and chart_style != "clean":
        ch_style = overrides_json({**EW_TREND_LINE, "linestyle": 2, "linewidth": 1})
        results["ew_channel"] = _draw_elliott_channel(
            channel,
            chart_times=ew_times,
            bar_times=bar_times,
            ltf_times=ltf_times,
            draw_on_ltf=False,  # channel also uses HTF coords
            style=ch_style,
        )

    projected = scenario.get("projected_points") or []
    if draw_ew and projected and ew_times and chart_style != "clean":
        from .chart_drawing_styles import EW_PROJECTED_LABEL, EW_PROJECTED_LINE, overrides_json

        proj_style = overrides_json(EW_PROJECTED_LINE)
        proj_lbl = overrides_json(EW_PROJECTED_LABEL)
        # No mapping — projected points also use HTF coordinates
        if points_drawable_on_chart(projected, ew_times):
            for i in range(len(projected) - 1):
                p1, p2 = projected[i], projected[i + 1]
                t1 = _resolve_point_time(p1, ew_times)
                t2 = _resolve_point_time(p2, ew_times)
                if t1 is None or t2 is None:
                    continue
                if not _ew_segment_ok(t1, float(p1["price"]), t2, float(p2["price"])):
                    continue
                results["wave_lines"].append(
                    tv_draw_trend_line(
                        t1, float(p1["price"]), t2, float(p2["price"]), overrides=proj_style
                    )
                )
                time.sleep(0.1)
            for p in projected:
                if not p.get("projected"):
                    continue
                t = _resolve_point_time(p, ew_times)
                lbl = p.get("label")
                if t is not None and lbl:
                    results["steps"].append(
                        tv_draw_text(t, float(p["price"]), str(lbl), overrides=proj_lbl)
                    )
            results["projected_drawn"] = True

    if draw_pa and mtf:
        results["pa"] = apply_pa_overlay_to_chart(
            mtf,
            ltf_times=ltf_times,
            ltf_closes=ltf_closes,
            ltf_highs=ltf_highs,
            minimal=chart_style == "clean",
        )
        if fundamental_banner and ltf_times and ltf_closes and chart_style != "clean":
            from .chart_drawing_styles import PA_BANNER_TEXT, overrides_json

            t_anchor = int(ltf_times[-1])
            hi = float(ltf_highs[-1]) if ltf_highs else float(ltf_closes[-1]) * 1.02
            fund_style = overrides_json({**PA_BANNER_TEXT, "fontsize": 11})
            results["steps"].append(
                tv_draw_text(
                    t_anchor,
                    hi * 1.008,
                    f"TEMEL · {fundamental_banner[:120]}",
                    overrides=fund_style,
                )
            )
            results["fundamental_banner"] = fundamental_banner[:120]

    if draw_position and plan_has_trade_levels(plan):
        pos = apply_trade_plan_to_chart(
            plan,
            symbol=None,
            timeframe=None,
            ltf_times=ltf_times,
            ltf_closes=ltf_closes,
            ltf_highs=ltf_highs,
            ltf_lows=ltf_lows,
            mtf=mtf,
            clear_drawings=False,
            inject_pine=False,
            draw_levels=True,
        )
        results["position"] = pos
        results["position_drawn"] = pos.get("position_drawn")
        results["position_shape"] = pos.get("position_shape")
        if not pos.get("position_drawn"):
            results["success"] = False
            results["error"] = pos.get("error") or "long_short_position_tool_failed"

    results["scenario_id"] = scenario.get("id")
    results["draw_timeframe"] = chart_tf
    results["chart_style"] = chart_style
    return results


__all__ = [
    "tv_call",
    "fetch_ohlcv_from_chart",
    "plan_has_trade_levels",
    "refine_chart_trade_plan",
    "build_demo_position_plan",
    "apply_trade_plan_to_chart",
    "apply_pa_overlay_to_chart",
    "apply_scenario_to_chart",
    "tv_mcp_root",
]

"""TradingView Desktop — proxied via tradingview-mcp CLI (single MCP surface)."""

from __future__ import annotations

import time
from typing import Any

from .tv_bridge import tv_call, tv_mcp_root


def _bars_from_ohlcv(res: dict[str, Any]) -> dict[str, list[float]]:
    bars = res.get("bars") or []
    return {
        "closes": [float(b["close"]) for b in bars],
        "highs": [float(b["high"]) for b in bars],
        "lows": [float(b["low"]) for b in bars],
        "volumes": [float(b.get("volume") or 0) for b in bars],
        "times": [int(b["time"]) for b in bars if b.get("time") is not None],
    }


def timeframe_to_seconds(timeframe: str) -> int | None:
    """Parse a TradingView timeframe label into seconds (None if unknown).

    Accepts bare minutes ("15", "60", "240"), and D/W/M suffixes ("1D", "D",
    "1W", "1M"). Used to confirm fetched bars actually match the timeframe we
    asked TradingView to switch to (guards a switch/fetch race condition).
    """
    tf = str(timeframe).strip().upper()
    if not tf:
        return None
    if tf.isdigit():
        return int(tf) * 60
    unit = tf[-1]
    num = tf[:-1]
    if num != "" and not num.isdigit():
        return None  # e.g. "BOGUS" — not a "<digits><unit>" label
    mult = int(num) if num.isdigit() else 1
    if unit == "D":
        return mult * 86_400
    if unit == "W":
        return mult * 7 * 86_400
    if unit == "M":  # month (approx) — TV uses M for monthly
        return mult * 30 * 86_400
    if unit == "S":
        return mult
    return None


def verify_bar_timeframe(times: list[int], timeframe: str) -> dict[str, Any]:
    """Confirm the median bar spacing matches the requested timeframe.

    Returns ``ok`` plus diagnostics. Tolerant by design: intraday series carry
    overnight/weekend gaps, so we check the *median* delta lands within a
    [0.5x, 2x] band of the expected interval rather than demanding exactness.
    """
    expected = timeframe_to_seconds(timeframe)
    if expected is None or len(times) < 3:
        return {"ok": True, "checked": False, "timeframe": timeframe}
    deltas = sorted(int(times[i]) - int(times[i - 1]) for i in range(1, len(times)))
    pos = [d for d in deltas if d > 0]
    if not pos:
        return {"ok": True, "checked": False, "timeframe": timeframe}
    actual = pos[len(pos) // 2]
    ok = expected * 0.5 <= actual <= expected * 2.0
    return {
        "ok": ok,
        "checked": True,
        "timeframe": timeframe,
        "expected_sec": expected,
        "median_delta_sec": actual,
    }


def tv_verify_chart_symbol(expected_tv: str) -> dict[str, Any]:
    """Confirm active chart symbol matches normalized TV ticker."""
    state = tv_chart_get_state()
    cur = str(state.get("symbol") or state.get("ticker") or "").upper()
    exp = str(expected_tv).upper()
    tail = exp.split(":")[-1]
    ok = bool(cur) and (exp in cur or cur.endswith(tail) or tail in cur)
    return {
        "source": "bist-trader-mcp — tv_tools.tv_verify_chart_symbol",
        "ok": ok,
        "chart_symbol": cur,
        "expected": exp,
        "warning": None if ok else "chart_symbol_mismatch",
    }


def tv_health_check() -> dict[str, Any]:
    """CDP + chart API health (requires TV on port 9222)."""
    import json
    import subprocess

    root = tv_mcp_root()
    proc = subprocess.run(
        [
            "node",
            "-e",
            """
import { healthCheck } from './src/core/health.js';
healthCheck()
  .then(r => { console.log(JSON.stringify(r)); process.exit(r.success ? 0 : 1); })
  .catch(e => { console.error(JSON.stringify({success:false,error:e.message})); process.exit(2); });
""",
        ],
        cwd=str(root),
        capture_output=True,
        text=True,
        timeout=25,
        check=False,
    )
    raw = (proc.stdout or "").strip().splitlines()
    if not raw:
        return {"success": False, "error": "health_check_empty", "detail": proc.stderr[:300]}
    try:
        data = json.loads(raw[-1])
    except json.JSONDecodeError:
        return {"success": False, "error": "invalid_json", "detail": raw[-1][:300]}
    return {"source": "bist-trader-mcp — tv_tools.tv_health_check", **data}


def tv_chart_set_symbol(symbol: str) -> dict[str, Any]:
    return {"source": "bist-trader-mcp — tv_tools", **tv_call("symbol", symbol)}


def tv_chart_set_timeframe(timeframe: str) -> dict[str, Any]:
    return {"source": "bist-trader-mcp — tv_tools", **tv_call("timeframe", timeframe)}


def tv_chart_get_state() -> dict[str, Any]:
    return {"source": "bist-trader-mcp — tv_tools", **tv_call("state")}


def tv_chart_set_candles() -> dict[str, Any]:
    return {"source": "bist-trader-mcp — tv_tools", **tv_call("type", "Candles")}


def tv_remove_studies_matching(name_substr: str) -> dict[str, Any]:
    """Remove chart studies whose name contains substring (e.g. PA Trade pine)."""
    state = tv_chart_get_state()
    removed: list[dict[str, Any]] = []
    for study in state.get("studies") or []:
        label = str(study.get("name") or "")
        if name_substr.lower() in label.lower():
            rid = study.get("id")
            if rid:
                res = tv_call("indicator", "remove", str(rid))
                removed.append({"id": rid, "name": label, "result": res})
                time.sleep(0.4)
    return {
        "source": "bist-trader-mcp — tv_tools.tv_remove_studies_matching",
        "matched": len(removed),
        "removed": removed,
    }


def tv_finalize_chart_view(
    symbol: str,
    ltf_timeframe: str,
    *,
    scroll_unix: int | None = None,
    wait_sec: float = 2.5,
) -> dict[str, Any]:
    """End on LTF + symbol, optional scroll, for clean screenshots."""
    steps: list[dict[str, Any]] = []
    steps.append(tv_chart_set_symbol(symbol))
    time.sleep(1.2)
    steps.append(tv_chart_set_timeframe(ltf_timeframe))
    time.sleep(wait_sec)
    steps.append(tv_chart_set_candles())
    time.sleep(0.8)
    if scroll_unix:
        from datetime import datetime, timezone

        from .tv_bridge import tv_call

        dt = datetime.fromtimestamp(int(scroll_unix), tz=timezone.utc).strftime("%Y-%m-%d")
        steps.append(tv_call("scroll", dt))
        time.sleep(1.5)
    state = tv_chart_get_state()
    return {
        "source": "bist-trader-mcp — tv_tools.tv_finalize_chart_view",
        "steps": steps,
        "state": state,
    }


def tv_data_get_ohlcv(count: int = 200, summary: bool = False) -> dict[str, Any]:
    args = ["ohlcv", "-n", str(min(max(count, 1), 500))]
    if summary:
        args.append("-s")
    return {"source": "bist-trader-mcp — tv_tools", **tv_call(*args)}


def tv_read_chart_bars(count: int = 200) -> dict[str, list[float]]:
    """OHLCV from the *current* chart symbol + timeframe (for draw time sync)."""
    raw = tv_data_get_ohlcv(count=count)
    return _bars_from_ohlcv(raw)


def tv_fetch_mtf_ohlcv(
    symbol: str,
    ltf_timeframe: str,
    htf_timeframe: str,
    bars: int | None = None,
    market: str | None = None,
) -> dict[str, Any]:
    """Set symbol, pull LTF then HTF OHLCV from active TradingView chart."""
    from .market_profiles import normalize_tv_symbol, resolve_assistant_config

    cfg = resolve_assistant_config(
        symbol,
        market=market,
        ltf_timeframe=ltf_timeframe,
        htf_timeframe=htf_timeframe,
    )
    sym_tv = normalize_tv_symbol(symbol, cfg["asset_class"])
    bar_n = int(bars if bars is not None else cfg["ohlcv_bars"])

    sym = tv_chart_set_symbol(sym_tv)
    if not sym.get("success", True) and sym.get("error"):
        return sym

    def _fetch_tf(tf: str) -> tuple[dict[str, Any], dict[str, list[float]], dict[str, Any]]:
        """Set timeframe, pull bars, and verify the bars match it — retry once.

        TradingView can lag a timeframe switch, returning the *previous*
        resolution's bars. A single re-pull after a longer wait clears it.
        """
        tv_chart_set_timeframe(tf)
        time.sleep(1.5)
        raw = tv_data_get_ohlcv(count=bar_n)
        bars = _bars_from_ohlcv(raw)
        check = verify_bar_timeframe(bars.get("times") or [], tf)
        if check.get("checked") and not check.get("ok"):
            time.sleep(2.0)
            raw = tv_data_get_ohlcv(count=bar_n)
            bars = _bars_from_ohlcv(raw)
            retry = verify_bar_timeframe(bars.get("times") or [], tf)
            retry["retried"] = True
            check = retry
        return raw, bars, check

    ltf_raw, ltf, ltf_tf_check = _fetch_tf(ltf_timeframe)
    if not ltf_raw.get("bars") and ltf_raw.get("error"):
        return ltf_raw

    htf_raw, htf, htf_tf_check = _fetch_tf(htf_timeframe)

    from .data_quality import assess_ohlcv_quality, merge_mtf_data_quality

    ac = cfg["asset_class"]

    from .session_filter import filter_session_bars, is_intraday_timeframe

    session_meta: dict[str, Any] | None = None
    if ac in ("bist_equity", "bist_index", "viop_future", "viop_option") and is_intraday_timeframe(
        ltf_timeframe
    ):
        filt = filter_session_bars(
            ltf["closes"],
            ltf["highs"],
            ltf["lows"],
            ltf["times"],
            volumes=ltf.get("volumes"),
            asset_class=ac,
        )
        if filt.get("filtered"):
            ltf = {
                "closes": filt["closes"],
                "highs": filt["highs"],
                "lows": filt["lows"],
                "times": filt["times"],
                "volumes": filt.get("volumes"),
            }
            session_meta = filt
    htf_q = assess_ohlcv_quality(
        htf["closes"], htf["highs"], htf["lows"],
        times=htf.get("times"),
        volumes=htf.get("volumes"),
        asset_class=ac,
    )
    ltf_q = assess_ohlcv_quality(
        ltf["closes"], ltf["highs"], ltf["lows"],
        times=ltf.get("times"),
        volumes=ltf.get("volumes"),
        asset_class=ac,
    )
    return {
        "source": "bist-trader-mcp — tv_tools.tv_fetch_mtf_ohlcv",
        "symbol": symbol,
        "symbol_tv": sym_tv,
        "asset_class": ac,
        "ltf_timeframe": ltf_timeframe,
        "htf_timeframe": htf_timeframe,
        "ltf": ltf,
        "htf": htf,
        "ltf_bar_count": len(ltf["closes"]),
        "htf_bar_count": len(htf["closes"]),
        "data_quality": merge_mtf_data_quality(htf_q, ltf_q),
        "data_quality_htf": htf_q,
        "data_quality_ltf": ltf_q,
        "session_filter": session_meta,
        "timeframe_check": {"ltf": ltf_tf_check, "htf": htf_tf_check},
    }


def tv_draw_position(
    direction: str,
    entry: float,
    stop: float,
    profit: float,
    time: int,
    time2: int | None = None,
    account_size: float | None = None,
    risk_pct: float | None = None,
    qty: float | None = None,
    overrides: str | None = None,
) -> dict[str, Any]:
    args = [
        "draw", "position",
        "-d", direction,
        "-e", str(entry),
        "-s", str(stop),
        "-P", str(profit),
        "--time", str(time),
    ]
    if time2 is not None:
        args.extend(["--time2", str(time2)])
    if account_size is not None:
        args.extend(["--account", str(int(account_size))])
    if risk_pct is not None:
        args.extend(["--risk", str(risk_pct)])
    if qty is not None:
        args.extend(["--qty", str(qty)])
    if overrides:
        args.extend(["--overrides", overrides])
    return {"source": "bist-trader-mcp — tv_tools", **tv_call(*args)}


def tv_draw_horizontal_line(
    time: int,
    price: float,
    text: str | None = None,
    overrides: str | None = None,
) -> dict[str, Any]:
    args = ["draw", "shape", "-t", "horizontal_line", "-p", str(price), "--time", str(time)]
    if text:
        args.extend(["--text", text])
    if overrides:
        args.extend(["--overrides", overrides])
    return {"source": "bist-trader-mcp — tv_tools", **tv_call(*args)}


def tv_draw_trend_line(
    time1: int,
    price1: float,
    time2: int,
    price2: float,
    overrides: str | None = None,
) -> dict[str, Any]:
    args = [
        "draw", "shape",
        "-t", "trend_line",
        "-p", str(price1),
        "--time", str(time1),
        "--price2", str(price2),
        "--time2", str(time2),
    ]
    if overrides:
        args.extend(["--overrides", overrides])
    return {"source": "bist-trader-mcp — tv_tools", **tv_call(*args)}


def tv_draw_rectangle(
    time1: int,
    price1: float,
    time2: int,
    price2: float,
    overrides: str | None = None,
) -> dict[str, Any]:
    args = [
        "draw", "shape",
        "-t", "rectangle",
        "-p", str(price1),
        "--time", str(time1),
        "--price2", str(price2),
        "--time2", str(time2),
    ]
    if overrides:
        args.extend(["--overrides", overrides])
    return {"source": "bist-trader-mcp — tv_tools", **tv_call(*args)}


def tv_draw_text(
    time: int,
    price: float,
    text: str,
    overrides: str | None = None,
) -> dict[str, Any]:
    args = [
        "draw", "shape",
        "-t", "text",
        "-p", str(price),
        "--time", str(time),
        "--text", text,
    ]
    if overrides:
        args.extend(["--overrides", overrides])
    return {"source": "bist-trader-mcp — tv_tools", **tv_call(*args)}


def tv_draw_clear() -> dict[str, Any]:
    return {"source": "bist-trader-mcp — tv_tools", **tv_call("draw", "clear")}


def tv_alert_create(
    price: float,
    condition: str = "crossing",
    message: str | None = None,
) -> dict[str, Any]:
    args = ["alert", "create", "-p", str(price), "-c", condition]
    if message:
        args.extend(["-m", message])
    return {"source": "bist-trader-mcp — tv_tools", **tv_call(*args)}


def tv_capture_screenshot(
    region: str = "chart",
    filename: str | None = None,
) -> dict[str, Any]:
    args = ["screenshot", "-r", region]
    if filename:
        args.extend(["-o", filename])
    return {"source": "bist-trader-mcp — tv_tools", **tv_call(*args)}


__all__ = [
    "timeframe_to_seconds",
    "verify_bar_timeframe",
    "tv_health_check",
    "tv_chart_set_symbol",
    "tv_chart_set_timeframe",
    "tv_chart_get_state",
    "tv_chart_set_candles",
    "tv_remove_studies_matching",
    "tv_finalize_chart_view",
    "tv_data_get_ohlcv",
    "tv_read_chart_bars",
    "tv_fetch_mtf_ohlcv",
    "tv_draw_position",
    "tv_draw_horizontal_line",
    "tv_draw_trend_line",
    "tv_draw_rectangle",
    "tv_draw_text",
    "tv_draw_clear",
    "tv_alert_create",
    "tv_capture_screenshot",
]

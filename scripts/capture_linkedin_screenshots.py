"""Capture LinkedIn demo screenshots: LTF chart + PA + EW + Long/Short position tool.

Prerequisites:
  1. TradingView Desktop via launch_tv_debug.bat (CDP :9222)
  2. tradingview-mcp npm install

Usage:
    python scripts/capture_linkedin_screenshots.py
"""

from __future__ import annotations

import shutil
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "images"
TV_MCP = Path(r"C:\Users\parlak\Downloads\tradingview-mcp")
TV_SHOTS = TV_MCP / "screenshots"


def cdp_up() -> bool:
    try:
        with urllib.request.urlopen("http://localhost:9222/json/version", timeout=3) as r:
            return r.status == 200
    except Exception:
        return False


def prepare_chart(sym_tv: str, ltf_tf: str) -> None:
    from bist_trader_mcp.tv_tools import (
        tv_chart_set_candles,
        tv_chart_set_symbol,
        tv_chart_set_timeframe,
        tv_draw_clear,
        tv_remove_studies_matching,
        tv_verify_chart_symbol,
    )

    # Aggressively clear ALL drawings + studies from previous symbol
    tv_draw_clear()
    time.sleep(0.5)
    tv_draw_clear()  # Double-clear to handle TradingView UI lag
    time.sleep(0.3)
    for pattern in ("PA Trade", "PA ", "trade", "overlay"):
        tv_remove_studies_matching(pattern)
    time.sleep(0.5)

    tv_chart_set_symbol(sym_tv)
    time.sleep(2.5)
    tv_chart_set_timeframe(ltf_tf)
    time.sleep(2.5)
    tv_chart_set_candles()
    time.sleep(0.5)

    # Clear again after symbol change (position tools may persist)
    tv_draw_clear()
    time.sleep(0.5)

    # Verify chart is showing the correct symbol
    verify = tv_verify_chart_symbol(sym_tv)
    if not verify.get("ok"):
        print(f"  [WARN] Symbol mismatch: expected={sym_tv}, got={verify.get('chart_symbol')}")
        # Retry
        tv_chart_set_symbol(sym_tv)
        time.sleep(2.0)


def demo_draw(
    symbol: str,
    market: str | None,
    *,
    draw_pa: bool = True,
    draw_ew: bool = True,
    draw_position: bool = True,
    chart_style: str = "clean",
) -> dict:
    from bist_trader_mcp.chart_scenarios import analyze_chart_scenarios
    from bist_trader_mcp.market_profiles import resolve_assistant_config
    from bist_trader_mcp.tv_bridge import apply_scenario_to_chart, build_demo_position_plan
    from bist_trader_mcp.tv_tools import (
        tv_fetch_mtf_ohlcv,
        tv_finalize_chart_view,
        tv_read_chart_bars,
    )

    # Apply basic overrides for clean visuals

    cfg = resolve_assistant_config(symbol, market=market)
    sym_tv = cfg["symbol_tv"]
    ltf_tf = cfg["ltf_timeframe"]
    htf_tf = cfg["htf_timeframe"]

    # Use max bars for richer EW wave detection on HTF
    htf_bars = min(500, max(cfg["ohlcv_bars"], 350))
    ltf_bars = cfg["ohlcv_bars"]

    prepare_chart(sym_tv, ltf_tf)

    ohlcv = tv_fetch_mtf_ohlcv(sym_tv, ltf_tf, htf_tf, bars=htf_bars, market=market)
    ltf = dict(ohlcv.get("ltf") or {})
    htf = ohlcv.get("htf") or {}

    # Sync LTF bar times with what TradingView chart actually shows
    prepare_chart(sym_tv, ltf_tf)
    live = tv_read_chart_bars(count=ltf_bars)
    if live.get("times"):
        ltf["times"] = live["times"]
        ltf["closes"] = live["closes"]
        ltf["highs"] = live["highs"]
        ltf["lows"] = live["lows"]

    pack = analyze_chart_scenarios(
        symbol=symbol,
        htf_closes=htf["closes"],
        htf_highs=htf["highs"],
        htf_lows=htf["lows"],
        ltf_closes=ltf["closes"],
        ltf_highs=ltf["highs"],
        ltf_lows=ltf["lows"],
        htf_times=htf.get("times"),
        ltf_times=ltf.get("times"),
        htf_label=htf_tf,
        ltf_label=ltf_tf,
        min_ew_score=float(cfg["min_ew_score"]) - 10,
        market=market,
    )

    primary = pack.get("primary_scenario") or {}
    mtf = pack.get("mtf") or {}

    plan = build_demo_position_plan(
        symbol=symbol,
        mtf=mtf,
        ltf_closes=ltf["closes"],
        ltf_highs=ltf["highs"],
        ltf_lows=ltf["lows"],
        equity=100_000.0,
        risk_per_trade_pct=float(cfg["risk_per_trade_pct"]),
        min_risk_reward=max(1.8, float(cfg["min_risk_reward"]) * 0.75),
        min_trade_quality="a",
    )

    chart = apply_scenario_to_chart(
        primary,
        symbol=sym_tv,
        htf_timeframe=htf_tf,
        ltf_timeframe=ltf_tf,
        bar_times=htf.get("times"),
        ltf_times=ltf.get("times"),
        ltf_closes=ltf.get("closes"),
        ltf_highs=ltf.get("highs"),
        ltf_lows=ltf.get("lows"),
        mtf=mtf,
        plan=plan,
        clear_drawings=True,
        draw_pa=draw_pa,
        draw_position=draw_position and plan is not None,
        draw_ew=draw_ew and bool((primary.get("elliott_primary") or {}).get("points")),
        draw_on_ltf=True,
        chart_style=chart_style,
    )

    # Smart scroll: center view to show both EW wave points and recent PA
    ew_points = (primary.get("elliott_primary") or {}).get("points") or []
    ew_times_list = [int(p["time"]) for p in ew_points if p.get("time") is not None]
    ltf_times_list = ltf.get("times") or []

    if ew_times_list and ltf_times_list:
        # Show from earliest EW point to recent LTF, centered
        earliest_ew = min(ew_times_list)
        latest_ltf = int(ltf_times_list[-1])
        # Scroll to ~30% from the earliest EW point for better framing
        scroll_t = earliest_ew + int((latest_ltf - earliest_ew) * 0.3)
    elif ltf_times_list:
        scroll_t = int(ltf_times_list[-25]) if len(ltf_times_list) >= 25 else int(ltf_times_list[0])
    else:
        scroll_t = None

    tv_finalize_chart_view(sym_tv, ltf_tf, scroll_unix=scroll_t, wait_sec=2.5)

    return {
        "symbol": symbol,
        "symbol_tv": sym_tv,
        "market_profile": cfg["profile"],
        "trade_quality": mtf.get("trade_quality"),
        "scenario_id": primary.get("id"),
        "plan_approved": plan.get("approved") if plan else False,
        "position_drawn": chart.get("position_drawn"),
        "position_shape": (chart.get("position") or {}).get("position_shape"),
        "ew_skipped": chart.get("ew_skipped"),
        "wave_lines": len(chart.get("wave_lines") or []),
        "chart": chart,
        "report": pack.get("report"),
    }


def copy_shot(name_prefix: str, dest: Path) -> bool:
    matches = sorted(
        TV_SHOTS.glob(f"{name_prefix}*.png"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    ) if TV_SHOTS.exists() else []
    if not matches:
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(matches[0], dest)
    print(f"  [OK] {dest.name} <- {matches[0].name}")
    return True


def main() -> int:
    sys.path.insert(0, str(ROOT / "src"))

    print("=" * 72)
    print("  LinkedIn screenshot capture (LTF + PA + EW + Long/Short tool)")
    print("=" * 72)

    if not cdp_up():
        print("\n  [FAIL] CDP :9222 not ready — run launch_tv_debug.bat first\n")
        return 2

    from bist_trader_mcp.tv_tools import tv_capture_screenshot

    demos = [
        # Slide 1: Hero PA
        {
            "symbol": "ASELS", "market": "bist", "shot_name": "linkedin_bist_asels", "out_path": OUT / "linkedin-bist-asels.png",
            "draw_pa": True, "draw_ew": False, "draw_position": False, "chart_style": "clean"
        },
        # Slide 2: Cross-market EW
        {
            "symbol": "OANDA:XAUUSD", "market": "crypto", "shot_name": "linkedin_xauusd", "out_path": OUT / "linkedin-xauusd.png",
            "draw_pa": True, "draw_ew": True, "draw_position": False, "chart_style": "clean"
        },
        # Slide 3: Crypto PA + FVG
        {
            "symbol": "BINANCE:BTCUSDT", "market": "crypto", "shot_name": "linkedin_crypto_btc", "out_path": OUT / "linkedin-crypto-btc.png",
            "draw_pa": True, "draw_ew": False, "draw_position": False, "chart_style": "full"
        },
        # Slide 4: Elliott Detail
        {
            "symbol": "ASELS", "market": "bist", "shot_name": "linkedin_bist_elliott", "out_path": OUT / "linkedin-bist-elliott.png",
            "draw_pa": False, "draw_ew": True, "draw_position": False, "chart_style": "clean"
        },
    ]

    for d in demos:
        symbol = d["symbol"]
        market = d["market"]
        shot_name = d["shot_name"]
        out_path = d["out_path"]
        print(f"\n--- {symbol} ({market}) ---")
        result = demo_draw(
            symbol, market,
            draw_pa=d["draw_pa"],
            draw_ew=d["draw_ew"],
            draw_position=d["draw_position"],
            chart_style=d["chart_style"]
        )
        print(f"  quality={result.get('trade_quality')} scenario={result.get('scenario_id')}")
        if not result.get("position_drawn") and d["draw_position"]:
            print("  [INFO] no aligned setup — PA + EW only (no position box)")
        print(f"  position_drawn={result.get('position_drawn')} shape={result.get('position_shape')}")
        print(f"  ew_lines={result.get('wave_lines')} skipped={result.get('ew_skipped')}")
        time.sleep(1.5)  # Let chart fully render before screenshot
        # Final clear of any stale study labels
        from bist_trader_mcp.tv_tools import tv_draw_clear, tv_verify_chart_symbol
        verify = tv_verify_chart_symbol(result.get("symbol_tv", ""))
        if not verify.get("ok"):
            print(f"  [WARN] Pre-capture symbol mismatch: {verify}")
        cap = tv_capture_screenshot(region="chart", filename=shot_name)
        fp = cap.get("file_path")
        if fp and Path(fp).exists():
            shutil.copy2(fp, out_path)
            print(f"  [OK] {out_path.name}")
        elif not copy_shot(shot_name, out_path):
            print(f"  [WARN] screenshot missing for {symbol}")

    print("\nFiles:")
    for d in demos:
        print(f"  {d['out_path'].relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

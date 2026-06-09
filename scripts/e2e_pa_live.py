"""Live E2E: TradingView OHLCV -> PA trade plan -> Long/Short position tool.

Requires TradingView Desktop with CDP on localhost:9222.

Usage:
    python scripts/e2e_pa_live.py BINANCE:BTCUSDT 60 long
    python scripts/e2e_pa_live.py BINANCE:BTCUSDT 60 long --inject-pine
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TV_MCP = Path(r"C:\Users\parlak\Downloads\tradingview-mcp")
PY = ROOT / ".venv" / "Scripts" / "python.exe"


def tv(*args: str, timeout: int = 60) -> dict:
    proc = subprocess.run(
        ["node", "src/cli/index.js", *args],
        cwd=str(TV_MCP),
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    raw = (proc.stdout or proc.stderr or "").strip()
    if not raw:
        raise RuntimeError(f"tv {' '.join(args)}: empty output (exit {proc.returncode})")
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"tv {' '.join(args)}: invalid JSON: {raw[:200]}") from e


def main() -> int:
    parser = argparse.ArgumentParser(description="Live PA E2E via TradingView + bist-trader")
    parser.add_argument("symbol", nargs="?", default="BINANCE:BTCUSDT")
    parser.add_argument("timeframe", nargs="?", default="60")
    parser.add_argument("direction", nargs="?", default="long", choices=["long", "short"])
    parser.add_argument("--equity", type=float, default=100_000)
    parser.add_argument("--bars", type=int, default=150)
    parser.add_argument("--inject-pine", action="store_true", default=False)
    args = parser.parse_args()

    print(f"1. Chart -> {args.symbol} @ {args.timeframe}")
    tv("symbol", args.symbol)
    tv("timeframe", args.timeframe)
    time.sleep(2)

    print(f"2. Fetch OHLCV ({args.bars} bars)")
    ohlcv = tv("ohlcv", "-n", str(args.bars))
    bars = ohlcv.get("bars") or []
    if len(bars) < 30:
        print(f"FAIL: only {len(bars)} bars", file=sys.stderr)
        return 1

    closes = [b["close"] for b in bars]
    highs = [b["high"] for b in bars]
    lows = [b["low"] for b in bars]

    print("3. Design trade plan")
    from bist_trader_mcp.tools import (
        apply_trade_to_chart,
        design_from_price_action,
        portfolio_risk_check,
    )

    plan = design_from_price_action(
        symbol=args.symbol,
        closes=closes,
        highs=highs,
        lows=lows,
        direction=args.direction,
        equity=args.equity,
    )
    if plan.get("error"):
        print(json.dumps(plan, indent=2))
        return 1

    gate = portfolio_risk_check(equity=args.equity, proposed_trade=plan)
    summary = {
        "symbol": plan.get("symbol"),
        "direction": plan.get("direction"),
        "structure": plan.get("price_action", {}).get("market_structure"),
        "entry": plan.get("entry"),
        "stop": plan.get("stop"),
        "targets": plan.get("targets"),
        "best_rr": plan.get("best_risk_reward"),
        "units": plan.get("sizing", {}).get("units"),
        "notional_pct": plan.get("sizing", {}).get("notional_pct_of_equity"),
        "notional_capped": plan.get("sizing", {}).get("notional_capped"),
        "plan_approved": plan.get("approved"),
        "portfolio_approved": gate.get("approved"),
        "violations": gate.get("violations"),
    }
    print(json.dumps(summary, indent=2))

    if plan.get("approved"):
        print("4. Draw Long/Short position tool on chart (Forecasting)")
        apply_res = apply_trade_to_chart(
            plan,
            symbol=args.symbol,
            timeframe=args.timeframe,
            clear_drawings=True,
            inject_pine=args.inject_pine,
            draw_levels=True,
        )
        print(json.dumps({
            "apply_trade_to_chart": apply_res.get("success"),
            "position_drawn": apply_res.get("position_drawn"),
            "shape": apply_res.get("shape"),
            "entity_id": apply_res.get("entity_id"),
            "position_tool": apply_res.get("position_tool"),
        }, indent=2))

        if args.inject_pine:
            print("5. Optional Pine stats overlay (no lines)")
            from bist_trader_mcp.recipes import render_recipe
            from bist_trader_mcp.tools import pine_payload_from_trade_plan

            pine_path = ROOT / "scripts" / "_pa_overlay.pine"
            payload = pine_payload_from_trade_plan(plan)
            pine_path.write_text(render_recipe("pa_trade_overlay", payload), encoding="utf-8")
            tv("ui", "panel", "pine-editor", "open")
            time.sleep(2)
            tv("pine", "set", "-f", str(pine_path.resolve()))
            time.sleep(1)
            compile_res = tv("pine", "compile")
            print(json.dumps({"pine_compile": compile_res.get("success")}, indent=2))

    if not gate.get("approved"):
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())

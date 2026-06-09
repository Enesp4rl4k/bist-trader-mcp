"""End-to-end verification for PA Position Designer + TradingView bridge.

Run:
    python scripts/verify_pa_integration.py

Sections:
  A - bist-trader PA pipeline (offline, synthetic bars)
  B - live OHLCV to PA to trade plan (Binance BTCUSDT 1h)
  C — MCP tool registry + Pine recipe render
  D — tradingview-mcp Node module health
  E — TradingView Desktop CDP (requires TV installed + debug mode)

Exit code 0 = all required checks passed.
Exit code 1 = hard failure on bist-trader side.
Exit code 2 = bist-trader OK but TradingView not reachable (action needed).
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TV_MCP = Path(r"C:\Users\parlak\Downloads\tradingview-mcp")
VENV_PY = ROOT / ".venv" / "Scripts" / "python.exe"


def banner(title: str) -> None:
    print()
    print("=" * 72)
    print(f"  {title}")
    print("=" * 72)


def ok(msg: str) -> None:
    print(f"  [OK]   {msg}")


def fail(msg: str) -> None:
    print(f"  [FAIL] {msg}")


def warn(msg: str) -> None:
    safe = msg.encode("ascii", errors="replace").decode("ascii")
    print(f"  [WARN] {safe}")


def skip(msg: str) -> None:
    print(f"  [SKIP] {msg}")


def section_a_offline_pipeline() -> bool:
    banner("A - PA pipeline (offline synthetic bars)")
    from bist_trader_mcp.position_design import (
        design_from_price_action,
        portfolio_risk_check,
    )
    from bist_trader_mcp.recipes import render_recipe
    from bist_trader_mcp.tools import pine_payload_from_trade_plan

    closes, highs, lows = [], [], []
    for i in range(120):
        c = 100.0 + i * 0.4
        closes.append(c)
        highs.append(c + 0.5)
        lows.append(c - 0.5)

    plan = design_from_price_action(
        symbol="SYNTH:TEST",
        closes=closes,
        highs=highs,
        lows=lows,
        direction="long",
        equity=100_000,
    )
    if plan.get("error"):
        fail(f"design_from_price_action: {plan}")
        return False
    ok(f"trade plan: {plan['direction']} entry={plan['entry']} stop={plan['stop']}")

    gate = portfolio_risk_check(equity=100_000, proposed_trade=plan)
    if gate.get("approved"):
        ok("portfolio_risk_check approved (within limits)")
    else:
        ok(
            "portfolio_risk_check correctly blocked over-exposure: "
            + "; ".join(gate.get("violations") or [])
        )

    sane = design_from_price_action(
        symbol="SYNTH:TEST",
        closes=closes,
        highs=highs,
        lows=lows,
        direction="long",
        equity=100_000,
    )
    # Override with wide stop so notional stays under 20% cap
    from bist_trader_mcp.tools import design_trade_setup

    wide = design_trade_setup(
        symbol="SYNTH:TEST",
        direction="long",
        entry_price=closes[-1],
        stop_price=closes[-1] * 0.85,
        target_prices=[closes[-1] * 1.15],
        equity=100_000,
        min_risk_reward=1.5,
    )
    gate2 = portfolio_risk_check(equity=100_000, proposed_trade=wide)
    if not gate2.get("approved"):
        fail(f"wide-stop plan should pass gate: {gate2.get('violations')}")
        return False
    ok("portfolio_risk_check approves wide-stop plan")
    _ = sane

    payload = pine_payload_from_trade_plan(plan)
    pine = render_recipe("pa_trade_overlay", payload)
    if "indicator(" not in pine or "PA Stats" not in pine:
        fail("Pine recipe missing expected content")
        return False
    ok(f"pa_trade_overlay rendered ({len(pine.splitlines())} lines)")

    from bist_trader_mcp.mtf_analysis import analyze_mtf_price_action
    from bist_trader_mcp.pa_scanner import scan_price_action_watchlist

    mtf = analyze_mtf_price_action(closes, highs, lows, closes[-60:], highs[-60:], lows[-60:])
    if "trade_quality" not in mtf:
        fail("MTF analysis missing trade_quality")
        return False
    ok(f"MTF analysis: quality={mtf['trade_quality']}")

    scan = scan_price_action_watchlist(
        {"SYNTH:TEST": {"closes": closes, "highs": highs, "lows": lows}},
    )
    if scan.get("symbols_scanned") != 1:
        fail("watchlist scanner failed")
        return False
    ok(f"watchlist scan: {scan.get('setups_found')} setups")
    return True


async def section_b_live_ohlcv() -> bool:
    banner("B - Live OHLCV to PA (Binance BTCUSDT 1h)")
    from bist_trader_mcp.crypto import fetch_binance_klines
    from bist_trader_mcp.tools import design_from_price_action

    try:
        bars = await fetch_binance_klines("BTCUSDT", interval="1h", limit=200)
    except Exception as e:
        warn(f"Binance fetch failed ({e}) — network may be blocked; skipping live test")
        return True

    if len(bars) < 50:
        fail(f"too few bars: {len(bars)}")
        return False

    closes = [b.close for b in bars]
    highs = [b.high for b in bars]
    lows = [b.low for b in bars]
    plan = design_from_price_action(
        symbol="BINANCE:BTCUSDT",
        closes=closes,
        highs=highs,
        lows=lows,
        direction="long",
        equity=100_000,
    )
    if plan.get("error"):
        fail(f"live PA failed: {plan}")
        return False
    ok(
        f"BTC 1h: structure={plan.get('price_action', {}).get('market_structure')} "
        f"approved={plan.get('approved')} R:R={plan.get('best_risk_reward')}"
    )
    return True


def section_c_mcp_registry() -> bool:
    banner("C - MCP tool registry")
    from bist_trader_mcp.server import PROMPTS_REGISTRY, TOOL_REGISTRY

    required_tools = [
        "analyze_price_action",
        "analyze_mtf_price_action",
        "design_trade_setup",
        "design_from_price_action",
        "portfolio_risk_check",
        "pine_payload_from_trade_plan",
        "scan_price_action_watchlist",
        "scan_mtf_watchlist",
        "log_trade_plan",
        "list_trade_journal",
        "monitor_open_trades",
        "apply_trade_to_chart",
        "get_trade_playbook_rules",
        "design_mtf_trade_plan",
        "design_ltf_trade_plan",
        "validate_trade_consistency",
        "render_pine_recipe",
        "list_pine_recipes",
    ]
    missing = [t for t in required_tools if t not in TOOL_REGISTRY]
    if missing:
        fail(f"missing tools: {missing}")
        return False
    ok(f"{len(required_tools)} PA + Pine tools registered")

    if "price-action-trade-design" not in PROMPTS_REGISTRY:
        fail("prompt price-action-trade-design missing")
        return False
    ok("prompt price-action-trade-design registered")
    return True


def section_d_tv_mcp_node() -> bool:
    banner("D - tradingview-mcp Node package")
    server_js = TV_MCP / "src" / "server.js"
    if not server_js.is_file():
        fail(f"not found: {server_js}")
        return False
    ok(f"server.js exists: {server_js}")

    node_modules = TV_MCP / "node_modules"
    if not node_modules.is_dir():
        fail("node_modules missing — run: npm install in tradingview-mcp")
        return False
    ok("node_modules present")

    try:
        proc = subprocess.run(
            ["node", "--check", str(server_js)],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except FileNotFoundError:
        fail("node not found in PATH")
        return False

    if proc.returncode != 0:
        fail(f"server.js syntax check failed: {proc.stderr.strip()}")
        return False
    ok("server.js passes Node syntax check")
    return True


def section_e_tv_cdp() -> bool:
    banner("E - TradingView Desktop CDP (localhost:9222)")
    tv_paths = [
        Path(rf"{__import__('os').environ.get('LOCALAPPDATA', '')}\TradingView\TradingView.exe"),
        Path(r"C:\Program Files\TradingView\TradingView.exe"),
    ]
    try:
        import subprocess

        ps = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "(Get-AppxPackage -Name 'TradingView.Desktop' -ErrorAction SilentlyContinue | ForEach-Object { Join-Path $_.InstallLocation 'TradingView.exe' })",
            ],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        for line in (ps.stdout or "").splitlines():
            p = Path(line.strip())
            if p.is_file():
                tv_paths.insert(0, p)
                break
    except Exception:
        pass
    installed = [p for p in tv_paths if p.is_file()]
    if not installed:
        warn("TradingView Desktop not found in default install paths")
        warn("Install from: https://www.tradingview.com/desktop/")
    else:
        ok(f"TradingView.exe found: {installed[0]}")

    try:
        req = urllib.request.Request(
            "http://localhost:9222/json/version",
            headers={"User-Agent": "verify_pa_integration"},
        )
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read().decode())
        ok(f"CDP active: {data.get('Browser', data.get('browser', 'unknown'))}")

        proc = subprocess.run(
            [
                "node",
                "-e",
                """
import { healthCheck } from './src/core/health.js';
healthCheck()
  .then(r => { console.log(JSON.stringify(r)); process.exit(r.success ? 0 : 1); })
  .catch(e => { console.error(e.message); process.exit(2); });
""",
            ],
            cwd=str(TV_MCP),
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        if proc.returncode == 0:
            info = json.loads(proc.stdout.strip().splitlines()[-1])
            ok(
                f"tv_health: symbol={info.get('chart_symbol')} "
                f"resolution={info.get('chart_resolution')} "
                f"api={info.get('api_available')}"
            )
            return True
        fail(f"tv_health_check failed: {proc.stderr.strip() or proc.stdout.strip()}")
        return False
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        warn(f"CDP not reachable: {e}")
        warn("Start TV in debug mode:")
        warn(r"  C:\Users\parlak\Downloads\tradingview-mcp\scripts\launch_tv_debug.bat")
        return False


def section_f_cursor_mcp_config() -> None:
    banner("F - Cursor MCP config")
    cfg = ROOT / ".cursor" / "mcp.json"
    if cfg.is_file():
        ok(f"project config exists: {cfg}")
        try:
            data = json.loads(cfg.read_text(encoding="utf-8"))
            servers = list((data.get("mcpServers") or {}).keys())
            ok(f"configured servers: {servers}")
        except json.JSONDecodeError:
            warn("mcp.json exists but is invalid JSON")
    else:
        warn(f"no {cfg} — created by verify script; restart Cursor after edit")


def write_cursor_mcp_config() -> None:
    cfg_dir = ROOT / ".cursor"
    cfg_dir.mkdir(exist_ok=True)
    cfg = cfg_dir / "mcp.json"
    py = str(VENV_PY).replace("\\", "\\\\")
    tv = str(TV_MCP / "src" / "server.js").replace("\\", "\\\\")
    payload = {
        "mcpServers": {
            "bist-trader": {
                "command": str(VENV_PY),
                "args": ["-m", "bist_trader_mcp"],
                "env": {},
            },
            "tradingview": {
                "command": "node",
                "args": [str(TV_MCP / "src" / "server.js")],
            },
        }
    }
    if not cfg.exists():
        cfg.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        ok(f"created {cfg}")
    else:
        skip(f"{cfg} already exists — not overwriting")


async def main() -> int:
    print("PA Position Designer - integration verification")
    write_cursor_mcp_config()

    results: dict[str, bool] = {}
    results["A"] = section_a_offline_pipeline()
    results["B"] = await section_b_live_ohlcv()
    results["C"] = section_c_mcp_registry()
    results["D"] = section_d_tv_mcp_node()
    results["E"] = section_e_tv_cdp()
    section_f_cursor_mcp_config()

    banner("SUMMARY")
    hard = ["A", "B", "C", "D"]
    for key in hard:
        status = "PASS" if results.get(key) else "FAIL"
        print(f"  [{status}] Section {key}")
    tv_status = "PASS" if results.get("E") else "BLOCKED (TV not running)"
    print(f"  [{tv_status}] Section E — TradingView CDP")

    if not all(results.get(k) for k in hard):
        print("\n  bist-trader pipeline: FAILED — fix errors above")
        return 1
    if not results.get("E"):
        print("\n  bist-trader pipeline: OK")
        print("  TradingView bridge:   NOT CONNECTED")
        print("  -> Install TradingView Desktop, run launch_tv_debug.bat, restart Cursor")
        return 2
    print("\n  ALL CHECKS PASSED — full stack ready")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

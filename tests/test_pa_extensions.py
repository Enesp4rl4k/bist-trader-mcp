"""Tests for MTF PA, watchlist scanner, trade journal."""

from __future__ import annotations

from pathlib import Path

from bist_trader_mcp.mtf_analysis import analyze_mtf_price_action
from bist_trader_mcp.pa_scanner import scan_mtf_watchlist, scan_price_action_watchlist
from bist_trader_mcp.trade_journal import (
    list_trade_journal,
    log_trade_plan,
    monitor_open_trades,
    update_trade_status,
)


def _synthetic_uptrend(n: int = 80) -> tuple[list[float], list[float], list[float]]:
    closes, highs, lows = [], [], []
    p = 100.0
    for i in range(n):
        p += 0.5 + (i % 5) * 0.1
        closes.append(p)
        highs.append(p + 1.2)
        lows.append(p - 0.8)
    return closes, highs, lows


def _synthetic_downtrend(n: int = 80) -> tuple[list[float], list[float], list[float]]:
    closes, highs, lows = [], [], []
    p = 200.0
    for i in range(n):
        p -= 0.4 + (i % 4) * 0.08
        closes.append(p)
        highs.append(p + 0.9)
        lows.append(p - 1.1)
    return closes, highs, lows


def test_mtf_aligned_long():
    htf_c, htf_h, htf_l = _synthetic_uptrend()
    ltf_c, ltf_h, ltf_l = _synthetic_uptrend(60)
    out = analyze_mtf_price_action(htf_c, htf_h, htf_l, ltf_c, ltf_h, ltf_l)
    assert out["htf_bias"] in ("long", "neutral", "short")
    assert out["trade_quality"] in ("a_plus", "a", "b", "c", "no_trade", "conflict")
    assert "recommended_setup" in out


def test_mtf_conflict():
    htf_c, htf_h, htf_l = _synthetic_uptrend()
    ltf_c, ltf_h, ltf_l = _synthetic_downtrend(60)
    out = analyze_mtf_price_action(htf_c, htf_h, htf_l, ltf_c, ltf_h, ltf_l)
    if out["htf_bias"] == "long" and out["ltf_bias"] == "short":
        assert out["conflict"] is True
        assert out["trade_quality"] == "conflict"


def test_watchlist_scanner():
    c, h, l = _synthetic_uptrend()
    out = scan_price_action_watchlist(
        {"BINANCE:BTCUSDT": {"closes": c, "highs": h, "lows": l}},
        directions=["long"],
    )
    assert out["symbols_scanned"] == 1
    assert "top_setups" in out


def test_mtf_watchlist_scanner():
    htf = dict(zip(["closes", "highs", "lows"], _synthetic_uptrend(), strict=True))
    ltf = dict(zip(["closes", "highs", "lows"], _synthetic_uptrend(60), strict=True))
    out = scan_mtf_watchlist(
        {"BINANCE:ETHUSDT": {"htf": htf, "ltf": ltf}},
        min_quality="c",
    )
    assert out["symbols_scanned"] == 1


def test_trade_journal_roundtrip(tmp_path: Path):
    jp = tmp_path / "journal.json"
    plan = {
        "symbol": "BINANCE:BTCUSDT",
        "direction": "long",
        "entry": 100.0,
        "stop": 95.0,
        "targets": [{"label": "TP1", "price": 110.0}],
        "best_risk_reward": 2.0,
        "approved": True,
        "sizing": {"units": 10},
    }
    logged = log_trade_plan(plan, status="open", journal_path=jp)
    tid = logged["trade_id"]
    lst = list_trade_journal(status="open", journal_path=jp)
    assert lst["open_count"] == 1
    upd = update_trade_status(tid, "closed", exit_price=108.0, pnl=80.0, journal_path=jp)
    assert upd["trade"]["status"] == "closed"
    mon = monitor_open_trades(
        mark_prices={"BINANCE:BTCUSDT": 94.0},
        journal_path=jp,
    )
    assert mon["open_count"] == 0


def test_tools_wrappers():
    from bist_trader_mcp.tools import (
        analyze_mtf_price_action as wrap_mtf,
    )
    from bist_trader_mcp.tools import (
        apply_trade_to_chart,
    )
    from bist_trader_mcp.tools import (
        scan_price_action_watchlist as wrap_scan,
    )

    c, h, l = _synthetic_uptrend()
    m = wrap_mtf(c, h, l, c[:60], h[:60], l[:60])
    assert "source" in m
    s = wrap_scan({"X": {"closes": c, "highs": h, "lows": l}})
    assert s["symbols_scanned"] == 1
    bad = apply_trade_to_chart({"error": "x"})
    assert bad.get("error") == "invalid_plan"

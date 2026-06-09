"""Tests for price action + position design — pure math, no network."""

from __future__ import annotations

import pytest

from bist_trader_mcp.position_design import (
    design_from_price_action,
    design_trade_setup,
    portfolio_risk_check,
    position_size_from_stop,
)
from bist_trader_mcp.price_action import (
    analyze_price_action,
    cluster_levels,
    find_swings,
    infer_market_structure,
)
from bist_trader_mcp.tools import pine_payload_from_trade_plan


def _uptrend_bars(n: int = 80) -> tuple[list[float], list[float], list[float]]:
    closes, highs, lows = [], [], []
    for i in range(n):
        c = 100.0 + i * 0.5
        closes.append(c)
        highs.append(c + 0.3)
        lows.append(c - 0.3)
    return closes, highs, lows


def test_find_swings_detects_local_extrema():
    highs = [1, 2, 3, 2, 1, 2, 4, 2, 1]
    lows = [0, 1, 2, 1, 0, 1, 3, 1, 0]
    sh, sl = find_swings(highs, lows, lookback=1)
    assert any(s.price == 3 for s in sh)
    assert any(s.price == 4 for s in sh)
    assert any(s.price == 0 for s in sl)


def test_cluster_levels_groups_nearby_prices():
    levels = cluster_levels([100.0, 100.1, 100.05, 105.0, 105.2], tolerance_pct=0.01)
    assert len(levels) == 2
    assert levels[0]["touches"] >= 2


def test_analyze_price_action_uptrend():
    closes, highs, lows = _uptrend_bars()
    out = analyze_price_action(closes, highs, lows, swing_lookback=3)
    assert out["current_price"] == closes[-1]
    assert out["atr_14"] is not None
    assert out["suggested_long_setup"] is not None


def test_position_size_from_stop_long():
    sizing = position_size_from_stop(
        equity=100_000,
        entry_price=100.0,
        stop_price=98.0,
        direction="long",
        risk_per_trade_pct=1.0,
    )
    assert sizing["risk_amount"] == pytest.approx(1000.0)
    assert sizing["units"] == pytest.approx(500.0)


def test_position_size_respects_notional_cap():
    sizing = position_size_from_stop(
        equity=100_000,
        entry_price=67_000,
        stop_price=66_500,
        direction="long",
        risk_per_trade_pct=1.0,
        max_notional_pct_of_equity=20.0,
    )
    assert sizing["notional_pct_of_equity"] <= 20.0 + 1e-9
    assert sizing["notional_capped"] is True
    assert sizing["actual_risk_pct_of_equity"] < 1.0


def test_design_trade_setup_approves_good_rr():
    plan = design_trade_setup(
        symbol="EURUSD",
        direction="long",
        entry_price=1.10,
        stop_price=1.09,
        target_prices=[1.12, 1.14],
        equity=100_000,
        min_risk_reward=2.0,
    )
    assert plan["approved"] is True
    assert plan["best_risk_reward"] >= 2.0


def test_design_trade_setup_rejects_poor_rr():
    plan = design_trade_setup(
        symbol="EURUSD",
        direction="long",
        entry_price=1.10,
        stop_price=1.09,
        target_prices=[1.105],
        equity=100_000,
        min_risk_reward=2.0,
    )
    assert plan["approved"] is False


def test_design_from_price_action_end_to_end():
    closes, highs, lows = _uptrend_bars()
    plan = design_from_price_action(
        symbol="TEST",
        closes=closes,
        highs=highs,
        lows=lows,
        direction="long",
    )
    assert plan.get("direction") == "long"
    assert "sizing" in plan


def test_portfolio_risk_check_blocks_max_positions():
    positions = [
        {"symbol": "A", "direction": "long", "entry": 10, "stop": 9, "units": 100},
    ] * 5
    out = portfolio_risk_check(
        equity=100_000,
        open_positions=positions,
        proposed_trade={"symbol": "B", "direction": "long", "sizing": {"risk_amount": 500}},
    )
    assert out["approved"] is False


def test_infer_market_structure_bullish():
    from bist_trader_mcp.price_action import SwingPoint

    sh = [
        SwingPoint(1, 100.0, "high"),
        SwingPoint(2, 110.0, "high"),
        SwingPoint(3, 120.0, "high"),
    ]
    sl = [
        SwingPoint(1, 90.0, "low"),
        SwingPoint(2, 95.0, "low"),
        SwingPoint(3, 100.0, "low"),
    ]
    info = infer_market_structure(sh, sl)
    assert info["structure"] == "bullish"


def test_pine_payload_from_trade_plan():
    plan = {
        "symbol": "XAUUSD",
        "direction": "long",
        "entry": 2350.0,
        "stop": 2340.0,
        "best_risk_reward": 2.5,
        "targets": [{"price": 2375.0}, {"price": 2400.0}],
        "sizing": {"units": 10.5, "risk_per_trade_pct": 1.0},
    }
    payload = pine_payload_from_trade_plan(plan, as_of_date="2026-06-03")
    assert payload["SYMBOL"] == "XAUUSD"
    assert payload["TP1"] == 2375.0
    assert payload["AS_OF_DATE"] == "2026-06-03"

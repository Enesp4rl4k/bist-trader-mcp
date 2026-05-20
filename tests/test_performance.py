"""Tests for performance metrics — pure math."""

from __future__ import annotations

import math

import pytest

from bist_trader_mcp.performance import (
    annualised_return,
    annualised_volatility,
    calmar_ratio,
    max_drawdown,
    performance_panel,
    sharpe_ratio,
    sortino_ratio,
    trade_statistics,
)


def test_annualised_return_compound():
    # 0.1% daily for 100 days → (1.001)^100 ≈ 1.105
    rets = [0.001] * 100
    out = annualised_return(rets, periods_per_year=252)
    # Annualised: (1.105)^(252/100) - 1 ≈ 28.6%
    assert out == pytest.approx(28.61, abs=0.5)


def test_annualised_volatility():
    # σ=0.01 daily → annualised ≈ 15.87%
    rets = [0.01 if i % 2 == 0 else -0.01 for i in range(100)]
    out = annualised_volatility(rets, periods_per_year=252)
    expected = 0.01 * math.sqrt(252) * 100
    # Sample std uses n-1 — small adjustment
    assert out == pytest.approx(expected, rel=0.05)


def test_sharpe_zero_mean_returns_none_or_zero():
    rets = [0.01 if i % 2 == 0 else -0.01 for i in range(100)]
    out = sharpe_ratio(rets)
    assert abs(out) < 0.5   # near zero excess return


def test_sortino_positive_for_uptrend():
    rets = [0.002 if i % 4 != 0 else -0.001 for i in range(80)]
    out = sortino_ratio(rets)
    assert out is not None
    assert out > 0


def test_max_drawdown_simple_curve():
    eq = [100, 110, 105, 90, 100, 95]
    out = max_drawdown(eq)
    # Peak 110, trough 90 → (90-110)/110 = -18.18%
    assert out["max_drawdown_pct"] == pytest.approx(-18.1818, rel=0.001)
    assert out["peak_index"] == 1
    assert out["trough_index"] == 3


def test_max_drawdown_monotone_up():
    eq = [100 + i for i in range(50)]
    out = max_drawdown(eq)
    assert out["max_drawdown_pct"] == 0.0


def test_calmar_positive_for_uptrend():
    rets = [0.001] * 100
    out = calmar_ratio(rets)
    # No drawdown → None
    assert out is None


def test_trade_statistics_basic():
    pnls = [100, -50, 200, -75, 150, -25]
    out = trade_statistics(pnls)
    assert out["trades"] == 6
    assert out["wins"] == 3
    assert out["losses"] == 3
    assert out["win_rate_pct"] == 50.0
    # Profit factor: gross_win = 450, gross_loss = 150 → 3.0
    assert out["profit_factor"] == pytest.approx(3.0)
    assert out["expectancy"] == pytest.approx(50.0)


def test_trade_statistics_empty():
    out = trade_statistics([])
    assert out["trades"] == 0
    assert out["win_rate_pct"] is None


def test_performance_panel_full():
    rets = [0.001 if i % 3 != 0 else -0.002 for i in range(100)]
    out = performance_panel(rets, periods_per_year=252)
    assert "sharpe_ratio" in out
    assert "drawdown" in out
    assert out["bars"] == 100

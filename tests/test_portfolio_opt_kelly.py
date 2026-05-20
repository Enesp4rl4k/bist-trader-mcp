"""Tests for Markowitz optimizer + Kelly sizing — pure math."""

from __future__ import annotations

import pytest

from bist_trader_mcp.kelly import (
    kelly_bet,
    kelly_continuous,
    kelly_panel,
    position_size_from_atr,
)
from bist_trader_mcp.portfolio_opt import optimize_portfolio


def _build_series(returns_a: list[float], returns_b: list[float]) -> dict[str, list[float]]:
    """Convert two return series into closes for the optimizer."""
    a_closes = [100.0]
    for r in returns_a:
        a_closes.append(a_closes[-1] * (1 + r))
    b_closes = [50.0]
    for r in returns_b:
        b_closes.append(b_closes[-1] * (1 + r))
    return {"A": a_closes, "B": b_closes}


def test_optimize_two_assets_returns_min_variance():
    # Distinct varying return profiles so cov matrix is non-singular
    rets_a = [0.008, -0.003, 0.012, -0.001, 0.005, -0.007, 0.010,
              0.002, -0.004, 0.006, 0.001, -0.008, 0.013, -0.002,
              0.009, -0.005, 0.011, 0.003, -0.006, 0.007] * 3
    rets_b = [-0.005, 0.009, -0.002, 0.011, -0.001, 0.006, -0.008,
              0.003, 0.012, -0.004, 0.007, 0.002, -0.011, 0.005,
              -0.003, 0.010, -0.007, 0.008, 0.001, -0.005] * 3
    series = _build_series(rets_a, rets_b)
    out = optimize_portfolio(series)
    assert "min_variance_portfolio" in out
    weights = out["min_variance_portfolio"]["weights"]
    # Both should have non-zero weight (diversification active)
    assert abs(weights["A"]) > 0
    assert abs(weights["B"]) > 0


def test_optimize_insufficient_assets():
    out = optimize_portfolio({"A": [100, 101, 102]})
    assert "error" in out


def test_optimize_provides_efficient_frontier():
    rets_a = [0.005 + 0.001 * (i % 5) for i in range(80)]
    rets_b = [0.003 - 0.001 * (i % 4) for i in range(80)]
    series = _build_series(rets_a, rets_b)
    out = optimize_portfolio(series)
    assert "efficient_frontier" in out
    assert len(out["efficient_frontier"]) > 5


# ---------------------------------------------------------------------------
# Kelly tests
# ---------------------------------------------------------------------------

def test_kelly_bet_fair_coin_zero():
    # 50/50 with 1:1 payoff → Kelly = 0
    assert kelly_bet(0.5, 1.0) == pytest.approx(0.0)


def test_kelly_bet_edge_positive():
    # 60% win, 1:1 payoff → 0.2
    assert kelly_bet(0.6, 1.0) == pytest.approx(0.2)


def test_kelly_bet_invalid_prob():
    with pytest.raises(ValueError):
        kelly_bet(1.5, 1.0)


def test_kelly_continuous_uses_sharpe_squared():
    # f = μ/σ². If μ=10%, σ=20% → f = 0.10/0.04 = 2.5
    f = kelly_continuous(annualised_return_pct=10.0, annualised_volatility_pct=20.0)
    assert f == pytest.approx(2.5)


def test_kelly_panel_fractional_variants():
    panel = kelly_panel(win_probability=0.6, win_loss_ratio=1.5)
    assert "bet_kelly_fraction" in panel
    assert "fractional_kelly" in panel
    half = panel["fractional_kelly"]["fraction_50pct"]
    full = panel["bet_kelly_fraction"]
    assert half == pytest.approx(full * 0.5)


def test_position_size_from_atr_basic():
    # 100k equity, 1% risk, ATR=2, 2x stop → risk dist = 4 → 250 shares
    out = position_size_from_atr(
        equity=100_000, entry_price=50.0, atr=2.0,
        atr_multiple_stop=2.0, risk_per_trade_pct=1.0,
    )
    assert out["shares"] == pytest.approx(250.0)
    assert out["stop_distance"] == 4.0
    assert out["stop_price_long"] == 46.0


def test_position_size_validates_inputs():
    with pytest.raises(ValueError):
        position_size_from_atr(equity=0, entry_price=50, atr=1)
    with pytest.raises(ValueError):
        position_size_from_atr(equity=1000, entry_price=50, atr=0)

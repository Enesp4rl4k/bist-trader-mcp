"""Tests for option strategy P&L simulator — pure math."""

from __future__ import annotations

import pytest

from bist_trader_mcp.strategies import (
    butterfly,
    iron_condor,
    long_straddle,
    long_strangle,
    short_straddle,
    simulate_strategy,
    vertical_spread,
)


def test_long_straddle_max_loss_at_strike():
    legs = long_straddle(strike=100.0, dte=30, vol_pct=30.0)
    result = simulate_strategy(legs, spot_range=(70.0, 130.0), spot_steps=61)
    # At expiry, max loss is the total premium paid, occurring at strike
    assert result["max_loss_at_spot"] == pytest.approx(100.0, abs=2.0)
    # Should have 2 breakevens
    assert len(result["breakevens"]) == 2


def test_long_straddle_profits_on_large_move():
    legs = long_straddle(strike=100.0, dte=30, vol_pct=30.0)
    result = simulate_strategy(legs, spot_range=(50.0, 150.0), spot_steps=21)
    # Far OTM should be very profitable
    far_left = result["grid"][0]["pnl"]
    far_right = result["grid"][-1]["pnl"]
    assert far_left > 0
    assert far_right > 0


def test_short_straddle_profits_at_strike():
    legs = short_straddle(strike=100.0, dte=30, vol_pct=30.0)
    result = simulate_strategy(legs, spot_range=(70.0, 130.0), spot_steps=61)
    # Max profit at strike
    assert result["max_profit_at_spot"] == pytest.approx(100.0, abs=2.0)
    assert result["max_profit"] > 0


def test_iron_condor_strike_validation():
    with pytest.raises(ValueError):
        iron_condor(put_low=90, put_high=80, call_low=110, call_high=120,
                     dte=30, vol_pct=30.0)


def test_iron_condor_bounded_profit_loss():
    legs = iron_condor(put_low=80, put_high=90, call_low=110, call_high=120,
                        dte=30, vol_pct=30.0)
    result = simulate_strategy(legs, spot_range=(60.0, 140.0), spot_steps=81)
    # Iron condor: net credit, defined risk → max_loss > -inf
    assert result["max_loss"] > -1e10
    # Max profit between the inner strikes
    assert 90 <= result["max_profit_at_spot"] <= 110


def test_butterfly_profits_at_mid():
    legs = butterfly(low=90, mid=100, high=110, right="call",
                       dte=30, vol_pct=30.0)
    result = simulate_strategy(legs, spot_range=(70.0, 130.0), spot_steps=61)
    # Peak profit at the mid strike
    assert result["max_profit_at_spot"] == pytest.approx(100.0, abs=2.0)


def test_butterfly_strike_validation():
    with pytest.raises(ValueError):
        butterfly(low=100, mid=90, high=110, right="call", dte=30, vol_pct=30.0)


def test_vertical_spread_bull_call_capped():
    legs = vertical_spread(low_strike=95, high_strike=105, right="call",
                             direction="bull", dte=30, vol_pct=30.0)
    result = simulate_strategy(legs, spot_range=(80.0, 120.0), spot_steps=41)
    # Max profit = (105-95) - debit, capped above high strike
    high_payoff = result["grid"][-1]["pnl"]
    low_payoff = result["grid"][0]["pnl"]
    assert high_payoff > low_payoff
    assert high_payoff > 0


def test_vertical_spread_invalid_direction():
    with pytest.raises(ValueError):
        vertical_spread(low_strike=95, high_strike=105, right="call",
                         direction="sideways", dte=30, vol_pct=30.0)


def test_strangle_strike_validation():
    with pytest.raises(ValueError):
        long_strangle(put_strike=110, call_strike=90, dte=30, vol_pct=30.0)


def test_simulate_strategy_invalid_range():
    legs = long_straddle(100, 30, 30.0)
    with pytest.raises(ValueError):
        simulate_strategy(legs, spot_range=(100, 100), spot_steps=10)


def test_simulate_strategy_min_steps():
    legs = long_straddle(100, 30, 30.0)
    with pytest.raises(ValueError):
        simulate_strategy(legs, spot_range=(80, 120), spot_steps=1)

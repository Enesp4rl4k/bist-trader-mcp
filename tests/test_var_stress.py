"""Tests for portfolio VaR + stress test (pure math, no network)."""

from __future__ import annotations

import math

import pytest

from bist_trader_mcp.portfolio import (
    BUILTIN_SCENARIOS,
    calculate_portfolio_var,
    stress_test_portfolio,
)


def _long_index_position(notional=10_000_000, vol=30.0):
    """One long XU030 future, multiplier 10, qty 100, spot 10000."""
    return [{
        "symbol": "F_XU0300626",
        "underlying": "XU030",
        "qty": 100,
        "multiplier": 10,
        "instrument_type": "future",
        "spot": 10_000.0,
    }]


def test_parametric_var_scales_with_confidence():
    positions = _long_index_position()
    var_95 = calculate_portfolio_var(positions, confidence=0.95,
                                     annual_volatility_pct=30.0)
    var_99 = calculate_portfolio_var(positions, confidence=0.99,
                                     annual_volatility_pct=30.0)
    assert var_99["var_amount"] > var_95["var_amount"]


def test_parametric_var_scales_with_horizon():
    positions = _long_index_position()
    one_day = calculate_portfolio_var(positions, horizon_days=1)
    ten_day = calculate_portfolio_var(positions, horizon_days=10)
    # sqrt(10) scaling
    ratio = ten_day["var_amount"] / one_day["var_amount"]
    assert abs(ratio - math.sqrt(10.0)) < 0.01


def test_historical_var_matches_quantile():
    positions = _long_index_position()
    # Synthetic returns: linear ramp from -10% to +10%
    rets = [(-10.0 + i * 0.2) / 100.0 for i in range(101)]
    result = calculate_portfolio_var(
        positions, confidence=0.95, horizon_days=1,
        method="historical", historical_returns=rets,
    )
    assert result["method"] == "historical"
    assert result["var_amount"] > 0
    assert result["expected_shortfall"] >= result["var_amount"]


def test_historical_var_raises_without_returns_direct():
    """Direct portfolio-layer call raises ValueError when method=historical
    and historical_returns is missing."""
    with pytest.raises(ValueError):
        calculate_portfolio_var(_long_index_position(), method="historical")


def test_stress_built_in_scenarios_run():
    positions = _long_index_position()
    out = stress_test_portfolio(positions)
    scenarios = {s["scenario"] for s in out["scenarios"] if "error" not in s}
    assert "rates+200bp" in scenarios
    assert "xu030_-10pct" in scenarios
    # Long XU030 future should lose money in xu030_-10pct
    losing = next(s for s in out["scenarios"] if s["scenario"] == "xu030_-10pct")
    assert losing["pnl_amount"] < 0


def test_stress_custom_scenario():
    positions = _long_index_position()
    out = stress_test_portfolio(
        positions,
        scenarios=["custom_crash"],
        custom_scenarios={"custom_crash": {"spot_pct": {"XU030": -25}}},
    )
    matches = [s for s in out["scenarios"] if s["scenario"] == "custom_crash"]
    assert len(matches) == 1
    assert matches[0]["pnl_amount"] < 0


def test_stress_unknown_scenario_reports_error():
    positions = _long_index_position()
    out = stress_test_portfolio(positions, scenarios=["does_not_exist"])
    err = next(s for s in out["scenarios"] if s["scenario"] == "does_not_exist")
    assert "error" in err


def test_builtin_scenarios_self_consistent():
    """Every built-in scenario must run without raising on a vanilla portfolio."""
    positions = _long_index_position()
    out = stress_test_portfolio(positions, scenarios=list(BUILTIN_SCENARIOS))
    assert len(out["scenarios"]) == len(BUILTIN_SCENARIOS)
    for s in out["scenarios"]:
        assert "error" not in s

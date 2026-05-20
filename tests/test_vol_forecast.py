"""Tests for EWMA + GARCH(1,1) — pure math."""

from __future__ import annotations

import math

import pytest

from bist_trader_mcp.vol_forecast import (
    ewma_volatility,
    fit_garch_11,
    garch_forecast,
)


def _synthetic_returns(n: int, sigma: float = 0.01) -> list[float]:
    """Build a deterministic alternating ±sigma return series."""
    return [sigma if i % 2 == 0 else -sigma for i in range(n)]


def test_ewma_zero_returns_yields_seed_floor():
    out = ewma_volatility([0.0] * 50)
    # Seed variance is essentially zero
    assert out["current_vol_pct"] is not None
    assert out["current_vol_pct"] < 1.0


def test_ewma_known_volatility_recovery():
    rets = _synthetic_returns(100, sigma=0.01)
    out = ewma_volatility(rets, decay=0.94)
    # σ=0.01 daily → annualised ≈ 0.01 * sqrt(252) * 100 ≈ 15.87%
    expected = 0.01 * math.sqrt(252) * 100
    assert out["current_vol_pct"] == pytest.approx(expected, rel=0.10)


def test_ewma_invalid_decay():
    with pytest.raises(ValueError):
        ewma_volatility([0.01, -0.01, 0.02], decay=1.5)


def test_ewma_empty_returns_safe():
    out = ewma_volatility([])
    assert out["current_vol_pct"] is None


def test_ewma_next_period_forecast_set():
    rets = _synthetic_returns(60, sigma=0.015)
    out = ewma_volatility(rets)
    assert out["next_period_forecast_pct"] is not None
    assert out["next_period_forecast_pct"] > 0


def test_garch_fit_returns_finite():
    rets = _synthetic_returns(200, sigma=0.02)
    params = fit_garch_11(rets, grid_steps=5)
    assert params.omega > 0
    assert 0 <= params.alpha < 1
    assert 0 <= params.beta < 1
    assert params.alpha + params.beta < 1.0
    assert params.log_likelihood > -1e17


def test_garch_fit_min_sample_size():
    with pytest.raises(ValueError):
        fit_garch_11([0.01, -0.01, 0.02], grid_steps=3)


def test_garch_forecast_path_length():
    rets = _synthetic_returns(150, sigma=0.015)
    out = garch_forecast(rets, horizon_days=10, annualise_days=252)
    assert len(out["forecast_path_pct"]) == 10
    assert out["h1_forecast_pct"] > 0


def test_garch_forecast_converges_toward_stationary():
    """For α+β < 1, long-horizon forecasts approach stationary level."""
    rets = _synthetic_returns(200, sigma=0.02)
    out = garch_forecast(rets, horizon_days=100)
    if out["stationary_vol_pct"] is not None and out["forecast_path_pct"]:
        far_horizon = out["forecast_path_pct"][-1]
        # Should be within 30% of stationary level at h=100
        # (relaxed tolerance because of coarse grid fit)
        assert abs(far_horizon - out["stationary_vol_pct"]) / max(
            out["stationary_vol_pct"], 1e-6) < 0.30


def test_garch_forecast_empty_returns_safe():
    out = garch_forecast([], horizon_days=10)
    assert out["forecast_path_pct"] == []

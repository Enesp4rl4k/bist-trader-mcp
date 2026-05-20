"""Tests for Nelson-Siegel-Svensson yield curve fitter — pure math."""

from __future__ import annotations

import pytest

from bist_trader_mcp.yield_fitter import (
    evaluate_curve,
    fit_nelson_siegel,
)


def test_fit_requires_matching_lengths():
    with pytest.raises(ValueError):
        fit_nelson_siegel([1.0, 2.0], [40.0])


def test_fit_requires_min_observations():
    with pytest.raises(ValueError):
        fit_nelson_siegel([1.0, 2.0], [40.0, 42.0])


def test_fit_recovers_flat_curve():
    """Flat 40% curve → NS fit β₀≈40, RMSE near zero."""
    maturities = [0.5, 1, 2, 3, 5, 7, 10]
    yields = [40.0] * 7
    params = fit_nelson_siegel(maturities, yields, use_svensson=False)
    assert params.beta0 == pytest.approx(40.0, abs=0.5)
    assert params.rmse < 0.5


def test_fit_normal_upward_sloping():
    """Upward sloping curve: 30% at 1Y → 45% at 10Y."""
    maturities = [0.5, 1, 2, 3, 5, 7, 10]
    yields = [28.0, 30.0, 33.0, 36.0, 40.0, 43.0, 45.0]
    params = fit_nelson_siegel(maturities, yields, use_svensson=True)
    # Eval at 1Y and 10Y should be close to observed
    y_1y = evaluate_curve(params, 1.0)
    y_10y = evaluate_curve(params, 10.0)
    assert abs(y_1y - 30.0) < 2.0
    assert abs(y_10y - 45.0) < 2.0


def test_evaluate_at_unobserved_tenor_is_smooth():
    """Curve passes between observed points."""
    maturities = [1, 2, 5, 10]
    yields = [30.0, 35.0, 42.0, 45.0]
    params = fit_nelson_siegel(maturities, yields, use_svensson=False)
    y_3y = evaluate_curve(params, 3.0)
    y_2y = evaluate_curve(params, 2.0)
    y_5y = evaluate_curve(params, 5.0)
    # 3Y should be between 2Y and 5Y values (monotone region)
    lo, hi = sorted([y_2y, y_5y])
    assert lo - 2 <= y_3y <= hi + 2


def test_ns_vs_nss_rmse_relation():
    """NSS should fit at least as well as NS on the same data."""
    maturities = [0.5, 1, 2, 3, 5, 7, 10, 15, 20]
    # Curve with two humps
    yields = [30.0, 32.0, 38.0, 42.0, 45.0, 44.0, 42.0, 40.0, 39.0]
    ns = fit_nelson_siegel(maturities, yields, use_svensson=False)
    nss = fit_nelson_siegel(maturities, yields, use_svensson=True)
    assert nss.rmse <= ns.rmse + 1e-6

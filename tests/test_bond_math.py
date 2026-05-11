"""Sanity tests for bond_math — no network required."""

from __future__ import annotations

import math

import pytest

from bist_trader_mcp.bond_math import bond_metrics


def test_par_bond_ytm_equals_coupon():
    """A bond priced at par with semi-annual coupon should have YTM == coupon."""
    ytm, mod_dur, convex = bond_metrics(
        face_value=100.0,
        coupon_rate_pct=25.0,
        years_to_maturity=5.0,
        market_price=100.0,
        coupon_frequency=2,
    )
    assert math.isclose(ytm * 100, 25.0, rel_tol=1e-3)
    assert mod_dur > 0
    assert convex > 0


def test_discount_bond_ytm_above_coupon():
    """A bond priced below par should have a YTM above its coupon."""
    ytm, _, _ = bond_metrics(
        face_value=100.0,
        coupon_rate_pct=20.0,
        years_to_maturity=3.0,
        market_price=90.0,
        coupon_frequency=2,
    )
    assert ytm * 100 > 20.0


def test_premium_bond_ytm_below_coupon():
    """A bond priced above par should have a YTM below its coupon."""
    ytm, _, _ = bond_metrics(
        face_value=100.0,
        coupon_rate_pct=30.0,
        years_to_maturity=3.0,
        market_price=110.0,
        coupon_frequency=2,
    )
    assert ytm * 100 < 30.0


def test_invalid_face_value_rejected():
    with pytest.raises(ValueError):
        bond_metrics(
            face_value=0,
            coupon_rate_pct=10,
            years_to_maturity=1,
            market_price=100,
        )


def test_duration_shorter_for_shorter_maturity():
    """Modified duration should monotonically increase with maturity for par bonds."""
    _, mod_dur_short, _ = bond_metrics(100, 25, 2, 100)
    _, mod_dur_long, _ = bond_metrics(100, 25, 10, 100)
    assert mod_dur_long > mod_dur_short

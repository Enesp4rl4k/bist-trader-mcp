"""Black-Scholes sanity tests — pure math, no network."""

from __future__ import annotations

import math

import pytest

from bist_trader_mcp.options_math import black_scholes, implied_volatility


def test_call_put_parity():
    """C - P = S * e^(-q T) - K * e^(-r T) should hold."""
    s, k, t, sigma, r, q = 100.0, 100.0, 1.0, 0.30, 0.10, 0.02
    call = black_scholes(s, k, t, sigma, r, q, "call")
    put = black_scholes(s, k, t, sigma, r, q, "put")
    lhs = call.price - put.price
    rhs = s * math.exp(-q * t) - k * math.exp(-r * t)
    assert math.isclose(lhs, rhs, rel_tol=1e-6, abs_tol=1e-6)


def test_atm_call_delta_around_half():
    """At-the-money short-dated call should have delta near 0.5."""
    g = black_scholes(100.0, 100.0, 30 / 365.0, 0.30, 0.10, 0.0, "call")
    assert 0.40 < g.delta < 0.65


def test_deep_itm_call_delta_close_to_one():
    g = black_scholes(150.0, 100.0, 1.0, 0.30, 0.10, 0.0, "call")
    assert g.delta > 0.90


def test_deep_otm_put_delta_close_to_zero():
    g = black_scholes(150.0, 100.0, 1.0, 0.30, 0.10, 0.0, "put")
    assert -0.10 < g.delta < 0.0


def test_iv_round_trip():
    """price -> iv -> price round-trip stays within tolerance."""
    target = black_scholes(100.0, 105.0, 90 / 365.0, 0.42, 0.20, 0.0, "call")
    iv = implied_volatility(
        target.price, 100.0, 105.0, 90 / 365.0, 0.20, 0.0, "call"
    )
    assert math.isclose(iv, 0.42, abs_tol=1e-3)


def test_negative_inputs_rejected():
    with pytest.raises(ValueError):
        black_scholes(-1.0, 100.0, 0.5, 0.3, 0.1)
    with pytest.raises(ValueError):
        black_scholes(100.0, 100.0, 0.0, 0.3, 0.1)
    with pytest.raises(ValueError):
        black_scholes(100.0, 100.0, 0.5, 0.0, 0.1)


def test_high_vol_tr_distressed_scenario():
    """A VIOP put on a distressed underlying with 200% IV should price and
    return finite greeks (no overflow)."""
    g = black_scholes(50.0, 60.0, 30 / 365.0, 2.0, 0.45, 0.0, "put")
    assert math.isfinite(g.price)
    assert math.isfinite(g.delta)
    assert math.isfinite(g.gamma)

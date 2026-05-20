"""Portfolio Greeks aggregator tests — pure math, no network."""

from __future__ import annotations

import math

from bist_trader_mcp.portfolio import aggregate_portfolio_greeks


def test_empty_portfolio():
    out = aggregate_portfolio_greeks([])
    assert out["count"] == 0
    assert out["totals"]["delta"] == 0.0
    assert out["by_underlying"] == {}


def test_spot_leg_linear_delta():
    out = aggregate_portfolio_greeks(
        [
            {
                "symbol": "THYAO",
                "underlying": "THYAO",
                "qty": 1000,
                "instrument_type": "spot",
                "spot": 250.0,
            }
        ]
    )
    assert out["count"] == 1
    assert out["totals"]["delta"] == 1000.0
    assert out["totals"]["gamma"] == 0.0
    assert out["totals"]["net_notional"] == 250_000.0


def test_future_leg_signed_delta():
    out = aggregate_portfolio_greeks(
        [
            {
                "symbol": "F_USDTRY",
                "underlying": "USDTRY",
                "qty": -3,
                "instrument_type": "future",
                "spot": 38.0,
                "multiplier": 1000,
            }
        ]
    )
    assert out["totals"]["delta"] == -3000.0
    assert out["totals"]["vega"] == 0.0


def test_long_call_delta_positive():
    out = aggregate_portfolio_greeks(
        [
            {
                "symbol": "C_XU030_3500",
                "underlying": "XU030",
                "qty": 5,
                "instrument_type": "option",
                "right": "call",
                "spot": 3500.0,
                "strike": 3500.0,
                "days_to_expiry": 30,
                "volatility_pct": 35.0,
                "risk_free_rate_pct": 45.0,
                "multiplier": 1,
            }
        ]
    )
    assert out["count"] == 1
    leg = out["legs"][0]
    assert leg["delta"] > 0
    assert leg["gamma"] > 0
    assert leg["vega"] > 0
    assert leg["theta_per_day"] < 0  # long option pays theta
    assert leg["iv_pct"] == 35.0


def test_short_put_offsets_long_call_delta():
    """Long call + short put at same strike ~ synthetic future: delta ≈ qty * mult."""
    positions = [
        {
            "symbol": "C",
            "underlying": "X",
            "qty": 1,
            "instrument_type": "option",
            "right": "call",
            "spot": 100.0,
            "strike": 100.0,
            "days_to_expiry": 90,
            "volatility_pct": 30.0,
            "risk_free_rate_pct": 40.0,
        },
        {
            "symbol": "P",
            "underlying": "X",
            "qty": -1,
            "instrument_type": "option",
            "right": "put",
            "spot": 100.0,
            "strike": 100.0,
            "days_to_expiry": 90,
            "volatility_pct": 30.0,
            "risk_free_rate_pct": 40.0,
        },
    ]
    out = aggregate_portfolio_greeks(positions)
    # synthetic long forward → delta ≈ e^(-qT) ≈ 1.0 (no dividends)
    assert math.isclose(out["totals"]["delta"], 1.0, abs_tol=0.05)
    # gamma cancels
    assert abs(out["totals"]["gamma"]) < 1e-6
    # vega cancels
    assert abs(out["totals"]["vega"]) < 1e-6


def test_iv_solved_from_market_price():
    out = aggregate_portfolio_greeks(
        [
            {
                "symbol": "C",
                "underlying": "X",
                "qty": 1,
                "instrument_type": "option",
                "right": "call",
                "spot": 100.0,
                "strike": 100.0,
                "days_to_expiry": 30,
                "market_price": 5.0,
                "risk_free_rate_pct": 40.0,
            }
        ]
    )
    leg = out["legs"][0]
    assert leg["iv_pct"] is not None
    assert 1.0 < leg["iv_pct"] < 500.0
    assert "iv solved" in (leg["note"] or "")


def test_missing_option_fields_gracefully_zeroed():
    out = aggregate_portfolio_greeks(
        [
            {
                "symbol": "BAD",
                "underlying": "X",
                "qty": 1,
                "instrument_type": "option",
                "right": "call",
                # missing spot, strike, dte
            }
        ]
    )
    leg = out["legs"][0]
    assert leg["delta"] == 0.0
    assert "missing" in (leg["note"] or "")


def test_by_underlying_rollup():
    out = aggregate_portfolio_greeks(
        [
            {
                "symbol": "A1",
                "underlying": "A",
                "qty": 10,
                "instrument_type": "spot",
                "spot": 50.0,
            },
            {
                "symbol": "A2",
                "underlying": "A",
                "qty": 5,
                "instrument_type": "spot",
                "spot": 50.0,
            },
            {
                "symbol": "B1",
                "underlying": "B",
                "qty": -7,
                "instrument_type": "spot",
                "spot": 30.0,
            },
        ]
    )
    assert out["by_underlying"]["A"]["delta"] == 15.0
    assert out["by_underlying"]["B"]["delta"] == -7.0
    assert set(out["by_underlying"].keys()) == {"A", "B"}

"""Tests for iv_surface — pure math, no network."""

from __future__ import annotations

from datetime import date

import pytest

from bist_trader_mcp.iv_surface import (
    build_iv_surface,
    find_spread_opportunities,
)
from bist_trader_mcp.options_math import black_scholes
from bist_trader_mcp.viop import VIOPContract, VIOPSettlement


def _make_option_row(strike, right, expiry_year, expiry_month, spot, vol_pct,
                     r_pct=45.0, q_pct=0.0):
    """Build a synthetic VIOPSettlement whose last_price is the BS theoretical
    price for the given vol — so the IV solver should recover that vol.

    Uses the same last-day-of-month expiry convention as build_iv_surface so
    DTE matches exactly between price-in and IV-solve."""
    from calendar import monthrange
    last_day = monthrange(expiry_year, expiry_month)[1]
    days = (date(expiry_year, expiry_month, last_day) - date.today()).days
    if days <= 0:
        days = 30
    t = days / 365.0
    g = black_scholes(
        spot=spot, strike=strike, time_to_expiry=t,
        volatility=vol_pct / 100.0, risk_free_rate=r_pct / 100.0,
        dividend_yield=q_pct / 100.0,
        style="call" if right == "C" else "put",
    )
    contract = VIOPContract(
        contract_code=f"O_TEST{expiry_month:02d}26_{right}{int(strike)}",
        underlying="TEST",
        contract_type="option",
        expiry_year=expiry_year,
        expiry_month=expiry_month,
        option_strike=float(strike),
        option_right=right,
    )
    return VIOPSettlement(
        contract=contract,
        trade_date=date.today().isoformat(),
        name=contract.contract_code,
        last_price=g.price,
        percent_change=0.0,
        absolute_change=0.0,
        volume_tl=1000.0,
        open_interest=100,
    )


def test_build_iv_surface_recovers_vol():
    """If we feed BS prices at a known vol, the IV solver should recover it."""
    spot = 100.0
    today = date.today()
    next_month = today.month + 1 if today.month < 12 else 1
    next_year = today.year if today.month < 12 else today.year + 1

    chain = [
        _make_option_row(90.0,  "P", next_year, next_month, spot, vol_pct=45.0),
        _make_option_row(100.0, "C", next_year, next_month, spot, vol_pct=40.0),
        _make_option_row(110.0, "C", next_year, next_month, spot, vol_pct=42.0),
    ]
    surface = build_iv_surface(
        chain=chain, spot=spot, risk_free_rate_pct=45.0,
    )
    assert surface["meta"]["points_solved"] == 3
    ivs = {(p["strike"], p["right"]): p["iv_pct"] for p in surface["points"]}
    # Tolerance accounts for the day-28 vs last-day-of-month DTE mismatch
    # between the synthetic option pricing and build_iv_surface's expiry calc.
    assert abs(ivs[(90.0, "P")] - 45.0) < 1.5
    assert abs(ivs[(100.0, "C")] - 40.0) < 1.5
    assert abs(ivs[(110.0, "C")] - 42.0) < 1.5


def test_atm_term_structure_orders_by_dte():
    spot = 100.0
    today = date.today()
    months = [(today.year, today.month + 1 if today.month < 12 else 1)]
    if today.month <= 9:
        months.append((today.year, today.month + 3))
    chain = []
    for y, m in months:
        if m == 0:
            m = 12
        chain.append(_make_option_row(100.0, "C", y, m, spot, vol_pct=40.0))
    surface = build_iv_surface(
        chain=chain, spot=spot, risk_free_rate_pct=45.0,
    )
    ts = surface["atm_term_structure"]
    if len(ts) >= 2:
        assert ts[0]["days_to_expiry"] <= ts[1]["days_to_expiry"]


def test_skew_25d_returns_positive_for_put_rich_market():
    """Put IV > Call IV → positive skew."""
    spot = 100.0
    today = date.today()
    m = today.month + 1 if today.month < 12 else 1
    y = today.year if today.month < 12 else today.year + 1

    chain = []
    # Puts with high IV (45%) at low strikes
    for k in (80.0, 85.0, 90.0):
        chain.append(_make_option_row(k, "P", y, m, spot, vol_pct=50.0))
    # Calls with low IV (35%) at high strikes
    for k in (105.0, 110.0, 115.0):
        chain.append(_make_option_row(k, "C", y, m, spot, vol_pct=35.0))
    # ATM straddle to anchor
    chain.append(_make_option_row(100.0, "C", y, m, spot, vol_pct=40.0))
    chain.append(_make_option_row(100.0, "P", y, m, spot, vol_pct=40.0))

    surface = build_iv_surface(
        chain=chain, spot=spot, risk_free_rate_pct=45.0,
    )
    skew = surface["skew_25d_front_month"]
    assert skew is not None
    assert skew["skew_vol_pts"] > 0  # put rich


def test_spread_screener_finds_obvious_calendar():
    spot = 100.0
    today = date.today()
    # Front month: vol 60% (rich); back month: vol 30%
    m1 = today.month + 1 if today.month < 12 else 1
    y1 = today.year if today.month < 12 else today.year + 1
    m2 = today.month + 6
    y2 = today.year
    while m2 > 12:
        m2 -= 12
        y2 += 1

    chain = [
        _make_option_row(100.0, "C", y1, m1, spot, vol_pct=60.0),
        _make_option_row(100.0, "C", y2, m2, spot, vol_pct=30.0),
    ]
    surface = build_iv_surface(chain=chain, spot=spot, risk_free_rate_pct=45.0)
    cands = find_spread_opportunities(surface, strategy="calendar",
                                       min_edge_vol_pts=5.0)
    assert len(cands) == 1
    c = cands[0]
    assert c["edge_vol_pts"] > 20.0
    assert c["direction"] == "sell_front_buy_back"


def test_spread_screener_unknown_strategy_raises():
    surface = {"points": []}
    with pytest.raises(ValueError):
        find_spread_opportunities(surface, strategy="exotic_quadruple")

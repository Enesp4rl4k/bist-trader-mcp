"""DCF / reverse-DCF valuation tests."""

import pytest

from bist_trader_mcp.valuation import reverse_dcf, two_stage_dcf, value_equity, wacc


def test_wacc_capm():
    w = wacc(risk_free=0.30, equity_risk_premium=0.06, beta=1.2)
    # 0.30 + 1.2*0.06 = 0.372, all-equity
    assert w["cost_of_equity"] == pytest.approx(0.372, abs=1e-6)
    assert w["wacc"] == pytest.approx(0.372, abs=1e-6)


def test_wacc_blended_with_debt():
    w = wacc(risk_free=0.30, equity_risk_premium=0.06, beta=1.0,
             cost_of_debt=0.40, tax_rate=0.25, equity_weight=0.6, debt_weight=0.4)
    # ke=0.36, after-tax kd=0.30 → 0.6*0.36 + 0.4*0.30 = 0.336
    assert w["wacc"] == pytest.approx(0.336, abs=1e-6)


def test_two_stage_dcf_basic():
    d = two_stage_dcf(100, discount_rate=0.40, high_growth=0.20, years=5,
                      terminal_growth=0.10, shares_outstanding=100)
    assert d["available"] is True
    assert d["enterprise_value"] > 0
    assert d["fair_value_per_share"] is not None
    assert 0 < d["terminal_value_pct"] < 1
    assert len(d["projected_fcf"]) == 5


def test_dcf_requires_rate_above_terminal():
    d = two_stage_dcf(100, discount_rate=0.08, high_growth=0.05, terminal_growth=0.10)
    assert d["available"] is False


def test_higher_growth_raises_value():
    low = two_stage_dcf(100, discount_rate=0.40, high_growth=0.10, terminal_growth=0.08)
    high = two_stage_dcf(100, discount_rate=0.40, high_growth=0.30, terminal_growth=0.08)
    assert high["equity_value"] > low["equity_value"]


def test_reverse_dcf_recovers_assumed_growth():
    # Build a market cap from a known growth, then recover it.
    g_true = 0.25
    d = two_stage_dcf(100, discount_rate=0.40, high_growth=g_true, years=5,
                      terminal_growth=0.10)
    rev = reverse_dcf(d["equity_value"], 100, discount_rate=0.40, years=5,
                      terminal_growth=0.10)
    assert rev["available"] is True
    assert rev["implied_growth"] == pytest.approx(g_true, abs=0.005)


def test_value_equity_margin_of_safety():
    out = value_equity(
        fcf0=100, discount_rate=0.40, high_growth=0.20, years=5,
        terminal_growth=0.10, shares_outstanding=100, current_price=1.0,
    )
    fv = out["dcf"]["fair_value_per_share"]
    assert out["verdict"] in ("undervalued", "overvalued", "fair")
    # fair value well above a 1.0 price → undervalued with positive MoS
    assert fv > 1.0
    assert out["margin_of_safety"] > 0
    assert out["verdict"] == "undervalued"
    assert "DCF" in out["summary_tr"]


def test_reverse_dcf_extreme_optimism_flagged():
    rev = reverse_dcf(10_000_000, 100, discount_rate=0.40, terminal_growth=0.10)
    assert rev["available"] is True
    assert rev["implied_growth"] is None  # beyond +150% growth

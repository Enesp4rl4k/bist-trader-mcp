"""Advanced valuation maths checked against closed-form / textbook results."""

import math
import random

import pytest

from bist_trader_mcp import valuation_pro as vp

BASE = dict(revenue0=1000.0, wacc=0.10, revenue_growth=0.0, ebit_margin=0.20, years=5,
            tax_rate=0.25, da_pct_revenue=0.05, capex_pct_revenue=0.05, nwc_pct_revenue=0.1,
            terminal_growth=0.0, mid_year=False)


def test_fisher_roundtrip():
    real = vp.fisher(0.45, 0.40)
    assert real == pytest.approx(1.45 / 1.40 - 1)
    assert vp.fisher(real, 0.40, to="nominal") == pytest.approx(0.45)


def test_beta_recovers_known_slope():
    rng = random.Random(1)
    idx, stk = [100.0], [50.0]
    for _ in range(250):
        r = rng.gauss(0, 0.01)
        idx.append(idx[-1] * (1 + r))
        stk.append(stk[-1] * (1 + 1.5 * r))
    b = vp.estimate_beta(stk, idx)
    assert b["raw_beta"] == pytest.approx(1.5, abs=1e-6)
    assert b["r_squared"] == pytest.approx(1.0, abs=1e-6)
    assert b["beta"] == pytest.approx(0.67 * 1.5 + 0.33, abs=1e-4)
    with pytest.raises(ValueError):
        vp.estimate_beta(stk[:10], idx[:10])


def test_unlever_relever_roundtrip():
    bu = vp.unlever_beta(1.4, 0.5, 0.25)
    assert bu == pytest.approx(1.4 / (1 + 0.75 * 0.5))
    assert vp.relever_beta(bu, 0.5, 0.25) == pytest.approx(1.4)


def test_build_wacc_market_weights():
    w = vp.build_wacc(risk_free=0.30, beta=1.2, equity_risk_premium=0.05,
                      country_risk_premium=0.03, pre_tax_cost_of_debt=0.35, tax_rate=0.25,
                      market_cap=700, debt=300)
    assert w["cost_of_equity"] == pytest.approx(0.396)
    assert w["after_tax_cost_of_debt"] == pytest.approx(0.2625)
    assert w["wacc"] == pytest.approx(0.7 * 0.396 + 0.3 * 0.2625, abs=1e-5)


def test_no_growth_firm_is_a_perpetuity():
    r = vp.driver_dcf(**BASE)
    fcff = 1000 * 0.20 * 0.75  # capex = D&A, no revenue change → no ΔNWC
    assert all(row["fcff"] == pytest.approx(fcff) for row in r["projection"])
    assert r["enterprise_value"] == pytest.approx(fcff / 0.10, rel=1e-9)


def test_mid_year_convention():
    r = vp.driver_dcf(**{**BASE, "mid_year": True})
    expected = sum(150 / 1.1 ** (t - 0.5) for t in range(1, 6)) + (150 / 0.1) / 1.1 ** 5
    assert r["enterprise_value"] == pytest.approx(expected, abs=0.01)  # output is 2 dp


def test_growth_needs_working_capital_and_value_driver_terminal():
    grow = vp.driver_dcf(**{**BASE, "revenue_growth": 0.10, "terminal_growth": 0.03,
                            "terminal_roic": 0.10})
    first = grow["projection"][0]
    assert first["revenue"] == pytest.approx(1100)
    # FCFF = NOPAT − ΔNWC (capex = D&A): 1100·0.2·0.75 − 0.1·100
    assert first["fcff"] == pytest.approx(165 - 10)
    # RONIC = WACC ⇒ TV = NOPAT_N+1 / WACC (growth adds no value)
    nopat_next = grow["projection"][-1]["nopat"] * 1.03
    assert grow["pv_terminal"] == pytest.approx(nopat_next / 0.10 / 1.1 ** 5, rel=1e-4)
    assert grow["terminal_method"] == "value_driver"


def test_equity_bridge_and_per_share():
    r = vp.driver_dcf(**{**BASE, "debt": 400, "cash": 100, "minority_interest": 50,
                         "non_operating_assets": 25, "shares_outstanding": 10})
    assert r["equity_value"] == pytest.approx(1500 - 400 + 100 - 50 + 25)
    assert r["fair_value_per_share"] == pytest.approx(117.5)


def test_invalid_inputs():
    assert not vp.driver_dcf(**{**BASE, "terminal_growth": 0.12})["available"]
    assert not vp.driver_dcf(**{**BASE, "revenue0": 0})["available"]


def test_sensitivity_is_monotonic():
    s = vp.sensitivity({**BASE, "terminal_growth": 0.02, "shares_outstanding": 10})
    grid = s["values"]
    assert all(row == sorted(row) for row in grid)                  # ↑ growth → ↑ value
    assert all(grid[i][2] > grid[i + 1][2] for i in range(len(grid) - 1))  # ↑ WACC → ↓


def test_scenarios_are_probability_weighted():
    sc = vp.scenario_valuation(
        {**BASE, "shares_outstanding": 10},
        {"bear": {"ebit_margin": 0.10}, "base": {}, "bull": {"ebit_margin": 0.30}},
        {"bear": 0.25, "base": 0.5, "bull": 0.25},
    )
    v = {k: s["value"] for k, s in sc["scenarios"].items()}
    assert sc["expected_value"] == pytest.approx(0.25 * v["bear"] + 0.5 * v["base"]
                                                 + 0.25 * v["bull"])
    assert v["bear"] < v["base"] < v["bull"]


def test_monte_carlo_is_reproducible_and_centred():
    kw = {**BASE, "revenue_growth": 0.05, "terminal_growth": 0.02, "shares_outstanding": 10}
    a = vp.monte_carlo_dcf(kw, n=600, price=100, seed=3)
    b = vp.monte_carlo_dcf(kw, n=600, price=100, seed=3)
    assert a == b
    base = vp.driver_dcf(**kw)["fair_value_per_share"]
    assert a["p5"] < a["p50"] < a["p95"]
    assert abs(a["p50"] - base) / base < 0.10
    assert 0 <= a["prob_above_price"] <= 1


def test_ddm_constant_growth_equals_gordon():
    r = vp.dividend_discount(dividend0=1.0, cost_of_equity=0.10, high_growth=0.05,
                             terminal_growth=0.05, years=7)
    assert r["value_per_share"] == pytest.approx(1.05 / 0.05)


def test_bank_models():
    assert vp.justified_pb(0.20, 0.15, 0.05) == pytest.approx(1.5)
    fair = vp.residual_income(book_value0=1000, roe=0.25, cost_of_equity=0.25,
                              shares_outstanding=100)
    assert fair["equity_value"] == pytest.approx(1000)       # ROE = ke → worth book
    rich = vp.residual_income(book_value0=1000, roe=0.35, cost_of_equity=0.25)
    assert rich["implied_pb"] > 1


def test_relative_valuation_uses_peer_medians():
    peers = [{"ticker": "A", "pe": 8, "ev_ebitda": 5}, {"ticker": "B", "pe": 10, "ev_ebitda": 6},
             {"ticker": "C", "pe": 12, "ev_ebitda": 7}, {"ticker": "D", "pe": -3},
             {"ticker": "E", "pe": float("nan")}]
    out = vp.relative_valuation(peers, {"net_income": 100, "ebitda": 200},
                                shares_outstanding=10, net_debt=300)
    assert out["multiples"]["pe"]["base"] == pytest.approx(10 * 100 / 10)
    assert out["multiples"]["pe"]["peers_used"] == 3
    assert out["multiples"]["ev_ebitda"]["base"] == pytest.approx((6 * 200 - 300) / 10)


def test_football_field_and_sanity():
    ff = vp.football_field({"dcf": {"low": 80, "base": 120, "high": 150},
                            "multiples": {"low": 90, "base": 100, "high": 110}},
                           price=80, weights={"dcf": 3, "multiples": 1})
    assert ff["blended_value"] == pytest.approx(115)
    assert ff["verdict"] == "undervalued"
    dcf = vp.driver_dcf(**{**BASE, "revenue_growth": 0.3, "wacc": 0.30, "terminal_growth": 0.05})
    notes = vp.sanity_checks(dcf, expected_inflation=0.30)
    assert any("enflasyon" in n for n in notes)
    assert any("terminal_roic" in n for n in notes)
    assert not math.isnan(dcf["enterprise_value"])

"""CFO-grade statement analysis — ratios, F/Z/M scores, selection signal."""

from bist_trader_mcp.fundamental_statements import (
    FinancialPeriod,
    altman_z_score,
    analyze_financials,
    beneish_m_score,
    compute_ratios,
    piotroski_f_score,
)


def _healthy_prior() -> FinancialPeriod:
    return FinancialPeriod(
        period_end="2022-12-31", is_inflation_adjusted=True,
        revenue=1000, cogs=600, gross_profit=400, sga=150,
        operating_income=250, depreciation=50, interest_expense=20,
        pretax_income=230, tax_expense=46, net_income=184,
        total_assets=1200, current_assets=600, cash=200, inventory=150,
        receivables=120, ppe=400, current_liabilities=300,
        long_term_debt=200, total_debt=300, total_liabilities=500,
        total_equity=700, retained_earnings=400, shares_outstanding=100,
        operating_cash_flow=240, capex=60, dividends_paid=40,
    )


def _healthy_current() -> FinancialPeriod:
    return FinancialPeriod(
        period_end="2023-12-31", is_inflation_adjusted=True,
        revenue=1250, cogs=720, gross_profit=530, sga=170,
        operating_income=340, depreciation=55, interest_expense=18,
        pretax_income=322, tax_expense=64, net_income=258,
        total_assets=1350, current_assets=700, cash=300, inventory=160,
        receivables=130, ppe=420, current_liabilities=300,
        long_term_debt=160, total_debt=260, total_liabilities=480,
        total_equity=870, retained_earnings=600, shares_outstanding=100,
        operating_cash_flow=300, capex=70, dividends_paid=50,
        market_cap=2600,
    )


def test_ratios_reasonable_for_healthy_firm():
    r = compute_ratios(_healthy_current(), _healthy_prior())
    assert 0.30 < r["roe"] < 0.40            # ~33% on avg equity
    assert r["net_margin"] > 0.18
    assert r["current_ratio"] > 2.0
    assert r["interest_coverage"] > 10
    assert r["fcf"] > 0
    assert r["fcf_yield"] is not None        # market_cap supplied


def test_piotroski_high_for_improving_firm():
    f = piotroski_f_score(_healthy_current(), _healthy_prior())
    assert f["max"] == 9
    assert f["score"] >= 7
    assert f["grade"] == "strong"


def test_piotroski_partial_without_prior():
    f = piotroski_f_score(_healthy_current(), None)
    assert f["max"] == 3
    assert f["grade"] == "partial"


def test_altman_em_safe_for_healthy_firm():
    z = altman_z_score(_healthy_current(), model="em")
    assert z["available"] is True
    assert z["model"] == "em"
    assert z["zone"] == "safe"


def test_altman_distress_for_weak_firm():
    weak = FinancialPeriod(
        period_end="2023-12-31",
        revenue=500, operating_income=-40, net_income=-90,
        total_assets=1000, current_assets=150, current_liabilities=400,
        retained_earnings=-300, total_liabilities=950, total_equity=50,
    )
    z = altman_z_score(weak, model="em")
    assert z["available"] is True
    assert z["zone"] == "distress"


def test_beneish_needs_prior_and_inputs():
    assert beneish_m_score(_healthy_current(), None)["available"] is False
    res = beneish_m_score(_healthy_current(), _healthy_prior())
    assert res["available"] is True
    assert res["flag"] == "clean"          # healthy firm not flagged


def test_beneish_flags_manipulator():
    prior = FinancialPeriod(
        period_end="2022-12-31",
        revenue=1000, gross_profit=400, sga=120, depreciation=80,
        receivables=100, current_assets=500, ppe=400, total_assets=1200,
        total_liabilities=500, net_income=150, operating_cash_flow=140,
    )
    # Receivables explode vs sales, margins fall, accruals spike → manipulation.
    cur = FinancialPeriod(
        period_end="2023-12-31",
        revenue=1100, gross_profit=300, sga=90, depreciation=40,
        receivables=400, current_assets=900, ppe=420, total_assets=1500,
        total_liabilities=800, net_income=260, operating_cash_flow=30,
    )
    res = beneish_m_score(cur, prior)
    assert res["available"] is True
    assert res["flag"] == "likely_manipulator"


def test_analyze_financials_selects_healthy_over_weak():
    good = analyze_financials(_healthy_current(), _healthy_prior(), ticker="GOOD")
    assert good["selection"]["grade"] in ("A", "B")
    assert good["selection"]["bias"] == "bullish"
    assert not good["selection"]["red_flags"]
    assert "GOOD" in good["summary_tr"]

    weak = FinancialPeriod(
        period_end="2023-12-31",
        revenue=500, operating_income=-40, net_income=-90,
        total_assets=1000, current_assets=150, current_liabilities=400,
        retained_earnings=-300, total_liabilities=950, total_equity=50,
        operating_cash_flow=-60,
    )
    bad = analyze_financials(weak, ticker="WEAK")
    assert bad["selection"]["score"] < good["selection"]["score"]
    assert "bankruptcy_distress" in bad["selection"]["red_flags"]


def test_red_flag_caps_score():
    # Decent profitability but distressed balance sheet → score must be capped down.
    fp = FinancialPeriod(
        period_end="2023-12-31",
        revenue=1000, operating_income=120, net_income=80, gross_profit=300,
        total_assets=2000, current_assets=300, current_liabilities=500,
        retained_earnings=-500, total_liabilities=1900, total_equity=100,
        operating_cash_flow=90,
    )
    out = analyze_financials(fp, ticker="TRAP")
    assert out["selection"]["score"] <= -5.0
    assert out["selection"]["red_flags"]


def test_accepts_plain_dict_input():
    out = analyze_financials(
        {"period_end": "2023-12-31", "revenue": 100, "net_income": 10,
         "total_assets": 200, "total_equity": 120, "operating_cash_flow": 12},
        ticker="DICT",
    )
    assert out["ratios"]["net_margin"] == 0.1
    assert out["period_end"] == "2023-12-31"

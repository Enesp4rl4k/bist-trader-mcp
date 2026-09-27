"""Company valuation orchestration: auto-fill, sources, models, MCP wiring."""

import asyncio
import json
import random

import pytest

from bist_trader_mcp import company_valuation as cv
from bist_trader_mcp.fundamental_data import derive_drivers, parse_timeseries


def _ts(field, rows):
    return {"meta": {"type": [field]}, "timestamp": [1],
            field: [{"asOfDate": d, "reportedValue": {"raw": v}} for d, v in rows]}


PAYLOAD = {"timeseries": {"result": [
    _ts("annualTotalRevenue", [("2023-12-31", 1000.0), ("2024-12-31", 1210.0),
                               ("2022-12-31", None)]),
    _ts("annualEBIT", [("2023-12-31", 150.0), ("2024-12-31", 200.0)]),
    _ts("annualReconciledDepreciation", [("2023-12-31", 40.0), ("2024-12-31", 48.4)]),
    _ts("annualCapitalExpenditure", [("2023-12-31", -60.0), ("2024-12-31", -72.6)]),
    _ts("annualTotalDebt", [("2024-12-31", 300.0)]),
    _ts("annualCashAndCashEquivalents", [("2024-12-31", 100.0)]),
    _ts("annualOrdinarySharesNumber", [("2024-12-31", 50.0)]),
    _ts("annualStockholdersEquity", [("2024-12-31", 800.0)]),
    _ts("annualNetIncome", [("2024-12-31", 120.0)]),
    _ts("annualCashDividendsPaid", [("2024-12-31", -30.0)]),
    _ts("annualTaxRateForCalcs", [("2024-12-31", 0.22)]),
    {"meta": {"type": ["somethingElse"]}},
]}}


def test_parse_and_derive():
    h = parse_timeseries(PAYLOAD)
    assert [d for d, _ in h["revenue"]] == ["2023-12-31", "2024-12-31"]  # None dropped, sorted
    d = derive_drivers(h)
    assert d["revenue0"] == 1210.0
    assert d["revenue_cagr"] == pytest.approx(0.21)
    assert d["ebit_margin_last"] == pytest.approx(200 / 1210, abs=1e-4)
    assert d["da_pct_revenue"] == pytest.approx(0.04)
    assert d["capex_pct_revenue"] == pytest.approx(0.06)          # abs of negative capex
    assert (d["debt"], d["cash"], d["shares_outstanding"]) == (300.0, 100.0, 50.0)
    assert d["roe"] == pytest.approx(0.15) and d["dividend_per_share"] == pytest.approx(0.6)
    assert d["payout"] == pytest.approx(0.25)
    assert not derive_drivers({})["available"]


def _walk(beta, n=260, seed=2):
    rng = random.Random(seed)
    idx, stk = [100.0], [10.0]
    for _ in range(n):
        r = rng.gauss(0, 0.01)
        idx.append(idx[-1] * (1 + r))
        stk.append(stk[-1] * (1 + beta * r + rng.gauss(0, 0.002)))
    return {"closes": stk}, {"closes": idx}


def _loaders(history=None, fund=None, beta=1.2, fail_bars=False):
    stock, index = _walk(beta)

    async def lh(sym):
        return derive_drivers(parse_timeseries(PAYLOAD)) if history is None else history

    async def lf(sym):
        if fund == "fail":
            raise RuntimeError("yahoo down")
        return fund or {"current_price": 20.0, "market_cap": 1000.0}

    async def lb(sym):
        if fail_bars:
            raise RuntimeError("no bars")
        return index if sym == "XU100" else stock

    return {"load_history": lh, "load_fundamentals": lf, "load_bars": lb}


def _run(**kw):
    return asyncio.run(cv.value_company(**kw))


def test_industrial_autofill_end_to_end():
    r = _run(symbol="THYAO", risk_free=0.10, expected_inflation=0.03, **_loaders())
    assert r["model"] == "industrial" and r["dcf"]["available"]
    assert r["sources"]["revenue0"] == "yahoo" and r["sources"]["beta"] == "derived"
    assert r["beta"]["raw_beta"] == pytest.approx(1.2, abs=0.05)
    assert r["inputs"]["terminal_growth"] == pytest.approx(1.02 * 1.03 - 1)
    assert r["dcf"]["assumptions"]["terminal_roic"] == pytest.approx(r["inputs"]["wacc"])
    ff = r["football_field"]
    assert ff["available"] and ff["price"] == 20.0 and "dcf" in ff["methods"]
    assert r["monte_carlo"]["p25"] <= r["dcf"]["fair_value_per_share"] <= r["monte_carlo"]["p75"]
    assert set(r["scenarios"]["scenarios"]) == {"ayı", "baz", "boğa"}
    assert "ddm" in r  # dividends paid → DDM included
    assert "güvenlik marjı" in r["summary_tr"]


def test_user_values_win_over_autofill():
    r = _run(symbol="THYAO", wacc=0.12, ebit_margin=0.30, shares_outstanding=100,
             beta=0.9, **_loaders())
    assert r["sources"]["ebit_margin"] == "user" and r["inputs"]["ebit_margin"] == 0.30
    assert r["sources"]["shares_outstanding"] == "user"
    assert r["sources"]["wacc"] == "user" and r["beta"] is None


def test_needs_discount_rate():
    r = _run(symbol="THYAO", **_loaders())
    assert r["error"] == "needs_input" and "risk_free" in r["detail"]


def test_manual_valuation_without_symbol():
    r = _run(revenue0=5000, revenue_growth=[0.3, 0.25, 0.2], ebit_margin=0.15, wacc=0.35,
             terminal_growth=0.25, expected_inflation=0.22, shares_outstanding=100, price=40,
             debt=1000, cash=500, run_monte_carlo=False)
    assert r["dcf"]["available"] and r["sources"]["revenue0"] == "user"
    assert r["sources"]["da_pct_revenue"] == "default"
    assert r["football_field"]["price"] == 40


def test_bank_model_is_chosen_for_banks():
    r = _run(symbol="GARAN", risk_free=0.10, **_loaders())
    assert r["model"] == "bank" and "dcf" not in r
    assert r["residual_income"]["available"]
    assert {"residual_income", "justified_pb"} <= set(r["football_field"]["methods"])


def test_missing_data_is_explained_not_crashed():
    r = _run(symbol="THYAO", risk_free=0.1, **_loaders(history={"available": False},
                                                      fund="fail", fail_bars=True))
    assert r["error"] == "needs_input"
    assert r["notes"] and any("Beta" in n for n in r["notes"])


def test_peer_multiples_feed_the_football_field():
    peers = [{"ticker": "A", "pe": 8, "ev_ebitda": 5}, {"ticker": "B", "pe": 10,
                                                       "ev_ebitda": 6},
             {"ticker": "C", "pe": 12, "ev_ebitda": 7}]
    r = _run(symbol="THYAO", risk_free=0.1, peers=peers, run_monte_carlo=False,
             **_loaders())
    assert r["relative"]["multiples"]["pe"]["base"] == pytest.approx(10 * 120 / 50)
    assert "multiples" in r["football_field"]["methods"]


def test_value_company_through_mcp(monkeypatch):
    from bist_trader_mcp import server as srv

    out = asyncio.run(srv._call_tool("value_company", {
        "revenue0": 1000, "revenue_growth": [0.2, 0.15], "ebit_margin": 0.2, "wacc": 0.3,
        "terminal_growth": 0.2, "shares_outstanding": 10, "price": 50,
        "run_monte_carlo": False}))
    res = json.loads(out[0].text)
    assert res["dcf"]["available"] and res["football_field"]["available"]
    bad = json.loads(asyncio.run(srv._call_tool("value_company",
                                                {"symbol": "$(id)", "wacc": 0.3}))[0].text)
    assert bad["error"] == "bad_input"

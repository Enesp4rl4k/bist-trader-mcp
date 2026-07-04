"""Cross-sectional factor ranking + screening tests."""

from bist_trader_mcp.universe_ranking import (
    build_factor_record,
    rank_universe,
    screen_universe,
)


def _universe():
    # AAA: cheap + high quality, BBB: mid, CCC: expensive + low quality.
    return [
        {"ticker": "AAA", "sector": "ind", "fcf_yield": 0.12, "roe": 0.30,
         "roic": 0.25, "momentum_6m": 0.20, "net_debt_to_ebitda": 0.5},
        {"ticker": "BBB", "sector": "ind", "fcf_yield": 0.06, "roe": 0.15,
         "roic": 0.12, "momentum_6m": 0.05, "net_debt_to_ebitda": 2.0},
        {"ticker": "CCC", "sector": "ind", "fcf_yield": 0.01, "roe": 0.04,
         "roic": 0.03, "momentum_6m": -0.10, "net_debt_to_ebitda": 5.0},
    ]


def test_ranking_orders_best_first():
    out = rank_universe(_universe())
    order = [r["ticker"] for r in out["ranking"]]
    assert order == ["AAA", "BBB", "CCC"]
    assert out["ranking"][0]["rank"] == 1
    assert out["ranking"][0]["percentile"] == 100.0
    assert out["rated"] == 3


def test_low_direction_factor_is_inverted():
    # net_debt_to_ebitda is "low good": AAA (0.5) should get a positive signed z.
    out = rank_universe(_universe())
    aaa = next(r for r in out["ranking"] if r["ticker"] == "AAA")
    ccc = next(r for r in out["ranking"] if r["ticker"] == "CCC")
    assert aaa["factor_z"]["net_debt_to_ebitda"] > 0
    assert ccc["factor_z"]["net_debt_to_ebitda"] < 0


def test_top_n_limits_results():
    out = rank_universe(_universe(), top=2)
    assert len(out["ranking"]) == 2
    assert out["count"] == 3


def test_sector_neutral_groups_by_sector():
    recs = _universe() + [
        {"ticker": "DDD", "sector": "bank", "fcf_yield": 0.05, "roe": 0.20,
         "roic": 0.10, "momentum_6m": 0.02, "net_debt_to_ebitda": 1.0},
        {"ticker": "EEE", "sector": "bank", "fcf_yield": 0.04, "roe": 0.10,
         "roic": 0.05, "momentum_6m": -0.01, "net_debt_to_ebitda": 1.5},
    ]
    out = rank_universe(recs, sector_neutral=True)
    assert out["sector_neutral"] is True
    # Within the 2-name bank group, DDD beats EEE.
    banks = [r for r in out["ranking"] if r["sector"] == "bank"]
    assert banks[0]["ticker"] == "DDD"


def test_missing_factors_handled():
    recs = [
        {"ticker": "AAA", "sector": "x", "roe": 0.3},
        {"ticker": "BBB", "sector": "x", "roe": 0.1},
        {"ticker": "ZZZ", "sector": "x"},  # no factors at all
    ]
    out = rank_universe(recs)
    zzz = next(r for r in out["ranking"] if r["ticker"] == "ZZZ")
    assert zzz["composite_z"] is None  # unrated, sorted last
    assert out["ranking"][-1]["ticker"] == "ZZZ"


def test_screen_universe_all_criteria():
    out = screen_universe(_universe(), [
        {"field": "roe", "op": ">", "value": 0.10},
        {"field": "net_debt_to_ebitda", "op": "<", "value": 3.0},
    ])
    tickers = {r["ticker"] for r in out["results"]}
    assert tickers == {"AAA", "BBB"}
    assert out["passed"] == 2


def test_build_factor_record_from_analysis():
    analysis = {
        "ratios": {"roe": 0.25, "roic": 0.18, "fcf_yield": 0.08,
                   "net_debt_to_ebitda": 1.2},
        "piotroski": {"score": 8},
        "selection": {"score": 55},
    }
    rec = build_factor_record(ticker="AAA", sector="ind", analysis=analysis,
                              momentum_6m=0.15)
    assert rec["roe"] == 0.25
    assert rec["piotroski"] == 8
    assert rec["selection_score"] == 55
    assert rec["momentum_6m"] == 0.15

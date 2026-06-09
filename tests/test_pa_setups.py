"""PA setup builder tests."""

from bist_trader_mcp.pa_setups import pick_best_setup, score_confluence


def test_score_confluence_long_bullish():
    s = score_confluence(
        direction="long",
        close=100.0,
        supports=[{"price": 99.5, "strength": 2}],
        resistances=[{"price": 105.0, "strength": 1}],
        structure="bullish",
        atr_val=2.0,
        volumes=None,
    )
    assert s["score"] >= 55


def test_pick_best_setup_requires_min_confluence():
    setup = {"direction": "long", "setup_type": "trend_retest", "entry": 100, "stop": 98}
    best = pick_best_setup([setup], {"score": 72, "factors": ["bullish_structure"]}, min_confluence=50)
    assert best is not None
    assert best["confluence"]["score"] == 72
    assert pick_best_setup([setup], {"score": 40}, min_confluence=50) is None

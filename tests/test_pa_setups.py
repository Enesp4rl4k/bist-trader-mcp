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


def test_score_confluence_premium_discount_penalty():
    s_premium = score_confluence(
        direction="long",
        close=108.0,
        supports=[],
        resistances=[],
        structure="bullish",
        atr_val=2.0,
        volumes=None,
        range_ctx={
            "swing_leg": {
                "active": True,
                "high": 110.0,
                "low": 100.0,
                "mid": 105.0,
                "zone": "premium",
                "fib_levels": {
                    "0.0": 100.0,
                    "0.25": 102.5,
                    "0.50": 105.0,
                    "0.75": 107.5,
                    "1.0": 110.0,
                }
            }
        }
    )
    assert "chasing_in_premium" in s_premium["factors"]


def test_build_setup_candidates_ote_long():
    from bist_trader_mcp.pa_setups import build_setup_candidates
    
    candidates = build_setup_candidates(
        direction="long",
        close=103.0,
        atr_val=2.0,
        structure="bullish",
        supports=[],
        resistances=[],
        last_swing_high=110.0,
        last_swing_low=100.0,
        recent_highs=[110.0],
        recent_lows=[100.0],
        range_ctx={
            "swing_leg": {
                "active": True,
                "high": 110.0,
                "low": 100.0,
                "mid": 105.0,
                "zone": "discount",
                "fib_levels": {
                    "0.0": 100.0,
                    "0.25": 102.5,
                    "0.50": 105.0,
                    "0.75": 107.5,
                    "1.0": 110.0,
                    "ote_long_low": 102.14,
                    "ote_long_high": 103.82,
                    "ote_short_low": 106.18,
                    "ote_short_high": 107.86,
                }
            }
        }
    )
    assert any(c["setup_type"] == "ote_retest_long" for c in candidates)


def test_build_setup_candidates_sweep():
    from bist_trader_mcp.pa_setups import build_setup_candidates
    
    candidates = build_setup_candidates(
        direction="long",
        close=101.0,
        atr_val=2.0,
        structure="bullish",
        supports=[],
        resistances=[],
        last_swing_high=110.0,
        last_swing_low=100.0,
        recent_highs=[110.0],
        recent_lows=[100.0],
        range_ctx={
            "sweeps": {
                "ssl_sweep": {
                    "kind": "ssl_sweep",
                    "bar": 45,
                    "level": 100.0,
                    "extreme": 99.0,
                    "close": 101.0,
                    "play": "sweep_fade_long",
                },
                "bsl_sweep": None
            }
        }
    )
    assert any(c["setup_type"] == "ssl_sweep_long" for c in candidates)


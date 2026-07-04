"""Enhanced market structure tests."""

from bist_trader_mcp.pa_structure import infer_bar_market_structure
from bist_trader_mcp.price_action import SwingPoint, analyze_price_action, infer_market_structure
from tests.test_position_design import _uptrend_bars


def test_infer_market_structure_still_bullish_on_pivots():
    sh = [
        SwingPoint(1, 100.0, "high"),
        SwingPoint(2, 110.0, "high"),
        SwingPoint(3, 120.0, "high"),
    ]
    sl = [
        SwingPoint(1, 90.0, "low"),
        SwingPoint(2, 95.0, "low"),
        SwingPoint(3, 100.0, "low"),
    ]
    info = infer_market_structure(sh, sl)
    assert info["structure"] == "bullish"
    assert "HH" in (info.get("high_swing_labels") or info.get("swing_labels") or [])


def test_bar_fallback_bullish_on_smooth_uptrend():
    c, h, l = _uptrend_bars(80)
    bar = infer_bar_market_structure(c, h, l)
    assert bar is not None
    assert bar["structure"] == "bullish"


def test_analyze_price_action_includes_fvg_and_events():
    c, h, l = _uptrend_bars(80)
    out = analyze_price_action(c, h, l, swing_lookback=3)
    assert "fvg" in out
    assert "structure_events" in out
    detail = out["structure_detail"]
    assert detail.get("structure_source") is not None
    assert out["market_structure"] in ("bullish", "transition", "ranging")


def test_classify_pivots_strong_weak():
    from bist_trader_mcp.pa_structure import classify_strong_weak_pivots
    
    sh = [
        SwingPoint(10, 100.0, "high"),
        SwingPoint(30, 110.0, "high"),
        SwingPoint(50, 105.0, "high"),
    ]
    sl = [
        SwingPoint(20, 90.0, "low"),
        SwingPoint(40, 85.0, "low"),
        SwingPoint(60, 95.0, "low"),
    ]
    closes = [95.0] * 70
    closes[35] = 112.0
    closes[45] = 80.0
    
    classified = classify_strong_weak_pivots(sh, sl, closes)
    assert len(classified["swing_highs"]) == 3
    assert len(classified["swing_lows"]) == 3
    assert classified["swing_lows"][1]["strength"] == "strong"


def test_detect_pivot_sweeps():
    from bist_trader_mcp.pa_structure import detect_pivot_sweeps
    
    swing_highs = [
        SwingPoint(10, 100.0, "high"),
        SwingPoint(30, 110.0, "high"),
    ]
    swing_lows = [
        SwingPoint(20, 90.0, "low"),
        SwingPoint(40, 85.0, "low"),
    ]
    
    highs = [105.0] * 50
    lows = [95.0] * 50
    closes = [100.0] * 50
    
    highs[45] = 111.0
    closes[45] = 109.0
    closes[-1] = 108.0
    
    sweeps = detect_pivot_sweeps(highs, lows, closes, swing_highs, swing_lows, lookback=8)
    assert sweeps["bsl_sweep"] is not None
    assert sweeps["bsl_sweep"]["level"] == 110.0
    assert sweeps["bsl_sweep"]["extreme"] == 111.0
    assert sweeps["bsl_sweep"]["play"] == "sweep_fade_short"


def test_infer_market_structure_enhanced_swing_leg():
    from bist_trader_mcp.pa_structure import infer_market_structure_enhanced
    
    swing_highs = [
        SwingPoint(10, 110.0, "high"),
    ]
    swing_lows = [
        SwingPoint(20, 90.0, "low"),
    ]
    closes = [92.0]
    
    res = infer_market_structure_enhanced(
        swing_highs, swing_lows,
        closes=closes, highs=[110.0], lows=[90.0]
    )
    assert "swing_leg" in res
    assert res["swing_leg"]["active"] is True
    assert res["swing_leg"]["zone"] == "discount"
    assert res["swing_leg"]["position_pct"] == 0.1
    
    fibs = res["swing_leg"]["fib_levels"]
    assert fibs["0.0"] == 90.0
    assert fibs["1.0"] == 110.0
    assert fibs["0.50"] == 100.0


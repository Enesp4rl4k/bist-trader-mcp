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

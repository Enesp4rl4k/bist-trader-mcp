"""TradingView chart plan refinement tests."""

from bist_trader_mcp.tv_bridge import (
    build_demo_position_plan,
    refine_chart_trade_plan,
)


def test_refine_short_uses_resistance_retest_not_close_at_support():
    close = 61272.0
    atr = 850.0
    plan = {
        "direction": "short",
        "entry": close,
        "stop": close * 1.02,
        "targets": [{"price": 59500.0}],
    }
    mtf = {
        "ltf_analysis": {
            "atr_14": atr,
            "resistance_levels": [{"price": 62000.0, "touches": 1}],
            "support_levels": [{"price": 59500.0, "touches": 1}],
        }
    }
    out = refine_chart_trade_plan(
        plan,
        ltf_closes=[close] * 5,
        ltf_highs=[close + 100] * 5,
        ltf_lows=[close - 100] * 5,
        mtf=mtf,
    )
    assert out["entry"] == 62000.0
    assert out["stop"] > out["entry"]
    assert out["targets"][0]["price"] <= out["entry"]


def test_refine_long_uses_support_retest():
    close = 363.0
    plan = {
        "direction": "long",
        "entry": 367.75,
        "stop": 355.0,
        "targets": [{"price": 409.0}],
    }
    mtf = {
        "ltf_analysis": {
            "atr_14": 4.5,
            "support_levels": [{"price": 356.75, "touches": 2}],
            "resistance_levels": [{"price": 383.0, "touches": 1}],
        }
    }
    out = refine_chart_trade_plan(
        plan,
        ltf_closes=[close] * 5,
        ltf_highs=[365.0] * 5,
        ltf_lows=[362.0] * 5,
        mtf=mtf,
    )
    assert out["entry"] == 356.75
    assert out["stop"] < out["entry"]


def test_build_demo_skips_mtf_conflict():
    mtf = {
        "trade_quality": "conflict",
        "aligned_direction": "long",
        "conflict": True,
        "recommended_setup": {
            "entry": 100.0,
            "stop": 95.0,
            "targets": [110.0],
        },
        "ltf_analysis": {},
    }
    plan = build_demo_position_plan(
        symbol="ASELS",
        mtf=mtf,
        ltf_closes=[100.0] * 20,
        ltf_highs=[101.0] * 20,
        ltf_lows=[99.0] * 20,
    )
    assert plan is None


def test_tv_draw_rectangle_and_fvg_overlay(monkeypatch):
    import bist_trader_mcp.tv_bridge
    import bist_trader_mcp.tv_tools
    
    calls = []
    def mock_tv_call(*args, **kwargs):
        calls.append(args)
        return {"success": True, "entity_id": "mock_id"}
        
    monkeypatch.setattr(bist_trader_mcp.tv_bridge, "tv_call", mock_tv_call)
    monkeypatch.setattr(bist_trader_mcp.tv_tools, "tv_call", mock_tv_call)
    
    # Test tv_draw_rectangle directly
    from bist_trader_mcp.tv_tools import tv_draw_rectangle
    res = tv_draw_rectangle(1700000000, 100.0, 170003600, 95.0)
    assert res["success"] is True
    assert any("rectangle" in arg for arg in calls)
    
    # Test apply_pa_overlay_to_chart draws rectangle
    from bist_trader_mcp.tv_bridge import apply_pa_overlay_to_chart
    mtf = {
        "aligned_direction": "long",
        "trade_quality": "a_plus",
        "htf_structure": "bullish",
        "ltf_structure": "bullish",
        "ltf_analysis": {
            "resistance_levels": [{"price": 105.0}],
            "support_levels": [{"price": 95.0}],
            "fvg": {
                "summary": {
                    "open_bullish_zones": [{"top": 102.0, "bottom": 100.0}],
                    "open_bearish_zones": []
                }
            }
        }
    }
    
    out = apply_pa_overlay_to_chart(
        mtf,
        ltf_times=[1700000000],
        ltf_closes=[101.0],
        ltf_highs=[102.0],
    )
    
    assert out["success"] is True


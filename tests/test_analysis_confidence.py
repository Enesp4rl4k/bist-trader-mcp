"""Analysis confidence scoring tests."""

from bist_trader_mcp.analysis_confidence import (
    build_executive_summary_tr,
    compute_analysis_confidence,
)


def test_confidence_blocks_low_score():
    mtf = {
        "trade_quality": "c",
        "aligned_direction": "long",
        "ltf_analysis": {"confluence_long": {"score": 30}},
    }
    conf = compute_analysis_confidence(
        mtf=mtf,
        ew_primary={"direction": "long", "score": 25},
        data_quality={"ok": True},
        diagnostics={"warnings": ["a", "b"]},
        trade_candidate=True,
    )
    assert conf["score"] < 58
    assert conf["trade_recommended"] is False


def test_executive_summary_tr_lines():
    text = build_executive_summary_tr(
        symbol="THYAO",
        mtf={"htf_structure": "bullish", "ltf_structure": "bullish", "aligned_direction": "long", "trade_quality": "a"},
        ew_primary={"kind": "impulse", "score": 70, "forecast_summary": "wave 5"},
        confidence={"grade": "B", "score": 66, "trade_recommended": True},
        trade_candidate=True,
        scenario_id="continuation_aligned",
    )
    assert "THYAO" in text
    assert text.count("\n") == 2

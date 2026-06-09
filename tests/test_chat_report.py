"""Chat trade report builder."""

from bist_trader_mcp.chat_report import build_chat_trade_report


def test_build_chat_trade_report_sections():
    ctx = {
        "trade_candidate": True,
        "technical": {
            "confidence": {"grade": "B", "score": 72},
            "mtf": {
                "htf_structure": "bullish",
                "ltf_structure": "bullish",
                "trade_quality": "a",
                "aligned_direction": "long",
            },
            "primary_scenario": {"id": "pa_ew_long", "reason": "aligned", "direction": "long"},
            "elliott_mtf": {"notes_tr": "EW uyumlu"},
        },
        "fundamental": {
            "focus_tr": "BIST hisse",
            "research_checklist_tr": ["KAP"],
        },
    }
    trade = {
        "approved": True,
        "action": "trade",
        "plan": {
            "direction": "long",
            "entry": 100.0,
            "stop": 98.0,
            "targets": [105.0],
            "best_risk_reward": 2.5,
        },
    }
    rep = build_chat_trade_report(
        symbol="THYAO",
        market_context=ctx,
        trade_result=trade,
        fundamental_enrich={"highlights_tr": ["KAP: test"]},
        tv_ready=True,
        chart_drawn=True,
    )
    assert "THYAO" in rep["headline_tr"]
    assert "Teknik" in rep["report_tr"]
    assert rep["execution"]["approved"] is True
    assert rep["trade_allowed"] is True
    assert "summary_tr" in rep["sections"]
    assert rep["ai_presentation_rules_tr"]


def test_chat_report_fusion_blocks_execution_display():
    ctx = {
        "trade_candidate": True,
        "technical": {
            "confidence": {"grade": "B", "score": 70},
            "mtf": {
                "htf_structure": "bullish",
                "ltf_structure": "bullish",
                "trade_quality": "a",
                "aligned_direction": "long",
            },
            "primary_scenario": {"id": "x", "reason": "ok", "direction": "long"},
        },
        "fundamental": {"focus_tr": "crypto"},
    }
    trade = {"approved": True, "action": "trade", "plan": {"direction": "long"}}
    fusion = {
        "trade_allowed": False,
        "block_reason": "fusion_crowded_funding",
        "summary_tr": "Fusion 45/100",
        "warnings": ["crowded_long_funding"],
    }
    rep = build_chat_trade_report(
        symbol="BINANCE:BTCUSDT",
        market_context=ctx,
        trade_result=trade,
        fusion=fusion,
    )
    assert rep["trade_allowed"] is False
    assert rep["execution"]["approved"] is False
    assert rep["execution"]["technical_approved"] is True
    assert "fusion_crowded" in (rep["execution"].get("fusion_block_reason") or "")

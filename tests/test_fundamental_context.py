"""Fundamental research checklist (no network)."""

from bist_trader_mcp.fundamental_context import (
    build_fundamental_context,
    merge_ta_fundamental_summary,
)


def test_bist_equity_fundamental_tools():
    ctx = build_fundamental_context("THYAO", market="bist")
    assert "get_kap_disclosures" in ctx["recommended_mcp_tools"]
    assert ctx["asset_class"] == "bist_equity"
    assert len(ctx["research_checklist_tr"]) >= 2


def test_merge_summary_includes_fundamental():
    fund = build_fundamental_context("ASELS")
    text = merge_ta_fundamental_summary(
        ta_summary_tr="Teknik: long setup A.",
        fundamental=fund,
        elliott_mtf={"notes_tr": "EW uyumlu."},
    )
    assert "Teknik" in text
    assert "Temel" in text
    assert "EW uyumlu" in text

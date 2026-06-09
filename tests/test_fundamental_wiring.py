"""Tests for the upgraded fundamental score + fusion wiring (offline)."""

from bist_trader_mcp.fundamental_score import score_from_enrich
from bist_trader_mcp.fundamental_technical_fusion import (
    fuse_fundamental_technical,
    localize_warnings_tr,
)


def _ratios_enrich(score, grade, bias, factors=None):
    return {
        "fetched": {
            "fundamental_ratios_score": {
                "available": True,
                "score": score,
                "grade": grade,
                "bias": bias,
                "factors": factors or [],
            }
        }
    }


def test_ratio_score_drives_equity_bias():
    pack = score_from_enrich(_ratios_enrich(67, "A", "bullish", ["cheap_pe", "strong_roe"]))
    assert pack["has_ratios"] is True
    assert pack["bias"] == "bullish"
    assert pack["score"] > 15
    assert "cheap_pe" in pack["labels"]


def test_weak_ratios_make_bearish():
    pack = score_from_enrich(_ratios_enrich(-50, "F", "bearish", ["expensive_pe"]))
    assert pack["bias"] == "bearish"
    assert pack["score"] < -15


def test_fear_greed_contrarian_extreme_fear_is_bullish():
    pack = score_from_enrich({"fetched": {"fear_greed": {"value": 12}}})
    assert "extreme_fear_contrarian_long" in pack["labels"]
    assert pack["score"] > 0


def test_fear_greed_extreme_greed_is_bearish():
    pack = score_from_enrich({"fetched": {"fear_greed": {"value": 90}}})
    assert "extreme_greed_contrarian_short" in pack["labels"]
    assert pack["score"] < 0


def test_positive_kap_keyword_adds_score():
    pack = score_from_enrich(
        {"fetched": {"kap_disclosures": [{"title": "Rekor kâr ve temettü dağıtımı"}]}}
    )
    assert pack["kap_tone"] == "positive_headline"
    assert pack["score"] > 0


def test_fusion_warns_on_weak_fundamentals_vs_long():
    technical = {
        "trade_candidate": True,
        "confidence": {"score": 75, "grade": "B"},
        "mtf": {"aligned_direction": "long", "conflict": False},
        "primary_scenario": {"direction": "long"},
        "data_quality": {"flag": "ok"},
        "elliott_mtf": {},
    }
    trade = {"approved": True, "plan": {"direction": "long"}}
    enrich = _ratios_enrich(-50, "F", "bearish", ["expensive_pe"])
    out = fuse_fundamental_technical(
        technical=technical, trade_result=trade,
        fund_enrich=enrich, symbol_check={"ok": True},
    )
    assert "weak_fundamentals_vs_long" in out["warnings"]
    assert out["fundamental_grade"] == "F"
    assert out["has_ratios"] is True


def test_localize_warnings_tr():
    tr = localize_warnings_tr(["mtf_conflict", "weak_fundamentals_vs_long", "unknown_code"])
    assert "çoklu zaman dilimi çelişkisi" in tr
    assert "zayıf temeller (long aleyhine)" in tr
    assert "unknown_code" in tr  # unknown passthrough

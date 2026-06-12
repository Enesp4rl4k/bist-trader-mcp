"""Fundamental–technical fusion unit tests (offline)."""

from bist_trader_mcp.fundamental_score import score_from_enrich
from bist_trader_mcp.fundamental_technical_fusion import fuse_fundamental_technical


def test_fundamental_score_negative_kap():
    pack = score_from_enrich(
        {
            "fetched": {
                "kap_disclosures": [{"title": "zarar açıklaması ve ceza"}],
            }
        }
    )
    assert pack["bias"] == "bearish" or pack["score"] < 0


def test_fusion_blocks_crowded_long_funding():
    technical = {
        "trade_candidate": True,
        "confidence": {"score": 72, "grade": "B"},
        "mtf": {"aligned_direction": "long", "conflict": False},
        "primary_scenario": {"direction": "long"},
        "data_quality": {"flag": "ok"},
        "elliott_mtf": {},
    }
    trade = {"approved": True, "plan": {"direction": "long"}}
    enrich = {
        "fetched": {
            "funding": {"last_rate_pct": 0.05},
        }
    }
    out = fuse_fundamental_technical(
        technical=technical,
        trade_result=trade,
        fund_enrich=enrich,
        symbol_check={"ok": True},
    )
    assert out["trade_allowed"] is False
    assert "crowded_long_funding" in out["warnings"]


def test_fusion_allows_clean_setup():
    technical = {
        "trade_candidate": True,
        "confidence": {"score": 78, "grade": "B+"},
        "mtf": {"aligned_direction": "long", "conflict": False},
        "primary_scenario": {"direction": "long"},
        "data_quality": {"flag": "ok"},
        "elliott_mtf": {},
    }
    trade = {"approved": True, "plan": {"direction": "long"}}
    out = fuse_fundamental_technical(
        technical=technical,
        trade_result=trade,
        fund_enrich={"fetched": {"bist_snapshot": {"change_pct": 1.0}}},
        symbol_check={"ok": True},
    )
    assert out["fusion_score"] >= 52
    assert out["trade_allowed"] is True


def test_fusion_blocks_elliott_htf_ltf_conflict():
    technical = {
        "trade_candidate": True,
        "confidence": {"score": 80, "grade": "A"},
        "mtf": {"aligned_direction": "long", "conflict": False},
        "primary_scenario": {"direction": "long"},
        "data_quality": {"flag": "ok"},
        "elliott_mtf": {"conflict": True},
    }
    trade = {"approved": True, "plan": {"direction": "long"}}
    out = fuse_fundamental_technical(
        technical=technical,
        trade_result=trade,
        fund_enrich={"fetched": {"bist_snapshot": {"change_pct": 1.0}}},
        symbol_check={"ok": True},
    )
    assert out["trade_allowed"] is False
    assert "elliott_htf_ltf_conflict" in out["warnings"]
    assert out["block_reason"] == "fusion_elliott_conflict"


def test_fusion_dynamic_weights_and_scaling():
    technical = {
        "trade_candidate": True,
        "confidence": {"score": 75, "grade": "B"},
        "mtf": {
            "aligned_direction": "long",
            "conflict": False,
            "recommended_setup": {"entry": 100.0, "stop": 95.0}  # 5% stop distance -> high volatility
        },
        "primary_scenario": {"direction": "long"},
        "data_quality": {"flag": "ok"},
        "elliott_mtf": {},
    }
    trade = {"approved": True, "plan": {"direction": "long", "entry": 100.0, "stop": 95.0}}
    
    # 1. High volatility stop distance (5% > 4%) -> Tech weight should be 0.80
    out = fuse_fundamental_technical(
        technical=technical,
        trade_result=trade,
        fund_enrich={"fetched": {"bist_snapshot": {"change_pct": 1.0}}},
        symbol_check={"ok": True},
    )
    assert out["tech_weight"] == 0.80
    assert out["fund_weight"] == 0.20
    
    # 2. Minor warning should scale down position size
    enrich_warning = {
        "fetched": {
            "fundamental_ratios_score": {
                "available": True,
                "score": -40.0,
                "grade": "F",
                "bias": "bearish",
                "factors": ["weak_fundamentals_vs_long"]
            }
        }
    }
    out_scaled = fuse_fundamental_technical(
        technical=technical,
        trade_result=trade,
        fund_enrich=enrich_warning,
        symbol_check={"ok": True},
    )
    assert out_scaled["position_scale_factor"] < 1.0


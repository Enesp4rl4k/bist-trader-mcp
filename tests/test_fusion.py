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

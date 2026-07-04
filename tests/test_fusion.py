"""Fundamental–technical fusion unit tests (offline)."""

from bist_trader_mcp.fundamental_score import score_from_enrich
from bist_trader_mcp.fundamental_statements import analyze_financials, to_fusion_entry
from bist_trader_mcp.fundamental_technical_fusion import fuse_fundamental_technical


def _long_technical():
    return {
        "trade_candidate": True,
        "confidence": {"score": 78, "grade": "B"},
        "mtf": {"aligned_direction": "long", "conflict": False},
        "primary_scenario": {"direction": "long"},
        "data_quality": {"flag": "ok"},
        "elliott_mtf": {},
    }


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


# --- D: statement-based CFO engine wired into fusion ----------------------


def test_statement_score_preferred_over_yahoo_ratios():
    # Yahoo ratio pack says bearish, but the deeper statement analysis says
    # strongly bullish — the statement core must win.
    pack = score_from_enrich({
        "fetched": {
            "fundamental_ratios_score": {"available": True, "score": -40, "grade": "F"},
            "financial_statements_score": {
                "available": True, "score": 60, "grade": "A", "factors": ["strong_roe"],
                "red_flags": [],
            },
        }
    })
    assert pack["core_source"] == "statements"
    assert pack["score"] > 0
    assert pack["ratio_grade"] == "A"


def test_fusion_red_flag_blocks_long():
    enrich = {
        "fetched": {
            "financial_statements_score": {
                "available": True, "score": 40, "grade": "B",
                "red_flags": ["earnings_manipulation"],
            }
        }
    }
    out = fuse_fundamental_technical(
        technical=_long_technical(),
        trade_result={"approved": True, "plan": {"direction": "long"}},
        fund_enrich=enrich,
        symbol_check={"ok": True},
    )
    assert out["trade_allowed"] is False
    assert "fundamental_red_flag" in out["warnings"]
    assert out["block_reason"] == "fusion_fundamental_red_flag"


def test_to_fusion_entry_roundtrips_into_score():
    # End-to-end: real engine output → adapter → fusion fundamental score.
    analysis = analyze_financials(
        {"period_end": "2023-12-31", "is_inflation_adjusted": True,
         "revenue": 1250, "cogs": 720, "operating_income": 340, "net_income": 258,
         "total_assets": 1350, "current_assets": 700, "cash": 300,
         "current_liabilities": 300, "total_equity": 870, "retained_earnings": 600,
         "total_liabilities": 480, "operating_cash_flow": 300, "capex": 70},
        ticker="GOOD",
    )
    entry = to_fusion_entry(analysis)
    assert entry["available"] is True
    pack = score_from_enrich({"fetched": {"financial_statements_score": entry}})
    assert pack["core_source"] == "statements"
    assert pack["has_ratios"] is True


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


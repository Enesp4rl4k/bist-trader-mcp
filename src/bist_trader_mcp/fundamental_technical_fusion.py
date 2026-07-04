"""Merge fundamental + technical gates — single trade_allowed decision."""

from __future__ import annotations

from typing import Any

from .fundamental_score import score_from_enrich

# Rates stored as percent (e.g. 0.03 = 0.03% funding)
FUNDING_CROWDED_LONG_PCT = 0.025
FUNDING_CROWDED_SHORT_PCT = -0.015

# Turkish labels for machine warning codes (so chat_report shows readable text)
WARNINGS_TR: dict[str, str] = {
    "technical_not_trade_candidate": "teknik kurulum onaylanmadı",
    "mtf_conflict": "çoklu zaman dilimi çelişkisi",
    "elliott_htf_ltf_conflict": "Elliott HTF/LTF çelişkisi",
    "crowded_long_funding": "aşırı kalabalık long funding",
    "elevated_positive_funding": "yüksek pozitif funding",
    "crowded_short_funding": "aşırı kalabalık short funding",
    "kap_negative_vs_long": "olumsuz KAP haberi (long aleyhine)",
    "sector_underperform_vs_long": "sektör zayıf (long aleyhine)",
    "sector_outperform_vs_short": "sektör güçlü (short aleyhine)",
    "weak_fundamentals_vs_long": "zayıf temeller (long aleyhine)",
    "strong_fundamentals_vs_short": "güçlü temeller (short aleyhine)",
    "tv_symbol_mismatch": "TradingView sembol uyuşmazlığı",
    "data_quality_thin": "veri kalitesi zayıf",
    "fundamental_red_flag": "temel kırmızı bayrak (manipülasyon/iflas riski)",
}

# Statement-level red flags severe enough to veto a long regardless of score.
HARD_FUNDAMENTAL_RED_FLAGS = {"earnings_manipulation", "bankruptcy_distress"}


def localize_warnings_tr(warnings: list[str]) -> list[str]:
    """Map machine warning codes to Turkish phrases for user-facing output."""
    return [WARNINGS_TR.get(w, w) for w in warnings]


def fuse_fundamental_technical(
    *,
    technical: dict[str, Any],
    trade_result: dict[str, Any],
    fund_enrich: dict[str, Any] | None = None,
    symbol_check: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Produce fusion_score, warnings, trade_allowed, summary_tr."""
    ta = technical or {}
    conf = ta.get("confidence") or {}
    mtf = ta.get("mtf") or {}
    primary = ta.get("primary_scenario") or {}
    tech_candidate = bool(ta.get("trade_candidate"))
    tech_approved = bool(trade_result.get("approved"))
    direction = (
        (trade_result.get("plan") or {}).get("direction")
        or mtf.get("aligned_direction")
        or primary.get("direction")
        or "neutral"
    )

    fund_score_pack = score_from_enrich(fund_enrich)
    fund_score = float(fund_score_pack.get("score") or 0)
    warnings: list[str] = []

    tech_score = float(conf.get("score") or 0)
    
    # Dynamic weighting of technical vs fundamental scores
    tech_weight = 0.72
    fund_weight = 0.28
    
    plan = trade_result.get("plan") or {}
    setup = technical.get("mtf", {}).get("recommended_setup") or {}
    entry = plan.get("entry") or setup.get("entry")
    stop = plan.get("stop") or setup.get("stop")
    if entry and stop and entry > 0:
        stop_dist = abs(entry - stop) / entry
        if stop_dist > 0.04:
            tech_weight = 0.80
            fund_weight = 0.20
        elif stop_dist < 0.015:
            tech_weight = 0.60
            fund_weight = 0.40
            
    fetched = (fund_enrich or {}).get("fetched") or {}
    is_crypto = "funding" in fetched or "fear_greed" in fetched
    if is_crypto:
        tech_weight = 0.65
        fund_weight = 0.35
        
    fusion_raw = tech_score * tech_weight + (fund_score + 50) * fund_weight

    if not tech_candidate:
        warnings.append("technical_not_trade_candidate")
    if mtf.get("conflict"):
        warnings.append("mtf_conflict")
    if (ta.get("elliott_mtf") or {}).get("conflict"):
        warnings.append("elliott_htf_ltf_conflict")

    fetched = (fund_enrich or {}).get("fetched") or {}
    funding = fetched.get("funding") or {}
    last_f = funding.get("last_rate_pct")
    if direction == "long" and last_f is not None:
        if last_f >= FUNDING_CROWDED_LONG_PCT:
            warnings.append("crowded_long_funding")
            fusion_raw -= 22
        elif last_f >= FUNDING_CROWDED_LONG_PCT * 0.6:
            warnings.append("elevated_positive_funding")
            fusion_raw -= 10
    if direction == "short" and last_f is not None:
        if last_f <= FUNDING_CROWDED_SHORT_PCT:
            warnings.append("crowded_short_funding")
            fusion_raw -= 18

    if fund_score_pack.get("kap_tone") == "negative_headline" and direction == "long":
        warnings.append("kap_negative_vs_long")
        fusion_raw -= 15
    if fund_score_pack.get("kap_tone") == "negative_headline" and direction == "short":
        fusion_raw += 5

    rot = fetched.get("sector_rotation") or {}
    rel = rot.get("ticker_relative_strength_pct")
    if direction == "long" and rel is not None and rel < -4:
        warnings.append("sector_underperform_vs_long")
        fusion_raw -= 8
    if direction == "short" and rel is not None and rel > 4:
        warnings.append("sector_outperform_vs_short")
        fusion_raw -= 8

    # Rigorous-ratio conflict: strong/weak equity fundamentals vs trade direction
    if fund_score_pack.get("has_ratios"):
        fb = fund_score_pack.get("bias")
        if direction == "long" and fb == "bearish":
            warnings.append("weak_fundamentals_vs_long")
            fusion_raw -= 12
        elif direction == "short" and fb == "bullish":
            warnings.append("strong_fundamentals_vs_short")
            fusion_raw -= 10

    # Hard statement-level red flags (earnings manipulation / bankruptcy distress)
    # veto a long outright — a CFO-grade screen must never buy a flagged name.
    hard_flags = [
        r for r in (fund_score_pack.get("red_flags") or [])
        if r in HARD_FUNDAMENTAL_RED_FLAGS
    ]
    if hard_flags and direction == "long":
        warnings.append("fundamental_red_flag")
        fusion_raw -= 45

    if symbol_check and not symbol_check.get("ok"):
        warnings.append("tv_symbol_mismatch")
        fusion_raw -= 12

    dq = ta.get("data_quality") or {}
    if dq.get("flag") == "thin":
        warnings.append("data_quality_thin")
        fusion_raw -= 5

    # Minor warnings position size scaling
    position_scale_factor = 1.0
    minor_warnings_penalties = {
        "elevated_positive_funding": 0.15,
        "kap_negative_vs_long": 0.25,
        "sector_underperform_vs_long": 0.20,
        "sector_outperform_vs_short": 0.20,
        "weak_fundamentals_vs_long": 0.25,
        "strong_fundamentals_vs_short": 0.20,
        "data_quality_thin": 0.10,
    }
    for w in warnings:
        if w in minor_warnings_penalties:
            position_scale_factor -= minor_warnings_penalties[w]
    position_scale_factor = round(max(0.40, position_scale_factor), 2)
    
    min_fusion_score = 52.0
    if position_scale_factor < 1.0:
        min_fusion_score = 48.0  # allow trade with reduced size/risk
        
    fusion_score = round(max(0.0, min(100.0, fusion_raw)), 1)
    trade_allowed = (
        tech_approved
        and tech_candidate
        and fusion_score >= min_fusion_score
        and "crowded_long_funding" not in warnings
        and "mtf_conflict" not in warnings
        and "elliott_htf_ltf_conflict" not in warnings
        and "tv_symbol_mismatch" not in warnings
        and "fundamental_red_flag" not in warnings
    )

    if tech_approved and not trade_allowed and "fundamental_red_flag" in warnings:
        block_reason = "fusion_fundamental_red_flag"
    elif tech_approved and not trade_allowed and "mtf_conflict" in warnings:
        block_reason = "fusion_mtf_conflict"
    elif tech_approved and not trade_allowed and "elliott_htf_ltf_conflict" in warnings:
        block_reason = "fusion_elliott_conflict"
    elif tech_approved and not trade_allowed and "crowded_long_funding" in warnings:
        block_reason = "fusion_crowded_funding"
    elif tech_approved and not trade_allowed:
        block_reason = "fusion_score_low"
    else:
        block_reason = trade_result.get("reason")

    aligned = (
        (fund_score_pack.get("bias") in ("bullish", "bearish") and direction in ("long", "short"))
        and (
            (fund_score_pack.get("bias") == "bullish" and direction == "long")
            or (fund_score_pack.get("bias") == "bearish" and direction == "short")
            or fund_score_pack.get("bias") == "neutral"
        )
    )

    warnings_tr = localize_warnings_tr(warnings)
    ratio_note = ""
    if fund_score_pack.get("has_ratios"):
        ratio_note = f" | temel not {fund_score_pack.get('ratio_grade')}"

    summary_tr = (
        f"Fusion {fusion_score}/100 | teknik {conf.get('grade')} ({tech_score}) | "
        f"temel {fund_score:+.0f}{ratio_note} | yön {direction} | "
        f"{'uyumlu' if aligned else 'kısmi'} | işlem={'evet' if trade_allowed else 'hayır'}"
    )
    if position_scale_factor < 1.0:
        summary_tr += f" (risk ölçeği {position_scale_factor}x)"
        
    if warnings_tr:
        summary_tr += " | uyarı: " + ", ".join(warnings_tr[:4])

    return {
        "source": "bist-trader-mcp — fundamental_technical_fusion",
        "fusion_score": fusion_score,
        "fundamental_score": fund_score,
        "fundamental_bias": fund_score_pack.get("bias"),
        "fundamental_grade": fund_score_pack.get("ratio_grade", "NA"),
        "has_ratios": bool(fund_score_pack.get("has_ratios")),
        "technical_score": tech_score,
        "aligned": aligned,
        "warnings": warnings,
        "warnings_tr": warnings_tr,
        "trade_allowed": trade_allowed,
        "block_reason": block_reason,
        "summary_tr": summary_tr,
        "position_scale_factor": position_scale_factor,
        "tech_weight": tech_weight,
        "fund_weight": fund_weight,
    }


__all__ = ["fuse_fundamental_technical", "localize_warnings_tr", "WARNINGS_TR"]

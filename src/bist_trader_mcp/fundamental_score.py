"""Composite fundamental bias score for the fusion layer.

Blends rigorous equity ratios (P/E, P/B, ROE, margins, leverage, growth — from
`fundamental_ratios`) with sentiment / positioning signals (KAP headline tone,
crowding via funding, crypto Fear & Greed, sector relative strength, macro
funding spread). Ratios dominate for equities; sentiment dominates for crypto.
"""

from __future__ import annotations

from typing import Any

NEGATIVE_KAP_KEYWORDS = (
    "zarar",
    "ceza",
    "iptal",
    "ertele",
    "temettü iptal",
    "iflas",
    "dava",
    "soruşturma",
    "haciz",
    "konkordato",
)

POSITIVE_KAP_KEYWORDS = (
    "kâr",
    "kar payı",
    "temettü",
    "rekor",
    "sözleşme",
    "ihale kazan",
    "yatırım",
    "geri alım",
    "bedelsiz",
)


def score_from_enrich(fund_enrich: dict[str, Any] | None) -> dict[str, Any]:
    """-100..+100 bias from live fundamental snapshot."""
    if not fund_enrich:
        return {"score": 0.0, "bias": "neutral", "labels": [], "kap_tone": "unknown"}

    fetched = fund_enrich.get("fetched") or {}
    score = 0.0
    labels: list[str] = []

    # --- Rigorous equity ratios (dominant for BIST equities) ---
    ratio_pack = fetched.get("fundamental_ratios_score") or {}
    ratio_score = 0.0
    if ratio_pack.get("available"):
        # Ratio composite is -100..100; weight it as the core of the score.
        ratio_score = float(ratio_pack.get("score") or 0) * 0.6
        score += ratio_score
        labels.extend(ratio_pack.get("factors") or [])

    snap = fetched.get("bist_snapshot") or {}
    ch = snap.get("change_pct")
    if ch is not None:
        if ch > 1.5:
            score += 5
            labels.append("spot_strong_day")
        elif ch < -1.5:
            score -= 5
            labels.append("spot_weak_day")

    kap_list = fetched.get("kap_disclosures") or []
    kap_tone = "neutral"
    if kap_list:
        subj = (kap_list[0].get("title") or "").lower()
        if any(k in subj for k in NEGATIVE_KAP_KEYWORDS):
            score -= 18
            kap_tone = "negative_headline"
            labels.append("kap_negative_recent")
        elif any(k in subj for k in POSITIVE_KAP_KEYWORDS):
            score += 8
            kap_tone = "positive_headline"
            labels.append("kap_positive_recent")
        else:
            score += 3
            kap_tone = "neutral_headline"

    fund = fetched.get("funding") or {}
    last_f = fund.get("last_rate_pct")
    if last_f is not None:
        if last_f > 0.03:
            score -= 12
            labels.append("funding_very_positive")
        elif last_f > 0.01:
            score -= 6
            labels.append("funding_positive")
        elif last_f < -0.01:
            score += 6
            labels.append("funding_negative")

    # Crypto Fear & Greed — contrarian (extreme fear = bullish, extreme greed = bearish)
    fng = fetched.get("fear_greed") or {}
    fng_val = fng.get("value")
    if fng_val is not None:
        v = float(fng_val)
        if v <= 20:
            score += 10
            labels.append("extreme_fear_contrarian_long")
        elif v <= 35:
            score += 5
            labels.append("fear")
        elif v >= 80:
            score -= 10
            labels.append("extreme_greed_contrarian_short")
        elif v >= 65:
            score -= 5
            labels.append("greed")

    rot = fetched.get("sector_rotation") or {}
    rel = rot.get("ticker_relative_strength_pct")
    if rel is not None:
        if rel > 3:
            score += 10
            labels.append("sector_outperform")
        elif rel < -3:
            score -= 10
            labels.append("sector_underperform")

    macro = fetched.get("macro_overlay") or {}
    if macro.get("tlref_bps_vs_policy") is not None:
        spread = float(macro["tlref_bps_vs_policy"])
        if spread > 150:
            score -= 5
            labels.append("funding_stress_wide")
        elif spread < 50:
            score += 3

    score = max(-100.0, min(100.0, score))
    bias = "neutral"
    if score >= 15:
        bias = "bullish"
    elif score <= -15:
        bias = "bearish"

    return {
        "score": round(score, 1),
        "bias": bias,
        "labels": labels,
        "kap_tone": kap_tone,
        "ratio_score": round(ratio_score, 1),
        "ratio_grade": ratio_pack.get("grade", "NA"),
        "has_ratios": bool(ratio_pack.get("available")),
    }


__all__ = ["score_from_enrich"]

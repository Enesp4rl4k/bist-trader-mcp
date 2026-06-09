"""Composite analysis confidence — PA + MTF + EW + data quality."""

from __future__ import annotations

from typing import Any


def _quality_points(mtf_quality: str) -> float:
    return {
        "a_plus": 95,
        "a": 82,
        "b": 62,
        "c": 42,
        "conflict": 10,
        "no_trade": 5,
    }.get(mtf_quality, 30)


def compute_analysis_confidence(
    *,
    mtf: dict[str, Any],
    ew_primary: dict[str, Any] | None,
    data_quality: dict[str, Any] | None,
    diagnostics: dict[str, Any] | None,
    trade_candidate: bool,
    pa_primary: bool = False,
) -> dict[str, Any]:
    """0–100 confidence with breakdown (not a guarantee of profit).

    When ``pa_primary`` is set (PA-driven trade with weak/absent Elliott), the
    Elliott weight is reduced and redistributed to price action + MTF so a clean
    structural trend is not dragged down by a noisy automatic wave count.
    """
    pa_ltf = mtf.get("ltf_analysis") or {}
    conf_long = (pa_ltf.get("confluence_long") or {}).get("score", 0)
    conf_short = (pa_ltf.get("confluence_short") or {}).get("score", 0)
    pa_conf = max(float(conf_long), float(conf_short))

    mtf_pts = _quality_points(str(mtf.get("trade_quality") or "no_trade"))
    ew_pts = float((ew_primary or {}).get("score") or 0)
    dq_pts = 90.0 if (data_quality or {}).get("ok") else 35.0

    aligned = mtf.get("aligned_direction")
    ew_dir = (ew_primary or {}).get("direction")
    align_bonus = 12.0 if aligned in ("long", "short") and aligned == ew_dir else 0.0
    if ew_dir and aligned not in ("neutral", ew_dir):
        align_bonus = -20.0

    warnings = list((diagnostics or {}).get("warnings") or [])
    warn_penalty = min(25.0, len(warnings) * 8.0)

    range_bonus = 0.0
    ltf = mtf.get("ltf_analysis") or {}
    rng = ltf.get("range") or {}
    box = rng.get("box") or {}
    if box.get("active"):
        rp = ltf.get("range_trade") or rng.get("recommended_play") or {}
        ad = mtf.get("aligned_direction")
        if rp.get("direction") == ad and ad in ("long", "short"):
            range_bonus = min(18.0, float(box.get("quality_score") or 0) * 0.15)

    # Momentum / divergence alignment from indicator signals (technical_signals)
    momentum_bonus = 0.0
    signals = ltf.get("indicator_signals") or {}
    ad = mtf.get("aligned_direction")
    if signals.get("available") and ad in ("long", "short"):
        mb = signals.get("momentum_bias")
        if mb == ad:
            momentum_bonus = 6.0
        elif mb not in ("neutral", ad):
            momentum_bonus = -10.0
        div = signals.get("divergence") or {}
        if div.get("type") not in (None, "none"):
            if div.get("bias") == ad:
                momentum_bonus += 6.0
            else:
                momentum_bonus -= 8.0
    momentum_bonus = max(-15.0, min(12.0, momentum_bonus))

    # PA-first with a weak EW count: de-emphasise Elliott, lift PA + MTF.
    reweighted = pa_primary and ew_pts < 30
    if reweighted:
        w_pa, w_mtf, w_ew, w_dq = 0.42, 0.38, 0.05, 0.10
        # EW direction disagreement penalty is irrelevant when EW isn't the basis
        align_bonus = max(0.0, align_bonus)
    else:
        w_pa, w_mtf, w_ew, w_dq = 0.35, 0.30, 0.20, 0.10

    raw = (
        pa_conf * w_pa
        + mtf_pts * w_mtf
        + ew_pts * w_ew
        + dq_pts * w_dq
        + align_bonus
        + range_bonus
        + momentum_bonus
        - warn_penalty
    )
    score = round(min(100.0, max(0.0, raw)), 1)

    grade = "F"
    if score >= 80:
        grade = "A"
    elif score >= 65:
        grade = "B"
    elif score >= 50:
        grade = "C"
    elif score >= 35:
        grade = "D"

    trade_ok = trade_candidate and score >= 58 and (data_quality or {}).get("ok", True)

    return {
        "score": score,
        "grade": grade,
        "trade_recommended": trade_ok,
        "breakdown": {
            "pa_confluence": pa_conf,
            "mtf_quality_pts": mtf_pts,
            "ew_score": ew_pts,
            "data_quality_pts": dq_pts,
            "alignment_bonus": align_bonus,
            "warning_penalty": warn_penalty,
            "range_bonus": range_bonus,
            "momentum_bonus": momentum_bonus,
            "pa_primary_reweighted": reweighted,
        },
        "warning_count": len(warnings),
    }


def build_executive_summary_tr(
    *,
    symbol: str,
    mtf: dict[str, Any],
    ew_primary: dict[str, Any] | None,
    confidence: dict[str, Any],
    trade_candidate: bool,
    scenario_id: str | None,
) -> str:
    """3-line Turkish summary for MCP / LinkedIn context."""
    pe = ew_primary or {}
    lines = [
        f"{symbol}: MTF {mtf.get('htf_structure')}/{mtf.get('ltf_structure')} "
        f"→ yön {mtf.get('aligned_direction')} (kalite {mtf.get('trade_quality')}).",
        f"Elliott: {pe.get('kind', 'yok')} skor {pe.get('score', '—')} | "
        f"{pe.get('forecast_summary', pe.get('current_wave', ''))[:120]}",
        f"Güven: {confidence.get('grade')} ({confidence.get('score')}/100) — "
        f"{'işlem adayı' if trade_candidate and confidence.get('trade_recommended') else 'bekle'} "
        f"[{scenario_id or 'n/a'}]",
    ]
    return "\n".join(lines)


__all__ = ["compute_analysis_confidence", "build_executive_summary_tr"]

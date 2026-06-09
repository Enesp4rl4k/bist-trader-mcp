"""Chart scenarios — merge PA + MTF + Elliott Wave into ranked trade scenarios."""

from __future__ import annotations

from typing import Any, Literal

from .analysis_confidence import build_executive_summary_tr, compute_analysis_confidence
from .data_quality import assess_ohlcv_quality, merge_mtf_data_quality
from .elliott_mtf import analyze_mtf_elliott
from .elliott_wave import analyze_elliott_wave
from .market_profiles import resolve_assistant_config
from .mtf_analysis import analyze_mtf_price_action
from .trade_playbook import design_mtf_trade_plan

Direction = Literal["long", "short", "neutral"]
ScenarioId = Literal[
    "continuation_aligned",
    "correction_complete",
    "alternate_ew",
    "pa_ew_conflict",
    "no_setup",
]


def _pa_scenario_score(mtf_q: str, confluence: float, ew_bonus: float = 0.0) -> float:
    """PA-driven scenario score — independent of Elliott (EW is a bonus only)."""
    base = {"a_plus": 72.0, "a": 64.0, "b": 56.0}.get(mtf_q, 40.0)
    conf_pts = (float(confluence) - 50.0) * 0.4
    return max(0.0, min(100.0, base + conf_pts + ew_bonus))


def _pick_primary_scenario(
    scenarios: list[dict[str, Any]],
    mtf: dict[str, Any],
) -> dict[str, Any]:
    """Never let alternate_ew beat PA-aligned continuation on score alone."""
    aligned = mtf.get("aligned_direction")
    preferred_ids = ("continuation_aligned", "correction_complete", "pa_aligned")
    aligned_ok = [
        s
        for s in scenarios
        if s.get("id") in preferred_ids
        and s.get("direction") == aligned
        and aligned in ("long", "short")
    ]
    if aligned_ok:
        return max(aligned_ok, key=lambda x: float(x.get("score") or 0))
    for sid in preferred_ids:
        for s in scenarios:
            if s.get("id") == sid:
                return s
    for s in scenarios:
        if s.get("id") != "alternate_ew":
            return s
    return scenarios[0]


def _alignment_score(
    mtf_direction: str,
    ew_direction: str,
    mtf_quality: str,
    ew_score: float,
) -> float:
    base = ew_score * 0.45
    q_bonus = {"a_plus": 35, "a": 28, "b": 12, "c": 5}.get(mtf_quality, 0)
    base += q_bonus
    if mtf_direction == ew_direction and mtf_direction in ("long", "short"):
        base += 20
    elif mtf_direction != ew_direction and mtf_direction != "neutral" and ew_direction != "neutral":
        base -= 40
    return base


def _align_forecast_with_setup(
    mtf: dict[str, Any],
    ew_primary: dict[str, Any] | None,
    *,
    max_divergence_pct: float = 0.12,
) -> dict[str, Any]:
    """Blend EW primary forecast into PA targets when direction matches."""
    if not ew_primary:
        return mtf
    setup = mtf.get("recommended_setup")
    if not setup:
        return mtf
    fc = float(ew_primary.get("primary_forecast_target") or 0)
    if fc <= 0:
        return mtf
    if ew_primary.get("direction") != setup.get("direction"):
        return mtf
    entry = float(setup.get("entry") or 0)
    if entry <= 0:
        return mtf
    div = abs(fc - entry) / entry
    targets = list(setup.get("targets") or [])
    if div <= max_divergence_pct:
        if targets:
            targets[0] = round(fc, 8)
        else:
            targets = [round(fc, 8)]
    else:
        targets.append(round(fc, 8))
    setup = {**setup, "targets": targets, "ew_forecast_tp": round(fc, 8)}
    return {**mtf, "recommended_setup": setup}


def analyze_chart_scenarios(
    *,
    symbol: str,
    htf_closes: list[float],
    htf_highs: list[float],
    htf_lows: list[float],
    ltf_closes: list[float],
    ltf_highs: list[float],
    ltf_lows: list[float],
    htf_times: list[int] | None = None,
    ltf_times: list[int] | None = None,
    htf_volumes: list[float] | None = None,
    ltf_volumes: list[float] | None = None,
    htf_label: str = "240",
    ltf_label: str = "60",
    min_ew_score: float | None = None,
    market: str | None = None,
    pa_kwargs: dict[str, Any] | None = None,
    data_quality: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build PA + MTF + EW scenario pack (no trade execution)."""
    cfg = resolve_assistant_config(
        symbol,
        market=market,
        ltf_timeframe=ltf_label,
        htf_timeframe=htf_label,
    )
    pa_kw = {**(cfg["pa_kwargs"]), **(pa_kwargs or {})}
    pa_kw.setdefault("max_entry_chase_atr", cfg.get("max_entry_chase_atr", 1.5))
    ew_min = float(min_ew_score if min_ew_score is not None else cfg["min_ew_score"])
    ac = cfg["asset_class"]

    if data_quality is None:
        htf_q = assess_ohlcv_quality(
            htf_closes, htf_highs, htf_lows,
            times=htf_times, volumes=htf_volumes, asset_class=ac,
        )
        ltf_q = assess_ohlcv_quality(
            ltf_closes, ltf_highs, ltf_lows,
            times=ltf_times, volumes=ltf_volumes, asset_class=ac,
        )
        data_quality = merge_mtf_data_quality(htf_q, ltf_q)

    if data_quality.get("flag") == "insufficient":
        flag = data_quality.get("flag")
        return {
            "source": "bist-trader-mcp — chart_scenarios.analyze_chart_scenarios",
            "symbol": symbol,
            "market_profile": cfg["profile"],
            "data_quality": data_quality,
            "approved": False,
            "action": "no_trade",
            "reason": f"data_quality_{flag}",
            "trade_candidate": False,
            "scenarios": [],
            "primary_scenario": {
                "id": "no_setup",
                "action": "no_trade",
                "reason": f"data_quality_{flag}",
            },
            "primary_scenario_id": "no_setup",
            "confidence": {"score": 0, "grade": "F", "trade_recommended": False},
            "executive_summary_tr": f"{symbol}: veri kalitesi yetersiz ({flag}) — analiz durduruldu.",
            "report": f"NO TRADE — {symbol}: veri kalitesi {flag}",
            "diagnostics": {"warnings": list(data_quality.get("issues") or [])},
        }

    dq_warnings: list[str] = []
    if not data_quality.get("ok"):
        dq_warnings.append(f"data_quality_{data_quality.get('flag')}")

    mtf = analyze_mtf_price_action(
        htf_closes, htf_highs, htf_lows,
        ltf_closes, ltf_highs, ltf_lows,
        htf_volumes=htf_volumes,
        ltf_volumes=ltf_volumes,
        htf_label=htf_label,
        ltf_label=ltf_label,
        pa_kwargs=pa_kw,
        min_ltf_confluence=float(cfg.get("min_pa_confluence", 52)),
    )
    ew = analyze_elliott_wave(
        htf_closes, htf_highs, htf_lows,
        times=htf_times,
        swing_lookback=int(pa_kw.get("swing_lookback", 5)),
    )
    ew_ltf: dict[str, Any] | None = None
    if len(ltf_closes) >= pa_kw.get("swing_lookback", 5) * 2 + 1:
        ew_ltf = analyze_elliott_wave(
            ltf_closes, ltf_highs, ltf_lows,
            times=ltf_times,
            swing_lookback=max(2, int(pa_kw.get("swing_lookback", 5)) - 1),
        )
    ew_mtf = analyze_mtf_elliott(ew, ew_ltf)

    scenarios: list[dict[str, Any]] = []
    primary_ew = ew.get("primary")
    alternate_ew = ew.get("alternate")
    aligned = mtf.get("aligned_direction") or "neutral"
    mtf_q = str(mtf.get("trade_quality") or "no_trade")
    ew_dir = (primary_ew or {}).get("direction") or "neutral"
    ew_score = float((primary_ew or {}).get("score") or 0)

    ltf_an = mtf.get("ltf_analysis") or {}
    if aligned == "long":
        aligned_conf = float((ltf_an.get("confluence_long") or {}).get("score") or 0)
    elif aligned == "short":
        aligned_conf = float((ltf_an.get("confluence_short") or {}).get("score") or 0)
    else:
        aligned_conf = 0.0

    has_setup = mtf.get("recommended_setup") is not None
    has_pa = aligned in ("long", "short") and has_setup and mtf_q in ("a_plus", "a", "b")
    ew_ok = bool(primary_ew) and ew_score >= ew_min
    ew_aligned = ew_ok and ew_dir == aligned and aligned in ("long", "short")
    ew_conflict = (
        bool(primary_ew)
        and ew_dir in ("long", "short")
        and aligned in ("long", "short")
        and ew_dir != aligned
    )

    def _attach_ew(scen: dict[str, Any]) -> dict[str, Any]:
        if primary_ew and not ew_conflict:
            scen.update({
                "elliott_primary": primary_ew,
                "invalidation": primary_ew.get("invalidation_price"),
                "draw_points": primary_ew.get("points"),
                "projected_points": primary_ew.get("projected_points"),
                "forecast": primary_ew.get("forecast"),
                "forecast_summary": primary_ew.get("forecast_summary"),
                "target_scenarios": primary_ew.get("target_scenarios"),
            })
        return scen

    if mtf.get("conflict"):
        scenarios.append({
            "id": "pa_ew_conflict",
            "title": "MTF PA conflict",
            "direction": "neutral",
            "action": "no_trade",
            "score": 0,
            "reason": "HTF/LTF PA bias conflict — wait",
            "mtf_quality": mtf_q,
            "elliott": primary_ew,
        })
    elif ew_aligned:
        # Strongest path: PA bias + a confirmed Elliott count point the same way.
        cont_score = _alignment_score(aligned, ew_dir, mtf_q, ew_score)
        scenarios.append(_attach_ew({
            "id": "continuation_aligned",
            "title": f"PA+EW aligned {ew_dir}",
            "direction": ew_dir,
            "action": "consider_trade" if cont_score >= 55 else "watch",
            "score": round(cont_score, 2),
            "reason": (
                f"HTF EW {primary_ew.get('kind')} (score {ew_score}) aligns with "
                f"MTF quality {mtf_q}, bias {aligned}"
            ),
            "mtf": mtf,
        }))
        if (primary_ew.get("degree") == "correction" or "abc" in str(primary_ew.get("kind", ""))):
            scenarios[-1]["id"] = "correction_complete"
            scenarios[-1]["title"] = f"ABC complete → {ew_dir}"
    elif has_pa:
        # PA-first path: tradeable on price-action quality even when the
        # automatic Elliott count is weak/absent. EW is overlay only.
        ew_bonus = 4.0 if ew_ok and not ew_conflict else 0.0
        pa_score = _pa_scenario_score(mtf_q, aligned_conf, ew_bonus)
        action = "watch" if ew_conflict or pa_score < 55 else "consider_trade"
        ew_note = (
            f"; EW {primary_ew.get('kind')} overlay (score {ew_score})"
            if primary_ew and not ew_conflict
            else ("; EW yön çelişkisi" if ew_conflict else "; EW zayıf/yok")
        )
        scenarios.append(_attach_ew({
            "id": "pa_aligned",
            "title": f"PA aligned {aligned}",
            "direction": aligned,
            "action": action,
            "score": round(pa_score, 2),
            "reason": (
                f"MTF {mtf_q} PA kurulumu, yön {aligned}, confluence {aligned_conf:.0f}"
                + ew_note
            ),
            "mtf": mtf,
            "pa_primary": True,
        }))

    add_alternate = (
        alternate_ew
        and float(alternate_ew.get("score") or 0) >= ew_min - 10
        and primary_ew
        and alternate_ew.get("name") != primary_ew.get("name")
    )
    if add_alternate:
        alt_dir = alternate_ew.get("direction") or "neutral"
        alt_score = _alignment_score(aligned, alt_dir, mtf_q, float(alternate_ew["score"]))
        scenarios.append({
            "id": "alternate_ew",
            "title": f"Alternate count ({alternate_ew.get('kind')})",
            "direction": alt_dir,
            "action": "watch",
            "score": round(alt_score * 0.75, 2),
            "reason": "Secondary Elliott hypothesis — use if primary invalidates",
            "elliott_alternate": alternate_ew,
            "invalidation": alternate_ew.get("invalidation_price"),
            "draw_points": None,
        })

    if primary_ew and ew_dir != "neutral" and aligned not in ("neutral", ew_dir):
        scenarios.append({
            "id": "pa_ew_conflict",
            "title": "PA vs Elliott conflict",
            "direction": "neutral",
            "action": "no_trade",
            "score": 0,
            "reason": f"MTF aligned={aligned} but EW primary={ew_dir}",
            "mtf_quality": mtf_q,
            "elliott_primary": primary_ew,
        })

    if not scenarios:
        scenarios.append({
            "id": "no_setup",
            "title": "No scored EW scenario",
            "direction": "neutral",
            "action": "no_trade",
            "score": 0,
            "reason": "Elliott score below threshold or insufficient pivots",
            "elliott": ew,
        })

    scenarios.sort(key=lambda s: -float(s.get("score") or 0))
    primary_scenario = _pick_primary_scenario(scenarios, mtf)
    primary_ew = (ew.get("primary") or {}) if ew else {}
    mtf = _align_forecast_with_setup(mtf, primary_ew)
    diagnostics = _analysis_diagnostics(mtf, ew, primary_ew, primary_scenario)
    if dq_warnings:
        diagnostics.setdefault("warnings", []).extend(dq_warnings)
    pa_primary = primary_scenario.get("id") == "pa_aligned"
    trade_ok_base = (
        primary_scenario.get("action") == "consider_trade"
        and primary_scenario.get("direction") in ("long", "short")
        and not mtf.get("conflict")
        and mtf_q in ("a_plus", "a", "b")
        and mtf.get("recommended_setup") is not None
    )
    # Elliott gates HARD-block only EW-driven primaries; for PA-first they are
    # advisory warnings (EW is overlay, not the trade basis).
    rules_total = int((primary_ew or {}).get("rules_total") or 0)
    rules_passed = int((primary_ew or {}).get("rules_passed") or 0)
    if rules_total >= 3 and rules_passed < 2:
        diagnostics.setdefault("warnings", []).append(
            "Elliott impulse rules failed — primary count weak"
        )
        if not pa_primary:
            trade_ok_base = False
    if ew_mtf.get("conflict") or ew_mtf.get("alignment_quality") == "conflict":
        diagnostics.setdefault("warnings", []).append("HTF/LTF Elliott direction conflict")
        if not pa_primary:
            trade_ok_base = False
    confidence = compute_analysis_confidence(
        mtf=mtf,
        ew_primary=primary_ew,
        data_quality=data_quality,
        diagnostics=diagnostics,
        trade_candidate=trade_ok_base,
        pa_primary=pa_primary,
    )
    trade_ok = trade_ok_base and confidence.get("trade_recommended", False)

    summary_tr = build_executive_summary_tr(
        symbol=symbol,
        mtf=mtf,
        ew_primary=primary_ew,
        confidence=confidence,
        trade_candidate=trade_ok,
        scenario_id=primary_scenario.get("id"),
    )

    return {
        "source": "bist-trader-mcp — chart_scenarios.analyze_chart_scenarios",
        "symbol": symbol,
        "market_profile": cfg["profile"],
        "data_quality": data_quality,
        "mtf": mtf,
        "elliott_htf": ew,
        "elliott_ltf": ew_ltf,
        "elliott_mtf": ew_mtf,
        "scenarios": scenarios,
        "primary_scenario_id": primary_scenario.get("id"),
        "primary_scenario": primary_scenario,
        "trade_candidate": trade_ok,
        "recommended_action": "consider_trade" if trade_ok else primary_scenario.get("action"),
        "confidence": confidence,
        "executive_summary_tr": summary_tr,
        "report": _build_report(symbol, mtf, ew, primary_scenario, scenarios, confidence),
        "diagnostics": diagnostics,
    }


def _analysis_diagnostics(
    mtf: dict[str, Any],
    ew: dict[str, Any],
    ew_primary: dict[str, Any] | None,
    scenario: dict[str, Any],
) -> dict[str, Any]:
    """Explain PA/EW quality — why chart labels may disagree with price."""
    aligned = mtf.get("aligned_direction")
    ew_dir = (ew_primary or {}).get("direction")
    pa_primary = scenario.get("id") == "pa_aligned"
    warnings: list[str] = []
    if mtf.get("conflict"):
        warnings.append("MTF bias or structure conflict — PA setup unreliable")
    if ew_dir and aligned not in ("neutral", ew_dir):
        warnings.append(f"EW direction ({ew_dir}) disagrees with MTF aligned ({aligned})")
    if scenario.get("id") == "alternate_ew":
        warnings.append("Alternate EW count selected — prefer continuation_aligned for trading")
    # A weak EW score is expected (and harmless) on a PA-first trade — don't
    # penalise confidence for it; EW is overlay only in that path.
    if not pa_primary and float((ew_primary or {}).get("score") or 0) < 45:
        warnings.append("Low EW hypothesis score — wave count is weak")
    setup = mtf.get("recommended_setup") or {}
    if setup and not setup.get("setup_type"):
        warnings.append("PA setup missing typed pattern")
    ltf = mtf.get("ltf_analysis") or {}
    if not ltf.get("suggested_long_setup") and not ltf.get("suggested_short_setup"):
        warnings.append("No LTF PA setup — entry/stop are model placeholders only")
    return {
        "mtf_quality": mtf.get("trade_quality"),
        "htf_structure": mtf.get("htf_structure"),
        "ltf_structure": mtf.get("ltf_structure"),
        "ew_kind": (ew_primary or {}).get("kind"),
        "ew_score": (ew_primary or {}).get("score"),
        "scenario_id": scenario.get("id"),
        "warnings": warnings,
    }


def _build_report(
    symbol: str,
    mtf: dict[str, Any],
    ew: dict[str, Any],
    primary: dict[str, Any],
    all_scenarios: list[dict[str, Any]],
    confidence: dict[str, Any] | None = None,
) -> str:
    pe = ew.get("primary") or {}
    lines = [
        f"=== {symbol} Chart Scenarios ===",
        f"MTF: HTF={mtf.get('htf_bias')} LTF={mtf.get('ltf_bias')} "
        f"quality={mtf.get('trade_quality')} aligned={mtf.get('aligned_direction')}",
        f"EW (HTF): {pe.get('kind', 'n/a')} score={pe.get('score', 'n/a')} "
        f"wave={pe.get('current_wave', 'n/a')} inv={pe.get('invalidation_price')}",
        f"Forecast: {pe.get('forecast_summary', 'n/a')}",
        f"EW TR: {(pe.get('report_tr') or 'n/a').split(chr(10))[0][:100]}",
        f"Primary scenario: {primary.get('id')} — {primary.get('title')} → {primary.get('action')}",
    ]
    for s in all_scenarios[:3]:
        lines.append(f"  - [{s.get('score')}] {s.get('id')}: {s.get('reason', '')[:80]}")
    setup = (mtf.get("recommended_setup") or {})
    if setup:
        lines.append(
            f"PA setup: {setup.get('setup_type', 'n/a')} {setup.get('direction')} "
            f"entry={setup.get('entry')} stop={setup.get('stop')} "
            f"conf={((setup.get('confluence') or {}).get('score'))}"
        )
    if confidence:
        lines.append(
            f"Confidence: {confidence.get('grade')} ({confidence.get('score')}/100) "
            f"trade={confidence.get('trade_recommended')}"
        )
    return "\n".join(lines)


def design_scenario_trade_plan(
    *,
    symbol: str,
    htf_closes: list[float],
    htf_highs: list[float],
    htf_lows: list[float],
    ltf_closes: list[float],
    ltf_highs: list[float],
    ltf_lows: list[float],
    htf_times: list[int] | None = None,
    ltf_times: list[int] | None = None,
    htf_volumes: list[float] | None = None,
    ltf_volumes: list[float] | None = None,
    data_quality: dict[str, Any] | None = None,
    htf_label: str = "240",
    ltf_label: str = "60",
    equity: float = 100_000.0,
    risk_per_trade_pct: float | None = None,
    min_risk_reward: float | None = None,
    min_ew_score: float | None = None,
    market: str | None = None,
    open_positions: list[dict[str, Any]] | None = None,
    rules: dict[str, Any] | None = None,
    journal_path: str | None = None,
    max_notional_pct: float | None = None,
    scenario_pack: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """MTF trade plan gated by EW+PA scenario alignment."""
    cfg = resolve_assistant_config(
        symbol,
        market=market,
        ltf_timeframe=ltf_label,
        htf_timeframe=htf_label,
        rules=rules,
    )
    if scenario_pack is not None:
        pack = scenario_pack
    else:
        pack = analyze_chart_scenarios(
            symbol=symbol,
            htf_closes=htf_closes,
            htf_highs=htf_highs,
            htf_lows=htf_lows,
            ltf_closes=ltf_closes,
            ltf_highs=ltf_highs,
            ltf_lows=ltf_lows,
            htf_times=htf_times,
            ltf_times=ltf_times,
            htf_volumes=htf_volumes,
            ltf_volumes=ltf_volumes,
            data_quality=data_quality,
            htf_label=htf_label,
            ltf_label=ltf_label,
            min_ew_score=min_ew_score,
            market=market,
        )

    if not pack.get("trade_candidate"):
        reason = pack.get("reason")
        if not reason:
            conf = pack.get("confidence") or {}
            if conf and not conf.get("trade_recommended"):
                reason = f"confidence_{conf.get('grade', 'low')}"
            else:
                reason = (
                    pack.get("primary_scenario", {}).get("reason")
                    or "scenario_not_tradeable"
                )
        return {
            "source": "bist-trader-mcp — chart_scenarios.design_scenario_trade_plan",
            "approved": False,
            "action": "no_trade",
            "reason": reason,
            "scenarios": pack,
            "trade_report": pack.get("report"),
            "executive_summary_tr": pack.get("executive_summary_tr"),
        }

    plan_result = design_mtf_trade_plan(
        symbol=symbol,
        htf_closes=htf_closes,
        htf_highs=htf_highs,
        htf_lows=htf_lows,
        ltf_closes=ltf_closes,
        ltf_highs=ltf_highs,
        ltf_lows=ltf_lows,
        htf_label=htf_label,
        ltf_label=ltf_label,
        equity=equity,
        risk_per_trade_pct=float(
            risk_per_trade_pct
            if risk_per_trade_pct is not None
            else cfg["risk_per_trade_pct"]
        ),
        min_risk_reward=float(
            min_risk_reward if min_risk_reward is not None else cfg["min_risk_reward"]
        ),
        max_notional_pct=float(
            max_notional_pct
            if max_notional_pct is not None
            else cfg["max_notional_pct"]
        ),
        open_positions=open_positions,
        rules=cfg["rules"],
        journal_path=journal_path,
        pa_kwargs=cfg["pa_kwargs"],
    )

    ew_primary = pack.get("elliott_htf", {}).get("primary")
    plan = plan_result.get("plan") or {}
    if plan and ew_primary:
        thesis = plan.get("thesis") or {}
        thesis["elliott"] = {
            "kind": ew_primary.get("kind"),
            "score": ew_primary.get("score"),
            "current_wave": ew_primary.get("current_wave"),
            "invalidation": ew_primary.get("invalidation_price"),
        }
        plan["thesis"] = thesis
        plan["scenario_id"] = pack.get("primary_scenario_id")
        plan_result["plan"] = plan

    return {
        **plan_result,
        "scenarios": pack,
        "confidence": pack.get("confidence"),
        "executive_summary_tr": pack.get("executive_summary_tr"),
        "data_quality": pack.get("data_quality"),
        "trade_report": (plan_result.get("trade_report") or "") + "\n\n" + (pack.get("report") or ""),
    }


__all__ = [
    "analyze_chart_scenarios",
    "design_scenario_trade_plan",
]

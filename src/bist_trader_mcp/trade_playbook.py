"""Trade playbook — consistent, detailed trade plans + validation gates."""

from __future__ import annotations

from typing import Any, Literal

from .mtf_analysis import analyze_mtf_price_action
from .position_design import (
    DEFAULT_RISK_RULES,
    design_trade_setup,
    portfolio_risk_check,
)
from .trade_journal import list_trade_journal

Direction = Literal["long", "short"]
Quality = Literal["a_plus", "a", "b", "c", "conflict", "no_trade"]

PLAYBOOK_RULES: dict[str, Any] = {
    "min_trade_quality": "a",
    "min_risk_reward": 2.0,
    "require_htf_ltf_alignment": True,
    "reject_on_mtf_conflict": True,
    "max_stop_atr_multiple": 3.0,
    "min_stop_atr_multiple": 0.3,
    "max_entry_chase_atr": 1.5,
    "tp1_partial_pct": 50,
    "tp2_partial_pct": 50,
    "move_stop_to_be_after_tp1": True,
    "require_journal_no_same_symbol_conflict": True,
    "mandatory_checks": [
        "mtf_quality",
        "structure_supports_direction",
        "risk_reward",
        "stop_atr_sane",
        "portfolio_gate",
        "no_journal_conflict",
    ],
}


def get_trade_playbook_rules() -> dict[str, Any]:
    """Return the canonical rules AI must follow for every trade."""
    return {
        "source": "bist-trader-mcp — trade_playbook.get_trade_playbook_rules",
        "rules": PLAYBOOK_RULES,
        "workflow": [
            "1. Fetch HTF + LTF OHLCV (e.g. 4H + 1H or D + 4H)",
            "2. design_mtf_trade_plan(...) — single entry point",
            "3. If plan.approved and validation.passed: apply_trade_to_chart",
            "4. log_trade_plan(status='open') + monitor_open_trades",
            "5. Never skip validation or portfolio gate",
        ],
        "quality_meanings": {
            "a_plus": "HTF + LTF same bias — preferred",
            "a": "HTF bias aligned, LTF neutral — acceptable",
            "b": "LTF-only — avoid unless user overrides",
            "conflict": "NO TRADE",
            "no_trade": "NO TRADE",
        },
    }


def _quality_rank(q: str) -> int:
    return {"a_plus": 4, "a": 3, "b": 2, "c": 1, "conflict": 0, "no_trade": 0}.get(q, 0)


def _setup_type(direction: Direction, structure: str, mtf: dict[str, Any]) -> str:
    htf_s = mtf.get("htf_structure") or structure
    ltf_s = mtf.get("ltf_structure") or structure
    if direction == "long":
        if htf_s == "bullish" and ltf_s in ("bullish", "transition"):
            return "htf_bullish_ltf_pullback_long"
        if ltf_s == "ranging":
            return "range_support_long"
        return "counter_trend_long" if htf_s == "bearish" else "structure_long"
    if htf_s == "bearish" and ltf_s in ("bearish", "transition"):
        return "htf_bearish_ltf_pullback_short"
    if ltf_s == "ranging":
        return "range_resistance_short"
    return "counter_trend_short" if htf_s == "bullish" else "structure_short"


def enrich_trade_plan(
    plan: dict[str, Any],
    *,
    mtf: dict[str, Any] | None = None,
    pa: dict[str, Any] | None = None,
    rules: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Add execution detail, thesis, and management rules to a base plan."""
    if plan.get("error"):
        return plan

    merged = {**PLAYBOOK_RULES, **(rules or {})}
    direction = str(plan.get("direction") or "long")
    entry = float(plan["entry"])
    stop = float(plan["stop"])
    targets = list(plan.get("targets") or [])
    atr = None
    if pa:
        atr = pa.get("atr_14")
    elif plan.get("price_action"):
        atr = plan["price_action"].get("atr_14")
    elif mtf and mtf.get("ltf_analysis"):
        atr = mtf["ltf_analysis"].get("atr_14")

    structure = (pa or plan.get("price_action") or {}).get("market_structure", "unknown")
    if mtf:
        structure = mtf.get("ltf_structure") or structure

    risk_per_unit = abs(entry - stop)
    tp1_pct = float(merged["tp1_partial_pct"])
    tp2_pct = float(merged["tp2_partial_pct"])

    enriched_targets: list[dict[str, Any]] = []
    for i, t in enumerate(targets):
        row = dict(t)
        pct = tp1_pct if i == 0 else tp2_pct if i == 1 else max(0.0, 100.0 - tp1_pct - tp2_pct)
        row["size_pct"] = pct
        row["action_after_fill"] = (
            "move_stop_to_breakeven" if i == 0 and merged.get("move_stop_to_be_after_tp1") else "close_partial"
        )
        enriched_targets.append(row)

    invalidation = (
        f"{direction} invalidated if price closes beyond stop {stop} "
        f"({merged.get('ltf_label', 'LTF') if mtf else 'chart TF'} close)"
    )
    if mtf and mtf.get("htf_label"):
        invalidation += f" or HTF ({mtf['htf_label']}) structure flips against {direction}"

    setup_type = _setup_type(direction, structure, mtf or {})

    thesis = {
        "setup_type": setup_type,
        "market_structure": structure,
        "direction": direction,
        "summary": plan.get("auto_setup_rationale") or plan.get("rationale") or "",
        "entry_logic": (
            "Entry at LTF level aligned with HTF bias; "
            "stop beyond last structural swing + buffer."
        ),
        "invalidation": invalidation,
        "edge": f"Min R:R {plan.get('min_risk_reward_required', 2)}; "
        f"quality {mtf.get('trade_quality') if mtf else 'n/a'}",
    }

    sizing = plan.get("sizing") or {}
    units = float(sizing.get("units") or 0)

    execution = {
        "entry": {
            "type": "limit",
            "price": entry,
            "alternative": "market_if_breakout_confirmed",
            "trigger": f"Price reaches {entry} with {direction} structure intact",
        },
        "stop": {
            "price": stop,
            "distance": risk_per_unit,
            "distance_atr": round(risk_per_unit / atr, 2) if atr else None,
            "reason": "Beyond last swing / S-R invalidation",
        },
        "targets": enriched_targets,
        "management": [
            {"after": "entry_fill", "action": "set_stop", "price": stop},
            *(
                [{"after": "tp1_fill", "action": "move_stop_to_breakeven", "price": entry}]
                if merged.get("move_stop_to_be_after_tp1") and enriched_targets
                else []
            ),
            {"after": "tp2_fill", "action": "close_remaining"},
        ],
        "position_size": {
            "units": units,
            "notional": sizing.get("notional"),
            "risk_amount": sizing.get("risk_amount"),
            "risk_pct_equity": sizing.get("actual_risk_pct_of_equity"),
        },
    }

    report_lines = [
        f"{'LONG' if direction == 'long' else 'SHORT'} {plan.get('symbol')}",
        f"Setup: {setup_type} | Structure: {structure}",
        f"Entry {entry} | Stop {stop} | Best R:R {plan.get('best_risk_reward')}",
    ]
    for t in enriched_targets:
        report_lines.append(
            f"  {t.get('label')}: {t.get('price')} ({t.get('size_pct')}% size, R:R {t.get('risk_reward')})"
        )
    if mtf:
        report_lines.append(
            f"MTF: {mtf.get('htf_label')} {mtf.get('htf_bias')} / "
            f"{mtf.get('ltf_label')} {mtf.get('ltf_bias')} → quality {mtf.get('trade_quality')}"
        )

    out = dict(plan)
    out["thesis"] = thesis
    out["execution_plan"] = execution
    out["trade_report"] = "\n".join(report_lines)
    out["playbook_version"] = "1.0"
    return out


def validate_trade_consistency(
    plan: dict[str, Any],
    *,
    mtf: dict[str, Any] | None = None,
    open_trades: list[dict[str, Any]] | None = None,
    journal_path: str | None = None,
    rules: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Checklist gate — same rules every time for AI consistency."""
    merged = {**PLAYBOOK_RULES, **(rules or {})}
    checks: list[dict[str, Any]] = []

    if plan.get("error"):
        return {
            "source": "bist-trader-mcp — trade_playbook.validate_trade_consistency",
            "passed": False,
            "score": 0.0,
            "checks": [{"id": "plan_valid", "passed": False, "detail": plan.get("detail", plan["error"])}],
            "mandatory_failed": ["plan_valid"],
        }

    min_q = str(merged["min_trade_quality"])
    quality = (mtf or {}).get("trade_quality", "no_trade")
    q_ok = _quality_rank(str(quality)) >= _quality_rank(min_q)
    if merged.get("reject_on_mtf_conflict") and (mtf or {}).get("conflict"):
        q_ok = False
    checks.append({
        "id": "mtf_quality",
        "passed": q_ok,
        "detail": f"quality={quality}, required>={min_q}",
        "mandatory": True,
    })

    direction = plan.get("direction")
    pa = plan.get("price_action") or (mtf or {}).get("ltf_analysis") or {}
    structure = pa.get("market_structure") or (mtf or {}).get("ltf_structure")
    struct_ok = True
    if direction == "long" and structure == "bearish":
        struct_ok = False
    if direction == "short" and structure == "bullish":
        struct_ok = False
    checks.append({
        "id": "structure_supports_direction",
        "passed": struct_ok,
        "detail": f"structure={structure}, direction={direction}",
        "mandatory": True,
    })

    min_rr = float(merged["min_risk_reward"])
    best_rr = float(plan.get("best_risk_reward") or 0)
    rr_ok = best_rr >= min_rr and plan.get("approved", False)
    checks.append({
        "id": "risk_reward",
        "passed": rr_ok,
        "detail": f"R:R={best_rr}, min={min_rr}, plan_approved={plan.get('approved')}",
        "mandatory": True,
    })

    atr = pa.get("atr_14")
    entry = float(plan.get("entry") or 0)
    stop = float(plan.get("stop") or 0)
    dist = abs(entry - stop)
    stop_ok = True
    if atr and atr > 0:
        mult = dist / atr
        stop_ok = (
            float(merged["min_stop_atr_multiple"]) <= mult <= float(merged["max_stop_atr_multiple"])
        )
        stop_detail = f"stop distance {mult:.2f}x ATR (allowed {merged['min_stop_atr_multiple']}-{merged['max_stop_atr_multiple']})"
    else:
        stop_detail = "ATR unavailable — skip ATR stop check"
    checks.append({
        "id": "stop_atr_sane",
        "passed": stop_ok,
        "detail": stop_detail,
        "mandatory": False,
    })

    journal_rows = open_trades
    if journal_rows is None and merged.get("require_journal_no_same_symbol_conflict"):
        j = list_trade_journal(status="open", journal_path=journal_path)
        journal_rows = j.get("trades") or []

    sym = str(plan.get("symbol") or "").upper()
    journal_ok = True
    conflict_detail = "no open journal conflict"
    for t in journal_rows or []:
        tsym = str(t.get("symbol") or "").upper()
        tdir = t.get("direction")
        if tsym == sym and tdir and tdir != direction:
            journal_ok = False
            conflict_detail = f"open {tdir} on {sym} conflicts with new {direction}"
            break
    checks.append({
        "id": "no_journal_conflict",
        "passed": journal_ok,
        "detail": conflict_detail,
        "mandatory": bool(merged.get("require_journal_no_same_symbol_conflict")),
    })

    mandatory_ids = set(merged.get("mandatory_checks") or [])
    mandatory_failed = [
        c["id"] for c in checks
        if c.get("mandatory") and c["id"] in mandatory_ids and not c["passed"]
    ]
    passed_count = sum(1 for c in checks if c["passed"])
    score = passed_count / len(checks) if checks else 0.0

    return {
        "source": "bist-trader-mcp — trade_playbook.validate_trade_consistency",
        "passed": len(mandatory_failed) == 0,
        "score": round(score, 2),
        "checks": checks,
        "mandatory_failed": mandatory_failed,
        "rules_applied": merged,
    }


def design_mtf_trade_plan(
    *,
    symbol: str,
    htf_closes: list[float],
    htf_highs: list[float],
    htf_lows: list[float],
    ltf_closes: list[float],
    ltf_highs: list[float],
    ltf_lows: list[float],
    htf_label: str = "HTF",
    ltf_label: str = "LTF",
    equity: float = DEFAULT_RISK_RULES["default_equity"],  # type: ignore[assignment]
    risk_per_trade_pct: float = DEFAULT_RISK_RULES["risk_per_trade_pct"],  # type: ignore[assignment]
    min_risk_reward: float = DEFAULT_RISK_RULES["min_risk_reward"],  # type: ignore[assignment]
    max_notional_pct: float = DEFAULT_RISK_RULES["max_single_asset_notional_pct"],  # type: ignore[assignment]
    open_positions: list[dict[str, Any]] | None = None,
    rules: dict[str, Any] | None = None,
    journal_path: str | None = None,
    pa_kwargs: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Full consistent pipeline: MTF → plan → enrich → validate → portfolio gate."""
    merged = {**PLAYBOOK_RULES, **(rules or {})}
    mtf = analyze_mtf_price_action(
        htf_closes, htf_highs, htf_lows,
        ltf_closes, ltf_highs, ltf_lows,
        htf_label=htf_label,
        ltf_label=ltf_label,
        pa_kwargs=pa_kwargs,
    )

    if mtf.get("conflict") or mtf.get("trade_quality") in ("conflict", "no_trade"):
        return {
            "source": "bist-trader-mcp — trade_playbook.design_mtf_trade_plan",
            "approved": False,
            "action": "no_trade",
            "reason": "MTF conflict or no aligned setup",
            "mtf": mtf,
            "trade_report": (
                f"NO TRADE — {symbol}: MTF quality={mtf.get('trade_quality')}, "
                f"HTF={mtf.get('htf_bias')} LTF={mtf.get('ltf_bias')}"
            ),
        }

    if _quality_rank(str(mtf.get("trade_quality"))) < _quality_rank(str(merged["min_trade_quality"])):
        return {
            "source": "bist-trader-mcp — trade_playbook.design_mtf_trade_plan",
            "approved": False,
            "action": "no_trade",
            "reason": f"trade quality {mtf.get('trade_quality')} below min {merged['min_trade_quality']}",
            "mtf": mtf,
        }

    direction = mtf.get("aligned_direction")
    setup = mtf.get("recommended_setup")
    if direction not in ("long", "short") or not setup:
        return {
            "source": "bist-trader-mcp — trade_playbook.design_mtf_trade_plan",
            "approved": False,
            "action": "no_trade",
            "reason": "no viable setup on aligned direction",
            "mtf": mtf,
        }

    base = design_trade_setup(
        symbol=symbol,
        direction=direction,
        entry_price=setup["entry"],
        stop_price=setup["stop"],
        target_prices=setup["targets"],
        equity=float(equity),
        risk_per_trade_pct=float(risk_per_trade_pct),
        min_risk_reward=float(min_risk_reward),
        max_notional_pct=float(max_notional_pct),
        closes=ltf_closes,
        highs=ltf_highs,
        lows=ltf_lows,
    )
    base["auto_setup_rationale"] = setup.get("rationale")
    base["price_action"] = mtf.get("ltf_analysis")

    plan = enrich_trade_plan(base, mtf=mtf, pa=mtf.get("ltf_analysis"), rules=merged)
    if pa_kwargs:
        plan["market_pa_params"] = pa_kwargs
    validation = validate_trade_consistency(
        plan, mtf=mtf, journal_path=journal_path, rules=merged,
    )
    portfolio = portfolio_risk_check(
        equity=float(equity),
        open_positions=open_positions,
        proposed_trade=plan,
        rules=merged,
    )

    checks_pass = validation.get("passed", False)
    port_pass = portfolio.get("approved", False)
    plan_approved = plan.get("approved", False)
    fully_approved = plan_approved and checks_pass and port_pass

    reject_reasons: list[str] = list(plan.get("reject_reasons") or [])
    if not checks_pass:
        reject_reasons.extend(validation.get("mandatory_failed") or [])
    if not port_pass:
        reject_reasons.extend(portfolio.get("violations") or [])

    return {
        "source": "bist-trader-mcp — trade_playbook.design_mtf_trade_plan",
        "approved": fully_approved,
        "action": "execute" if fully_approved else "no_trade",
        "symbol": symbol,
        "direction": direction,
        "mtf": mtf,
        "plan": plan,
        "validation": validation,
        "portfolio_gate": portfolio,
        "reject_reasons": reject_reasons,
        "trade_report": plan.get("trade_report"),
        "next_steps": (
            ["apply_trade_to_chart(plan)", "log_trade_plan(plan, status='open')"]
            if fully_approved
            else ["review reject_reasons", "wait for better MTF alignment or adjust levels"]
        ),
    }


def design_ltf_trade_plan(
    *,
    symbol: str,
    closes: list[float],
    highs: list[float],
    lows: list[float],
    direction: str | None = None,
    equity: float = DEFAULT_RISK_RULES["default_equity"],  # type: ignore[assignment]
    risk_per_trade_pct: float = DEFAULT_RISK_RULES["risk_per_trade_pct"],  # type: ignore[assignment]
    min_risk_reward: float = DEFAULT_RISK_RULES["min_risk_reward"],  # type: ignore[assignment]
    open_positions: list[dict[str, Any]] | None = None,
    rules: dict[str, Any] | None = None,
    journal_path: str | None = None,
) -> dict[str, Any]:
    """Single-TF plan with same enrich + validate + portfolio pipeline."""
    from .position_design import design_from_price_action

    merged = {**PLAYBOOK_RULES, **(rules or {})}
    dir_arg = direction if direction in ("long", "short") else None
    base = design_from_price_action(
        symbol=symbol,
        closes=closes,
        highs=highs,
        lows=lows,
        direction=dir_arg,  # type: ignore[arg-type]
        equity=float(equity),
        risk_per_trade_pct=float(risk_per_trade_pct),
        min_risk_reward=float(min_risk_reward),
    )
    if base.get("error"):
        return {
            "source": "bist-trader-mcp — trade_playbook.design_ltf_trade_plan",
            "approved": False,
            "action": "no_trade",
            "reason": base.get("detail", base["error"]),
            "plan": base,
        }

    pa = base.get("price_action")
    plan = enrich_trade_plan(base, pa=pa, rules=merged)
    validation = validate_trade_consistency(plan, journal_path=journal_path, rules=merged)
    portfolio = portfolio_risk_check(
        equity=float(equity),
        open_positions=open_positions,
        proposed_trade=plan,
        rules=merged,
    )

    fully_approved = (
        plan.get("approved")
        and validation.get("passed")
        and portfolio.get("approved")
    )
    reject_reasons: list[str] = list(plan.get("reject_reasons") or [])
    if not validation.get("passed"):
        reject_reasons.extend(validation.get("mandatory_failed") or [])
    if not portfolio.get("approved"):
        reject_reasons.extend(portfolio.get("violations") or [])

    return {
        "source": "bist-trader-mcp — trade_playbook.design_ltf_trade_plan",
        "approved": fully_approved,
        "action": "execute" if fully_approved else "no_trade",
        "symbol": symbol,
        "plan": plan,
        "validation": validation,
        "portfolio_gate": portfolio,
        "reject_reasons": reject_reasons,
        "trade_report": plan.get("trade_report"),
        "next_steps": (
            ["apply_trade_to_chart(plan)", "log_trade_plan(plan, status='open')"]
            if fully_approved
            else ["review reject_reasons"]
        ),
    }


def run_trade_assistant(
    *,
    symbol: str,
    ltf_timeframe: str | None = None,
    htf_timeframe: str | None = None,
    market: str | None = None,
    equity: float = DEFAULT_RISK_RULES["default_equity"],  # type: ignore[assignment]
    risk_per_trade_pct: float | None = None,
    min_risk_reward: float | None = None,
    open_positions: list[dict[str, Any]] | None = None,
    rules: dict[str, Any] | None = None,
    journal_path: str | None = None,
    draw_on_chart: bool = True,
    log_journal: bool = True,
    set_alerts: bool = False,
) -> dict[str, Any]:
    """One-shot assistant flow: TV OHLCV → MTF plan → validate → draw → journal."""
    from .market_profiles import resolve_assistant_config
    from .tv_bridge import apply_trade_plan_to_chart
    from .tv_tools import tv_fetch_mtf_ohlcv, tv_health_check

    cfg = resolve_assistant_config(
        symbol,
        market=market,
        ltf_timeframe=ltf_timeframe,
        htf_timeframe=htf_timeframe,
        rules=rules,
    )
    sym_tv = cfg["symbol_tv"]
    ltf_tf = cfg["ltf_timeframe"]
    htf_tf = cfg["htf_timeframe"]

    health = tv_health_check()
    if not health.get("success"):
        return {
            "source": "bist-trader-mcp — trade_playbook.run_trade_assistant",
            "approved": False,
            "action": "no_trade",
            "reason": "TradingView CDP not ready — run launch_tv_debug.bat first",
            "health": health,
        }

    ohlcv = tv_fetch_mtf_ohlcv(
        sym_tv,
        ltf_tf,
        htf_tf,
        bars=cfg["ohlcv_bars"],
        market=market,
    )
    if len((ohlcv.get("ltf") or {}).get("closes") or []) < 30:
        return {
            "source": "bist-trader-mcp — trade_playbook.run_trade_assistant",
            "approved": False,
            "action": "no_trade",
            "reason": "insufficient LTF bars from TradingView",
            "ohlcv": ohlcv,
            "market_profile": cfg["profile"],
        }

    ltf = ohlcv["ltf"]
    htf = ohlcv["htf"]
    result = design_mtf_trade_plan(
        symbol=symbol,
        htf_closes=htf["closes"],
        htf_highs=htf["highs"],
        htf_lows=htf["lows"],
        ltf_closes=ltf["closes"],
        ltf_highs=ltf["highs"],
        ltf_lows=ltf["lows"],
        htf_label=htf_tf,
        ltf_label=ltf_tf,
        equity=float(equity),
        risk_per_trade_pct=float(
            risk_per_trade_pct
            if risk_per_trade_pct is not None
            else cfg["risk_per_trade_pct"]
        ),
        min_risk_reward=float(
            min_risk_reward if min_risk_reward is not None else cfg["min_risk_reward"]
        ),
        max_notional_pct=float(cfg["max_notional_pct"]),
        open_positions=open_positions,
        rules=cfg["rules"],
        journal_path=journal_path,
        pa_kwargs=cfg["pa_kwargs"],
    )

    out: dict[str, Any] = {
        "source": "bist-trader-mcp — trade_playbook.run_trade_assistant",
        "health": health,
        "market_profile": cfg["profile"],
        "ohlcv_meta": {
            "ltf_bars": ohlcv.get("ltf_bar_count"),
            "htf_bars": ohlcv.get("htf_bar_count"),
            "symbol_tv": sym_tv,
        },
        **result,
    }

    if not result.get("approved"):
        return out

    plan = result.get("plan") or {}
    if draw_on_chart:
        out["chart"] = apply_trade_plan_to_chart(
            plan,
            symbol=sym_tv,
            timeframe=ltf_tf,
            clear_drawings=True,
            inject_pine=False,
        )

    if set_alerts:
        alerts: list[dict[str, Any]] = []
        try:
            from .tv_tools import tv_alert_create

            alerts.append(tv_alert_create(plan["entry"], message=f"{symbol} entry"))
            alerts.append(tv_alert_create(plan["stop"], message=f"{symbol} stop"))
            if plan.get("targets"):
                alerts.append(
                    tv_alert_create(
                        plan["targets"][0]["price"],
                        message=f"{symbol} TP1",
                    )
                )
        except Exception as e:
            alerts.append({"error": str(e)})
        out["alerts"] = alerts

    if log_journal:
        from .trade_journal import log_trade_plan

        out["journal"] = log_trade_plan(plan, status="open", journal_path=journal_path)

    return out


def run_scenario_assistant(
    *,
    symbol: str,
    ltf_timeframe: str | None = None,
    htf_timeframe: str | None = None,
    market: str | None = None,
    equity: float = DEFAULT_RISK_RULES["default_equity"],  # type: ignore[assignment]
    risk_per_trade_pct: float | None = None,
    min_risk_reward: float | None = None,
    min_ew_score: float | None = None,
    open_positions: list[dict[str, Any]] | None = None,
    rules: dict[str, Any] | None = None,
    journal_path: str | None = None,
    draw_on_chart: bool = True,
    log_journal: bool = True,
) -> dict[str, Any]:
    """Backward-compatible alias → run_market_assistant (temel + teknik + TV)."""
    from .market_assistant import run_market_assistant

    out = run_market_assistant(
        symbol=symbol,
        ltf_timeframe=ltf_timeframe,
        htf_timeframe=htf_timeframe,
        market=market,
        equity=float(equity),
        risk_per_trade_pct=risk_per_trade_pct,
        min_risk_reward=min_risk_reward,
        min_ew_score=min_ew_score,
        open_positions=open_positions,
        rules=rules,
        journal_path=journal_path,
        fetch_fundamentals=True,
        draw_on_chart=draw_on_chart,
        draw_when_no_trade=True,
        log_journal=log_journal,
    )
    out["source"] = "bist-trader-mcp — trade_playbook.run_scenario_assistant"
    return out


__all__ = [
    "PLAYBOOK_RULES",
    "get_trade_playbook_rules",
    "enrich_trade_plan",
    "validate_trade_consistency",
    "design_mtf_trade_plan",
    "design_ltf_trade_plan",
    "run_trade_assistant",
    "run_scenario_assistant",
]

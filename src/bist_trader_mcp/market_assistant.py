"""Unified technical + fundamental market analysis + TV trade assistant."""

from __future__ import annotations

import asyncio
from typing import Any

from .chart_scenarios import analyze_chart_scenarios, design_scenario_trade_plan
from .chat_report import AI_PRESENTATION_RULES_TR, build_chat_trade_report
from .eod_htf_fallback import apply_eod_htf_fallback
from .fundamental_context import build_fundamental_context, merge_ta_fundamental_summary
from .fundamental_enrich import enrich_fundamental_snapshot
from .fundamental_technical_fusion import fuse_fundamental_technical
from .market_profiles import resolve_assistant_config


def _run_async(coro: Any) -> Any:
    """Run an async coroutine from sync code, even if a loop is already running."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    # A loop is already running (e.g. inside an async MCP host) — use a worker thread.
    import concurrent.futures

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
        return ex.submit(lambda: asyncio.run(coro)).result()


def _attach_crypto_derivatives_hint(
    fundamental: dict[str, Any],
    symbol: str,
) -> dict[str, Any]:
    core = symbol.split(":")[-1].upper().replace("USDT", "").replace("USD", "")
    if "get_crypto_funding_rates" not in (fundamental.get("recommended_mcp_tools") or []):
        fundamental.setdefault("recommended_mcp_tools", []).append("get_crypto_funding_rates")
    fundamental.setdefault("recommended_mcp_tools", []).append("get_crypto_open_interest")
    fundamental["crypto_derivatives_tr"] = (
        f"Kripto türev: get_crypto_funding_rates + get_crypto_open_interest "
        f"({core or 'symbol'}) — aşırı funding ile PA yönünü çaprazla."
    )
    return fundamental


def analyze_market_context(
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
    market: str | None = None,
    min_ew_score: float | None = None,
    data_quality: dict[str, Any] | None = None,
    fetch_fundamentals: bool = False,
    fund_enrich: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Full TA pack (PA+range+imbalance+EW MTF) + fundamental research context.

    When ``fetch_fundamentals`` is set (or ``fund_enrich`` is supplied), this also
    pulls live fundamentals (equity ratios / KAP / funding / sector / macro),
    scores them, and runs the fundamental↔technical fusion gate so the OFFLINE
    path returns the same depth as ``run_market_assistant`` (minus chart drawing).
    """
    cfg = resolve_assistant_config(
        symbol, market=market, ltf_timeframe=ltf_label, htf_timeframe=htf_label
    )
    ew_min = float(min_ew_score if min_ew_score is not None else cfg["min_ew_score"])

    ta = analyze_chart_scenarios(
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
        htf_label=htf_label,
        ltf_label=ltf_label,
        min_ew_score=ew_min,
        market=market,
        data_quality=data_quality,
    )

    fundamental = build_fundamental_context(symbol, market=market)
    if cfg["asset_class"] == "crypto":
        fundamental = _attach_crypto_derivatives_hint(fundamental, symbol)
    ew_mtf = ta.get("elliott_mtf") or {}
    combined_tr = merge_ta_fundamental_summary(
        ta_summary_tr=ta.get("executive_summary_tr") or "",
        fundamental=fundamental,
        elliott_mtf=ew_mtf,
    )

    out: dict[str, Any] = {
        "source": "bist-trader-mcp — market_assistant.analyze_market_context",
        "symbol": symbol,
        "market_profile": cfg["profile"],
        "technical": ta,
        "fundamental": fundamental,
        "elliott_htf": ta.get("elliott_htf"),
        "elliott_ltf": ta.get("elliott_ltf"),
        "elliott_mtf": ew_mtf,
        "trade_candidate": bool(ta.get("trade_candidate")),
        "executive_summary_tr": combined_tr,
        "recommended_mcp_tools": fundamental.get("recommended_mcp_tools"),
    }

    # Optional live fundamentals + fusion so the offline path matches the
    # online assistant's depth (real F/K, ROE, KAP tone, funding, fusion gate).
    if fetch_fundamentals and fund_enrich is None:
        try:
            fund_enrich = _run_async(enrich_fundamental_snapshot(symbol, market=market))
        except Exception as e:  # network/parse failure must not break TA output
            out["fundamental_error"] = str(e)
            fund_enrich = None

    if fund_enrich is not None:
        out["fundamental_enrich"] = fund_enrich
        fundamental["live"] = fund_enrich.get("fetched")
        fundamental["highlights_tr"] = fund_enrich.get("highlights_tr")
        fusion = fuse_fundamental_technical(
            technical=ta,
            trade_result={
                "approved": bool(ta.get("trade_candidate")),
                "plan": {"direction": (ta.get("mtf") or {}).get("aligned_direction")},
                "reason": ta.get("reason"),
            },
            fund_enrich=fund_enrich,
        )
        out["fusion"] = fusion
        out["trade_allowed"] = fusion.get("trade_allowed")
        highlights = fund_enrich.get("highlights_tr") or []
        if highlights:
            out["executive_summary_tr"] = (
                combined_tr + "\n" + " | ".join(highlights[:3])
            )
        out["executive_summary_tr"] += f"\nFusion: {fusion.get('summary_tr', '')}"

    return out


def run_market_assistant(
    *,
    symbol: str,
    ltf_timeframe: str | None = None,
    htf_timeframe: str | None = None,
    market: str | None = None,
    equity: float = 100_000.0,
    risk_per_trade_pct: float | None = None,
    min_risk_reward: float | None = None,
    min_ew_score: float | None = None,
    open_positions: list[dict[str, Any]] | None = None,
    rules: dict[str, Any] | None = None,
    journal_path: str | None = None,
    fetch_fundamentals: bool = True,
    draw_on_chart: bool = True,
    draw_when_no_trade: bool = True,
    log_journal: bool = True,
) -> dict[str, Any]:
    """ALL-IN-ONE: TV OHLCV → temel+teknik analiz → plan → chat raporu → grafik çizimi."""
    from .tv_bridge import apply_scenario_to_chart
    from .tv_tools import (
        tv_fetch_mtf_ohlcv,
        tv_finalize_chart_view,
        tv_health_check,
        tv_verify_chart_symbol,
    )

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
    tv_ready = bool(health.get("success"))

    if not tv_ready:
        return {
            "source": "bist-trader-mcp — market_assistant.run_market_assistant",
            "approved": False,
            "action": "no_trade",
            "reason": "tradingview_not_ready",
            "health": health,
            "ai_presentation_rules_tr": AI_PRESENTATION_RULES_TR,
            "assistant_note_tr": (
                "TradingView CDP kapalı. launch_tv_debug.bat (9222) sonra tekrar "
                "run_market_assistant çağır. Offline: analyze_market_context + OHLCV."
            ),
        }

    ohlcv = tv_fetch_mtf_ohlcv(
        sym_tv,
        ltf_tf,
        htf_tf,
        bars=cfg["ohlcv_bars"],
        market=market,
    )
    ohlcv = apply_eod_htf_fallback(ohlcv, symbol=symbol, market=market)
    ltf = ohlcv.get("ltf") or {}
    htf = ohlcv.get("htf") or {}
    if len(ltf.get("closes") or []) < 30:
        return {
            "source": "bist-trader-mcp — market_assistant.run_market_assistant",
            "approved": False,
            "action": "no_trade",
            "reason": "insufficient_ltf_bars",
            "ohlcv": ohlcv,
            "health": health,
        }

    symbol_check = tv_verify_chart_symbol(sym_tv)

    market_ctx = analyze_market_context(
        symbol=symbol,
        htf_closes=htf["closes"],
        htf_highs=htf["highs"],
        htf_lows=htf["lows"],
        ltf_closes=ltf["closes"],
        ltf_highs=ltf["highs"],
        ltf_lows=ltf["lows"],
        htf_times=htf.get("times"),
        ltf_times=ltf.get("times"),
        htf_volumes=htf.get("volumes"),
        ltf_volumes=ltf.get("volumes"),
        htf_label=htf_tf,
        ltf_label=ltf_tf,
        min_ew_score=min_ew_score,
        market=market,
        data_quality=ohlcv.get("data_quality"),
    )

    fund_enrich: dict[str, Any] | None = None
    if fetch_fundamentals:
        fund_enrich = asyncio.run(enrich_fundamental_snapshot(symbol, market=market))
        fund = market_ctx.get("fundamental") or {}
        fund["live"] = fund_enrich.get("fetched")
        fund["highlights_tr"] = fund_enrich.get("highlights_tr")
        if fund_enrich.get("highlights_tr"):
            market_ctx["executive_summary_tr"] = (
                market_ctx.get("executive_summary_tr", "")
                + "\n"
                + " | ".join(fund_enrich["highlights_tr"][:3])
            )

    trade_result = design_scenario_trade_plan(
        symbol=symbol,
        htf_closes=htf["closes"],
        htf_highs=htf["highs"],
        htf_lows=htf["lows"],
        ltf_closes=ltf["closes"],
        ltf_highs=ltf["highs"],
        ltf_lows=ltf["lows"],
        htf_times=htf.get("times"),
        ltf_times=ltf.get("times"),
        htf_volumes=htf.get("volumes"),
        ltf_volumes=ltf.get("volumes"),
        data_quality=ohlcv.get("data_quality"),
        htf_label=htf_tf,
        ltf_label=ltf_tf,
        equity=float(equity),
        risk_per_trade_pct=risk_per_trade_pct,
        min_risk_reward=min_risk_reward,
        min_ew_score=min_ew_score,
        market=market,
        open_positions=open_positions,
        rules=rules,
        journal_path=journal_path,
        scenario_pack=market_ctx.get("technical"),
    )

    fusion = fuse_fundamental_technical(
        technical=market_ctx.get("technical") or {},
        trade_result=trade_result,
        fund_enrich=fund_enrich,
        symbol_check=symbol_check,
    )
    if trade_result.get("approved") and not fusion.get("trade_allowed"):
        trade_result = dict(trade_result)
        trade_result["approved"] = False
        trade_result["action"] = "no_trade"
        trade_result["reason"] = fusion.get("block_reason") or "fusion_blocked"
        trade_result["fusion_blocked"] = True

    chart_drawn = False
    pack = trade_result.get("scenarios") or market_ctx.get("technical") or {}
    primary = pack.get("primary_scenario") or {}
    plan = trade_result.get("plan") or {}
    should_draw = draw_on_chart and (trade_result.get("approved") or draw_when_no_trade)

    out: dict[str, Any] = {
        "source": "bist-trader-mcp — market_assistant.run_market_assistant",
        "health": health,
        "symbol_tv": sym_tv,
        "symbol_check": symbol_check,
        "market_profile": cfg["profile"],
        "data_quality": ohlcv.get("data_quality"),
        "session_filter": ohlcv.get("session_filter"),
        "market_context": market_ctx,
        "fundamental_enrich": fund_enrich,
        "fusion": fusion,
        "htf_eod_fallback": ohlcv.get("htf_eod_fallback"),
        "ai_presentation_rules_tr": AI_PRESENTATION_RULES_TR,
        **trade_result,
    }

    if should_draw and primary.get("id") not in (None, "no_setup"):
        mtf_pack = pack.get("mtf") or {}
        fund_line = ""
        if fund_enrich and fund_enrich.get("highlights_tr"):
            fund_line = " · ".join(fund_enrich["highlights_tr"][:2])
        out["chart"] = apply_scenario_to_chart(
            primary,
            symbol=sym_tv,
            htf_timeframe=htf_tf,
            ltf_timeframe=ltf_tf,
            bar_times=htf.get("times"),
            ltf_times=ltf.get("times"),
            ltf_closes=ltf.get("closes"),
            ltf_highs=ltf.get("highs"),
            mtf=mtf_pack,
            plan=plan if plan.get("entry") is not None else None,
            clear_drawings=True,
            draw_pa=True,
            draw_ew=True,
            draw_position=bool(fusion.get("trade_allowed")),
            fundamental_banner=fund_line or None,
        )
        scroll_t = int(ltf["times"][-1]) if ltf.get("times") else None
        out["chart_finalize"] = tv_finalize_chart_view(
            sym_tv, ltf_tf, scroll_unix=scroll_t
        )
        chart_drawn = True

    out["chat_report"] = build_chat_trade_report(
        symbol=symbol,
        market_context=market_ctx,
        trade_result=trade_result,
        fundamental_enrich=fund_enrich,
        fusion=fusion,
        tv_ready=tv_ready,
        chart_drawn=chart_drawn,
    )
    out["report_tr"] = out["chat_report"].get("report_tr")
    out["assistant_note_tr"] = (
        "Chat: chat_report.report_tr alanını kullanıcıya Türkçe özetle. "
        "Grafik TradingView'da güncellendi." if chart_drawn else
        "Chat: chat_report.report_tr — grafik çizilmedi."
    )

    if log_journal and fusion.get("trade_allowed") and plan:
        from .trade_journal import log_trade_plan

        out["journal"] = log_trade_plan(plan, status="open", journal_path=journal_path)

    return out


__all__ = [
    "analyze_market_context",
    "run_market_assistant",
    "AI_PRESENTATION_RULES_TR",
]

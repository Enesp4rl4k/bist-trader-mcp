"""Structured trade-assistant report for LLM chat (TR)."""

from __future__ import annotations

from typing import Any

AI_PRESENTATION_RULES_TR = (
    "Kullanıcıya Türkçe yanıt ver. Yalnızca JSON'daki sayıları kullan; uydurma yok. "
    "Sıra: (1) Özet (2) Teknik (3) Temel (4) İşlem planı veya neden yok (5) Grafik durumu. "
    "Yatırım tavsiyesi değildir."
)


def build_chat_trade_report(
    *,
    symbol: str,
    market_context: dict[str, Any],
    trade_result: dict[str, Any],
    fundamental_enrich: dict[str, Any] | None = None,
    fusion: dict[str, Any] | None = None,
    tv_ready: bool = False,
    chart_drawn: bool = False,
) -> dict[str, Any]:
    """Single payload for chatbot to render a full assistant briefing."""
    ta = market_context.get("technical") or {}
    fund = market_context.get("fundamental") or {}
    conf = ta.get("confidence") or {}
    mtf = ta.get("mtf") or {}
    primary = ta.get("primary_scenario") or {}
    enrich = fundamental_enrich or {}
    highlights = list(enrich.get("highlights_tr") or [])
    checklist = fund.get("research_checklist_tr") or []

    tech_approved = bool(trade_result.get("approved"))
    fus = fusion or {}
    trade_allowed = bool(fus.get("trade_allowed")) if fus else tech_approved
    plan = trade_result.get("plan") or {}
    direction = plan.get("direction") or primary.get("direction") or "neutral"

    headline_parts = [
        f"{symbol}:",
        f"teknik güven {conf.get('grade', '?')} ({conf.get('score', 0)}/100)",
    ]
    if fus:
        headline_parts.append(f"fusion {fus.get('fusion_score', '?')}/100")
    if trade_allowed:
        headline_parts.append(f"işlem adayı {direction.upper()}")
    elif tech_approved and fus and not trade_allowed:
        headline_parts.append(f"teknik onay — fusion blok ({fus.get('block_reason')})")
    else:
        headline_parts.append(f"işlem yok — {trade_result.get('reason', 'gate')}")

    technical_lines = [
        f"HTF yapı: {mtf.get('htf_structure')} · LTF: {mtf.get('ltf_structure')}",
        f"MTF kalite: {mtf.get('trade_quality')} · yön: {mtf.get('aligned_direction')}",
        f"Senaryo: {primary.get('id', 'n/a')} — {primary.get('reason', '')[:100]}",
    ]
    ew_mtf = market_context.get("elliott_mtf") or {}
    if ew_mtf.get("notes_tr"):
        technical_lines.append(ew_mtf["notes_tr"])
    # Momentum / divergence line from indicator fusion (technical_signals)
    ltf_an = mtf.get("ltf_analysis") or {}
    signals = ltf_an.get("indicator_signals") or {}
    if signals.get("available"):
        from .technical_signals import indicator_summary_tr

        technical_lines.append(indicator_summary_tr(signals))
    if ta.get("report_tr") or ta.get("report"):
        technical_lines.append(str(ta.get("report_tr") or ta.get("report"))[:400])

    fundamental_lines = [fund.get("focus_tr", "")]
    fundamental_lines.extend(highlights[:5])
    if not highlights and checklist:
        fundamental_lines.append("Checklist: " + checklist[0][:80])

    fusion_lines: list[str] = []
    if fus:
        fusion_lines.append(fus.get("summary_tr", ""))
        warn_tr = fus.get("warnings_tr") or fus.get("warnings")
        if warn_tr:
            fusion_lines.append("Uyarılar: " + ", ".join(warn_tr[:6]))

    execution: dict[str, Any] = {
        "approved": trade_allowed,
        "technical_approved": tech_approved,
        "action": trade_result.get("action", "no_trade"),
        "reason": trade_result.get("reason"),
        "fusion_block_reason": fus.get("block_reason") if fus and not trade_allowed else None,
    }
    if trade_allowed and plan:
        execution.update(
            {
                "direction": plan.get("direction"),
                "entry": plan.get("entry"),
                "stop": plan.get("stop"),
                "targets": plan.get("targets"),
                "best_risk_reward": plan.get("best_risk_reward"),
                "position_size": plan.get("position_size"),
            }
        )

    remaining_tools = list(fund.get("recommended_mcp_tools") or [])
    if enrich.get("complete"):
        remaining_tools = [
            t for t in remaining_tools
            if t not in ("get_kap_disclosures", "get_bist_snapshot", "get_crypto_funding_rates")
        ]

    report_tr = "\n".join(
        [
            " ".join(headline_parts),
            "",
            "=== Teknik ===",
            *technical_lines,
            "",
            "=== Temel ===",
            *[x for x in fundamental_lines if x],
            "",
            "=== Fusion (temel+teknik) ===",
            *[x for x in fusion_lines if x],
            "",
            "=== İşlem ===",
            (
                f"{execution.get('direction')} entry={execution.get('entry')} "
                f"stop={execution.get('stop')} TP={execution.get('targets')}"
                if trade_allowed
                else f"NO TRADE: {execution.get('fusion_block_reason') or execution.get('reason')}"
            ),
            "",
            f"TradingView: {'çizildi' if chart_drawn else ('hazır' if tv_ready else 'kapalı')}",
        ]
    )

    sections = {
        "summary_tr": " ".join(headline_parts),
        "technical_tr": "\n".join(technical_lines),
        "fundamental_tr": "\n".join(x for x in fundamental_lines if x),
        "fusion_tr": "\n".join(x for x in fusion_lines if x) if fus else "",
        "execution": execution,
        "chart_tr": (
            f"TradingView: {'çizildi' if chart_drawn else ('hazır' if tv_ready else 'kapalı')}"
        ),
    }

    return {
        "source": "bist-trader-mcp — chat_report.build_chat_trade_report",
        "symbol": symbol,
        "headline_tr": sections["summary_tr"],
        "technical_summary_tr": sections["technical_tr"],
        "fundamental_summary_tr": sections["fundamental_tr"],
        "fusion_summary_tr": sections["fusion_tr"],
        "sections": sections,
        "execution": execution,
        "fusion": fus,
        "report_tr": report_tr,
        "ai_presentation_rules_tr": AI_PRESENTATION_RULES_TR,
        "remaining_mcp_tools": remaining_tools[:8],
        "trade_candidate": market_context.get("trade_candidate"),
        "confidence": conf,
        "trade_allowed": trade_allowed,
    }


__all__ = [
    "AI_PRESENTATION_RULES_TR",
    "build_chat_trade_report",
]

"""Tool profiles — expose fewer tools to cut the per-conversation token bill.

Every tool's name + description + JSON schema is sent to the model with each
request. With all ~115 tools that is ~17k tokens before the user says a word.
``BIST_TOOL_PROFILE`` picks a subset:

- ``core``    daily trading loop: simple PA, forecast, risk, dashboard, pipeline,
              backtests, journal, news/KAP, market summary
- ``trader``  core + the detailed analysis, TradingView, data and valuation tools
- ``full``    everything (default, backwards compatible)

``BIST_TOOLS_EXTRA=a,b`` adds individual tools to any profile. Tools hidden by
the profile are also refused on call, except the dashboard's own tools which
every profile keeps (the panel needs them).
"""

from __future__ import annotations

import os

ALWAYS = frozenset({"dashboard_snapshot", "dashboard_action", "get_job"})

CORE = frozenset({
    "get_simple_price_action", "forecast_next_candles",
    "open_dashboard", "run_daily_pipeline",
    "check_trade_risk", "get_portfolio_risk", "get_risk_config", "set_risk_config",
    "backtest_price_action", "backtest_price_action_universe", "evaluate_forecast_accuracy",
    "start_job", "check_alerts", "get_alerts", "send_test_alert", "get_paper_account",
    "list_trade_journal", "update_trade_status", "apply_trade_to_chart",
    "get_market_summary", "get_news_headlines", "get_kap_disclosures",
    "get_network_stats", "get_health_status",
}) | ALWAYS

TRADER = CORE | frozenset({
    "run_market_assistant", "analyze_market_context", "analyze_chart_scenarios",
    "analyze_price_action", "analyze_mtf_price_action", "analyze_elliott_wave",
    "analyze_range_imbalance", "get_market_profile", "scan_price_action_watchlist",
    "design_from_price_action", "log_trade_plan", "monitor_open_trades",
    "tv_health_check", "tv_chart_set_symbol", "tv_chart_set_timeframe", "tv_data_get_ohlcv",
    "get_bist_eod_ohlcv", "get_bist_snapshot", "get_crypto_klines", "get_global_pulse",
    "get_economic_calendar", "get_bist_sector_rotation", "get_foreign_ownership",
    "calculate_technicals", "analyze_financial_statements", "value_equity_dcf",
    "rank_equity_universe", "calculate_kelly_sizing",
})

PROFILES: dict[str, frozenset[str] | None] = {"core": CORE, "trader": TRADER, "full": None}


def active_profile() -> str:
    name = (os.environ.get("BIST_TOOL_PROFILE") or "full").strip().lower()
    return name if name in PROFILES else "full"


def enabled_tools(all_tools: list[str]) -> list[str]:
    """Registered tool names visible under the active profile (registry order)."""
    allowed = PROFILES[active_profile()]
    if allowed is None:
        return list(all_tools)
    extra = {t.strip() for t in (os.environ.get("BIST_TOOLS_EXTRA") or "").split(",")
             if t.strip()}
    keep = allowed | extra
    return [t for t in all_tools if t in keep]


def is_enabled(name: str, all_tools: list[str]) -> bool:
    return name in set(enabled_tools(all_tools))


__all__ = ["CORE", "TRADER", "PROFILES", "active_profile", "enabled_tools", "is_enabled"]

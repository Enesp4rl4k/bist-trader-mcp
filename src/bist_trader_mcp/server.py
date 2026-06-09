"""MCP server entrypoint — registers tools via decorators and runs over stdio.

v0.3: migrated from manual TOOL_DEFS list + giant if/elif dispatch to
the MCP SDK's `@server.tool()` decorator pattern. Each tool function is
registered directly with its name, docstring → description, and type
hints → JSON Schema. This eliminates ~300 lines of boilerplate and makes
adding new tools trivial (just define a function and decorate it).
"""

from __future__ import annotations

import json
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent

from .http_utils import close_shared_client
from .tools import (
    aggregate_portfolio_greeks,
    analyze_chart_scenarios,
    analyze_elliott_wave,
    analyze_market_context,
    analyze_mtf_price_action,
    analyze_price_action,
    analyze_range_imbalance,
    apply_scenario_to_chart,
    apply_trade_to_chart,
    backtest_strategy,
    calculate_atr_position_size,
    calculate_basis_fair_value,
    calculate_bond_metrics,
    calculate_correlation_matrix,
    calculate_ewma_volatility,
    calculate_garch_forecast,
    calculate_implied_volatility,
    calculate_kelly_sizing,
    calculate_option_greeks,
    calculate_performance_panel,
    calculate_portfolio_var,
    calculate_realized_vol,
    calculate_rolling_correlation,
    calculate_technicals,
    design_from_price_action,
    design_ltf_trade_plan,
    design_mtf_trade_plan,
    design_scenario_trade_plan,
    design_trade_setup,
    find_viop_spread_opportunities,
    fit_yield_curve_nss,
    get_bist_eod_ohlcv,
    get_bist_sector_rotation,
    get_bist_snapshot,
    get_btc_network_stats,
    get_crypto_fear_greed,
    get_crypto_funding_rates,
    get_crypto_klines,
    get_crypto_open_interest,
    get_crypto_spots,
    get_deribit_iv_surface,
    get_dibs_auctions,
    get_economic_calendar,
    get_eth_gas_oracle,
    get_foreign_ownership,
    get_fx_forward_curve,
    get_global_fx_history,
    get_global_fx_matrix,
    get_global_fx_spot,
    get_global_pulse,
    get_health_status,
    get_kap_disclosures,
    get_market_profile,
    get_market_summary,
    get_mkk_market_stats,
    get_news_headlines,
    get_repo_curve,
    get_tcmb_policy_rates,
    get_trade_playbook_rules,
    get_turib_endeks_overview,
    get_viop_dashboard,
    get_viop_iv_surface,
    get_viop_margin_call_alerts,
    get_viop_margin_parameters,
    get_viop_option_chain,
    get_viop_settlement,
    get_viop_term_structure,
    get_yield_curve,
    list_catalog,
    list_pine_recipes,
    list_signal_generators,
    list_strategy_templates,
    list_trade_journal,
    log_trade_plan,
    monitor_open_trades,
    optimize_portfolio_markowitz,
    pine_payload_from_trade_plan,
    portfolio_risk_check,
    render_pine_recipe,
    run_market_assistant,
    run_scenario_assistant,
    run_trade_assistant,
    scan_mtf_watchlist,
    scan_price_action_watchlist,
    simulate_option_strategy,
    stress_test_portfolio,
    tv_chart_set_symbol,
    tv_chart_set_timeframe,
    tv_data_get_ohlcv,
    tv_fetch_mtf_ohlcv,
    tv_health_check,
    update_trade_status,
    validate_trade_consistency,
)

server: Server = Server("bist-trader-mcp")


# ---------------------------------------------------------------------------
# Tool registry: each decorated function is auto-registered with its name,
# docstring, and JSON Schema inferred from parameters.
# ---------------------------------------------------------------------------

TOOL_REGISTRY: dict[str, dict[str, Any]] = {}


def _register(
    name: str,
    *,
    description: str,
    input_schema: dict[str, Any],
    handler: Any,
) -> None:
    """Internal helper to register a tool for dispatch."""
    TOOL_REGISTRY[name] = {
        "description": description,
        "inputSchema": input_schema,
        "handler": handler,
    }


# --- Rates / TCMB ---------------------------------------------------------

_register(
    "get_yield_curve",
    description=(
        "Return the Turkish DİBS (TL government bond) benchmark yield curve "
        "as of a date. Tenors: 1M, 3M, 6M, 1Y, 2Y, 3Y, 5Y, 10Y. Source: TCMB "
        "EVDS TP.ATBPK series family. Yields are nominal annualised percent."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "as_of": {"type": "string", "description": "YYYY-MM-DD"},
            "tenors": {"type": "array", "items": {"type": "string"}},
        },
    },
    handler=lambda args: get_yield_curve(
        as_of=args.get("as_of"),
        tenors=args.get("tenors"),
    ),
)

_register(
    "get_repo_curve",
    description=(
        "Turkish TL money-market / repo panel: TCMB 1w policy rate, BIST "
        "TLREF (effective O/N), and BIST O/N weighted-avg repo, plus "
        "cross-spreads in bps (TL funding stress signals). Source: TCMB "
        "EVDS. Use this as the short-end complement to get_yield_curve."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "as_of": {"type": "string", "description": "YYYY-MM-DD"},
            "window_days": {"type": "integer", "default": 14},
        },
    },
    handler=lambda args: get_repo_curve(
        as_of=args.get("as_of"),
        window_days=int(args.get("window_days", 14)),
    ),
)

_register(
    "get_tcmb_policy_rates",
    description=(
        "TCMB policy rate (1w repo) plus overnight corridor over a window. "
        "Source: TCMB EVDS TP.APIFON family."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "start": {"type": "string"},
            "end": {"type": "string"},
        },
    },
    handler=lambda args: get_tcmb_policy_rates(
        start=args.get("start"),
        end=args.get("end"),
    ),
)

_register(
    "calculate_bond_metrics",
    description=(
        "YTM, modified duration and convexity for a plain-vanilla bond. "
        "Rates passed as percent. Defaults to semi-annual coupon."
    ),
    input_schema={
        "type": "object",
        "required": [
            "face_value",
            "coupon_rate_pct",
            "years_to_maturity",
            "market_price",
        ],
        "properties": {
            "face_value": {"type": "number"},
            "coupon_rate_pct": {"type": "number"},
            "years_to_maturity": {"type": "number"},
            "market_price": {"type": "number"},
            "coupon_frequency": {"type": "integer", "default": 2},
        },
    },
    handler=lambda args: calculate_bond_metrics(
        face_value=float(args["face_value"]),
        coupon_rate_pct=float(args["coupon_rate_pct"]),
        years_to_maturity=float(args["years_to_maturity"]),
        market_price=float(args["market_price"]),
        coupon_frequency=int(args.get("coupon_frequency", 2)),
    ),
)

_register(
    "list_catalog",
    description="Curated EVDS series codes used by this MCP.",
    input_schema={"type": "object", "properties": {}},
    handler=lambda args: list_catalog(),
)


# --- KAP ------------------------------------------------------------------

_register(
    "get_kap_disclosures",
    description=(
        "List KAP disclosures within a date window. Optional ticker filter. "
        "`only_material=true` keeps high-signal subjects (material, "
        "transactions, dividends, mergers, tenders). Source: KAP public JSON."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "ticker": {"type": "string"},
            "since": {"type": "string"},
            "until": {"type": "string"},
            "only_material": {"type": "boolean", "default": False},
            "limit": {"type": "integer", "default": 100},
        },
    },
    handler=lambda args: get_kap_disclosures(
        ticker=args.get("ticker"),
        since=args.get("since"),
        until=args.get("until"),
        only_material=bool(args.get("only_material", False)),
        limit=int(args.get("limit", 100)),
    ),
)


# --- TÜRİB (commodity indices, public) ------------------------------------

_register(
    "get_turib_endeks_overview",
    description=(
        "TÜRİB public hububat/tarım endeks özeti (buğday, mısır, arpa, hububat). "
        "Bilgi amaçlı — canlı ELÜS derinlik için lisanslı veri dağıtıcı gerekir. "
        "XGIDA / gıda hisseleri ve makro bağlam için teknik analizle çapraz kullanın."
    ),
    input_schema={"type": "object", "properties": {}},
    handler=lambda args: get_turib_endeks_overview(),
)


# --- BIST equity EOD ------------------------------------------------------

_register(
    "get_bist_eod_ohlcv",
    description=(
        "Daily OHLCV bars for a BIST symbol via Yahoo Finance. EOD only — "
        "not for real-time. Indices use ^XU100 / ^XU030 form. "
        "Set `format='compact'` to return a CSV-style string instead of "
        "JSON array (saves ~70% LLM tokens for large date ranges)."
    ),
    input_schema={
        "type": "object",
        "required": ["ticker"],
        "properties": {
            "ticker": {"type": "string"},
            "since": {"type": "string"},
            "until": {"type": "string"},
            "format": {
                "type": "string",
                "default": "json",
                "description": "Output format: 'json' (default) or 'compact' (CSV-style)",
            },
        },
    },
    handler=lambda args: get_bist_eod_ohlcv(
        ticker=args["ticker"],
        since=args.get("since"),
        until=args.get("until"),
        fmt=args.get("format", "json"),
    ),
)


# --- Real-time snapshot ---------------------------------------------------

_register(
    "get_bist_snapshot",
    description=(
        "Latest price / change% / volume for 1-10 BIST tickers (15-min "
        "delayed via Yahoo Finance intraday). Answers 'şu an fiyat ne?' "
        "Accepts BIST tickers (THYAO, GARAN), indices (XU100, XU030), "
        "FX aliases (USDTRY, EURTRY), or Yahoo symbols. Returns each "
        "ticker's last, change, change%, open, high, low, volume, and "
        "market_state (REGULAR/CLOSED)."
    ),
    input_schema={
        "type": "object",
        "required": ["tickers"],
        "properties": {
            "tickers": {
                "type": "array",
                "items": {"type": "string"},
                "maxItems": 10,
                "description": "Ticker symbols (max 10). E.g. ['THYAO', 'GARAN', 'USDTRY']",
            },
        },
    },
    handler=lambda args: get_bist_snapshot(
        tickers=args["tickers"],
    ),
)

_register(
    "get_market_summary",
    description=(
        "One-shot Turkish market overview: XU100, XU030, XBANK indices + "
        "USDTRY, EURTRY, GBPTRY exchange rates + Gold (USD/oz), Brent "
        "crude + BTC/USD — all in a single parallel call. Returns a "
        "categorised snapshot with a headline string suitable for the "
        "user's 'Bugün piyasa nasıl?' question. 15-min delayed."
    ),
    input_schema={"type": "object", "properties": {}},
    handler=lambda args: get_market_summary(),
)


# --- VIOP -----------------------------------------------------------------


_register(
    "get_viop_settlement",
    description=(
        "All VIOP contract settlement rows (futures + options) for one "
        "trade date. Optional underlying filter. "
        "Set `format='compact'` for a CSV-style string (saves ~70% tokens "
        "for the full 480+ contract table)."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "trade_date": {"type": "string"},
            "underlying": {"type": "string"},
            "format": {
                "type": "string",
                "default": "json",
                "description": "Output format: 'json' (default) or 'compact' (CSV-style)",
            },
        },
    },
    handler=lambda args: get_viop_settlement(
        trade_date=args.get("trade_date"),
        underlying=args.get("underlying"),
        fmt=args.get("format", "json"),
    ),
)

_register(
    "get_viop_option_chain",
    description=(
        "VIOP option chain for one underlying — strikes × calls/puts. "
        "Optionally pinned to one expiry (year + month). If spot_price "
        "and risk_free_rate_pct are passed, IV is solved per row and "
        "ATM IV + ±5% skew are reported per expiry. Source: İş Yatırım "
        "viop.aspx (live last price + volume + OI) + bs IV math."
    ),
    input_schema={
        "type": "object",
        "required": ["underlying"],
        "properties": {
            "underlying": {"type": "string"},
            "expiry_year": {"type": "integer"},
            "expiry_month": {"type": "integer"},
            "as_of": {"type": "string"},
            "spot_price": {"type": "number"},
            "risk_free_rate_pct": {"type": "number"},
            "dividend_yield_pct": {"type": "number", "default": 0.0},
            "solve_iv": {"type": "boolean", "default": True},
        },
    },
    handler=lambda args: get_viop_option_chain(
        underlying=args["underlying"],
        expiry_year=(
            int(args["expiry_year"]) if args.get("expiry_year") is not None else None
        ),
        expiry_month=(
            int(args["expiry_month"]) if args.get("expiry_month") is not None else None
        ),
        as_of=args.get("as_of"),
        spot_price=(
            float(args["spot_price"]) if args.get("spot_price") is not None else None
        ),
        risk_free_rate_pct=(
            float(args["risk_free_rate_pct"])
            if args.get("risk_free_rate_pct") is not None
            else None
        ),
        dividend_yield_pct=float(args.get("dividend_yield_pct", 0.0)),
        solve_iv=bool(args.get("solve_iv", True)),
    ),
)

_register(
    "get_viop_term_structure",
    description=(
        "Futures-only term structure for one VIOP underlying, sorted by "
        "expiry. Useful for contango/backwardation and basis analysis."
    ),
    input_schema={
        "type": "object",
        "required": ["underlying"],
        "properties": {
            "underlying": {"type": "string"},
            "as_of": {"type": "string"},
        },
    },
    handler=lambda args: get_viop_term_structure(
        underlying=args["underlying"],
        as_of=args.get("as_of"),
    ),
)


# --- MKK ------------------------------------------------------------------

_register(
    "get_foreign_ownership",
    description=(
        "Daily per-ticker foreign-ownership ratio (% of free float). "
        "v0.2 WIP: requires MKK portal auth. Use get_mkk_market_stats "
        "for marketwide retail/institutional + equity/fixed-income trends."
    ),
    input_schema={
        "type": "object",
        "required": ["ticker"],
        "properties": {
            "ticker": {"type": "string"},
            "since": {"type": "string"},
            "until": {"type": "string"},
        },
    },
    handler=lambda args: get_foreign_ownership(
        ticker=args["ticker"],
        since=args.get("since"),
        until=args.get("until"),
    ),
)

_register(
    "get_mkk_market_stats",
    description=(
        "Marketwide MKK monthly system statistics: 12-month time series "
        "for total investors, investors holding equities / gov debt / "
        "corp bonds / mutual funds / structured products, transfers, "
        "and transactions. Source: MKK monthly bulletin PDF, cached 24h."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "pdf_url": {"type": "string"},
            "use_cache": {"type": "boolean", "default": True},
            "cache_ttl_seconds": {"type": "integer", "default": 86400},
        },
    },
    handler=lambda args: get_mkk_market_stats(
        pdf_url=args.get("pdf_url"),
        use_cache=bool(args.get("use_cache", True)),
        cache_ttl_seconds=int(args.get("cache_ttl_seconds", 86400)),
    ),
)


# --- Takasbank — VIOP margin parameters -----------------------------------

_register(
    "get_viop_margin_parameters",
    description=(
        "Daily Takasbank initial/maintenance margin per VIOP contract. "
        "A jump in initial_margin precedes broker margin calls. Set "
        "only_changed=true for the signal-rich subset."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "trade_date": {"type": "string"},
            "underlying": {"type": "string"},
            "only_changed": {"type": "boolean", "default": False},
        },
    },
    handler=lambda args: get_viop_margin_parameters(
        trade_date=args.get("trade_date"),
        underlying=args.get("underlying"),
        only_changed=bool(args.get("only_changed", False)),
    ),
)

_register(
    "get_viop_margin_call_alerts",
    description=(
        "Contracts whose initial margin moved by more than threshold_pct "
        "(default 5%) vs prior day — the morning scan for upcoming "
        "margin-call waves."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "trade_date": {"type": "string"},
            "threshold_pct": {"type": "number", "default": 5.0},
        },
    },
    handler=lambda args: get_viop_margin_call_alerts(
        trade_date=args.get("trade_date"),
        threshold_pct=float(args.get("threshold_pct", 5.0)),
    ),
)

_register(
    "get_viop_dashboard",
    description=(
        "Marketwide VIOP aggregate margin snapshot from Takasbank "
        "(margined account count, transaction/guarantee-fund margin, "
        "margin-call total, required margin). Cached 6h to respect "
        "Takasbank's F5 WAF rate limit. THE marketwide margin stress "
        "signal."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "use_cache": {"type": "boolean", "default": True},
            "cache_ttl_seconds": {"type": "integer", "default": 21600},
        },
    },
    handler=lambda args: get_viop_dashboard(
        use_cache=bool(args.get("use_cache", True)),
        cache_ttl_seconds=int(args.get("cache_ttl_seconds", 6 * 3600)),
    ),
)


# --- Options math ---------------------------------------------------------

_register(
    "calculate_option_greeks",
    description=(
        "Black-Scholes price + delta/gamma/theta/vega/rho for a European "
        "option (VIOP options are European-style)."
    ),
    input_schema={
        "type": "object",
        "required": [
            "spot",
            "strike",
            "days_to_expiry",
            "volatility_pct",
            "risk_free_rate_pct",
        ],
        "properties": {
            "spot": {"type": "number"},
            "strike": {"type": "number"},
            "days_to_expiry": {"type": "number"},
            "volatility_pct": {"type": "number"},
            "risk_free_rate_pct": {"type": "number"},
            "dividend_yield_pct": {"type": "number", "default": 0.0},
            "style": {"type": "string", "default": "call"},
        },
    },
    handler=lambda args: calculate_option_greeks(
        spot=float(args["spot"]),
        strike=float(args["strike"]),
        days_to_expiry=float(args["days_to_expiry"]),
        volatility_pct=float(args["volatility_pct"]),
        risk_free_rate_pct=float(args["risk_free_rate_pct"]),
        dividend_yield_pct=float(args.get("dividend_yield_pct", 0.0)),
        style=str(args.get("style", "call")),
    ),
)

_register(
    "calculate_implied_volatility",
    description=(
        "Solve Black-Scholes for sigma given an observed market option "
        "price. Returns IV as percent."
    ),
    input_schema={
        "type": "object",
        "required": [
            "market_price",
            "spot",
            "strike",
            "days_to_expiry",
            "risk_free_rate_pct",
        ],
        "properties": {
            "market_price": {"type": "number"},
            "spot": {"type": "number"},
            "strike": {"type": "number"},
            "days_to_expiry": {"type": "number"},
            "risk_free_rate_pct": {"type": "number"},
            "dividend_yield_pct": {"type": "number", "default": 0.0},
            "style": {"type": "string", "default": "call"},
        },
    },
    handler=lambda args: calculate_implied_volatility(
        market_price=float(args["market_price"]),
        spot=float(args["spot"]),
        strike=float(args["strike"]),
        days_to_expiry=float(args["days_to_expiry"]),
        risk_free_rate_pct=float(args["risk_free_rate_pct"]),
        dividend_yield_pct=float(args.get("dividend_yield_pct", 0.0)),
        style=str(args.get("style", "call")),
    ),
)


# --- Portfolio Greeks aggregator -----------------------------------------

_register(
    "aggregate_portfolio_greeks",
    description=(
        "Net delta / gamma / vega / theta for a list of positions "
        "(options, futures, spot). Each option leg is repriced with "
        "Black-Scholes; IV can be supplied (volatility_pct) or solved "
        "from market_price. Returns per-leg detail, portfolio totals, "
        "and a per-underlying rollup. Pure math — no network."
    ),
    input_schema={
        "type": "object",
        "required": ["positions"],
        "properties": {
            "positions": {
                "type": "array",
                "description": (
                    "List of position dicts. Required keys per leg: "
                    "symbol, underlying, qty, instrument_type "
                    "('option'|'future'|'spot'). For options, also: "
                    "strike, days_to_expiry, right ('call'|'put'), spot, "
                    "risk_free_rate_pct, and one of volatility_pct OR "
                    "market_price. Optional: dividend_yield_pct, multiplier."
                ),
                "items": {
                    "type": "object",
                    "required": ["qty", "instrument_type"],
                    "properties": {
                        "symbol": {"type": "string"},
                        "underlying": {"type": "string"},
                        "qty": {"type": "number"},
                        "instrument_type": {"type": "string"},
                        "strike": {"type": "number"},
                        "days_to_expiry": {"type": "number"},
                        "right": {"type": "string"},
                        "volatility_pct": {"type": "number"},
                        "market_price": {"type": "number"},
                        "spot": {"type": "number"},
                        "risk_free_rate_pct": {"type": "number"},
                        "dividend_yield_pct": {"type": "number"},
                        "multiplier": {"type": "number"},
                    },
                },
            },
        },
    },
    handler=lambda args: aggregate_portfolio_greeks(
        positions=args.get("positions") or [],
    ),
)


# --- Hazine — DİBS auctions -----------------------------------------------

_register(
    "get_dibs_auctions",
    description=(
        "DİBS auction calendar parsed from Hazine's quarterly İç "
        "Borçlanma Stratejisi PDF. Default window: -30 to +90 days. "
        "Filter by status (scheduled/completed/cancelled) or override "
        "the source PDF via `pdf_url`."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "since": {"type": "string"},
            "until": {"type": "string"},
            "status": {"type": "string"},
            "pdf_url": {"type": "string"},
        },
    },
    handler=lambda args: get_dibs_auctions(
        since=args.get("since"),
        until=args.get("until"),
        status=args.get("status"),
        pdf_url=args.get("pdf_url"),
    ),
)


# --- Economic calendar ----------------------------------------------------

_register(
    "get_economic_calendar",
    description=(
        "Turkish macro & monetary policy event calendar: TCMB PPK "
        "(MPC) decision dates, TÜİK TÜFE (CPI) and Yİ-ÜFE (PPI) "
        "release dates. Optional date window and category filter. "
        "Source: static TCMB schedule + TÜİK 3rd-business-day rule."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "since": {"type": "string", "description": "YYYY-MM-DD"},
            "until": {"type": "string", "description": "YYYY-MM-DD"},
            "categories": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Filter — any of: monetary_policy, inflation, "
                    "growth, labour, trade"
                ),
            },
        },
    },
    handler=lambda args: get_economic_calendar(
        since=args.get("since"),
        until=args.get("until"),
        categories=args.get("categories"),
    ),
)


# --- FX forward / swap curve ----------------------------------------------

_register(
    "get_fx_forward_curve",
    description=(
        "CIP-implied FX forward outrights + forward points for USDTRY "
        "or EURTRY. Spot + TL leg auto-pulled from TCMB EVDS; the "
        "foreign rate (USD/EUR) must be supplied. Returns tenor × "
        "forward + pip points. Onshore TR forward market is illiquid; "
        "offshore NDFs typically track CIP plus a credit premium."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "pair": {
                "type": "string",
                "default": "USDTRY",
                "description": "USDTRY or EURTRY",
            },
            "foreign_rate_pct": {
                "type": "number",
                "default": 4.5,
                "description": "USD or EUR rate in percent",
            },
            "spot": {"type": "number"},
            "domestic_rate_pct": {"type": "number"},
            "tenors": {"type": "array", "items": {"type": "string"}},
        },
    },
    handler=lambda args: get_fx_forward_curve(
        pair=str(args.get("pair", "USDTRY")),
        foreign_rate_pct=float(args.get("foreign_rate_pct", 4.5)),
        spot=(float(args["spot"]) if args.get("spot") is not None else None),
        domestic_rate_pct=(
            float(args["domestic_rate_pct"])
            if args.get("domestic_rate_pct") is not None
            else None
        ),
        tenors=args.get("tenors"),
    ),
)


# --- Cross-asset basis ----------------------------------------------------

_register(
    "calculate_basis_fair_value",
    description=(
        "Cost-of-carry fair value of a futures contract vs observed "
        "market. Returns deviation_from_fair_bps and implied_repo_rate. "
        "Pair with get_yield_curve for the risk-free input."
    ),
    input_schema={
        "type": "object",
        "required": [
            "spot_price",
            "futures_price",
            "days_to_expiry",
            "risk_free_rate_pct",
        ],
        "properties": {
            "spot_price": {"type": "number"},
            "futures_price": {"type": "number"},
            "days_to_expiry": {"type": "number"},
            "risk_free_rate_pct": {"type": "number"},
            "dividend_yield_pct": {"type": "number", "default": 0.0},
        },
    },
    handler=lambda args: calculate_basis_fair_value(
        spot_price=float(args["spot_price"]),
        futures_price=float(args["futures_price"]),
        days_to_expiry=float(args["days_to_expiry"]),
        risk_free_rate_pct=float(args["risk_free_rate_pct"]),
        dividend_yield_pct=float(args.get("dividend_yield_pct", 0.0)),
    ),
)


# --- VIOP IV surface + spread screener (v0.3) -----------------------------

_register(
    "get_viop_iv_surface",
    description=(
        "Build a full IV surface from the live VIOP option chain. Returns "
        "per-quote IV/delta/moneyness, ATM term structure, 25-delta skew "
        "on the front month, and front-vs-back vol slope. Combine with "
        "find_viop_spread_opportunities to scan for calendar/butterfly "
        "dislocations."
    ),
    input_schema={
        "type": "object",
        "required": ["underlying", "spot_price", "risk_free_rate_pct"],
        "properties": {
            "underlying": {"type": "string"},
            "spot_price": {"type": "number"},
            "risk_free_rate_pct": {"type": "number"},
            "dividend_yield_pct": {"type": "number", "default": 0.0},
            "expiry_year": {"type": "integer"},
            "expiry_month": {"type": "integer"},
            "min_price": {"type": "number", "default": 0.01},
        },
    },
    handler=lambda args: get_viop_iv_surface(
        underlying=str(args["underlying"]),
        spot_price=float(args["spot_price"]),
        risk_free_rate_pct=float(args["risk_free_rate_pct"]),
        dividend_yield_pct=float(args.get("dividend_yield_pct", 0.0)),
        expiry_year=args.get("expiry_year"),
        expiry_month=args.get("expiry_month"),
        min_price=float(args.get("min_price", 0.01)),
    ),
)

_register(
    "find_viop_spread_opportunities",
    description=(
        "Scan an IV surface (from get_viop_iv_surface) for calendar / "
        "vertical / butterfly dislocations. Returns ranked candidates by "
        "vol-point edge."
    ),
    input_schema={
        "type": "object",
        "required": ["surface"],
        "properties": {
            "surface": {
                "type": "object",
                "description": "The full output of get_viop_iv_surface.",
            },
            "strategy": {
                "type": "string",
                "enum": ["calendar", "vertical", "butterfly"],
                "default": "calendar",
            },
            "min_edge_vol_pts": {"type": "number", "default": 3.0},
            "max_results": {"type": "integer", "default": 20},
        },
    },
    handler=lambda args: find_viop_spread_opportunities(
        surface=args["surface"],
        strategy=str(args.get("strategy", "calendar")),
        min_edge_vol_pts=float(args.get("min_edge_vol_pts", 3.0)),
        max_results=int(args.get("max_results", 20)),
    ),
)


# --- Portfolio VaR + stress (v0.3) ----------------------------------------

_register(
    "calculate_portfolio_var",
    description=(
        "Portfolio Value-at-Risk under parametric or historical method. "
        "Pair with aggregate_portfolio_greeks for first-order risk and "
        "stress_test_portfolio for non-linear scenarios."
    ),
    input_schema={
        "type": "object",
        "required": ["positions"],
        "properties": {
            "positions": {"type": "array", "items": {"type": "object"}},
            "confidence": {"type": "number", "default": 0.99},
            "horizon_days": {"type": "integer", "default": 1},
            "annual_volatility_pct": {"type": "number", "default": 30.0},
            "method": {
                "type": "string",
                "enum": ["parametric", "historical"],
                "default": "parametric",
            },
            "historical_returns": {
                "type": "array",
                "items": {"type": "number"},
                "description": "Decimal daily returns; required for method=historical.",
            },
        },
    },
    handler=lambda args: calculate_portfolio_var(
        positions=args.get("positions") or [],
        confidence=float(args.get("confidence", 0.99)),
        horizon_days=int(args.get("horizon_days", 1)),
        annual_volatility_pct=float(args.get("annual_volatility_pct", 30.0)),
        method=str(args.get("method", "parametric")),
        historical_returns=args.get("historical_returns"),
    ),
)

_register(
    "stress_test_portfolio",
    description=(
        "Reprice a portfolio under named shock scenarios (e.g. rates+200bp, "
        "tl_devalue_20pct, xu030_-10pct, vol_spike_+50pct_rel). Returns each "
        "scenario's P&L, sorted worst-to-best."
    ),
    input_schema={
        "type": "object",
        "required": ["positions"],
        "properties": {
            "positions": {"type": "array", "items": {"type": "object"}},
            "scenarios": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Subset of built-in scenario names. Defaults to all.",
            },
            "custom_scenarios": {
                "type": "object",
                "description": "Optional {name: shock_dict} extra scenarios.",
            },
        },
    },
    handler=lambda args: stress_test_portfolio(
        positions=args.get("positions") or [],
        scenarios=args.get("scenarios"),
        custom_scenarios=args.get("custom_scenarios"),
    ),
)


# --- Global markets (v0.4) ------------------------------------------------

_register(
    "get_global_pulse",
    description=(
        "One-shot global market snapshot bucketed by category: indices "
        "(SPX/NDX/DAX/FTSE/N225/HSI), treasuries (UST 3M/5Y/10Y/30Y), "
        "commodities (WTI/Brent/Gold/Silver/Copper/Natgas), and crypto "
        "majors (BTC/ETH/SOL/etc). All via Yahoo Finance, delayed."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "categories": {
                "type": "array",
                "items": {"type": "string",
                           "enum": ["indices", "treasuries", "commodities", "crypto"]},
                "description": "Defaults to all four.",
            },
        },
    },
    handler=lambda args: get_global_pulse(categories=args.get("categories")),
)


# --- Global FX (v0.4) -----------------------------------------------------

_register(
    "get_global_fx_spot",
    description=(
        "Latest ECB reference rate for a major FX pair (e.g. EURUSD, USDJPY). "
        "Daily update ~16:00 CET — not intraday. Source: Frankfurter."
    ),
    input_schema={
        "type": "object",
        "required": ["pair"],
        "properties": {
            "pair": {"type": "string",
                      "description": "6-char pair like 'EURUSD' or 'EUR/USD'"},
        },
    },
    handler=lambda args: get_global_fx_spot(pair=str(args["pair"])),
)

_register(
    "get_global_fx_history",
    description=(
        "Daily history (last N business days) of an FX pair from ECB "
        "reference rates."
    ),
    input_schema={
        "type": "object",
        "required": ["pair"],
        "properties": {
            "pair": {"type": "string"},
            "days": {"type": "integer", "default": 30},
        },
    },
    handler=lambda args: get_global_fx_history(
        pair=str(args["pair"]),
        days=int(args.get("days", 30)),
    ),
)

_register(
    "get_global_fx_matrix",
    description=(
        "N×M FX rate matrix for screening. Defaults to G10 bases × EM "
        "quote currencies (TRY, CNY, MXN, BRL, ZAR, INR, ...)."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "bases": {"type": "array", "items": {"type": "string"}},
            "quotes": {"type": "array", "items": {"type": "string"}},
        },
    },
    handler=lambda args: get_global_fx_matrix(
        bases=args.get("bases"),
        quotes=args.get("quotes"),
    ),
)


# --- Crypto (v0.4) --------------------------------------------------------

_register(
    "get_crypto_spots",
    description=(
        "Spot snapshots for a list of CoinGecko coins (price, market cap, "
        "24h vol, 24h/7d % change, ATH). E.g. coin_ids=['bitcoin','ethereum']."
    ),
    input_schema={
        "type": "object",
        "required": ["coin_ids"],
        "properties": {
            "coin_ids": {"type": "array", "items": {"type": "string"}},
            "vs_currency": {"type": "string", "default": "usd"},
        },
    },
    handler=lambda args: get_crypto_spots(
        coin_ids=args.get("coin_ids") or [],
        vs_currency=str(args.get("vs_currency", "usd")),
    ),
)

_register(
    "get_crypto_klines",
    description=(
        "OHLCV klines from Binance spot. Symbol like 'BTCUSDT', interval "
        "in {1m,5m,15m,1h,4h,1d,1w}. Max 1000 bars. Pair with "
        "calculate_technicals for RSI/MACD/Bollinger on the result."
    ),
    input_schema={
        "type": "object",
        "required": ["symbol"],
        "properties": {
            "symbol": {"type": "string"},
            "interval": {"type": "string", "default": "1d"},
            "limit": {"type": "integer", "default": 200},
        },
    },
    handler=lambda args: get_crypto_klines(
        symbol=str(args["symbol"]),
        interval=str(args.get("interval", "1d")),
        limit=int(args.get("limit", 200)),
    ),
)

_register(
    "get_crypto_funding_rates",
    description=(
        "Recent funding rate history for a Binance USD-M perp. Persistently "
        "positive funding = bullish leverage; negative = bearish. Includes "
        "an annualised average for quick comparison vs spot/repo."
    ),
    input_schema={
        "type": "object",
        "required": ["symbol"],
        "properties": {
            "symbol": {"type": "string"},
            "limit": {"type": "integer", "default": 30},
        },
    },
    handler=lambda args: get_crypto_funding_rates(
        symbol=str(args["symbol"]),
        limit=int(args.get("limit", 30)),
    ),
)

_register(
    "get_crypto_open_interest",
    description="Open interest history for a Binance USD-M perp.",
    input_schema={
        "type": "object",
        "required": ["symbol"],
        "properties": {
            "symbol": {"type": "string"},
            "period": {"type": "string", "default": "1h"},
            "limit": {"type": "integer", "default": 30},
        },
    },
    handler=lambda args: get_crypto_open_interest(
        symbol=str(args["symbol"]),
        period=str(args.get("period", "1h")),
        limit=int(args.get("limit", 30)),
    ),
)


# --- Option strategy simulator (v0.6) ------------------------------------

_register(
    "list_strategy_templates",
    description=(
        "List available option strategy templates and their required args."
    ),
    input_schema={"type": "object", "properties": {}},
    handler=lambda args: list_strategy_templates(),
)

_register(
    "simulate_option_strategy",
    description=(
        "Simulate an option strategy's P&L across a spot range. Use a "
        "named template (long_straddle, short_straddle, long_strangle, "
        "iron_condor, butterfly, vertical_spread) with template_args, or "
        "pass `legs` directly. Returns the full P&L grid, max profit/loss, "
        "breakevens, and net debit/credit. Set at_expiry=false + "
        "days_forward=N to see mid-life P&L."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "template": {"type": "string",
                          "description": "One of list_strategy_templates."},
            "template_args": {"type": "object",
                               "description": "Args for the template."},
            "legs": {"type": "array", "items": {"type": "object"},
                      "description": "Custom legs if no template."},
            "spot_low":  {"type": "number", "default": 0.0},
            "spot_high": {"type": "number", "default": 0.0},
            "spot_steps": {"type": "integer", "default": 41},
            "risk_free_rate_pct": {"type": "number", "default": 0.0},
            "dividend_yield_pct": {"type": "number", "default": 0.0},
            "days_forward": {"type": "number", "default": 0,
                              "description": "Days from now (ignored if at_expiry)."},
            "at_expiry": {"type": "boolean", "default": True},
        },
    },
    handler=lambda args: simulate_option_strategy(
        template=args.get("template"),
        template_args=args.get("template_args"),
        legs=args.get("legs"),
        spot_low=float(args.get("spot_low", 0.0)),
        spot_high=float(args.get("spot_high", 0.0)),
        spot_steps=int(args.get("spot_steps", 41)),
        risk_free_rate_pct=float(args.get("risk_free_rate_pct", 0.0)),
        dividend_yield_pct=float(args.get("dividend_yield_pct", 0.0)),
        days_forward=float(args.get("days_forward", 0)),
        at_expiry=bool(args.get("at_expiry", True)),
    ),
)


# --- Realized volatility (v0.6) ------------------------------------------

_register(
    "calculate_realized_vol",
    description=(
        "Realized volatility panel: close-to-close, Parkinson (H/L), "
        "Garman-Klass (O/H/L/C). Provide iv_atm_pct (from "
        "get_viop_iv_surface or get_deribit_iv_surface) for IV/RV ratio "
        "and spread — the classic option mean-reversion signal. For crypto "
        "set annualise_days=365."
    ),
    input_schema={
        "type": "object",
        "required": ["closes"],
        "properties": {
            "closes": {"type": "array", "items": {"type": "number"}},
            "opens":  {"type": "array", "items": {"type": "number"}},
            "highs":  {"type": "array", "items": {"type": "number"}},
            "lows":   {"type": "array", "items": {"type": "number"}},
            "period": {"type": "integer", "default": 30},
            "annualise_days": {"type": "integer", "default": 252},
            "iv_atm_pct": {"type": "number",
                            "description": "Optional: ATM IV % for IV/RV ratio."},
        },
    },
    handler=lambda args: calculate_realized_vol(
        closes=args.get("closes") or [],
        opens=args.get("opens"),
        highs=args.get("highs"),
        lows=args.get("lows"),
        period=int(args.get("period", 30)),
        annualise_days=int(args.get("annualise_days", 252)),
        iv_atm_pct=args.get("iv_atm_pct"),
    ),
)


# --- News headlines (v0.6) -----------------------------------------------

_register(
    "get_news_headlines",
    description=(
        "Financial news headlines from curated free RSS feeds (Investing.com "
        "sections, Yahoo Finance, Reuters via Google News, CoinDesk). "
        "Default: investing_top + investing_economy + yahoo_markets."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "feeds": {"type": "array", "items": {"type": "string"},
                       "description": "Subset of NEWS_FEEDS keys."},
            "limit_per_feed": {"type": "integer", "default": 10},
        },
    },
    handler=lambda args: get_news_headlines(
        feeds=args.get("feeds"),
        limit_per_feed=int(args.get("limit_per_feed", 10)),
    ),
)


# --- Backtest + performance + optimizer + Kelly (v0.8) -------------------

_register(
    "list_signal_generators",
    description="List built-in backtest signal generators and their args.",
    input_schema={"type": "object", "properties": {}},
    handler=lambda args: list_signal_generators(),
)

_register(
    "backtest_strategy",
    description=(
        "Event-driven backtest: closes + signals → equity curve + trades + "
        "full performance panel. Provide signals directly or use "
        "signal_generator ∈ {sma_crossover, rsi_thresholds, "
        "bollinger_mean_reversion}. Includes commission + slippage costs."
    ),
    input_schema={
        "type": "object",
        "required": ["closes"],
        "properties": {
            "closes": {"type": "array", "items": {"type": "number"}},
            "signals": {"type": "array", "items": {"type": "number"}},
            "signal_generator": {
                "type": "string",
                "enum": ["sma_crossover", "rsi_thresholds",
                          "bollinger_mean_reversion"],
            },
            "signal_args": {"type": "object"},
            "initial_equity": {"type": "number", "default": 100000.0},
            "commission_pct": {"type": "number", "default": 0.05},
            "slippage_pct": {"type": "number", "default": 0.05},
            "risk_free_pct": {"type": "number", "default": 0.0},
            "periods_per_year": {"type": "integer", "default": 252},
        },
    },
    handler=lambda args: backtest_strategy(
        closes=args.get("closes") or [],
        signals=args.get("signals"),
        signal_generator=args.get("signal_generator"),
        signal_args=args.get("signal_args"),
        initial_equity=float(args.get("initial_equity", 100000.0)),
        commission_pct=float(args.get("commission_pct", 0.05)),
        slippage_pct=float(args.get("slippage_pct", 0.05)),
        risk_free_pct=float(args.get("risk_free_pct", 0.0)),
        periods_per_year=int(args.get("periods_per_year", 252)),
    ),
)

_register(
    "calculate_performance_panel",
    description=(
        "Standalone performance panel for any returns / equity curve / "
        "trade P&L list: Sharpe, Sortino, Calmar, max drawdown, win rate, "
        "profit factor, expectancy."
    ),
    input_schema={
        "type": "object",
        "required": ["returns"],
        "properties": {
            "returns": {"type": "array", "items": {"type": "number"}},
            "equity_curve": {"type": "array", "items": {"type": "number"}},
            "trade_pnls": {"type": "array", "items": {"type": "number"}},
            "risk_free_pct": {"type": "number", "default": 0.0},
            "periods_per_year": {"type": "integer", "default": 252},
        },
    },
    handler=lambda args: calculate_performance_panel(
        returns=args.get("returns") or [],
        equity_curve=args.get("equity_curve"),
        trade_pnls=args.get("trade_pnls"),
        risk_free_pct=float(args.get("risk_free_pct", 0.0)),
        periods_per_year=int(args.get("periods_per_year", 252)),
    ),
)

_register(
    "optimize_portfolio_markowitz",
    description=(
        "Markowitz portfolio optimization: min-variance, max-Sharpe "
        "(tangency), and 25-point efficient frontier. Pass "
        "{asset_name: closes_list}. Allows shorting (unconstrained closed "
        "form). For long-only, screen frontier rows where weights ≥ 0."
    ),
    input_schema={
        "type": "object",
        "required": ["series"],
        "properties": {
            "series": {"type": "object",
                        "description": "asset_name → closes list"},
            "target_return_pct": {"type": "number",
                                    "description": "Optional target annual return"},
            "risk_free_pct": {"type": "number", "default": 0.0},
            "periods_per_year": {"type": "integer", "default": 252},
        },
    },
    handler=lambda args: optimize_portfolio_markowitz(
        series=args.get("series") or {},
        target_return_pct=args.get("target_return_pct"),
        risk_free_pct=float(args.get("risk_free_pct", 0.0)),
        periods_per_year=int(args.get("periods_per_year", 252)),
    ),
)

_register(
    "calculate_kelly_sizing",
    description=(
        "Kelly criterion position sizing — bet Kelly (win_prob + win/loss "
        "ratio) and/or continuous Kelly (annualised return + vol). Returns "
        "fractional Kelly variants (25%, 50%, 100%)."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "win_probability": {"type": "number"},
            "win_loss_ratio": {"type": "number"},
            "annualised_return_pct": {"type": "number"},
            "annualised_volatility_pct": {"type": "number"},
            "risk_free_pct": {"type": "number", "default": 0.0},
            "kelly_fractions": {"type": "array", "items": {"type": "number"}},
        },
    },
    handler=lambda args: calculate_kelly_sizing(
        win_probability=args.get("win_probability"),
        win_loss_ratio=args.get("win_loss_ratio"),
        annualised_return_pct=args.get("annualised_return_pct"),
        annualised_volatility_pct=args.get("annualised_volatility_pct"),
        risk_free_pct=float(args.get("risk_free_pct", 0.0)),
        kelly_fractions=args.get("kelly_fractions"),
    ),
)

_register(
    "calculate_atr_position_size",
    description=(
        "Volatility-based position sizing using ATR-based stop loss. Sizes "
        "the trade so a stop-out at atr_multiple_stop ATRs loses exactly "
        "risk_per_trade_pct% of equity. Canonical 1% rule for trend-following."
    ),
    input_schema={
        "type": "object",
        "required": ["equity", "entry_price", "atr"],
        "properties": {
            "equity": {"type": "number"},
            "entry_price": {"type": "number"},
            "atr": {"type": "number"},
            "atr_multiple_stop": {"type": "number", "default": 2.0},
            "risk_per_trade_pct": {"type": "number", "default": 1.0},
        },
    },
    handler=lambda args: calculate_atr_position_size(
        equity=float(args["equity"]),
        entry_price=float(args["entry_price"]),
        atr=float(args["atr"]),
        atr_multiple_stop=float(args.get("atr_multiple_stop", 2.0)),
        risk_per_trade_pct=float(args.get("risk_per_trade_pct", 1.0)),
    ),
)

# --- Price action + position design (v0.9) --------------------------------

_register(
    "analyze_price_action",
    description=(
        "Universal price action analysis on any OHLCV series: fractal swing "
        "highs/lows, market structure (bullish/bearish/ranging), FVG/IFVG "
        "imbalances, range box (discount/premium), support and "
        "resistance clusters, directional bias, and suggested long/short "
        "setups with entry/stop/targets. Feed bars from TradingView "
        "data_get_ohlcv, get_crypto_klines, or get_bist_eod_ohlcv."
    ),
    input_schema={
        "type": "object",
        "required": ["closes", "highs", "lows"],
        "properties": {
            "closes": {"type": "array", "items": {"type": "number"}},
            "highs": {"type": "array", "items": {"type": "number"}},
            "lows": {"type": "array", "items": {"type": "number"}},
            "swing_lookback": {"type": "integer", "default": 5},
            "sr_tolerance_pct": {"type": "number", "default": 0.003},
        },
    },
    handler=lambda args: analyze_price_action(
        closes=args.get("closes") or [],
        highs=args.get("highs") or [],
        lows=args.get("lows") or [],
        swing_lookback=int(args.get("swing_lookback", 5)),
        sr_tolerance_pct=float(args.get("sr_tolerance_pct", 0.003)),
    ),
)

_register(
    "analyze_range_imbalance",
    description=(
        "Range-trade specialist: horizontal box (discount/premium/EQ), "
        "liquidity sweeps, FVG/IFVG stacks, range-aligned imbalances, and "
        "fade/breakout play recommendation. Use when market is ranging or "
        "for mean-reversion planning on BIST/VIOP/crypto OHLCV."
    ),
    input_schema={
        "type": "object",
        "required": ["closes", "highs", "lows"],
        "properties": {
            "closes": {"type": "array", "items": {"type": "number"}},
            "highs": {"type": "array", "items": {"type": "number"}},
            "lows": {"type": "array", "items": {"type": "number"}},
            "volumes": {"type": "array", "items": {"type": "number"}},
            "swing_lookback": {"type": "integer", "default": 5},
            "range_window": {"type": "integer", "default": 48},
            "market": {"type": "string"},
            "symbol": {"type": "string"},
        },
    },
    handler=lambda args: analyze_range_imbalance(
        closes=args.get("closes") or [],
        highs=args.get("highs") or [],
        lows=args.get("lows") or [],
        volumes=args.get("volumes"),
        swing_lookback=int(args.get("swing_lookback", 5)),
        range_window=int(args.get("range_window", 48)),
        market=args.get("market"),
        symbol=args.get("symbol"),
    ),
)

_register(
    "get_market_profile",
    description=(
        "Detect BIST / VIOP / crypto and return tuned PA, Elliott, timeframe, "
        "risk, and TradingView symbol (symbol_tv)."
    ),
    input_schema={
        "type": "object",
        "required": ["symbol"],
        "properties": {
            "symbol": {"type": "string"},
            "market": {
                "type": "string",
                "description": "Override: crypto, bist, bist_index, viop, viop_option",
            },
        },
    },
    handler=lambda args: get_market_profile(
        str(args["symbol"]),
        market=args.get("market"),
    ),
)

_register(
    "analyze_elliott_wave",
    description=(
        "Elliott Wave on one timeframe: zigzag pivots, impulse/ABC hypotheses, "
        "rule_checklist, fib grades, wave traits, channel, projections, report_tr."
    ),
    input_schema={
        "type": "object",
        "required": ["closes", "highs", "lows"],
        "properties": {
            "closes": {"type": "array", "items": {"type": "number"}},
            "highs": {"type": "array", "items": {"type": "number"}},
            "lows": {"type": "array", "items": {"type": "number"}},
            "times": {"type": "array", "items": {"type": "integer"}},
            "swing_lookback": {"type": "integer", "default": 5},
        },
    },
    handler=lambda args: analyze_elliott_wave(
        closes=args.get("closes") or [],
        highs=args.get("highs") or [],
        lows=args.get("lows") or [],
        times=args.get("times"),
        swing_lookback=int(args.get("swing_lookback", 5)),
    ),
)

_register(
    "analyze_chart_scenarios",
    description=(
        "Merge PA MTF + HTF Elliott: ranked scenarios (continuation, ABC, "
        "alternate count, conflict). Returns report + trade_candidate flag."
    ),
    input_schema={
        "type": "object",
        "required": ["symbol", "htf_closes", "htf_highs", "htf_lows", "ltf_closes", "ltf_highs", "ltf_lows"],
        "properties": {
            "symbol": {"type": "string"},
            "htf_closes": {"type": "array", "items": {"type": "number"}},
            "htf_highs": {"type": "array", "items": {"type": "number"}},
            "htf_lows": {"type": "array", "items": {"type": "number"}},
            "ltf_closes": {"type": "array", "items": {"type": "number"}},
            "ltf_highs": {"type": "array", "items": {"type": "number"}},
            "ltf_lows": {"type": "array", "items": {"type": "number"}},
            "htf_times": {"type": "array", "items": {"type": "integer"}},
            "htf_label": {"type": "string", "default": "240"},
            "ltf_label": {"type": "string", "default": "60"},
            "min_ew_score": {"type": "number"},
            "market": {"type": "string"},
        },
    },
    handler=lambda args: analyze_chart_scenarios(
        symbol=str(args["symbol"]),
        htf_closes=args.get("htf_closes") or [],
        htf_highs=args.get("htf_highs") or [],
        htf_lows=args.get("htf_lows") or [],
        ltf_closes=args.get("ltf_closes") or [],
        ltf_highs=args.get("ltf_highs") or [],
        ltf_lows=args.get("ltf_lows") or [],
        htf_times=args.get("htf_times"),
        ltf_times=args.get("ltf_times"),
        htf_label=str(args.get("htf_label", "240")),
        ltf_label=str(args.get("ltf_label", "60")),
        min_ew_score=args.get("min_ew_score"),
        market=args.get("market"),
    ),
)

_register(
    "analyze_market_context",
    description=(
        "Unified fundamental + technical analysis: PA MTF, range/FVG, "
        "HTF/LTF Elliott alignment, confidence gates, and KAP/BIST/VIOP/crypto "
        "research checklist. Set fetch_fundamentals=true to also pull LIVE "
        "fundamentals (F/K, ROE, KAP tone, funding, sector) + run the fusion "
        "gate offline (no TradingView needed)."
    ),
    input_schema={
        "type": "object",
        "required": ["symbol", "htf_closes", "htf_highs", "htf_lows", "ltf_closes", "ltf_highs", "ltf_lows"],
        "properties": {
            "symbol": {"type": "string"},
            "htf_closes": {"type": "array", "items": {"type": "number"}},
            "htf_highs": {"type": "array", "items": {"type": "number"}},
            "htf_lows": {"type": "array", "items": {"type": "number"}},
            "ltf_closes": {"type": "array", "items": {"type": "number"}},
            "ltf_highs": {"type": "array", "items": {"type": "number"}},
            "ltf_lows": {"type": "array", "items": {"type": "number"}},
            "htf_times": {"type": "array", "items": {"type": "integer"}},
            "ltf_times": {"type": "array", "items": {"type": "integer"}},
            "htf_volumes": {"type": "array", "items": {"type": "number"}},
            "ltf_volumes": {"type": "array", "items": {"type": "number"}},
            "htf_label": {"type": "string", "default": "240"},
            "ltf_label": {"type": "string", "default": "60"},
            "market": {"type": "string"},
            "min_ew_score": {"type": "number"},
            "fetch_fundamentals": {"type": "boolean", "default": False},
        },
    },
    handler=lambda args: analyze_market_context(
        symbol=str(args["symbol"]),
        htf_closes=args.get("htf_closes") or [],
        htf_highs=args.get("htf_highs") or [],
        htf_lows=args.get("htf_lows") or [],
        ltf_closes=args.get("ltf_closes") or [],
        ltf_highs=args.get("ltf_highs") or [],
        ltf_lows=args.get("ltf_lows") or [],
        htf_times=args.get("htf_times"),
        ltf_times=args.get("ltf_times"),
        htf_volumes=args.get("htf_volumes"),
        ltf_volumes=args.get("ltf_volumes"),
        htf_label=str(args.get("htf_label", "240")),
        ltf_label=str(args.get("ltf_label", "60")),
        market=args.get("market"),
        min_ew_score=args.get("min_ew_score"),
        fetch_fundamentals=bool(args.get("fetch_fundamentals", False)),
    ),
)

_register(
    "design_trade_setup",
    description=(
        "Design a complete trade plan with explicit entry/stop/targets: "
        "position sizing (% equity risk), R:R validation (default min 1:2), "
        "and approved/reject gate. Works for any market symbol."
    ),
    input_schema={
        "type": "object",
        "required": ["symbol", "direction", "entry_price", "stop_price", "target_prices"],
        "properties": {
            "symbol": {"type": "string"},
            "direction": {"type": "string", "enum": ["long", "short"]},
            "entry_price": {"type": "number"},
            "stop_price": {"type": "number"},
            "target_prices": {"type": "array", "items": {"type": "number"}},
            "equity": {"type": "number", "default": 100000},
            "risk_per_trade_pct": {"type": "number", "default": 1.0},
            "min_risk_reward": {"type": "number", "default": 2.0},
            "closes": {"type": "array", "items": {"type": "number"}},
            "highs": {"type": "array", "items": {"type": "number"}},
            "lows": {"type": "array", "items": {"type": "number"}},
        },
    },
    handler=lambda args: design_trade_setup(
        symbol=str(args["symbol"]),
        direction=str(args["direction"]),
        entry_price=float(args["entry_price"]),
        stop_price=float(args["stop_price"]),
        target_prices=args.get("target_prices") or [],
        equity=float(args.get("equity", 100_000)),
        risk_per_trade_pct=float(args.get("risk_per_trade_pct", 1.0)),
        min_risk_reward=float(args.get("min_risk_reward", 2.0)),
        closes=args.get("closes"),
        highs=args.get("highs"),
        lows=args.get("lows"),
    ),
)

_register(
    "design_from_price_action",
    description=(
        "One-shot PA workflow: analyze OHLCV structure, auto-pick long or "
        "short setup (or pass direction), size the trade, and validate R:R. "
        "Primary tool for AI-driven price action position design."
    ),
    input_schema={
        "type": "object",
        "required": ["symbol", "closes", "highs", "lows"],
        "properties": {
            "symbol": {"type": "string"},
            "closes": {"type": "array", "items": {"type": "number"}},
            "highs": {"type": "array", "items": {"type": "number"}},
            "lows": {"type": "array", "items": {"type": "number"}},
            "direction": {"type": "string", "enum": ["long", "short"]},
            "equity": {"type": "number", "default": 100000},
            "risk_per_trade_pct": {"type": "number", "default": 1.0},
            "min_risk_reward": {"type": "number", "default": 2.0},
        },
    },
    handler=lambda args: design_from_price_action(
        symbol=str(args["symbol"]),
        closes=args.get("closes") or [],
        highs=args.get("highs") or [],
        lows=args.get("lows") or [],
        direction=args.get("direction"),
        equity=float(args.get("equity", 100_000)),
        risk_per_trade_pct=float(args.get("risk_per_trade_pct", 1.0)),
        min_risk_reward=float(args.get("min_risk_reward", 2.0)),
    ),
)

_register(
    "portfolio_risk_check",
    description=(
        "Portfolio risk gate before opening a new trade: max open positions "
        "(5), total open risk (5% equity), single-asset notional cap (20%), "
        "optional daily loss limit. Pass open_positions list and optional "
        "proposed_trade from design_trade_setup."
    ),
    input_schema={
        "type": "object",
        "required": ["equity"],
        "properties": {
            "equity": {"type": "number"},
            "open_positions": {"type": "array", "items": {"type": "object"}},
            "proposed_trade": {"type": "object"},
            "rules": {"type": "object"},
        },
    },
    handler=lambda args: portfolio_risk_check(
        equity=float(args["equity"]),
        open_positions=args.get("open_positions"),
        proposed_trade=args.get("proposed_trade"),
        rules=args.get("rules"),
    ),
)

_register(
    "pine_payload_from_trade_plan",
    description=(
        "Convert a design_trade_setup / design_from_price_action output into "
        "placeholders for render_pine_recipe('pa_trade_overlay')."
    ),
    input_schema={
        "type": "object",
        "required": ["plan"],
        "properties": {
            "plan": {"type": "object"},
            "as_of_date": {"type": "string", "description": "YYYY-MM-DD"},
        },
    },
    handler=lambda args: pine_payload_from_trade_plan(
        plan=args.get("plan") or {},
        as_of_date=args.get("as_of_date"),
    ),
)

_register(
    "analyze_mtf_price_action",
    description=(
        "Multi-timeframe PA: HTF structure/bias + LTF setup alignment. "
        "Returns trade_quality (a_plus/a/b/conflict) and recommended_setup. "
        "Fetch HTF bars (e.g. 4H/D) and LTF bars (e.g. 15m/1H) via TradingView "
        "or get_crypto_klines."
    ),
    input_schema={
        "type": "object",
        "required": [
            "htf_closes", "htf_highs", "htf_lows",
            "ltf_closes", "ltf_highs", "ltf_lows",
        ],
        "properties": {
            "htf_closes": {"type": "array", "items": {"type": "number"}},
            "htf_highs": {"type": "array", "items": {"type": "number"}},
            "htf_lows": {"type": "array", "items": {"type": "number"}},
            "ltf_closes": {"type": "array", "items": {"type": "number"}},
            "ltf_highs": {"type": "array", "items": {"type": "number"}},
            "ltf_lows": {"type": "array", "items": {"type": "number"}},
            "htf_label": {"type": "string", "default": "HTF"},
            "ltf_label": {"type": "string", "default": "LTF"},
        },
    },
    handler=lambda args: analyze_mtf_price_action(
        htf_closes=args.get("htf_closes") or [],
        htf_highs=args.get("htf_highs") or [],
        htf_lows=args.get("htf_lows") or [],
        ltf_closes=args.get("ltf_closes") or [],
        ltf_highs=args.get("ltf_highs") or [],
        ltf_lows=args.get("ltf_lows") or [],
        htf_label=str(args.get("htf_label", "HTF")),
        ltf_label=str(args.get("ltf_label", "LTF")),
    ),
)

_register(
    "scan_price_action_watchlist",
    description=(
        "Scan multiple symbols for PA setups. Pass pre-fetched OHLCV per "
        "symbol; returns ranked top_setups by score (R:R + structure + bias)."
    ),
    input_schema={
        "type": "object",
        "required": ["series"],
        "properties": {
            "series": {"type": "object", "description": "{symbol: {closes, highs, lows}}"},
            "directions": {"type": "array", "items": {"type": "string", "enum": ["long", "short"]}},
            "equity": {"type": "number", "default": 100000},
            "min_risk_reward": {"type": "number", "default": 2.0},
            "min_score": {"type": "number", "default": 0.0},
        },
    },
    handler=lambda args: scan_price_action_watchlist(
        series=args.get("series") or {},
        directions=args.get("directions"),
        equity=float(args.get("equity", 100_000)),
        min_risk_reward=float(args.get("min_risk_reward", 2.0)),
        min_score=float(args.get("min_score", 0.0)),
    ),
)

_register(
    "scan_mtf_watchlist",
    description=(
        "MTF watchlist scan: each symbol needs htf + ltf OHLCV blocks. "
        "Filters by trade_quality (default min 'a')."
    ),
    input_schema={
        "type": "object",
        "required": ["series"],
        "properties": {
            "series": {
                "type": "object",
                "description": "{symbol: {htf: {closes,highs,lows}, ltf: {...}}}",
            },
            "equity": {"type": "number", "default": 100000},
            "min_risk_reward": {"type": "number", "default": 2.0},
            "min_quality": {"type": "string", "default": "a"},
        },
    },
    handler=lambda args: scan_mtf_watchlist(
        series=args.get("series") or {},
        equity=float(args.get("equity", 100_000)),
        min_risk_reward=float(args.get("min_risk_reward", 2.0)),
        min_quality=str(args.get("min_quality", "a")),
    ),
)

_register(
    "log_trade_plan",
    description="Persist an approved trade plan to local journal (~/.bist-trader/trade_journal.json).",
    input_schema={
        "type": "object",
        "required": ["plan"],
        "properties": {
            "plan": {"type": "object"},
            "status": {"type": "string", "enum": ["planned", "open", "closed", "cancelled"], "default": "planned"},
            "notes": {"type": "string"},
            "journal_path": {"type": "string"},
        },
    },
    handler=lambda args: log_trade_plan(
        plan=args.get("plan") or {},
        status=str(args.get("status", "planned")),
        notes=args.get("notes"),
        journal_path=args.get("journal_path"),
    ),
)

_register(
    "list_trade_journal",
    description="List trade journal entries; filter by status or symbol.",
    input_schema={
        "type": "object",
        "properties": {
            "status": {"type": "string", "enum": ["planned", "open", "closed", "cancelled"]},
            "symbol": {"type": "string"},
            "limit": {"type": "integer", "default": 50},
            "journal_path": {"type": "string"},
        },
    },
    handler=lambda args: list_trade_journal(
        status=args.get("status"),
        symbol=args.get("symbol"),
        limit=int(args.get("limit", 50)),
        journal_path=args.get("journal_path"),
    ),
)

_register(
    "update_trade_status",
    description="Update journal trade status, optional exit price and PnL.",
    input_schema={
        "type": "object",
        "required": ["trade_id", "status"],
        "properties": {
            "trade_id": {"type": "string"},
            "status": {"type": "string", "enum": ["planned", "open", "closed", "cancelled"]},
            "exit_price": {"type": "number"},
            "pnl": {"type": "number"},
            "notes": {"type": "string"},
            "journal_path": {"type": "string"},
        },
    },
    handler=lambda args: update_trade_status(
        trade_id=str(args["trade_id"]),
        status=str(args["status"]),
        exit_price=args.get("exit_price"),
        pnl=args.get("pnl"),
        notes=args.get("notes"),
        journal_path=args.get("journal_path"),
    ),
)

_register(
    "monitor_open_trades",
    description=(
        "Monitor open journal trades against mark_prices dict "
        "(symbol -> latest price). Alerts on stop hit / TP2 zone."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "mark_prices": {"type": "object", "additionalProperties": {"type": "number"}},
            "journal_path": {"type": "string"},
        },
    },
    handler=lambda args: monitor_open_trades(
        mark_prices=args.get("mark_prices"),
        journal_path=args.get("journal_path"),
    ),
)

_register(
    "apply_trade_to_chart",
    description=(
        "One-shot chart apply: set symbol/TF, draw TradingView Long/Short "
        "position tool (Forecasting menu) with entry/stop/TP box. "
        "Requires TradingView Desktop CDP on port 9222 + tradingview-mcp CLI."
    ),
    input_schema={
        "type": "object",
        "required": ["plan"],
        "properties": {
            "plan": {"type": "object", "description": "Output from design_mtf_trade_plan or design_ltf_trade_plan"},
            "symbol": {"type": "string"},
            "timeframe": {"type": "string"},
            "clear_drawings": {"type": "boolean", "default": True},
            "inject_pine": {"type": "boolean", "default": False},
            "draw_levels": {"type": "boolean", "default": True},
        },
    },
    handler=lambda args: apply_trade_to_chart(
        plan=args.get("plan") or {},
        symbol=args.get("symbol"),
        timeframe=args.get("timeframe"),
        clear_drawings=bool(args.get("clear_drawings", True)),
        inject_pine=bool(args.get("inject_pine", False)),
        draw_levels=bool(args.get("draw_levels", True)),
    ),
)

_register(
    "get_trade_playbook_rules",
    description=(
        "Canonical trade consistency rules + workflow. AI must read this before "
        "every trade decision — same checklist, same gates, every time."
    ),
    input_schema={"type": "object", "properties": {}},
    handler=lambda args: get_trade_playbook_rules(),
)

_register(
    "design_mtf_trade_plan",
    description=(
        "PRIMARY trade tool: HTF+LTF OHLCV → MTF alignment → detailed plan "
        "(thesis, execution, partial TPs, management) → consistency validation "
        "→ portfolio gate. Returns approved/no_trade + trade_report."
    ),
    input_schema={
        "type": "object",
        "required": [
            "symbol",
            "htf_closes", "htf_highs", "htf_lows",
            "ltf_closes", "ltf_highs", "ltf_lows",
        ],
        "properties": {
            "symbol": {"type": "string"},
            "htf_closes": {"type": "array", "items": {"type": "number"}},
            "htf_highs": {"type": "array", "items": {"type": "number"}},
            "htf_lows": {"type": "array", "items": {"type": "number"}},
            "ltf_closes": {"type": "array", "items": {"type": "number"}},
            "ltf_highs": {"type": "array", "items": {"type": "number"}},
            "ltf_lows": {"type": "array", "items": {"type": "number"}},
            "htf_label": {"type": "string", "default": "HTF"},
            "ltf_label": {"type": "string", "default": "LTF"},
            "equity": {"type": "number", "default": 100000},
            "risk_per_trade_pct": {"type": "number", "default": 1.0},
            "min_risk_reward": {"type": "number", "default": 2.0},
            "open_positions": {"type": "array", "items": {"type": "object"}},
            "rules": {"type": "object"},
            "journal_path": {"type": "string"},
        },
    },
    handler=lambda args: design_mtf_trade_plan(
        symbol=str(args["symbol"]),
        htf_closes=args.get("htf_closes") or [],
        htf_highs=args.get("htf_highs") or [],
        htf_lows=args.get("htf_lows") or [],
        ltf_closes=args.get("ltf_closes") or [],
        ltf_highs=args.get("ltf_highs") or [],
        ltf_lows=args.get("ltf_lows") or [],
        htf_label=str(args.get("htf_label", "HTF")),
        ltf_label=str(args.get("ltf_label", "LTF")),
        equity=float(args.get("equity", 100_000)),
        risk_per_trade_pct=float(args.get("risk_per_trade_pct", 1.0)),
        min_risk_reward=float(args.get("min_risk_reward", 2.0)),
        open_positions=args.get("open_positions"),
        rules=args.get("rules"),
        journal_path=args.get("journal_path"),
    ),
)

_register(
    "design_ltf_trade_plan",
    description=(
        "Single-TF trade plan with same enrich + validate + portfolio pipeline "
        "as design_mtf_trade_plan. Use when only one timeframe is available."
    ),
    input_schema={
        "type": "object",
        "required": ["symbol", "closes", "highs", "lows"],
        "properties": {
            "symbol": {"type": "string"},
            "closes": {"type": "array", "items": {"type": "number"}},
            "highs": {"type": "array", "items": {"type": "number"}},
            "lows": {"type": "array", "items": {"type": "number"}},
            "direction": {"type": "string", "enum": ["long", "short"]},
            "equity": {"type": "number", "default": 100000},
            "risk_per_trade_pct": {"type": "number", "default": 1.0},
            "min_risk_reward": {"type": "number", "default": 2.0},
            "open_positions": {"type": "array", "items": {"type": "object"}},
            "rules": {"type": "object"},
            "journal_path": {"type": "string"},
        },
    },
    handler=lambda args: design_ltf_trade_plan(
        symbol=str(args["symbol"]),
        closes=args.get("closes") or [],
        highs=args.get("highs") or [],
        lows=args.get("lows") or [],
        direction=args.get("direction"),
        equity=float(args.get("equity", 100_000)),
        risk_per_trade_pct=float(args.get("risk_per_trade_pct", 1.0)),
        min_risk_reward=float(args.get("min_risk_reward", 2.0)),
        open_positions=args.get("open_positions"),
        rules=args.get("rules"),
        journal_path=args.get("journal_path"),
    ),
)

_register(
    "validate_trade_consistency",
    description=(
        "Run playbook checklist on a plan: MTF quality, structure, R:R, "
        "stop/ATR sanity, journal conflicts. Same rules every trade."
    ),
    input_schema={
        "type": "object",
        "required": ["plan"],
        "properties": {
            "plan": {"type": "object"},
            "mtf": {"type": "object"},
            "open_trades": {"type": "array", "items": {"type": "object"}},
            "journal_path": {"type": "string"},
            "rules": {"type": "object"},
        },
    },
    handler=lambda args: validate_trade_consistency(
        plan=args.get("plan") or {},
        mtf=args.get("mtf"),
        open_trades=args.get("open_trades"),
        journal_path=args.get("journal_path"),
        rules=args.get("rules"),
    ),
)

_register(
    "run_trade_assistant",
    description=(
        "ALL-IN-ONE trade assistant (single MCP): TV health → MTF OHLCV → "
        "design_mtf_trade_plan → draw Long/Short position → optional journal/alerts. "
        "Requires TradingView CDP on :9222."
    ),
    input_schema={
        "type": "object",
        "required": ["symbol", "ltf_timeframe"],
        "properties": {
            "symbol": {"type": "string"},
            "ltf_timeframe": {"type": "string"},
            "htf_timeframe": {"type": "string", "default": "240"},
            "equity": {"type": "number", "default": 100000},
            "risk_per_trade_pct": {"type": "number", "default": 1.0},
            "min_risk_reward": {"type": "number", "default": 2.0},
            "open_positions": {"type": "array", "items": {"type": "object"}},
            "rules": {"type": "object"},
            "journal_path": {"type": "string"},
            "draw_on_chart": {"type": "boolean", "default": True},
            "log_journal": {"type": "boolean", "default": True},
            "set_alerts": {"type": "boolean", "default": False},
        },
    },
    handler=lambda args: run_trade_assistant(
        symbol=str(args["symbol"]),
        ltf_timeframe=args.get("ltf_timeframe"),
        htf_timeframe=args.get("htf_timeframe"),
        market=args.get("market"),
        equity=float(args.get("equity", 100_000)),
        risk_per_trade_pct=args.get("risk_per_trade_pct"),
        min_risk_reward=args.get("min_risk_reward"),
        open_positions=args.get("open_positions"),
        rules=args.get("rules"),
        journal_path=args.get("journal_path"),
        draw_on_chart=bool(args.get("draw_on_chart", True)),
        log_journal=bool(args.get("log_journal", True)),
        set_alerts=bool(args.get("set_alerts", False)),
    ),
)

_register(
    "design_scenario_trade_plan",
    description=(
        "Like design_mtf_trade_plan but gated by analyze_chart_scenarios "
        "(PA + Elliott alignment required)."
    ),
    input_schema={
        "type": "object",
        "required": ["symbol", "htf_closes", "htf_highs", "htf_lows", "ltf_closes", "ltf_highs", "ltf_lows"],
        "properties": {
            "symbol": {"type": "string"},
            "htf_closes": {"type": "array", "items": {"type": "number"}},
            "htf_highs": {"type": "array", "items": {"type": "number"}},
            "htf_lows": {"type": "array", "items": {"type": "number"}},
            "ltf_closes": {"type": "array", "items": {"type": "number"}},
            "ltf_highs": {"type": "array", "items": {"type": "number"}},
            "ltf_lows": {"type": "array", "items": {"type": "number"}},
            "htf_times": {"type": "array", "items": {"type": "integer"}},
            "htf_label": {"type": "string", "default": "240"},
            "ltf_label": {"type": "string", "default": "60"},
            "equity": {"type": "number", "default": 100000},
            "risk_per_trade_pct": {"type": "number", "default": 1.0},
            "min_risk_reward": {"type": "number", "default": 2.0},
            "min_ew_score": {"type": "number", "default": 35},
            "open_positions": {"type": "array", "items": {"type": "object"}},
            "rules": {"type": "object"},
            "journal_path": {"type": "string"},
        },
    },
    handler=lambda args: design_scenario_trade_plan(
        symbol=str(args["symbol"]),
        htf_closes=args.get("htf_closes") or [],
        htf_highs=args.get("htf_highs") or [],
        htf_lows=args.get("htf_lows") or [],
        ltf_closes=args.get("ltf_closes") or [],
        ltf_highs=args.get("ltf_highs") or [],
        ltf_lows=args.get("ltf_lows") or [],
        htf_times=args.get("htf_times"),
        htf_label=str(args.get("htf_label", "240")),
        ltf_label=str(args.get("ltf_label", "60")),
        equity=float(args.get("equity", 100_000)),
        risk_per_trade_pct=float(args.get("risk_per_trade_pct", 1.0)),
        min_risk_reward=float(args.get("min_risk_reward", 2.0)),
        min_ew_score=float(args.get("min_ew_score", 35)),
        open_positions=args.get("open_positions"),
        rules=args.get("rules"),
        journal_path=args.get("journal_path"),
    ),
)

_register(
    "run_market_assistant",
    description=(
        "PRIMARY trade assistant: TradingView OHLCV → live fundamentals "
        "(KAP / funding / snapshot) + technical (PA, range, FVG, EW MTF) → "
        "trade plan → chat_report for LLM → chart overlay (PA, EW, position, "
        "fundamental banner). Requires TV CDP :9222."
    ),
    input_schema={
        "type": "object",
        "required": ["symbol"],
        "properties": {
            "symbol": {"type": "string"},
            "market": {"type": "string"},
            "ltf_timeframe": {"type": "string"},
            "htf_timeframe": {"type": "string"},
            "equity": {"type": "number", "default": 100000},
            "risk_per_trade_pct": {"type": "number"},
            "min_risk_reward": {"type": "number"},
            "min_ew_score": {"type": "number"},
            "open_positions": {"type": "array", "items": {"type": "object"}},
            "rules": {"type": "object"},
            "journal_path": {"type": "string"},
            "fetch_fundamentals": {"type": "boolean", "default": True},
            "draw_on_chart": {"type": "boolean", "default": True},
            "draw_when_no_trade": {"type": "boolean", "default": True},
            "log_journal": {"type": "boolean", "default": True},
        },
    },
    handler=lambda args: run_market_assistant(
        symbol=str(args["symbol"]),
        ltf_timeframe=args.get("ltf_timeframe"),
        htf_timeframe=args.get("htf_timeframe"),
        market=args.get("market"),
        equity=float(args.get("equity", 100_000)),
        risk_per_trade_pct=args.get("risk_per_trade_pct"),
        min_risk_reward=args.get("min_risk_reward"),
        min_ew_score=args.get("min_ew_score"),
        open_positions=args.get("open_positions"),
        rules=args.get("rules"),
        journal_path=args.get("journal_path"),
        fetch_fundamentals=bool(args.get("fetch_fundamentals", True)),
        draw_on_chart=bool(args.get("draw_on_chart", True)),
        draw_when_no_trade=bool(args.get("draw_when_no_trade", True)),
        log_journal=bool(args.get("log_journal", True)),
    ),
)

_register(
    "run_scenario_assistant",
    description=(
        "Alias of run_market_assistant (temel + teknik + TV). "
        "Use run_market_assistant for new integrations."
    ),
    input_schema={
        "type": "object",
        "required": ["symbol"],
        "properties": {
            "symbol": {"type": "string"},
            "market": {"type": "string"},
            "ltf_timeframe": {"type": "string"},
            "htf_timeframe": {"type": "string"},
            "equity": {"type": "number", "default": 100000},
            "risk_per_trade_pct": {"type": "number"},
            "min_risk_reward": {"type": "number"},
            "min_ew_score": {"type": "number"},
            "open_positions": {"type": "array", "items": {"type": "object"}},
            "rules": {"type": "object"},
            "journal_path": {"type": "string"},
            "draw_on_chart": {"type": "boolean", "default": True},
            "log_journal": {"type": "boolean", "default": True},
        },
    },
    handler=lambda args: run_scenario_assistant(
        symbol=str(args["symbol"]),
        ltf_timeframe=args.get("ltf_timeframe"),
        htf_timeframe=args.get("htf_timeframe"),
        market=args.get("market"),
        equity=float(args.get("equity", 100_000)),
        risk_per_trade_pct=args.get("risk_per_trade_pct"),
        min_risk_reward=args.get("min_risk_reward"),
        min_ew_score=args.get("min_ew_score"),
        open_positions=args.get("open_positions"),
        rules=args.get("rules"),
        journal_path=args.get("journal_path"),
        draw_on_chart=bool(args.get("draw_on_chart", True)),
        log_journal=bool(args.get("log_journal", True)),
    ),
)

_register(
    "apply_scenario_to_chart",
    description=(
        "Draw Elliott wave trend lines + point labels; optional position "
        "from plan. Pass primary_scenario from analyze_chart_scenarios."
    ),
    input_schema={
        "type": "object",
        "required": ["scenario"],
        "properties": {
            "scenario": {"type": "object"},
            "symbol": {"type": "string"},
            "timeframe": {"type": "string"},
            "htf_timeframe": {"type": "string"},
            "ltf_timeframe": {"type": "string"},
            "bar_times": {"type": "array", "items": {"type": "integer"}},
            "ltf_times": {"type": "array", "items": {"type": "integer"}},
            "ltf_closes": {"type": "array", "items": {"type": "number"}},
            "ltf_highs": {"type": "array", "items": {"type": "number"}},
            "mtf": {"type": "object", "description": "MTF PA pack (ltf_analysis, htf_structure, trade_quality)"},
            "plan": {"type": "object"},
            "clear_drawings": {"type": "boolean", "default": True},
            "draw_pa": {"type": "boolean", "default": True},
            "draw_position": {"type": "boolean", "default": True},
        },
    },
    handler=lambda args: apply_scenario_to_chart(
        scenario=args.get("scenario") or {},
        symbol=args.get("symbol"),
        timeframe=args.get("timeframe"),
        htf_timeframe=args.get("htf_timeframe"),
        ltf_timeframe=args.get("ltf_timeframe"),
        bar_times=args.get("bar_times"),
        ltf_times=args.get("ltf_times"),
        ltf_closes=args.get("ltf_closes"),
        ltf_highs=args.get("ltf_highs"),
        mtf=args.get("mtf"),
        plan=args.get("plan"),
        clear_drawings=bool(args.get("clear_drawings", True)),
        draw_pa=bool(args.get("draw_pa", True)),
        draw_position=bool(args.get("draw_position", True)),
    ),
)

_register(
    "tv_health_check",
    description="TradingView CDP connection (built-in — no separate tradingview MCP).",
    input_schema={"type": "object", "properties": {}},
    handler=lambda args: tv_health_check(),
)

_register(
    "tv_fetch_mtf_ohlcv",
    description="Fetch LTF + HTF OHLCV from TradingView chart via CDP.",
    input_schema={
        "type": "object",
        "required": ["symbol", "ltf_timeframe", "htf_timeframe"],
        "properties": {
            "symbol": {"type": "string"},
            "ltf_timeframe": {"type": "string"},
            "htf_timeframe": {"type": "string"},
            "bars": {"type": "integer", "default": 200},
        },
    },
    handler=lambda args: tv_fetch_mtf_ohlcv(
        symbol=str(args["symbol"]),
        ltf_timeframe=str(args["ltf_timeframe"]),
        htf_timeframe=str(args["htf_timeframe"]),
        bars=int(args.get("bars", 200)),
    ),
)

_register(
    "tv_chart_set_symbol",
    description="Set TradingView chart symbol (CDP).",
    input_schema={
        "type": "object",
        "required": ["symbol"],
        "properties": {"symbol": {"type": "string"}},
    },
    handler=lambda args: tv_chart_set_symbol(str(args["symbol"])),
)

_register(
    "tv_chart_set_timeframe",
    description="Set TradingView chart timeframe (CDP).",
    input_schema={
        "type": "object",
        "required": ["timeframe"],
        "properties": {"timeframe": {"type": "string"}},
    },
    handler=lambda args: tv_chart_set_timeframe(str(args["timeframe"])),
)

_register(
    "tv_data_get_ohlcv",
    description="Get OHLCV from current TradingView chart.",
    input_schema={
        "type": "object",
        "properties": {
            "count": {"type": "integer", "default": 200},
            "summary": {"type": "boolean", "default": False},
        },
    },
    handler=lambda args: tv_data_get_ohlcv(
        count=int(args.get("count", 200)),
        summary=bool(args.get("summary", False)),
    ),
)


# --- Volatility forecasting (v0.7) ---------------------------------------

_register(
    "calculate_ewma_volatility",
    description=(
        "EWMA (RiskMetrics) volatility forecast. Pass log returns. Decay "
        "0.94 (daily) by default; 0.97 for higher persistence. Crypto: "
        "annualise_days=365."
    ),
    input_schema={
        "type": "object",
        "required": ["returns"],
        "properties": {
            "returns": {"type": "array", "items": {"type": "number"}},
            "decay": {"type": "number", "default": 0.94},
            "annualise_days": {"type": "integer", "default": 252},
        },
    },
    handler=lambda args: calculate_ewma_volatility(
        returns=args.get("returns") or [],
        decay=float(args.get("decay", 0.94)),
        annualise_days=int(args.get("annualise_days", 252)),
    ),
)

_register(
    "calculate_garch_forecast",
    description=(
        "Fit GARCH(1,1) (coarse grid MLE) and forecast vol path. Returns "
        "(ω,α,β), stationary long-run vol, 1-step forecast, and the full "
        "horizon path in annualised %."
    ),
    input_schema={
        "type": "object",
        "required": ["returns"],
        "properties": {
            "returns": {"type": "array", "items": {"type": "number"}},
            "horizon_days": {"type": "integer", "default": 20},
            "annualise_days": {"type": "integer", "default": 252},
        },
    },
    handler=lambda args: calculate_garch_forecast(
        returns=args.get("returns") or [],
        horizon_days=int(args.get("horizon_days", 20)),
        annualise_days=int(args.get("annualise_days", 252)),
    ),
)


# --- BIST sector rotation (v0.7) -----------------------------------------

_register(
    "get_bist_sector_rotation",
    description=(
        "Rotation analytics across BIST sector indices (XBANK, XUSIN, "
        "XGIDA, XKAGT, XHOLD, ...). Returns ranked sectors, top-3 / "
        "bottom-3, and relative strength vs XU100."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "sectors": {"type": "array", "items": {"type": "string"}},
            "period": {"type": "string", "default": "3mo"},
            "lookback_bars": {"type": "integer", "default": 21},
            "include_benchmark": {"type": "boolean", "default": True},
        },
    },
    handler=lambda args: get_bist_sector_rotation(
        sectors=args.get("sectors"),
        period=str(args.get("period", "3mo")),
        lookback_bars=int(args.get("lookback_bars", 21)),
        include_benchmark=bool(args.get("include_benchmark", True)),
    ),
)


# --- On-chain (v0.7) -----------------------------------------------------

_register(
    "get_eth_gas_oracle",
    description=(
        "Etherscan gas oracle — current safe/propose/fast gas in Gwei + "
        "suggested base fee. High fast gas often coincides with NFT mints, "
        "airdrops, or risk-on flow."
    ),
    input_schema={"type": "object", "properties": {}},
    handler=lambda args: get_eth_gas_oracle(),
)

_register(
    "get_btc_network_stats",
    description=(
        "Bitcoin network stats: hashrate, difficulty, supply, mempool size."
    ),
    input_schema={"type": "object", "properties": {}},
    handler=lambda args: get_btc_network_stats(),
)


# --- Nelson-Siegel-Svensson yield curve (v0.7) ---------------------------

_register(
    "fit_yield_curve_nss",
    description=(
        "Fit Nelson-Siegel or NSS to a discrete yield curve and evaluate "
        "at any tenor. Used to derive non-observed tenors (e.g. 3.5Y from "
        "2Y/5Y) or smooth noisy DİBS auction yields."
    ),
    input_schema={
        "type": "object",
        "required": ["maturities_years", "yields_pct"],
        "properties": {
            "maturities_years": {"type": "array", "items": {"type": "number"}},
            "yields_pct": {"type": "array", "items": {"type": "number"}},
            "use_svensson": {"type": "boolean", "default": True},
            "output_tenors_years": {"type": "array", "items": {"type": "number"}},
        },
    },
    handler=lambda args: fit_yield_curve_nss(
        maturities_years=args.get("maturities_years") or [],
        yields_pct=args.get("yields_pct") or [],
        use_svensson=bool(args.get("use_svensson", True)),
        output_tenors_years=args.get("output_tenors_years"),
    ),
)


# --- Crypto Fear & Greed (v0.5) ------------------------------------------

_register(
    "get_crypto_fear_greed",
    description=(
        "Crypto Fear & Greed Index (alternative.me): 0-25 Extreme Fear → "
        "75-100 Extreme Greed. Composite of momentum, volume, social, "
        "dominance, Google Trends. Historically contrarian signal."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "limit": {"type": "integer", "default": 30,
                       "description": "Days of history (max 1000)."},
        },
    },
    handler=lambda args: get_crypto_fear_greed(
        limit=int(args.get("limit", 30)),
    ),
)


# --- Deribit BTC/ETH IV surface (v0.5) -----------------------------------

_register(
    "get_deribit_iv_surface",
    description=(
        "Live BTC/ETH option IV surface from Deribit. Returns the same "
        "shape as get_viop_iv_surface so the same screener / Pine recipes "
        "work for crypto. Spot is auto-fetched from Binance if not given."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "currency": {"type": "string", "enum": ["BTC", "ETH", "SOL"],
                          "default": "BTC"},
            "spot_price": {"type": "number",
                            "description": "Optional override; auto from Binance otherwise."},
        },
    },
    handler=lambda args: get_deribit_iv_surface(
        currency=str(args.get("currency", "BTC")),
        spot_price=args.get("spot_price"),
    ),
)


# --- Cross-asset correlation (v0.5) --------------------------------------

_register(
    "calculate_correlation_matrix",
    description=(
        "Pairwise correlation matrix of returns across multiple assets. "
        "Pass {asset_name: closes_list}. Returns full N×N matrix + ranked "
        "top-10 |ρ| pairs + bottom-10 (diversifying) pairs."
    ),
    input_schema={
        "type": "object",
        "required": ["series"],
        "properties": {
            "series": {
                "type": "object",
                "description": "Map of asset_name → closes list (same length).",
            },
            "method": {"type": "string", "enum": ["log", "simple"],
                        "default": "log"},
        },
    },
    handler=lambda args: calculate_correlation_matrix(
        series=args.get("series") or {},
        method=str(args.get("method", "log")),
    ),
)

_register(
    "calculate_rolling_correlation",
    description=(
        "Rolling correlation between two return series. Use to detect "
        "regime changes (e.g. BTC-SPX correlation flip during risk-off)."
    ),
    input_schema={
        "type": "object",
        "required": ["series_a", "series_b"],
        "properties": {
            "series_a": {"type": "array", "items": {"type": "number"}},
            "series_b": {"type": "array", "items": {"type": "number"}},
            "window": {"type": "integer", "default": 30},
            "method": {"type": "string", "enum": ["log", "simple"],
                        "default": "log"},
        },
    },
    handler=lambda args: calculate_rolling_correlation(
        series_a=args.get("series_a") or [],
        series_b=args.get("series_b") or [],
        window=int(args.get("window", 30)),
        method=str(args.get("method", "log")),
    ),
)


# --- Technical indicators (v0.4) -----------------------------------------

_register(
    "calculate_technicals",
    description=(
        "Standard indicator snapshot from any closes series: SMA 20/50/200, "
        "EMA 12/26, RSI(14), MACD(12/26/9), Bollinger(20,2), ATR(14) if "
        "highs+lows provided. Returns categorical labels (trend, RSI, BB) "
        "for fast LLM reasoning."
    ),
    input_schema={
        "type": "object",
        "required": ["closes"],
        "properties": {
            "closes": {"type": "array", "items": {"type": "number"}},
            "highs": {"type": "array", "items": {"type": "number"}},
            "lows":  {"type": "array", "items": {"type": "number"}},
        },
    },
    handler=lambda args: calculate_technicals(
        closes=args.get("closes") or [],
        highs=args.get("highs"),
        lows=args.get("lows"),
    ),
)


# --- Observability --------------------------------------------------------

_register(
    "get_health_status",
    description=(
        "Report freshness of cached data sources + Playwright availability. "
        "Use to diagnose stale/broken data sources before running a workflow."
    ),
    input_schema={"type": "object", "properties": {}},
    handler=lambda args: get_health_status(),
)


# --- Pine recipes ---------------------------------------------------------

_register(
    "list_pine_recipes",
    description=(
        "List Pine v6 recipe templates this MCP can render. Designed to be "
        "handed to tradesdontlie/tradingview-mcp `pine_new` + "
        "`pine_smart_compile` for execution inside TradingView Desktop."
    ),
    input_schema={"type": "object", "properties": {}},
    handler=lambda args: list_pine_recipes(),
)

_register(
    "render_pine_recipe",
    description=(
        "Render a Pine recipe with placeholders substituted. If "
        "`auto_fetch=true` and the recipe needs TCMB macro values, this "
        "tool will pull the latest policy rate, corridor, and CPI from "
        "EVDS automatically. The returned `pine_v6_source` is ready to "
        "paste into TradingView via tradesdontlie/tradingview-mcp."
    ),
    input_schema={
        "type": "object",
        "required": ["name"],
        "properties": {
            "name": {"type": "string", "description": "Recipe name, e.g. 'tr_macro_backdrop'"},
            "data": {
                "type": "object",
                "description": (
                    "Placeholder overrides (keys map to "
                    "{{TOKEN}}s in the template)."
                ),
            },
            "auto_fetch": {
                "type": "boolean",
                "default": False,
                "description": "If true, fill macro placeholders from EVDS automatically.",
            },
        },
    },
    handler=lambda args: render_pine_recipe(
        name=args["name"],
        data=args.get("data") or {},
        auto_fetch=bool(args.get("auto_fetch", False)),
    ),
)


# ---------------------------------------------------------------------------
# MCP protocol handlers
# ---------------------------------------------------------------------------

from mcp.types import Tool  # noqa: E402


@server.list_tools()
async def _list_tools() -> list[Tool]:
    return [
        Tool(
            name=name,
            description=info["description"],
            inputSchema=info["inputSchema"],
        )
        for name, info in TOOL_REGISTRY.items()
    ]


@server.call_tool()
async def _call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    arguments = arguments or {}
    try:
        entry = TOOL_REGISTRY.get(name)
        if entry is None:
            result = {"error": "unknown_tool", "detail": name}
        else:
            handler = entry["handler"]
            result = handler(arguments)
            # If handler returns a coroutine, await it
            if hasattr(result, "__await__"):
                result = await result
    except KeyError as e:
        result = {"error": "missing_argument", "detail": str(e)}
    except Exception as e:  # surface unexpected errors as structured payload
        result = {"error": "tool_failed", "detail": f"{type(e).__name__}: {e}"}

    return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, default=str))]


# ---------------------------------------------------------------------------
# MCP Resources — curated, read-only datasets that don't require a tool call.
# Useful for Claude to ground answers in stable reference data.
# ---------------------------------------------------------------------------

from mcp.types import (  # noqa: E402
    GetPromptResult,
    Prompt,
    PromptArgument,
    PromptMessage,
    Resource,
)
from pydantic import AnyUrl  # noqa: E402

RESOURCES = [
    {
        "uri": "bist-trader://catalog/evds-series",
        "name": "EVDS series catalog",
        "description": "Curated TCMB EVDS series codes used by this MCP "
                       "(policy rate, corridor, CPI, FX, DIBS yields).",
        "mimeType": "application/json",
    },
    {
        "uri": "bist-trader://catalog/pine-recipes",
        "name": "Pine recipe catalog",
        "description": "All Pine v6 recipes this MCP can render — names, "
                       "descriptions, required placeholders.",
        "mimeType": "application/json",
    },
    {
        "uri": "bist-trader://catalog/stress-scenarios",
        "name": "Stress scenarios catalog",
        "description": "Built-in stress scenarios for stress_test_portfolio.",
        "mimeType": "application/json",
    },
    {
        "uri": "bist-trader://snapshot/daily-report",
        "name": "Daily TR markets snapshot",
        "description": "Compact Markdown report: BIST indices + FX + commodities "
                       "+ TCMB policy + latest CPI. Refreshes on read.",
        "mimeType": "text/markdown",
    },
]


@server.list_resources()
async def _list_resources() -> list[Resource]:
    return [
        Resource(
            uri=AnyUrl(r["uri"]),
            name=r["name"],
            description=r["description"],
            mimeType=r["mimeType"],
        )
        for r in RESOURCES
    ]


@server.read_resource()
async def _read_resource(uri: AnyUrl) -> str:
    uri_s = str(uri)
    if uri_s == "bist-trader://catalog/evds-series":
        return json.dumps(list_catalog(), ensure_ascii=False, indent=2)
    if uri_s == "bist-trader://catalog/pine-recipes":
        return json.dumps(list_pine_recipes(), ensure_ascii=False, indent=2)
    if uri_s == "bist-trader://catalog/stress-scenarios":
        from .portfolio import BUILTIN_SCENARIOS
        return json.dumps(BUILTIN_SCENARIOS, ensure_ascii=False, indent=2)
    if uri_s == "bist-trader://snapshot/daily-report":
        return await _render_daily_report()
    raise ValueError(f"unknown resource: {uri_s}")


async def _render_daily_report() -> str:
    """Compact Markdown summary; called on every resource read."""
    try:
        summary = await get_market_summary()
    except Exception as e:
        summary = {"error": str(e)}
    lines = [
        "# TR Markets Daily Snapshot",
        "",
        f"_Source: {summary.get('source', 'n/a')}_",
        "",
    ]
    if "headline" in summary:
        lines.append(f"**{summary['headline']}**")
        lines.append("")
    cats = summary.get("categories", {})
    for cat_name in ("bist_indices", "fx", "commodities", "crypto"):
        block = cats.get(cat_name) or {}
        if not block:
            continue
        lines.append(f"## {cat_name.replace('_', ' ').title()}")
        for sym, vals in block.items():
            last = vals.get("last")
            chg = vals.get("change_pct")
            if last is None:
                continue
            sign = "+" if (chg or 0) >= 0 else ""
            lines.append(f"- **{sym}**: {last:,.4f}  ({sign}{chg:.2f}%)" if chg is not None
                         else f"- **{sym}**: {last:,.4f}")
        lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# MCP Prompts — pre-built analysis workflows the user can invoke from Claude.
# ---------------------------------------------------------------------------

PROMPTS_REGISTRY: dict[str, dict[str, Any]] = {
    "daily-tr-rates-report": {
        "description": (
            "Generate a daily TR rates report — policy rate path, repo curve, "
            "DİBS auction calendar, and upcoming TCMB / TÜİK events. The model "
            "calls get_tcmb_policy_rates, get_repo_curve, get_dibs_auctions and "
            "get_economic_calendar, then summarises in Turkish."
        ),
        "arguments": [
            PromptArgument(
                name="lookback_days",
                description="Repo curve history window (default 90).",
                required=False,
            ),
        ],
        "render": lambda args: (
            "TR rates için günlük rapor üret. Şu adımları takip et:\n"
            "1. get_tcmb_policy_rates(lookback_months=12) ile politika faizi"
            " ve koridoru çek.\n"
            f"2. get_repo_curve(lookback_days={int(args.get('lookback_days', 90))})"
            " ile TLREF + O/N repo + spread.\n"
            "3. get_dibs_auctions() ile yaklaşan Hazine ihalelerini listele.\n"
            "4. get_economic_calendar() ile PPK + TÜİK yayın tarihleri.\n"
            "5. Çıktıları Türkçe, kompakt, başlıklı bir rapor olarak özetle.\n"
            "6. İsteğe bağlı: render_pine_recipe('tr_macro_backdrop',"
            " auto_fetch=true) ile Pine sürümünü üret."
        ),
    },
    "viop-opportunity-scan": {
        "description": (
            "Tek bir VIOP underlying için fırsat taraması: term structure, "
            "IV surface, ve calendar/butterfly spread adayları. Pine "
            "tr_iv_surface ile sonucu chart'a basabilir."
        ),
        "arguments": [
            PromptArgument(
                name="underlying",
                description="VIOP underlying (XU030, USD, GARAN, ...)",
                required=True,
            ),
            PromptArgument(
                name="spot_price",
                description="Spot price for IV solve.",
                required=True,
            ),
            PromptArgument(
                name="risk_free_rate_pct",
                description="TL risk-free in percent.",
                required=True,
            ),
        ],
        "render": lambda args: (
            f"VIOP {args['underlying']} için fırsat taraması yap:\n"
            f"1. get_viop_term_structure(underlying='{args['underlying']}')"
            " — vade eğrisi.\n"
            f"2. get_viop_iv_surface(underlying='{args['underlying']}',"
            f" spot_price={args['spot_price']},"
            f" risk_free_rate_pct={args['risk_free_rate_pct']}) — IV surface.\n"
            "3. find_viop_spread_opportunities(surface=<above>,"
            " strategy='calendar', min_edge_vol_pts=3.0).\n"
            "4. find_viop_spread_opportunities(surface=<above>,"
            " strategy='butterfly', min_edge_vol_pts=3.0).\n"
            "5. En iyi 3-5 adayı tablo olarak Türkçe sun, likidite uyarısı ekle.\n"
            "6. İsteğe bağlı: render_pine_recipe('tr_iv_surface') ile overlay."
        ),
    },
    "kap-event-impact": {
        "description": (
            "Bir BIST hissesi için son materyal KAP bildirimleri + sonraki "
            "5 işlem gününün fiyat tepkisini analiz et."
        ),
        "arguments": [
            PromptArgument(
                name="ticker",
                description="BIST equity code",
                required=True,
            ),
            PromptArgument(
                name="since",
                description="ISO date, default 90 days ago",
                required=False,
            ),
        ],
        "render": lambda args: (
            f"BIST hissesi {args['ticker']} için KAP olay-fiyat analizi yap:\n"
            f"1. get_kap_disclosures(ticker='{args['ticker']}',"
            f" since='{args.get('since', '')}', only_material=true).\n"
            f"2. get_bist_eod_ohlcv(ticker='{args['ticker']}', period='3mo').\n"
            "3. Her materyal olay için: t+1 ve t+5 günlük getiriyi hesapla.\n"
            "4. Anormal tepkilerin örüntülerini Türkçe özetle.\n"
            "5. İsteğe bağlı: render_pine_recipe('tr_kap_marker') ile markerlar."
        ),
    },
    "crypto-derivatives-scan": {
        "description": (
            "BTC veya ETH için tam kripto türev tarama: spot, funding "
            "rate, OI, F&G index, Deribit IV surface, spread fırsatları."
        ),
        "arguments": [
            PromptArgument(
                name="currency",
                description="BTC veya ETH",
                required=True,
            ),
        ],
        "render": lambda args: (
            f"Kripto türev tarama — {args['currency']}:\n"
            "1. get_crypto_spots(coin_ids=['"
            f"{ {'BTC':'bitcoin','ETH':'ethereum'}.get(args['currency'].upper(),'bitcoin') }"
            "']) — spot.\n"
            f"2. get_crypto_funding_rates(symbol='{args['currency']}USDT', limit=30)"
            " — funding 8h history + annualised avg.\n"
            f"3. get_crypto_open_interest(symbol='{args['currency']}USDT',"
            " period='1h', limit=48) — OI 2 günlük.\n"
            "4. get_crypto_fear_greed(limit=14) — sentiment.\n"
            f"5. get_deribit_iv_surface(currency='{args['currency']}')"
            " — IV surface + skew + term structure.\n"
            "6. find_viop_spread_opportunities(surface=<above>,"
            " strategy='calendar', min_edge_vol_pts=2.0) — bu BTC/ETH için"
            " de çalışır (aynı şema).\n"
            "7. Tüm sinyalleri (funding stress, OI build, F&G,"
            " skew, term structure) Türkçe özetle ve net bias ver."
        ),
    },
    "global-macro-report": {
        "description": (
            "Tek prompt'ta global makro snapshot: indices + treasuries + "
            "commodities + crypto + FX + crypto F&G."
        ),
        "arguments": [],
        "render": lambda args: (
            "Global makro raporu üret:\n"
            "1. get_global_pulse() — SPX/NDX/DAX/N225 + UST yields + WTI/Gold + BTC/ETH.\n"
            "2. get_global_fx_spot('EURUSD'), ('USDJPY'), ('GBPUSD') — major FX.\n"
            "3. get_global_fx_matrix(bases=['USD'], quotes=['TRY','MXN','BRL','ZAR'])"
            " — EM stres.\n"
            "4. get_crypto_fear_greed(limit=7) — kripto sentiment.\n"
            "5. get_market_summary() — TR (XU100, USDTRY).\n"
            "6. Türkçe özet: risk-on mu risk-off mu, hangi rejim, ne yöne bias,"
            " TR varlıkları için ne anlama geliyor."
        ),
    },
    "option-strategy-explorer": {
        "description": (
            "Bir underlying için 4 standart strateji adayını paralel "
            "simüle eder ve en iyi risk/reward'ı önerir."
        ),
        "arguments": [
            PromptArgument(name="underlying", description="VIOP underlying", required=True),
            PromptArgument(name="spot", description="Current spot", required=True),
            PromptArgument(name="atm_iv_pct", description="ATM IV %", required=True),
            PromptArgument(name="dte", description="Days to expiry", required=True),
        ],
        "render": lambda args: (
            f"{args['underlying']} için opsiyon stratejisi tarama "
            f"(spot={args['spot']}, IV={args['atm_iv_pct']}%, DTE={args['dte']}):\n"
            "1. calculate_realized_vol(closes=<recent>, iv_atm_pct="
            f"{args['atm_iv_pct']}) — IV/RV oranı.\n"
            "2. simulate_option_strategy(template='long_straddle', "
            f"template_args={{'strike': {args['spot']}, 'dte': {args['dte']}, "
            f"'vol_pct': {args['atm_iv_pct']}}}) — long vol.\n"
            "3. simulate_option_strategy(template='short_straddle', ...) "
            "— short vol.\n"
            "4. simulate_option_strategy(template='iron_condor', ...) — "
            "neutral, defined risk.\n"
            "5. simulate_option_strategy(template='butterfly', ...) — "
            "pin riski.\n"
            "6. Her birinin max profit, max loss, breakevens, ve net "
            "debit/credit'ini tabloda göster.\n"
            "7. IV/RV oranı > 1.2 ise short-vol biaslı; < 0.8 ise long-vol "
            "biaslı seç. Türkçe öneri ver."
        ),
    },
    "news-pulse": {
        "description": (
            "Son finansal başlıkları çeker, kategorize eder, ve TR "
            "piyasaları için olası etkisini değerlendirir."
        ),
        "arguments": [],
        "render": lambda args: (
            "Son finansal başlıkları çek ve analiz et:\n"
            "1. get_news_headlines(feeds=['investing_top', 'investing_economy',"
            " 'investing_fx', 'investing_crypto'], limit_per_feed=15).\n"
            "2. Başlıkları kategoriye ayır: makro (Fed, ECB, TÜFE),"
            " hisse (M&A, kazanç), emtia, FX, kripto, jeopolitik.\n"
            "3. Her kategori için 2-3 cümlelik Türkçe özet ver.\n"
            "4. TR varlıkları (XU030, USDTRY, DİBS) için potansiyel etkiyi"
            " değerlendir.\n"
            "5. get_market_summary() ve get_global_pulse() çıktısı ile başlıkları"
            " çapraz doğrula."
        ),
    },
    "portfolio-risk-overview": {
        "description": (
            "Bir VIOP/spot pozisyon listesi için tam risk dökümü: Greeks, "
            "VaR, ve standart stres senaryoları."
        ),
        "arguments": [
            PromptArgument(
                name="positions_json",
                description="JSON array of positions",
                required=True,
            ),
        ],
        "render": lambda args: (
            f"Aşağıdaki pozisyonlar için tam risk dökümü çıkar:\n{args['positions_json']}\n\n"
            "Adımlar:\n"
            "1. aggregate_portfolio_greeks(positions=<above>) — net Δ/Γ/Vega/Θ.\n"
            "2. calculate_portfolio_var(positions=<above>, confidence=0.99, "
            "horizon_days=1, annual_volatility_pct=35.0) — VaR + ES.\n"
            "3. stress_test_portfolio(positions=<above>) — built-in scenario suite.\n"
            "4. En kötü 3 senaryoyu, net delta konsantrasyonunu, ve gamma riskini Türkçe özetle."
        ),
    },
    "price-action-trade-design": {
        "description": (
            "Tutarlı PA trade playbook: HTF+LTF analiz, detaylı execution plan, "
            "checklist validation, Long/Short position çizimi, journal. "
            "Her trade aynı kurallardan geçer."
        ),
        "arguments": [
            PromptArgument(
                name="symbol",
                description="TradingView symbol, e.g. BINANCE:BTCUSDT",
                required=True,
            ),
            PromptArgument(
                name="timeframe",
                description="LTF chart TF, e.g. 60, 15",
                required=True,
            ),
            PromptArgument(
                name="htf_timeframe",
                description="HTF for bias, e.g. 240, D (default 4x LTF)",
                required=False,
            ),
            PromptArgument(
                name="equity",
                description="Account equity (default 100000)",
                required=False,
            ),
        ],
        "render": lambda args: (
            f"Trade Assistant (temel + teknik) — {args['symbol']}:\n\n"
            "=== 0. KURALLAR ===\n"
            "get_trade_playbook_rules()\n\n"
            "=== 1. TEK KOMUT (önerilen) ===\n"
            f"run_market_assistant(\n"
            f"  symbol='{args['symbol']}',\n"
            "  market=<auto: crypto|bist|viop>,\n"
            f"  ltf_timeframe='{args['timeframe']}'  # optional — profile default\n"
            f"  htf_timeframe='{args.get('htf_timeframe', '')}'  # optional\n"
            f"  equity={float(args.get('equity', 100000))},\n"
            "  fetch_fundamentals=true,\n"
            "  draw_on_chart=true,\n"
            "  draw_when_no_trade=true,\n"
            "  log_journal=true\n"
            ")\n"
            "→ KAP/funding + PA/EW + chat_report.report_tr + TradingView çizimi\n\n"
            "=== 1a. Chat-only (TV kapalı) ===\n"
            "tv_fetch_mtf_ohlcv veya get_bist_eod_ohlcv → analyze_market_context\n\n"
            "=== 1b. Offline senaryo (veri elindeyse) ===\n"
            "analyze_chart_scenarios → design_scenario_trade_plan → apply_scenario_to_chart\n\n"
            "=== 2. TradingView önkoşul ===\n"
            "launch_tv_debug.bat (port 9222). İkinci MCP gerekmez.\n\n"
            "=== 3. RAPOR ===\n"
            "trade_report + thesis + execution_plan + validation.checks. "
            "Red ise no_trade açıkla."
        ),
    },
    "trade-assistant": {
        "description": (
            "Temel+teknik fusion: run_market_assistant → fusion.trade_allowed, "
            "chat_report.report_tr, TradingView PA/EW/position."
        ),
        "arguments": [
            PromptArgument(
                name="symbol",
                description="BIST:ASELS, BINANCE:BTCUSDT, …",
                required=True,
            ),
            PromptArgument(
                name="market",
                description="bist | crypto | viop (optional auto)",
                required=False,
            ),
        ],
        "render": lambda args: (
            f"Trade assistant — {args['symbol']}:\n\n"
            "1. TradingView CDP (9222) açık olmalı.\n"
            f"2. run_market_assistant(symbol='{args['symbol']}', "
            f"market={args.get('market') or 'auto'}, fetch_fundamentals=true, "
            "draw_on_chart=true)\n"
            "3. Kullanıcıya yalnızca JSON'daki chat_report.report_tr özetini Türkçe ver.\n"
            "4. fusion.trade_allowed=false ise pozisyon çizilmez — fusion uyarılarını açıkla.\n"
            "5. Ek temel: get_kap_disclosures, get_bist_sector_rotation, get_turib_endeks_overview.\n"
            "Yatırım tavsiyesi değildir."
        ),
    },
}


@server.list_prompts()
async def _list_prompts() -> list[Prompt]:
    return [
        Prompt(
            name=name,
            description=info["description"],
            arguments=info.get("arguments", []),
        )
        for name, info in PROMPTS_REGISTRY.items()
    ]


@server.get_prompt()
async def _get_prompt(name: str, arguments: dict[str, Any] | None = None) -> GetPromptResult:
    entry = PROMPTS_REGISTRY.get(name)
    if entry is None:
        raise ValueError(f"unknown prompt: {name}")
    body = entry["render"](arguments or {})
    return GetPromptResult(
        description=entry["description"],
        messages=[
            PromptMessage(
                role="user",
                content=TextContent(type="text", text=body),
            )
        ],
    )


async def run() -> None:
    try:
        async with stdio_server() as (read_stream, write_stream):
            await server.run(
                read_stream,
                write_stream,
                server.create_initialization_options(),
            )
    finally:
        # Gracefully close the shared HTTP client on shutdown
        await close_shared_client()

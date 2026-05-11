"""MCP server entrypoint — registers tools and runs over stdio."""

from __future__ import annotations

import json
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from .tools import (
    calculate_basis_fair_value,
    calculate_bond_metrics,
    calculate_implied_volatility,
    calculate_option_greeks,
    get_bist_eod_ohlcv,
    get_dibs_auctions,
    get_foreign_ownership,
    get_kap_disclosures,
    get_tcmb_policy_rates,
    get_viop_dashboard,
    get_viop_margin_call_alerts,
    get_viop_margin_parameters,
    get_viop_settlement,
    get_viop_term_structure,
    get_yield_curve,
    list_catalog,
    list_pine_recipes,
    render_pine_recipe,
)

server: Server = Server("bist-trader-mcp")


TOOL_DEFS: list[Tool] = [
    # --- Rates / TCMB ---------------------------------------------------------
    Tool(
        name="get_yield_curve",
        description=(
            "Return the Turkish DİBS (TL government bond) benchmark yield curve "
            "as of a date. Tenors: 1M, 3M, 6M, 1Y, 2Y, 3Y, 5Y, 10Y. Source: TCMB "
            "EVDS TP.ATBPK series family. Yields are nominal annualised percent."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "as_of": {"type": "string", "description": "YYYY-MM-DD"},
                "tenors": {"type": "array", "items": {"type": "string"}},
            },
        },
    ),
    Tool(
        name="get_tcmb_policy_rates",
        description=(
            "TCMB policy rate (1w repo) plus overnight corridor over a window. "
            "Source: TCMB EVDS TP.APIFON family."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "start": {"type": "string"},
                "end": {"type": "string"},
            },
        },
    ),
    Tool(
        name="calculate_bond_metrics",
        description=(
            "YTM, modified duration and convexity for a plain-vanilla bond. "
            "Rates passed as percent. Defaults to semi-annual coupon."
        ),
        inputSchema={
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
    ),
    Tool(
        name="list_catalog",
        description="Curated EVDS series codes used by this MCP.",
        inputSchema={"type": "object", "properties": {}},
    ),

    # --- KAP ------------------------------------------------------------------
    Tool(
        name="get_kap_disclosures",
        description=(
            "List KAP disclosures within a date window. Optional ticker filter. "
            "`only_material=true` keeps high-signal subjects (material, "
            "transactions, dividends, mergers, tenders). Source: KAP public JSON."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "ticker": {"type": "string"},
                "since": {"type": "string"},
                "until": {"type": "string"},
                "only_material": {"type": "boolean", "default": False},
                "limit": {"type": "integer", "default": 100},
            },
        },
    ),

    # --- BIST equity EOD ------------------------------------------------------
    Tool(
        name="get_bist_eod_ohlcv",
        description=(
            "Daily OHLCV bars for a BIST symbol via Yahoo Finance. EOD only — "
            "not for real-time. Indices use ^XU100 / ^XU030 form."
        ),
        inputSchema={
            "type": "object",
            "required": ["ticker"],
            "properties": {
                "ticker": {"type": "string"},
                "since": {"type": "string"},
                "until": {"type": "string"},
            },
        },
    ),

    # --- VIOP -----------------------------------------------------------------
    Tool(
        name="get_viop_settlement",
        description=(
            "All VIOP contract settlement rows (futures + options) for one "
            "trade date. Optional underlying filter."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "trade_date": {"type": "string"},
                "underlying": {"type": "string"},
            },
        },
    ),
    Tool(
        name="get_viop_term_structure",
        description=(
            "Futures-only term structure for one VIOP underlying, sorted by "
            "expiry. Useful for contango/backwardation and basis analysis."
        ),
        inputSchema={
            "type": "object",
            "required": ["underlying"],
            "properties": {
                "underlying": {"type": "string"},
                "as_of": {"type": "string"},
            },
        },
    ),

    # --- MKK ------------------------------------------------------------------
    Tool(
        name="get_foreign_ownership",
        description=(
            "Daily foreign-ownership ratio (% of free float) for a BIST ticker. "
            "Source: MKK."
        ),
        inputSchema={
            "type": "object",
            "required": ["ticker"],
            "properties": {
                "ticker": {"type": "string"},
                "since": {"type": "string"},
                "until": {"type": "string"},
            },
        },
    ),

    # --- Takasbank — VIOP margin parameters (margin-call signal) -------------
    Tool(
        name="get_viop_margin_parameters",
        description=(
            "Daily Takasbank initial/maintenance margin per VIOP contract. "
            "A jump in initial_margin precedes broker margin calls. Set "
            "only_changed=true for the signal-rich subset."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "trade_date": {"type": "string"},
                "underlying": {"type": "string"},
                "only_changed": {"type": "boolean", "default": False},
            },
        },
    ),
    Tool(
        name="get_viop_margin_call_alerts",
        description=(
            "Contracts whose initial margin moved by more than threshold_pct "
            "(default 5%) vs prior day — the morning scan for upcoming "
            "margin-call waves."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "trade_date": {"type": "string"},
                "threshold_pct": {"type": "number", "default": 5.0},
            },
        },
    ),
    Tool(
        name="get_viop_dashboard",
        description=(
            "Marketwide VIOP aggregate margin snapshot from Takasbank "
            "(margined account count, transaction/guarantee-fund margin, "
            "margin-call total, required margin). Cached 6h to respect "
            "Takasbank's F5 WAF rate limit. THE marketwide margin stress "
            "signal."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "use_cache": {"type": "boolean", "default": True},
                "cache_ttl_seconds": {"type": "integer", "default": 21600},
            },
        },
    ),

    # --- Options math --------------------------------------------------------
    Tool(
        name="calculate_option_greeks",
        description=(
            "Black-Scholes price + delta/gamma/theta/vega/rho for a European "
            "option (VIOP options are European-style)."
        ),
        inputSchema={
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
    ),
    Tool(
        name="calculate_implied_volatility",
        description=(
            "Solve Black-Scholes for sigma given an observed market option "
            "price. Returns IV as percent."
        ),
        inputSchema={
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
    ),

    # --- Hazine — DİBS auctions ---------------------------------------------
    Tool(
        name="get_dibs_auctions",
        description=(
            "Treasury (Hazine) DİBS auction calendar + results. Default "
            "window: -30 to +60 days. Filter by status: scheduled | "
            "completed | cancelled."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "since": {"type": "string"},
                "until": {"type": "string"},
                "status": {"type": "string"},
            },
        },
    ),

    # --- Cross-asset basis ---------------------------------------------------
    Tool(
        name="calculate_basis_fair_value",
        description=(
            "Cost-of-carry fair value of a futures contract vs observed "
            "market. Returns deviation_from_fair_bps and implied_repo_rate. "
            "Pair with get_yield_curve for the risk-free input."
        ),
        inputSchema={
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
    ),

    # --- Pine recipes (companion to tradesdontlie/tradingview-mcp) -----------
    Tool(
        name="list_pine_recipes",
        description=(
            "List Pine v6 recipe templates this MCP can render. Designed to be "
            "handed to tradesdontlie/tradingview-mcp `pine_new` + "
            "`pine_smart_compile` for execution inside TradingView Desktop."
        ),
        inputSchema={"type": "object", "properties": {}},
    ),
    Tool(
        name="render_pine_recipe",
        description=(
            "Render a Pine recipe with placeholders substituted. If "
            "`auto_fetch=true` and the recipe needs TCMB macro values, this "
            "tool will pull the latest policy rate, corridor, and CPI from "
            "EVDS automatically. The returned `pine_v6_source` is ready to "
            "paste into TradingView via tradesdontlie/tradingview-mcp."
        ),
        inputSchema={
            "type": "object",
            "required": ["name"],
            "properties": {
                "name": {"type": "string", "description": "Recipe name, e.g. 'tr_macro_backdrop'"},
                "data": {
                    "type": "object",
                    "description": "Placeholder overrides (keys map to {{TOKEN}}s in the template).",
                },
                "auto_fetch": {
                    "type": "boolean",
                    "default": False,
                    "description": "If true, fill macro placeholders from EVDS automatically.",
                },
            },
        },
    ),
]


@server.list_tools()
async def _list_tools() -> list[Tool]:
    return TOOL_DEFS


_SYNC_TOOLS = {"calculate_bond_metrics", "list_catalog", "list_pine_recipes"}


@server.call_tool()
async def _call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    arguments = arguments or {}
    try:
        if name == "get_yield_curve":
            result = await get_yield_curve(
                as_of=arguments.get("as_of"),
                tenors=arguments.get("tenors"),
            )
        elif name == "get_tcmb_policy_rates":
            result = await get_tcmb_policy_rates(
                start=arguments.get("start"),
                end=arguments.get("end"),
            )
        elif name == "calculate_bond_metrics":
            result = calculate_bond_metrics(
                face_value=float(arguments["face_value"]),
                coupon_rate_pct=float(arguments["coupon_rate_pct"]),
                years_to_maturity=float(arguments["years_to_maturity"]),
                market_price=float(arguments["market_price"]),
                coupon_frequency=int(arguments.get("coupon_frequency", 2)),
            )
        elif name == "list_catalog":
            result = list_catalog()
        elif name == "get_kap_disclosures":
            result = await get_kap_disclosures(
                ticker=arguments.get("ticker"),
                since=arguments.get("since"),
                until=arguments.get("until"),
                only_material=bool(arguments.get("only_material", False)),
                limit=int(arguments.get("limit", 100)),
            )
        elif name == "get_bist_eod_ohlcv":
            result = await get_bist_eod_ohlcv(
                ticker=arguments["ticker"],
                since=arguments.get("since"),
                until=arguments.get("until"),
            )
        elif name == "get_viop_settlement":
            result = await get_viop_settlement(
                trade_date=arguments.get("trade_date"),
                underlying=arguments.get("underlying"),
            )
        elif name == "get_viop_term_structure":
            result = await get_viop_term_structure(
                underlying=arguments["underlying"],
                as_of=arguments.get("as_of"),
            )
        elif name == "get_foreign_ownership":
            result = await get_foreign_ownership(
                ticker=arguments["ticker"],
                since=arguments.get("since"),
                until=arguments.get("until"),
            )
        elif name == "get_viop_margin_parameters":
            result = await get_viop_margin_parameters(
                trade_date=arguments.get("trade_date"),
                underlying=arguments.get("underlying"),
                only_changed=bool(arguments.get("only_changed", False)),
            )
        elif name == "get_viop_margin_call_alerts":
            result = await get_viop_margin_call_alerts(
                trade_date=arguments.get("trade_date"),
                threshold_pct=float(arguments.get("threshold_pct", 5.0)),
            )
        elif name == "get_viop_dashboard":
            result = await get_viop_dashboard(
                use_cache=bool(arguments.get("use_cache", True)),
                cache_ttl_seconds=int(arguments.get("cache_ttl_seconds", 6 * 3600)),
            )
        elif name == "calculate_option_greeks":
            result = calculate_option_greeks(
                spot=float(arguments["spot"]),
                strike=float(arguments["strike"]),
                days_to_expiry=float(arguments["days_to_expiry"]),
                volatility_pct=float(arguments["volatility_pct"]),
                risk_free_rate_pct=float(arguments["risk_free_rate_pct"]),
                dividend_yield_pct=float(arguments.get("dividend_yield_pct", 0.0)),
                style=str(arguments.get("style", "call")),
            )
        elif name == "calculate_implied_volatility":
            result = calculate_implied_volatility(
                market_price=float(arguments["market_price"]),
                spot=float(arguments["spot"]),
                strike=float(arguments["strike"]),
                days_to_expiry=float(arguments["days_to_expiry"]),
                risk_free_rate_pct=float(arguments["risk_free_rate_pct"]),
                dividend_yield_pct=float(arguments.get("dividend_yield_pct", 0.0)),
                style=str(arguments.get("style", "call")),
            )
        elif name == "get_dibs_auctions":
            result = await get_dibs_auctions(
                since=arguments.get("since"),
                until=arguments.get("until"),
                status=arguments.get("status"),
            )
        elif name == "calculate_basis_fair_value":
            result = calculate_basis_fair_value(
                spot_price=float(arguments["spot_price"]),
                futures_price=float(arguments["futures_price"]),
                days_to_expiry=float(arguments["days_to_expiry"]),
                risk_free_rate_pct=float(arguments["risk_free_rate_pct"]),
                dividend_yield_pct=float(arguments.get("dividend_yield_pct", 0.0)),
            )
        elif name == "list_pine_recipes":
            result = list_pine_recipes()
        elif name == "render_pine_recipe":
            result = await render_pine_recipe(
                name=arguments["name"],
                data=arguments.get("data") or {},
                auto_fetch=bool(arguments.get("auto_fetch", False)),
            )
        else:
            result = {"error": "unknown_tool", "detail": name}
    except KeyError as e:
        result = {"error": "missing_argument", "detail": str(e)}
    except Exception as e:  # surface unexpected errors as structured payload
        result = {"error": "tool_failed", "detail": f"{type(e).__name__}: {e}"}

    return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, default=str))]


async def run() -> None:
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )

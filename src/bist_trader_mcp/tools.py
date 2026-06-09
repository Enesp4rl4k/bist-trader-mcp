"""High-level tool functions exposed via MCP.

Each function returns a JSON-serialisable dict. Errors are converted to a
structured `{"error": ..., "detail": ...}` payload so the LLM can reason about
them instead of receiving an opaque exception.
"""

from __future__ import annotations

import math
from datetime import date, timedelta
from typing import Any

from ._wip import wip_payload
from .backtest import SIGNAL_GENERATORS, run_backtest
from .bist_eod import fetch_eod_ohlcv
from .bist_sectors import (
    BIST_SECTORS,
    compute_rotation_metrics,
    fetch_sector_closes,
)
from .bist_snapshot import fetch_market_summary as _fetch_market_summary
from .bist_snapshot import fetch_snapshot as _fetch_snapshot
from .bond_math import bond_metrics
from .calendar_data import build_calendar as _build_calendar
from .chart_scenarios import (
    analyze_chart_scenarios as _analyze_chart_scenarios,
)
from .chart_scenarios import (
    design_scenario_trade_plan as _design_scenario_trade_plan,
)
from .correlation import correlation_matrix as _correlation_matrix
from .correlation import rolling_correlation as _rolling_correlation
from .crypto import (
    fetch_binance_klines,
    fetch_coin_spots,
    fetch_funding_rates,
    fetch_open_interest_history,
)
from .deribit import build_deribit_surface, fetch_deribit_option_chain
from .elliott_wave import analyze_elliott_wave as _analyze_elliott_wave
from .evds import EVDSClient, EVDSError, EVDSObservation
from .fear_greed import fetch_fear_greed
from .fx import fx_forward_curve as _fx_forward_curve
from .global_fx import fetch_fx_history, fetch_fx_matrix, fetch_fx_spot
from .global_markets import fetch_global_pulse
from .hazine import fetch_auctions
from .http_utils import SourceError
from .iv_surface import build_iv_surface, find_spread_opportunities
from .kap import fetch_disclosures
from .kelly import kelly_panel, position_size_from_atr
from .market_assistant import (
    analyze_market_context as _analyze_market_context,
)
from .market_assistant import (
    run_market_assistant as _run_market_assistant,
)
from .market_profiles import (
    get_market_profile as _get_market_profile,
)
from .market_profiles import (
    resolve_assistant_config as _resolve_assistant_config,
)
from .mkk import fetch_foreign_ownership, fetch_market_stats
from .mtf_analysis import analyze_mtf_price_action as _analyze_mtf_price_action
from .news import NEWS_FEEDS, fetch_news
from .onchain import fetch_btc_network_stats, fetch_eth_gas_oracle
from .options_math import black_scholes, implied_volatility
from .pa_scanner import scan_mtf_watchlist as _scan_mtf_watchlist
from .pa_scanner import scan_price_action_watchlist as _scan_price_action_watchlist
from .performance import performance_panel
from .portfolio import aggregate_portfolio_greeks as _aggregate_portfolio_greeks
from .portfolio import calculate_portfolio_var as _calc_var
from .portfolio import stress_test_portfolio as _stress_test
from .portfolio_opt import optimize_portfolio
from .position_design import (
    design_from_price_action as _design_from_price_action,
)
from .position_design import (
    design_trade_setup as _design_trade_setup,
)
from .position_design import (
    portfolio_risk_check as _portfolio_risk_check,
)
from .price_action import analyze_price_action as _analyze_price_action
from .realized_vol import realized_vol_panel
from .recipes import list_recipes, render_recipe
from .series_catalog import (
    CPI_HEADLINE,
    DIBS_YIELD_SERIES,
    EURTRY_SELLING,
    POLICY_RATE_SERIES,
    USDTRY_SELLING,
    list_known_series,
)
from .strategies import STRATEGY_TEMPLATES, StrategyLeg, simulate_strategy
from .takasbank import (
    fetch_margin_change_alerts,
    fetch_margin_parameters,
    fetch_viop_margin_snapshot,
)
from .technicals import compute_snapshot as _tech_snapshot
from .trade_journal import (
    list_trade_journal as _list_trade_journal,
)
from .trade_journal import (
    log_trade_plan as _log_trade_plan,
)
from .trade_journal import (
    monitor_open_trades as _monitor_open_trades,
)
from .trade_journal import (
    update_trade_status as _update_trade_status,
)
from .trade_playbook import (
    design_ltf_trade_plan as _design_ltf_trade_plan,
)
from .trade_playbook import (
    design_mtf_trade_plan as _design_mtf_trade_plan,
)
from .trade_playbook import (
    enrich_trade_plan as _enrich_trade_plan,
)
from .trade_playbook import (
    get_trade_playbook_rules as _get_trade_playbook_rules,
)
from .trade_playbook import (
    run_trade_assistant as _run_trade_assistant,
)
from .trade_playbook import (
    validate_trade_consistency as _validate_trade_consistency,
)
from .tv_bridge import (
    apply_scenario_to_chart as _apply_scenario_to_chart,
)
from .tv_bridge import (
    apply_trade_plan_to_chart as _apply_trade_plan_to_chart,
)
from .tv_tools import (
    tv_alert_create as _tv_alert_create,
)
from .tv_tools import (
    tv_capture_screenshot as _tv_capture_screenshot,
)
from .tv_tools import (
    tv_chart_get_state as _tv_chart_get_state,
)
from .tv_tools import (
    tv_chart_set_symbol as _tv_chart_set_symbol,
)
from .tv_tools import (
    tv_chart_set_timeframe as _tv_chart_set_timeframe,
)
from .tv_tools import (
    tv_data_get_ohlcv as _tv_data_get_ohlcv,
)
from .tv_tools import (
    tv_draw_clear as _tv_draw_clear,
)
from .tv_tools import (
    tv_fetch_mtf_ohlcv as _tv_fetch_mtf_ohlcv,
)
from .tv_tools import (
    tv_health_check as _tv_health_check,
)
from .viop import fetch_daily_settlement, fetch_option_chain, fetch_term_structure
from .vol_forecast import ewma_volatility, garch_forecast
from .yield_fitter import (
    evaluate_curve_grid,
    fit_nelson_siegel,
)


def _observations_to_series(
    observations: list[EVDSObservation],
) -> dict[str, list[dict[str, Any]]]:
    """Group flat observations by series_code into {code: [{date,value}, ...]}."""
    by_code: dict[str, list[dict[str, Any]]] = {}
    for obs in observations:
        by_code.setdefault(obs.series_code, []).append(
            {"date": obs.date, "value": obs.value}
        )
    return by_code


def _latest_non_null(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    for row in reversed(rows):
        if row.get("value") is not None:
            return row
    return None


async def get_yield_curve(
    as_of: str | None = None,
    tenors: list[str] | None = None,
    client: EVDSClient | None = None,
) -> dict[str, Any]:
    """Return the TL DİBS benchmark yield curve as of a given date.

    Args:
        as_of: YYYY-MM-DD. If None, latest available is used.
        tenors: Subset of tenors to fetch. Defaults to all known benchmarks.
    """
    if not DIBS_YIELD_SERIES:
        return wip_payload(
            "evds_dibs_curve",
            "TCMB retired the TP.ATBPK benchmark family in 2024; tenor-bucketed "
            "yield curve construction from per-ISIN bie_pydibs data is tracked "
            "for v0.3.",
        )

    client = client or EVDSClient()
    tenors = tenors or list(DIBS_YIELD_SERIES.keys())
    unknown = [t for t in tenors if t not in DIBS_YIELD_SERIES]
    if unknown:
        return {
            "error": "unknown_tenor",
            "detail": f"Unknown tenor(s): {unknown}. Known: {list(DIBS_YIELD_SERIES)}",
        }

    series_codes = [DIBS_YIELD_SERIES[t] for t in tenors]
    end = date.fromisoformat(as_of) if as_of else date.today()
    start = end - timedelta(days=14)  # small window so we can pick latest non-null

    try:
        observations = await client.get_series(series_codes, start=start, end=end)
    except EVDSError as e:
        return {"error": "evds_error", "detail": str(e)}

    series_map = _observations_to_series(observations)
    curve: list[dict[str, Any]] = []
    for tenor in tenors:
        code = DIBS_YIELD_SERIES[tenor]
        rows = series_map.get(code, [])
        latest = _latest_non_null(rows)
        curve.append(
            {
                "tenor": tenor,
                "series_code": code,
                "as_of": latest["date"] if latest else None,
                "yield_pct": latest["value"] if latest else None,
            }
        )

    return {
        "source": "TCMB EVDS — TP.ATBPK family (DİBS benchmark yields)",
        "requested_as_of": as_of or end.isoformat(),
        "curve": curve,
        "disclaimer": (
            "This data is for research / informational use only and is not "
            "investment advice. Verify with primary sources for trading decisions."
        ),
    }


async def get_repo_curve(
    as_of: str | None = None,
    window_days: int = 14,
    client: EVDSClient | None = None,
) -> dict[str, Any]:
    """Turkish TL money-market / repo rate panel as of a date.

    Returns the practical short-end of the TL curve: TCMB 1-week repo
    (the policy rate), BIST TLREF (effective O/N TL benchmark), and BIST
    overnight weighted-avg repo. Plus cross-spreads vs the policy rate —
    the canonical funding-stress reads:

    - tlref - policy:  positive = TL is more expensive than policy → tightening
    - bist_o/n - policy: same idea, broader collateral pool
    - bist_o/n - tlref: collateral-quality spread (positive = sec-funding stress)

    The legacy interest-rate corridor (APIFON1/APIFON2) was retired by
    TCMB in 2024; this is the current effective replacement. For a full
    DİBS yield curve see get_yield_curve (v0.3 WIP for tenor-bucketed).

    Args:
        as_of: YYYY-MM-DD. If None, latest available is used.
        window_days: how many days back to search for the latest non-null
            observation per series. Default 14 (covers long weekends).
    """
    client = client or EVDSClient()
    end = date.fromisoformat(as_of) if as_of else date.today()
    start = end - timedelta(days=max(1, window_days))

    series_codes = list(POLICY_RATE_SERIES.values())
    try:
        observations = await client.get_series(series_codes, start=start, end=end)
    except EVDSError as e:
        return {"error": "evds_error", "detail": str(e)}

    series_map = _observations_to_series(observations)

    # tenor → (friendly_key, EVDS code)
    rows: list[dict[str, Any]] = []
    latest: dict[str, dict[str, Any] | None] = {}
    for friendly, code in POLICY_RATE_SERIES.items():
        obs = _latest_non_null(series_map.get(code, []))
        latest[friendly] = obs
        rows.append(
            {
                "key": friendly,
                "series_code": code,
                "as_of": obs["date"] if obs else None,
                "rate_pct": obs["value"] if obs else None,
            }
        )

    policy = latest.get("policy_rate_1w_repo")
    tlref = latest.get("tlref_overnight")
    bist_repo = latest.get("bist_overnight_repo")

    def _spread(a: dict[str, Any] | None, b: dict[str, Any] | None) -> float | None:
        if not a or not b or a.get("value") is None or b.get("value") is None:
            return None
        return float(a["value"]) - float(b["value"])

    spreads = {
        "tlref_minus_policy_bps": (
            _spread(tlref, policy) * 100 if _spread(tlref, policy) is not None else None
        ),
        "bist_overnight_minus_policy_bps": (
            _spread(bist_repo, policy) * 100
            if _spread(bist_repo, policy) is not None
            else None
        ),
        "bist_overnight_minus_tlref_bps": (
            _spread(bist_repo, tlref) * 100
            if _spread(bist_repo, tlref) is not None
            else None
        ),
    }

    return {
        "source": "TCMB EVDS — TL money-market panel (policy, TLREF, BIST O/N repo)",
        "requested_as_of": as_of or end.isoformat(),
        "panel": rows,
        "spreads_bps": spreads,
        "interpretation": (
            "Positive tlref_minus_policy_bps means TL O/N funding is "
            "trading above policy — typical sign of system-wide TL "
            "tightness / TCMB allowing market rate to drift up. "
            "bist_overnight_minus_tlref_bps measures sec-funding stress "
            "(collateral quality premium). Sustained moves > +50bps are "
            "unusual outside policy turning points."
        ),
        "notes": (
            "The classic 'corridor' (APIFON1 borrowing / APIFON2 lending) "
            "was retired by TCMB in 2024. This panel reports the current "
            "effective short-end. For a tenor-bucketed DİBS yield curve "
            "see get_yield_curve (v0.3 WIP)."
        ),
    }


async def get_tcmb_policy_rates(
    start: str | None = None,
    end: str | None = None,
    client: EVDSClient | None = None,
) -> dict[str, Any]:
    """Return TCMB policy rate and interest-rate corridor over a date window.

    Returns the 1-week repo rate, overnight borrowing & lending and late
    liquidity lending rate. Useful for charting the corridor history.
    """
    client = client or EVDSClient()
    end_date = date.fromisoformat(end) if end else date.today()
    start_date = (
        date.fromisoformat(start) if start else end_date - timedelta(days=365)
    )

    series_codes = list(POLICY_RATE_SERIES.values())
    try:
        observations = await client.get_series(
            series_codes, start=start_date, end=end_date
        )
    except EVDSError as e:
        return {"error": "evds_error", "detail": str(e)}

    series_map = _observations_to_series(observations)
    # Re-key by friendly names
    friendly: dict[str, list[dict[str, Any]]] = {}
    for name, code in POLICY_RATE_SERIES.items():
        friendly[name] = series_map.get(code, [])

    latest_snapshot = {
        name: _latest_non_null(rows) for name, rows in friendly.items()
    }

    return {
        "source": "TCMB EVDS — TP.APIFON family",
        "window": {"start": start_date.isoformat(), "end": end_date.isoformat()},
        "latest": latest_snapshot,
        "series": friendly,
        "notes": (
            "1w_repo is the policy rate. Overnight borrowing/lending define "
            "the symmetric corridor around it; late liquidity window applies "
            "outside operating hours."
        ),
    }


def calculate_bond_metrics(
    face_value: float,
    coupon_rate_pct: float,
    years_to_maturity: float,
    market_price: float,
    coupon_frequency: int = 2,
) -> dict[str, Any]:
    """Compute YTM, modified duration and convexity for a plain-vanilla bond.

    All rates and yields are expressed in percent (e.g. 25.0 = %25).
    Coupon frequency defaults to semi-annual (Turkish DİBS often coupon
    twice a year for fixed-rate notes).
    """
    try:
        ytm, mod_dur, convex = bond_metrics(
            face_value=face_value,
            coupon_rate_pct=coupon_rate_pct,
            years_to_maturity=years_to_maturity,
            market_price=market_price,
            coupon_frequency=coupon_frequency,
        )
    except (ValueError, ArithmeticError) as e:
        return {"error": "calculation_failed", "detail": str(e)}

    return {
        "inputs": {
            "face_value": face_value,
            "coupon_rate_pct": coupon_rate_pct,
            "years_to_maturity": years_to_maturity,
            "market_price": market_price,
            "coupon_frequency": coupon_frequency,
        },
        "ytm_pct": ytm * 100,
        "modified_duration_years": mod_dur,
        "convexity_years_sq": convex,
        "notes": (
            "YTM is solved numerically; assumes the bond is held to maturity "
            "and all coupons are reinvested at the same yield. Inflation-linked "
            "(TÜFEX) bonds require a different model."
        ),
    }


def list_catalog() -> dict[str, Any]:
    """Expose the curated EVDS series catalog for discovery."""
    return {
        "source": "TCMB EVDS — curated subset",
        "series": list_known_series(),
        "evds_browse_url": "https://evds2.tcmb.gov.tr/index.php?/evds/serieMarket",
    }


# -----------------------------------------------------------------------------
# KAP — public disclosures
# -----------------------------------------------------------------------------
async def get_kap_disclosures(
    ticker: str | None = None,
    since: str | None = None,
    until: str | None = None,
    only_material: bool = False,
    limit: int = 100,
) -> dict[str, Any]:
    """List KAP disclosures within a date window."""
    try:
        items = await fetch_disclosures(
            ticker=ticker,
            since=since,
            until=until,
            only_material=only_material,
            limit=limit,
        )
    except SourceError as e:
        if "endpoint discovery pending" in str(e):
            return wip_payload("kap", str(e))
        return {"error": "kap_error", "detail": str(e)}

    return {
        "source": "KAP (Kamuyu Aydınlatma Platformu)",
        "ticker_filter": ticker,
        "only_material": only_material,
        "count": len(items),
        "disclosures": [
            {
                "id": d.disclosure_id,
                "publish_date": d.publish_date,
                "ticker": d.company_ticker,
                "company": d.company_name,
                "subject": d.subject,
                "summary": d.summary,
                "is_late": d.is_late,
                "is_material": d.is_material,
                "url": d.url,
            }
            for d in items
        ],
        "disclaimer": (
            "Materiality flag is heuristic, based on subject-keyword matching. "
            "Always verify with the underlying disclosure text."
        ),
    }


# -----------------------------------------------------------------------------
# BIST EOD — equity OHLCV
# -----------------------------------------------------------------------------
async def get_bist_eod_ohlcv(
    ticker: str,
    since: str | None = None,
    until: str | None = None,
    fmt: str = "json",
) -> dict[str, Any]:
    """Daily OHLCV bars for a BIST symbol (Yahoo Finance backend, free, EOD).

    Args:
        fmt: 'json' returns full JSON array; 'compact' returns a CSV-style
             string that saves ~70% LLM context tokens for long series.
    """
    try:
        bars = await fetch_eod_ohlcv(ticker, since=since, until=until)
    except SourceError as e:
        return {"error": "bist_eod_error", "detail": str(e)}

    result: dict[str, Any] = {
        "source": "Yahoo Finance (BIST EOD)",
        "ticker": ticker,
        "count": len(bars),
        "disclaimer": (
            "EOD data is sourced from Yahoo Finance, which mirrors official "
            "BIST closing prices but is not the primary source. Do not use "
            "for clearing/settlement reconciliation."
        ),
    }

    if fmt == "compact" and bars:
        header = "date,open,high,low,close,volume"
        rows = [f"{b.date},{b.open},{b.high},{b.low},{b.close},{b.volume}" for b in bars]
        result["bars_csv"] = header + "\n" + "\n".join(rows)
    else:
        result["bars"] = [
            {
                "date": b.date,
                "open": b.open,
                "high": b.high,
                "low": b.low,
                "close": b.close,
                "volume": b.volume,
            }
            for b in bars
        ]
    return result


# -----------------------------------------------------------------------------
# VIOP — derivatives settlement & term structure
# -----------------------------------------------------------------------------
async def get_viop_settlement(
    trade_date: str | None = None,
    underlying: str | None = None,
    fmt: str = "json",
) -> dict[str, Any]:
    """Live VIOP contract snapshot — last price, % change, volume, OI.

    Source: İş Yatırım's public viop.aspx page (no auth, no WAF). All
    actively trading futures and options are returned in a single call;
    use the optional `underlying` filter (e.g. "XU030", "USD") to slice.

    Note: Settlement prices in the strict Takasbank EOD sense are NOT
    exposed here — last_price + % change + volume + OI are. For the
    marketwide aggregate margin / volume / OI dashboard use
    `get_viop_dashboard`. For per-contract official end-of-day settle
    prices, v0.3 will add a Takasbank-overnight pipeline.

    Args:
        fmt: 'json' returns full JSON; 'compact' returns a CSV-style
             string that saves ~70% tokens for the full 480+ contract table.
    """
    try:
        rows = await fetch_daily_settlement(
            trade_date=trade_date, underlying_filter=underlying
        )
    except SourceError as e:
        if "endpoint discovery pending" in str(e):
            return wip_payload("viop", str(e))
        return {"error": "viop_error", "detail": str(e)}

    result: dict[str, Any] = {
        "source": "İş Yatırım — viop.aspx live contract snapshot",
        "trade_date": rows[0].trade_date if rows else trade_date,
        "underlying_filter": underlying,
        "count": len(rows),
    }

    if fmt == "compact" and rows:
        header = "code,underlying,type,expiry,last,chg%,vol_tl,oi"
        csv_rows = [
            f"{r.contract.contract_code},{r.contract.underlying},"
            f"{r.contract.contract_type},"
            f"{r.contract.expiry_year}-{r.contract.expiry_month:02d},"
            f"{r.last_price},{r.percent_change},{r.volume_tl},{r.open_interest}"
            for r in rows
        ]
        result["rows_csv"] = header + "\n" + "\n".join(csv_rows)
    else:
        result["rows"] = [
            {
                "contract_code": r.contract.contract_code,
                "underlying": r.contract.underlying,
                "contract_type": r.contract.contract_type,
                "expiry_year": r.contract.expiry_year,
                "expiry_month": r.contract.expiry_month,
                "option_strike": r.contract.option_strike,
                "option_right": r.contract.option_right,
                "name": r.name,
                "last_price": r.last_price,
                "percent_change": r.percent_change,
                "absolute_change": r.absolute_change,
                "volume_tl": r.volume_tl,
                "open_interest": r.open_interest,
            }
            for r in rows
        ]
    return result


async def get_viop_option_chain(
    underlying: str,
    expiry_year: int | None = None,
    expiry_month: int | None = None,
    as_of: str | None = None,
    spot_price: float | None = None,
    risk_free_rate_pct: float | None = None,
    dividend_yield_pct: float = 0.0,
    solve_iv: bool = True,
) -> dict[str, Any]:
    """VIOP option chain for one underlying — strikes × calls/puts.

    If `spot_price` and `risk_free_rate_pct` are provided and
    `solve_iv=True`, each row's IV is solved from its last_price. ATM IV
    and 25-delta skew (call - put) are reported when both wings can be
    priced. Without spot/r the chain is returned without IV — last/% chg
    /volume/OI only.

    Args:
        underlying: VIOP underlying (e.g. "XU030", "USD", "GARAN").
        expiry_year, expiry_month: pin chain to one expiry. Both required
            to filter; otherwise the full multi-expiry chain is returned.
        spot_price: cash price of the underlying. Pull via get_bist_snapshot
            for indices or via market data for equities.
        risk_free_rate_pct: TL risk-free at the option's tenor. Pull the
            relevant point of get_repo_curve / get_yield_curve.
        solve_iv: if False, skip IV solve even when inputs are provided.
    """
    try:
        rows = await fetch_option_chain(
            underlying=underlying,
            expiry_year=expiry_year,
            expiry_month=expiry_month,
            as_of=as_of,
        )
    except SourceError as e:
        if "endpoint discovery pending" in str(e):
            return wip_payload("viop", str(e))
        return {"error": "viop_error", "detail": str(e)}

    have_iv_inputs = (
        solve_iv
        and spot_price is not None
        and risk_free_rate_pct is not None
        and spot_price > 0
    )

    r = (risk_free_rate_pct or 0.0) / 100.0
    q = (dividend_yield_pct or 0.0) / 100.0

    # Cosmetic trade_date — pick from any row
    trade_date = rows[0].trade_date if rows else (as_of or date.today().isoformat())
    today = date.today()

    out_rows: list[dict[str, Any]] = []
    for s in rows:
        c = s.contract
        # Approximate days-to-expiry from VIOP convention: contracts expire
        # the last business day of `expiry_month`; use end-of-month as a
        # workable proxy. The IV solver is only mildly sensitive.
        from calendar import monthrange

        last_day = monthrange(c.expiry_year, c.expiry_month)[1]
        try:
            expiry_date = date(c.expiry_year, c.expiry_month, last_day)
        except ValueError:
            expiry_date = today
        dte = max(1, (expiry_date - today).days)

        iv_pct: float | None = None
        if (
            have_iv_inputs
            and c.option_strike
            and c.option_right
            and s.last_price
            and s.last_price > 0
        ):
            try:
                iv = implied_volatility(
                    market_price=float(s.last_price),
                    spot=float(spot_price),
                    strike=float(c.option_strike),
                    time_to_expiry=dte / 365.0,
                    risk_free_rate=r,
                    dividend_yield=q,
                    style=("call" if c.option_right == "C" else "put"),
                )
                iv_pct = iv * 100.0
            except (ValueError, ArithmeticError):
                iv_pct = None

        out_rows.append(
            {
                "contract_code": c.contract_code,
                "expiry_year": c.expiry_year,
                "expiry_month": c.expiry_month,
                "days_to_expiry": dte,
                "strike": c.option_strike,
                "right": c.option_right,
                "last_price": s.last_price,
                "percent_change": s.percent_change,
                "volume_tl": s.volume_tl,
                "open_interest": s.open_interest,
                "iv_pct": iv_pct,
            }
        )

    # ATM IV + 25-delta skew (per-expiry)
    summary: list[dict[str, Any]] = []
    if have_iv_inputs and out_rows:
        by_expiry: dict[tuple[int, int], list[dict[str, Any]]] = {}
        for r_ in out_rows:
            if r_.get("strike") is None:
                continue
            by_expiry.setdefault((r_["expiry_year"], r_["expiry_month"]), []).append(r_)

        for (yr, mo), group in by_expiry.items():
            with_iv = [g for g in group if g.get("iv_pct") is not None]
            if not with_iv:
                continue
            # ATM IV: row with strike closest to spot, averaging C/P if both
            atm_strike = min(
                {g["strike"] for g in with_iv},
                key=lambda k: abs(k - float(spot_price)),
            )
            atm_rows = [g for g in with_iv if g["strike"] == atm_strike]
            atm_iv = sum(g["iv_pct"] for g in atm_rows) / len(atm_rows)

            # 25-delta skew: cheap approximation — pick strikes ±5% from spot
            otm_call_strike = float(spot_price) * 1.05
            otm_put_strike = float(spot_price) * 0.95

            def _closest(side: str, target: float, _pool=with_iv) -> float | None:
                cands = [g for g in _pool if g.get("right") == side]
                if not cands:
                    return None
                pick = min(cands, key=lambda g: abs(g["strike"] - target))
                return pick["iv_pct"]

            call_wing = _closest("C", otm_call_strike)
            put_wing = _closest("P", otm_put_strike)
            skew_25d = (
                call_wing - put_wing
                if call_wing is not None and put_wing is not None
                else None
            )
            summary.append(
                {
                    "expiry_year": yr,
                    "expiry_month": mo,
                    "atm_strike": atm_strike,
                    "atm_iv_pct": atm_iv,
                    "iv_25d_call_pct": call_wing,
                    "iv_25d_put_pct": put_wing,
                    "skew_25d_call_minus_put_pct": skew_25d,
                }
            )

    return {
        "source": "İş Yatırım — viop.aspx (options filtered & paired with IV math)",
        "underlying": underlying,
        "trade_date": trade_date,
        "spot_price": spot_price,
        "risk_free_rate_pct": risk_free_rate_pct,
        "count": len(out_rows),
        "iv_solved": have_iv_inputs,
        "summary_by_expiry": summary,
        "rows": out_rows,
        "notes": (
            "IV is solved from last_price; if your last_price is stale "
            "(no trades) the IV will be noisy or unbracketable. Skew is "
            "computed at ±5% strikes around spot — a fast proxy, not a "
            "true 25-delta. days_to_expiry uses end-of-expiry-month; for "
            "the official VIOP last-business-day rule the difference is "
            "≤3 days and IV impact is small."
        ),
    }


async def get_viop_term_structure(
    underlying: str,
    as_of: str | None = None,
) -> dict[str, Any]:
    """Futures-only term structure for one underlying, sorted by expiry."""
    try:
        rows = await fetch_term_structure(underlying=underlying, as_of=as_of)
    except SourceError as e:
        if "endpoint discovery pending" in str(e):
            return wip_payload("viop", str(e))
        return {"error": "viop_error", "detail": str(e)}

    return {
        "source": "İş Yatırım — viop.aspx (futures only)",
        "underlying": underlying,
        "as_of": rows[0].trade_date if rows else as_of,
        "count": len(rows),
        "term_structure": [
            {
                "contract_code": r.contract.contract_code,
                "expiry_year": r.contract.expiry_year,
                "expiry_month": r.contract.expiry_month,
                "last_price": r.last_price,
                "percent_change": r.percent_change,
                "absolute_change": r.absolute_change,
                "volume_tl": r.volume_tl,
                "open_interest": r.open_interest,
            }
            for r in rows
        ],
        "notes": (
            "Adjacent-month basis can be inferred from last_price. For a "
            "spot/futures basis or fair-value calculation, combine with "
            "get_yield_curve and a spot data source via "
            "calculate_basis_fair_value."
        ),
    }


# -----------------------------------------------------------------------------
# MKK — foreign ownership
# -----------------------------------------------------------------------------
async def get_foreign_ownership(
    ticker: str,
    since: str | None = None,
    until: str | None = None,
) -> dict[str, Any]:
    """Daily foreign-ownership ratio (% of free float) for one BIST ticker."""
    try:
        points = await fetch_foreign_ownership(ticker, since=since, until=until)
    except SourceError as e:
        if "endpoint discovery pending" in str(e):
            return wip_payload("mkk", str(e))
        return {"error": "mkk_error", "detail": str(e)}

    return {
        "source": "MKK (Merkezi Kayıt Kuruluşu) — daily ownership snapshot",
        "ticker": ticker,
        "count": len(points),
        "series": [
            {
                "date": p.date,
                "foreign_pct_of_freefloat": p.foreign_pct_of_freefloat,
                "foreign_pct_of_total": p.foreign_pct_of_total,
                "foreign_investor_count": p.foreign_investor_count,
            }
            for p in points
        ],
        "disclaimer": (
            "Free-float definition follows MKK convention; some delisted or "
            "newly listed companies may report partial history."
        ),
    }


async def get_mkk_market_stats(
    pdf_url: str | None = None,
    use_cache: bool = True,
    cache_ttl_seconds: int = 24 * 3600,
) -> dict[str, Any]:
    """Marketwide MKK system-statistics (monthly time series) from PDF.

    The MKK publishes a monthly PDF with a 12-month rolling matrix of:
        - account openings
        - total investors
        - investors holding equities, gov debt, corp bonds, mutual funds,
          structured products, etc.
        - securities transfers (count + nominal + market value)
        - total transactions (count + nominal + market value)

    A trend break in any row is a macro tell for Turkish retail
    participation. Cached 24h; the PDF only changes monthly.
    """
    try:
        stats = await fetch_market_stats(
            pdf_url=pdf_url,
            use_cache=use_cache,
            cache_ttl_seconds=cache_ttl_seconds,
        )
    except SourceError as e:
        if "endpoint discovery pending" in str(e):
            return wip_payload("mkk", str(e))
        return {"error": "mkk_error", "detail": str(e)}

    # Build a quick-look snapshot from the latest column.
    latest_idx = len(stats.months) - 1 if stats.months else -1
    latest_month = stats.months[latest_idx] if latest_idx >= 0 else None

    latest_snapshot: dict[str, float | None] = {}
    history: list[dict[str, Any]] = []
    for r in stats.rows:
        history.append({
            "row_id": r.row_id,
            "metric": r.metric,
            "monthly_values": r.monthly_values,
        })
        if latest_idx >= 0 and latest_idx < len(r.monthly_values):
            latest_snapshot[r.metric] = r.monthly_values[latest_idx]

    return {
        "source": "MKK — System Statistics monthly bulletin (English)",
        "source_url": stats.source_url,
        "fetched_at": stats.fetched_at,
        "months": stats.months,
        "latest_month": latest_month,
        "latest_snapshot": latest_snapshot,
        "history": history,
        "notes": (
            "Each metric carries a full monthly time series (one value "
            "per month in the `months` array, oldest-first). Use this "
            "for retail-vs-institutional, equity-vs-fixed-income and "
            "transaction-throughput trend reads."
        ),
    }


# -----------------------------------------------------------------------------
# Pine recipe helpers (companion to tradesdontlie/tradingview-mcp)
# -----------------------------------------------------------------------------
def list_pine_recipes() -> dict[str, Any]:
    """Enumerate TR-aware Pine v6 recipe templates shipped with this MCP."""
    return {
        "recipes": list_recipes(),
        "usage": (
            "Call render_pine_recipe(name, data) to fill placeholders with "
            "live values, then hand the resulting Pine code to "
            "tradesdontlie/tradingview-mcp via `pine_new` + `pine_smart_compile`."
        ),
    }


async def render_pine_recipe(
    name: str,
    data: dict[str, Any] | None = None,
    auto_fetch: bool = False,
    client: EVDSClient | None = None,
) -> dict[str, Any]:
    """Render a Pine recipe with placeholders substituted.

    If `auto_fetch=True` and the recipe is `tr_macro_backdrop`, the MCP will
    populate macro placeholders itself by pulling the latest policy rate,
    corridor and CPI from EVDS. The caller can still pass `data` to override
    individual fields (notably PPK dates, which we cannot infer from EVDS).
    """
    payload: dict[str, Any] = dict(data or {})

    if auto_fetch and name == "tr_macro_backdrop":
        try:
            macro = await _fetch_macro_snapshot(client)
        except EVDSError as e:
            return {"error": "evds_error", "detail": str(e)}
        for k, v in macro.items():
            payload.setdefault(k, v)

    try:
        body = render_recipe(name, payload)
    except KeyError as e:
        return {"error": "unknown_recipe", "detail": str(e)}
    except ValueError as e:
        return {"error": "missing_placeholders", "detail": str(e)}

    return {
        "recipe": name,
        "pine_v6_source": body,
        "next_step": (
            "Hand pine_v6_source to tradesdontlie/tradingview-mcp: "
            "call pine_new then pine_smart_compile."
        ),
    }


async def _fetch_macro_snapshot(
    client: EVDSClient | None = None,
) -> dict[str, Any]:
    """Pull the macro values needed by tr_macro_backdrop from EVDS.

    Notes on series semantics:
    - `TP.APIFON4` is the 1-week repo policy rate (the press headline).
    - `TP.BISTTLREF.ORAN` is TLREF — the post-2024 effective overnight TL
      rate, used as the corridor proxy (legacy APIFON1/2 retired in 2024).
    - CPI is rebased to 2025=100 and published as an INDEX, not a YoY
      change, so we compute YoY = (latest / value_12m_ago) - 1.
    """
    client = client or EVDSClient()
    today = date.today()
    # Rates: 60-day window is plenty. CPI: need 13 months for YoY.
    rate_start = today - timedelta(days=60)
    cpi_start = today - timedelta(days=400)

    rate_codes = list(POLICY_RATE_SERIES.values())
    rate_obs = await client.get_series(rate_codes, start=rate_start, end=today)
    cpi_obs = await client.get_series([CPI_HEADLINE], start=cpi_start, end=today)

    by_code: dict[str, list[EVDSObservation]] = {}
    for o in [*rate_obs, *cpi_obs]:
        by_code.setdefault(o.series_code, []).append(o)

    def _latest(code: str) -> float | None:
        for o in reversed(by_code.get(code, [])):
            if o.value is not None:
                return o.value
        return None

    def _value_n_months_ago(code: str, months: int) -> float | None:
        non_null = [o for o in by_code.get(code, []) if o.value is not None]
        if len(non_null) <= months:
            return None
        # Series is monthly; the value `months` rows before the latest is
        # the YoY comparison point.
        return non_null[-(months + 1)].value

    cpi_now = _latest(CPI_HEADLINE)
    cpi_12m = _value_n_months_ago(CPI_HEADLINE, 12)
    cpi_yoy_pct = (
        (cpi_now / cpi_12m - 1.0) * 100.0
        if cpi_now is not None and cpi_12m
        else 0.0
    )

    return {
        "POLICY_RATE_PCT": _latest(POLICY_RATE_SERIES["policy_rate_1w_repo"]) or 0.0,
        # The corridor concept was retired in 2024; we report TLREF + BIST
        # overnight repo as the practical "effective overnight" pair.
        "O_NIGHT_LENDING": _latest(POLICY_RATE_SERIES["tlref_overnight"]) or 0.0,
        "O_NIGHT_BORROWING": _latest(POLICY_RATE_SERIES["bist_overnight_repo"]) or 0.0,
        "CPI_YOY_PCT": cpi_yoy_pct,
        "PPK_DATES_JSON": [],  # caller injects if known
        "AS_OF_DATE": today.isoformat(),
    }


# -----------------------------------------------------------------------------
# Takasbank — daily VIOP margin / collateral parameters (margin call signal)
# -----------------------------------------------------------------------------
async def get_viop_margin_parameters(
    trade_date: str | None = None,
    underlying: str | None = None,
    only_changed: bool = False,
) -> dict[str, Any]:
    """Daily Takasbank initial/maintenance margin parameters per VIOP contract.

    A sharp jump in `initial_margin` is the canary signal: when the CCP
    tightens, brokers start issuing margin calls (teminat tamamlama
    çağrısı) to clients whose collateral has fallen below the new
    requirement.

    Set `only_changed=true` to return only contracts whose initial margin
    moved versus the prior trading day.
    """
    try:
        rows = await fetch_margin_parameters(
            trade_date=trade_date,
            underlying_filter=underlying,
            only_changed=only_changed,
        )
    except SourceError as e:
        if "endpoint discovery pending" in str(e):
            return wip_payload("takasbank", str(e))
        return {"error": "takasbank_error", "detail": str(e)}

    return {
        "source": "Takasbank — VIOP daily risk parameters",
        "trade_date": rows[0].trade_date if rows else trade_date,
        "underlying_filter": underlying,
        "only_changed": only_changed,
        "count": len(rows),
        "parameters": [
            {
                "contract_code": r.contract_code,
                "underlying": r.underlying,
                "initial_margin": r.initial_margin,
                "maintenance_margin": r.maintenance_margin,
                "price_scan_range": r.price_scan_range,
                "spread_credit": r.spread_credit,
                "initial_margin_prev": r.initial_margin_prev,
                "pct_change_initial": r.pct_change_initial,
            }
            for r in rows
        ],
        "notes": (
            "True margin-call events per trader are broker-confidential. "
            "What's exposed here is the parameter side — a sharp jump in "
            "initial_margin (>5%) reliably precedes broker calls."
        ),
    }


async def get_viop_margin_call_alerts(
    trade_date: str | None = None,
    threshold_pct: float = 5.0,
) -> dict[str, Any]:
    """Contracts whose initial margin moved by more than `threshold_pct`%.

    A simple alert filter on top of `get_viop_margin_parameters` — what most
    risk desks scan for first thing each morning.
    """
    try:
        rows = await fetch_margin_change_alerts(
            trade_date=trade_date, threshold_pct=threshold_pct
        )
    except SourceError as e:
        if "endpoint discovery pending" in str(e):
            return wip_payload("takasbank", str(e))
        return {"error": "takasbank_error", "detail": str(e)}

    rows_sorted = sorted(
        rows, key=lambda r: abs(r.pct_change_initial or 0), reverse=True
    )
    return {
        "source": "Takasbank — VIOP daily risk parameters",
        "trade_date": rows_sorted[0].trade_date if rows_sorted else trade_date,
        "threshold_pct": threshold_pct,
        "count": len(rows_sorted),
        "alerts": [
            {
                "contract_code": r.contract_code,
                "underlying": r.underlying,
                "initial_margin": r.initial_margin,
                "initial_margin_prev": r.initial_margin_prev,
                "pct_change_initial": r.pct_change_initial,
            }
            for r in rows_sorted
        ],
        "interpretation": (
            "Positive pct_change_initial = CCP tightening. Holders of long "
            "or short positions in these contracts may face margin calls "
            "today. Cross-check with get_viop_settlement to see if a price "
            "move (rather than vol regime change) drove the tightening."
        ),
    }


async def get_viop_dashboard(
    use_cache: bool = True,
    cache_ttl_seconds: int = 6 * 3600,
) -> dict[str, Any]:
    """Marketwide VIOP aggregate margin snapshot from Takasbank dashboard.

    Returns the same 5 numbers a trader sees on the live Takasbank
    statistics page:
        - margined_account_count
        - transaction_margin_total      (TL)
        - guarantee_fund_margin_total   (TL)
        - margin_call_total             (TL)  ← marketwide stress signal
        - required_margin_total         (TL)

    Cache: file-backed, default 6h TTL. Override with use_cache=false
    to force a live fetch (will hit Takasbank's WAF; use sparingly).
    """
    try:
        snap = await fetch_viop_margin_snapshot(
            use_cache=use_cache, cache_ttl_seconds=cache_ttl_seconds
        )
    except SourceError as e:
        if "endpoint discovery pending" in str(e):
            return wip_payload("takasbank", str(e))
        return {"error": "takasbank_error", "detail": str(e)}

    # Derived health ratio: how much of the required margin is currently
    # in margin-call status. A spike here = brokers are pulling money in.
    call_ratio_pct = None
    if snap.required_margin_total and snap.margin_call_total is not None:
        call_ratio_pct = (snap.margin_call_total / snap.required_margin_total) * 100.0

    # Total cash + non-cash margin posted, if both halves came through.
    def _sum_compound(d: dict[str, float | None] | None) -> float | None:
        if not d:
            return None
        vals = [v for v in d.values() if isinstance(v, int | float)]
        return float(sum(vals)) if vals else None

    transaction_margin_total = _sum_compound(snap.transaction_margin)
    guarantee_fund_total = _sum_compound(snap.guarantee_fund_margin)

    return {
        "source": "Takasbank — VIOP marketwide aggregate dashboard",
        "as_of": snap.as_of,
        "snapshot": {
            "margined_account_count": snap.margined_account_count,
            "margined_account_bireysel": snap.margined_account_bireysel,
            "margined_account_kurumsal": snap.margined_account_kurumsal,
            "transaction_margin_tl": snap.transaction_margin,
            "transaction_margin_total_tl": transaction_margin_total,
            "guarantee_fund_margin_tl": snap.guarantee_fund_margin,
            "guarantee_fund_total_tl": guarantee_fund_total,
            "margin_call_total_tl": snap.margin_call_total,
            "required_margin_total_tl": snap.required_margin_total,
            "margin_call_to_required_pct": call_ratio_pct,
            "profit_loss_total_tl": snap.profit_loss_total,
            "futures_volume_tl": snap.futures_volume_tl,
            "options_volume_tl": snap.options_volume_tl,
            "options_premium_volume_tl": snap.options_premium_volume_tl,
            "futures_oi_count": snap.futures_oi_count,
            "futures_oi_value_tl": snap.futures_oi_value_tl,
            "options_oi_count": snap.options_oi_count,
            "options_oi_value_tl": snap.options_oi_value_tl,
        },
        "interpretation": (
            "margin_call_total_tl is THE marketwide stress signal. A jump "
            "in margin_call_to_required_pct vs the prior trading day means "
            "the CCP is tightening collateral; brokers will issue calls. "
            "futures_volume_tl + options_volume_tl + open interest are the "
            "VIOP activity headline. Per-contract SPAN parameters are not "
            "yet wired (v0.3)."
        ),
    }


# -----------------------------------------------------------------------------
# Options math — Black-Scholes greeks, IV
# -----------------------------------------------------------------------------
def calculate_option_greeks(
    spot: float,
    strike: float,
    days_to_expiry: float,
    volatility_pct: float,
    risk_free_rate_pct: float,
    dividend_yield_pct: float = 0.0,
    style: str = "call",
) -> dict[str, Any]:
    """Black-Scholes price + delta/gamma/theta/vega/rho.

    All percentages passed as plain percent (e.g. 45 = %45). Theta returned
    is per-year; divide by 365 for daily decay.
    """
    try:
        g = black_scholes(
            spot=float(spot),
            strike=float(strike),
            time_to_expiry=float(days_to_expiry) / 365.0,
            volatility=float(volatility_pct) / 100.0,
            risk_free_rate=float(risk_free_rate_pct) / 100.0,
            dividend_yield=float(dividend_yield_pct) / 100.0,
            style=style,
        )
    except (ValueError, ArithmeticError) as e:
        return {"error": "calculation_failed", "detail": str(e)}

    return {
        "inputs": {
            "spot": spot,
            "strike": strike,
            "days_to_expiry": days_to_expiry,
            "volatility_pct": volatility_pct,
            "risk_free_rate_pct": risk_free_rate_pct,
            "dividend_yield_pct": dividend_yield_pct,
            "style": style,
        },
        "price": g.price,
        "delta": g.delta,
        "gamma": g.gamma,
        "theta_per_year": g.theta_per_year,
        "theta_per_day": g.theta_per_year / 365.0,
        "vega": g.vega,
        "rho": g.rho,
        "notes": (
            "European-style Black-Scholes; VIOP options are physically "
            "settled European, so this is the correct model. Use the "
            "yield curve at the appropriate tenor for risk_free_rate_pct."
        ),
    }


def calculate_implied_volatility(
    market_price: float,
    spot: float,
    strike: float,
    days_to_expiry: float,
    risk_free_rate_pct: float,
    dividend_yield_pct: float = 0.0,
    style: str = "call",
) -> dict[str, Any]:
    """Solve Black-Scholes for sigma given a market option price."""
    try:
        iv = implied_volatility(
            market_price=float(market_price),
            spot=float(spot),
            strike=float(strike),
            time_to_expiry=float(days_to_expiry) / 365.0,
            risk_free_rate=float(risk_free_rate_pct) / 100.0,
            dividend_yield=float(dividend_yield_pct) / 100.0,
            style=style,
        )
    except (ValueError, ArithmeticError) as e:
        return {"error": "calculation_failed", "detail": str(e)}

    return {
        "implied_volatility_pct": iv * 100.0,
        "inputs": {
            "market_price": market_price,
            "spot": spot,
            "strike": strike,
            "days_to_expiry": days_to_expiry,
            "risk_free_rate_pct": risk_free_rate_pct,
            "dividend_yield_pct": dividend_yield_pct,
            "style": style,
        },
    }


# -----------------------------------------------------------------------------
# Portfolio Greeks aggregator — pure math, no network
# -----------------------------------------------------------------------------
def aggregate_portfolio_greeks(
    positions: list[dict[str, Any]],
) -> dict[str, Any]:
    """Net delta/gamma/vega/theta for a list of derivative + spot positions.

    Each position is repriced with Black-Scholes (for options) or treated
    as linear delta (futures/spot). Returns per-leg risk + totals + a
    per-underlying rollup so a risk desk can spot concentration.

    See `portfolio.py` docstring for the position schema. The function is
    pure math — no network, no cache — so call it freely.
    """
    try:
        return {
            "source": "bist-trader-mcp — portfolio.aggregate_portfolio_greeks",
            **_aggregate_portfolio_greeks(positions or []),
            "notes": (
                "Greeks are repriced from Black-Scholes; supply spot, strike, "
                "days_to_expiry, and either volatility_pct or market_price for "
                "each option. Futures/spot legs contribute linear delta only. "
                "Theta_per_day = theta_per_year / 365."
            ),
        }
    except (TypeError, ValueError) as e:
        return {"error": "bad_input", "detail": str(e)}


# -----------------------------------------------------------------------------
# Hazine — DİBS auctions
# -----------------------------------------------------------------------------
async def get_dibs_auctions(
    since: str | None = None,
    until: str | None = None,
    status: str | None = None,
    pdf_url: str | None = None,
) -> dict[str, Any]:
    """DİBS auction calendar parsed from Hazine's quarterly strategy PDF.

    Args:
        since: lower-bound auction date (default 30 days ago).
        until: upper-bound auction date (default +90 days).
        status: filter — "scheduled" | "completed" | "cancelled".
        pdf_url: optional override of the strategy PDF URL (useful when
            a fresher quarterly bulletin has been published).
    """
    try:
        auctions = await fetch_auctions(
            since=since, until=until, status=status, pdf_url=pdf_url
        )
    except SourceError as e:
        if "endpoint discovery pending" in str(e):
            return wip_payload("hazine", str(e))
        return {"error": "hazine_error", "detail": str(e)}

    return {
        "source": (
            "Hazine ve Maliye Bakanlığı — quarterly İç Borçlanma "
            "Stratejisi PDF (auction calendar)"
        ),
        "status_filter": status,
        "count": len(auctions),
        "auctions": [
            {
                "auction_id": a.auction_id,
                "auction_date": a.auction_date,
                "settlement_date": a.settlement_date,
                "maturity_date": a.maturity_date,
                "instrument": a.instrument,
                "tenor_days": a.tenor_days,
                "tenor_label": a.tenor_label,
                "issuance_method": a.issuance_method,
                "coupon_frequency": a.coupon_frequency,
                "status": a.status,
                "avg_yield_pct": a.avg_yield_pct,
                "cut_off_yield_pct": a.cut_off_yield_pct,
                "bid_amount": a.bid_amount,
                "accepted_amount": a.accepted_amount,
                "bid_to_cover": a.bid_to_cover,
            }
            for a in auctions
        ],
        "notes": (
            "Auction results (cut-off, bid/cover) are NOT in the strategy "
            "PDF — those are published as separate per-auction press "
            "releases that v0.3 will ingest."
        ),
    }


# -----------------------------------------------------------------------------
# Economic calendar — TCMB MPC + TÜİK CPI/PPI
# -----------------------------------------------------------------------------
def get_economic_calendar(
    since: str | None = None,
    until: str | None = None,
    categories: list[str] | None = None,
) -> dict[str, Any]:
    """TR macro & policy event calendar within a date window.

    Currently surfaces:
        - TCMB PPK (MPC) announcement dates — high importance
        - TÜİK TÜFE (CPI) release dates — 3rd business day each month
        - TÜİK Yİ-ÜFE (PPI) release dates — same publication day

    Args:
        since: YYYY-MM-DD (default: today - 7 days).
        until: YYYY-MM-DD (default: today + 90 days).
        categories: optional filter — ['monetary_policy', 'inflation', ...].
    """
    today = date.today()
    s = date.fromisoformat(since) if since else today - timedelta(days=7)
    u = date.fromisoformat(until) if until else today + timedelta(days=90)
    if s > u:
        return {"error": "bad_window", "detail": "since must be <= until"}

    events = _build_calendar(s, u, categories=categories)
    return {
        "source": (
            "bist-trader-mcp — static TCMB MPC schedule + TÜİK release pattern. "
            "MPC dates require yearly updating in calendar_data.py."
        ),
        "window": {"since": s.isoformat(), "until": u.isoformat()},
        "categories_filter": categories,
        "count": len(events),
        "events": [
            {
                "date": e.date,
                "event": e.event,
                "category": e.category,
                "importance": e.importance,
                "notes": e.notes,
            }
            for e in events
        ],
        "notes": (
            "TCMB MPC dates are authoritative until the year ends; TÜİK "
            "publish-day rule (3rd business day) has held since 2010. "
            "GSYH (GDP), işsizlik (unemployment), and external balance "
            "release dates can be added when needed."
        ),
    }


# -----------------------------------------------------------------------------
# FX forward / swap curve via covered interest-rate parity
# -----------------------------------------------------------------------------
_FX_SPOT_SERIES: dict[str, str] = {
    "USDTRY": USDTRY_SELLING,
    "EURTRY": EURTRY_SELLING,
}


async def get_fx_forward_curve(
    pair: str = "USDTRY",
    foreign_rate_pct: float = 4.5,
    spot: float | None = None,
    domestic_rate_pct: float | None = None,
    tenors: list[str] | None = None,
    client: EVDSClient | None = None,
) -> dict[str, Any]:
    """CIP-implied FX forward curve for USDTRY or EURTRY.

    If `spot` is not provided, the latest TCMB selling rate is fetched
    from EVDS. If `domestic_rate_pct` is not provided, the current TCMB
    1-week repo policy rate is used as the TL leg. The foreign leg must
    be supplied by the caller (we don't have a Fed-funds / ECB feed) —
    pass a sensible level (e.g. SOFR or EURIBOR closing) for the
    tenor of interest.

    Args:
        pair: "USDTRY" or "EURTRY".
        foreign_rate_pct: USD or EUR rate in percent.
        spot: override spot. If None, pulled from EVDS.
        domestic_rate_pct: override TL rate. If None, TCMB 1w policy used.
        tenors: list of tenor strings (e.g. ["1W","1M","3M","6M","1Y"]).
    """
    pair_norm = pair.upper().strip()
    if pair_norm not in _FX_SPOT_SERIES:
        return {
            "error": "unknown_pair",
            "detail": f"pair must be one of {sorted(_FX_SPOT_SERIES)}",
        }

    client = client or EVDSClient()
    today = date.today()
    fetch_window_start = today - timedelta(days=14)

    series_needed: list[str] = []
    if spot is None:
        series_needed.append(_FX_SPOT_SERIES[pair_norm])
    if domestic_rate_pct is None:
        series_needed.append(POLICY_RATE_SERIES["policy_rate_1w_repo"])

    if series_needed:
        try:
            obs = await client.get_series(series_needed, start=fetch_window_start, end=today)
        except EVDSError as e:
            return {"error": "evds_error", "detail": str(e)}
        series_map = _observations_to_series(obs)
        if spot is None:
            latest = _latest_non_null(series_map.get(_FX_SPOT_SERIES[pair_norm], []))
            if not latest or latest["value"] is None:
                return {
                    "error": "spot_unavailable",
                    "detail": f"EVDS returned no value for {pair_norm} in the last 14 days",
                }
            spot = float(latest["value"])
        if domestic_rate_pct is None:
            latest = _latest_non_null(
                series_map.get(POLICY_RATE_SERIES["policy_rate_1w_repo"], [])
            )
            if not latest or latest["value"] is None:
                return {
                    "error": "domestic_rate_unavailable",
                    "detail": "EVDS returned no value for TCMB 1w repo in the last 14 days",
                }
            domestic_rate_pct = float(latest["value"])

    try:
        points = _fx_forward_curve(
            spot=spot,
            domestic_rate_pct=domestic_rate_pct,
            foreign_rate_pct=foreign_rate_pct,
            tenors=tenors,
        )
    except (ValueError, ArithmeticError) as e:
        return {"error": "calculation_failed", "detail": str(e)}

    return {
        "source": (
            "TCMB EVDS (spot + TL policy rate) + caller-supplied foreign rate. "
            "Forwards computed via covered interest-rate parity."
        ),
        "pair": pair_norm,
        "spot": spot,
        "domestic_rate_pct": domestic_rate_pct,
        "foreign_rate_pct": foreign_rate_pct,
        "implied_diff_pct": (domestic_rate_pct or 0.0) - foreign_rate_pct,
        "curve": [
            {
                "tenor": p.tenor,
                "days": p.days,
                "forward_outright": p.forward_outright,
                "forward_points_pips": p.forward_points_pips,
            }
            for p in points
        ],
        "notes": (
            "Continuous compounding. Pip factor = 10,000 for 4-decimal "
            "TRY quotes. The Turkish onshore forward market is illiquid "
            "for non-bank participants; offshore NDF pricing typically "
            "tracks CIP-implied + a credit/regulatory premium that has "
            "ranged from a few bps to several hundred bps in stress."
        ),
    }


# -----------------------------------------------------------------------------
# Cross-asset — futures/spot basis fair value
# -----------------------------------------------------------------------------
def calculate_basis_fair_value(
    spot_price: float,
    futures_price: float,
    days_to_expiry: float,
    risk_free_rate_pct: float,
    dividend_yield_pct: float = 0.0,
) -> dict[str, Any]:
    """Cost-of-carry fair value of a futures contract vs observed market.

    Returns:
        - theoretical_futures_price = spot * exp((r - q) * T)
        - basis_bps = (futures - spot) / spot * 10000
        - deviation_bps = (futures - theoretical) / theoretical * 10000
        - implied_repo_rate_pct = implied dividend-adjusted carry implied by
          the actual quote (useful for spotting funding-stress signals).
    """
    if spot_price <= 0 or futures_price <= 0:
        return {"error": "bad_input", "detail": "prices must be positive"}
    if days_to_expiry <= 0:
        return {"error": "bad_input", "detail": "days_to_expiry must be positive"}

    t = days_to_expiry / 365.0
    r = risk_free_rate_pct / 100.0
    q = dividend_yield_pct / 100.0

    theoretical = spot_price * math.exp((r - q) * t)
    basis = futures_price - spot_price
    basis_bps = basis / spot_price * 10000
    deviation_bps = (futures_price - theoretical) / theoretical * 10000

    # implied repo: solve futures = spot * exp((r_impl - q) * T) for r_impl
    implied_repo = math.log(futures_price / spot_price) / t + q

    return {
        "inputs": {
            "spot_price": spot_price,
            "futures_price": futures_price,
            "days_to_expiry": days_to_expiry,
            "risk_free_rate_pct": risk_free_rate_pct,
            "dividend_yield_pct": dividend_yield_pct,
        },
        "theoretical_futures_price": theoretical,
        "basis": basis,
        "basis_bps": basis_bps,
        "deviation_from_fair_bps": deviation_bps,
        "implied_repo_rate_pct": implied_repo * 100.0,
        "interpretation": (
            "deviation_from_fair_bps > 0 means futures rich vs cost-of-carry "
            "(cash & carry arb candidate: sell futures, buy spot, fund via "
            "borrowing). < 0 means cheap (reverse cash & carry). |deviation| "
            "consistently > 50bps over multiple days is unusual for liquid "
            "BIST30 / USDTRY futures."
        ),
    }


# -----------------------------------------------------------------------------
# Real-time snapshot — "piyasa şu an ne durumda?"
# -----------------------------------------------------------------------------
async def get_turib_endeks_overview() -> dict[str, Any]:
    """TÜRİB public hububat/tarım endeks özeti (bilgi amaçlı, lisanslı feed değil)."""
    from .turib import fetch_turib_endeks_overview

    return await fetch_turib_endeks_overview()


async def get_bist_snapshot(
    tickers: list[str],
) -> dict[str, Any]:
    """Latest price / change / volume snapshot for 1-10 BIST or FX tickers.

    Backed by Yahoo Finance intraday data (15-min delayed). NOT real-time
    in the exchange feed sense — but covers the critical "şu an fiyat ne?"
    question.

    Args:
        tickers: BIST tickers (e.g. ["THYAO", "GARAN"]) or Yahoo symbols.
            Accepts also aliases like "USDTRY", "XU100". Max 10 per call.
    """
    try:
        snapshots = await _fetch_snapshot(tickers)
    except SourceError as e:
        return {"error": "snapshot_error", "detail": str(e)}

    return {
        "source": "Yahoo Finance (15-min delayed intraday)",
        "count": len(snapshots),
        "snapshots": [
            {
                "ticker": s.ticker,
                "last_price": s.last_price,
                "change": s.change,
                "change_pct": s.change_pct,
                "open": s.open,
                "day_high": s.day_high,
                "day_low": s.day_low,
                "previous_close": s.previous_close,
                "volume": s.volume,
                "market_state": s.market_state,
                "currency": s.currency,
                "as_of": s.as_of,
            }
            for s in snapshots
        ],
        "disclaimer": (
            "Prices are 15-minute delayed via Yahoo Finance. This is NOT a "
            "real-time feed. Do not use for order execution or HFT. For "
            "live L1/L2 data, use Matriks or Foreks."
        ),
    }


async def get_market_summary() -> dict[str, Any]:
    """One-shot overview of the Turkish market: indices, FX, commodities.

    Returns current snapshot of:
        - BIST indices: XU100, XU030, XBANK
        - FX: USDTRY, EURTRY, GBPTRY
        - Commodities: Gold (USD/oz), Brent crude
        - Crypto: BTC/USD
    All in a single parallel call. The "Bugün piyasa nasıl?" answer.
    """
    try:
        summary = await _fetch_market_summary()
    except SourceError as e:
        return {"error": "summary_error", "detail": str(e)}

    result: dict[str, Any] = {
        "source": "Yahoo Finance (15-min delayed)",
        "categories": {},
    }

    indices = {}
    fx = {}
    commodities = {}
    crypto = {}

    for alias, snap in summary.items():
        entry = {
            "last": snap.last_price,
            "change": snap.change,
            "change_pct": snap.change_pct,
            "day_high": snap.day_high,
            "day_low": snap.day_low,
            "market_state": snap.market_state,
        }
        if alias in ("XU100", "XU030", "XBANK"):
            indices[alias] = entry
        elif alias in ("USDTRY", "EURTRY", "GBPTRY"):
            fx[alias] = entry
        elif alias in ("GOLD_USD", "BRENT"):
            commodities[alias] = entry
        elif alias in ("BTCUSD",):
            crypto[alias] = entry

    result["categories"] = {
        "bist_indices": indices,
        "fx": fx,
        "commodities": commodities,
        "crypto": crypto,
    }

    # Quick headline
    xu100 = summary.get("XU100")
    usdtry = summary.get("USDTRY")
    headline_parts = []
    if xu100 and xu100.last_price:
        sign = "+" if (xu100.change_pct or 0) >= 0 else ""
        headline_parts.append(f"XU100: {xu100.last_price:,.0f} ({sign}{xu100.change_pct:.2f}%)")
    if usdtry and usdtry.last_price:
        headline_parts.append(f"$/TL: {usdtry.last_price:.4f}")
    if headline_parts:
        result["headline"] = " | ".join(headline_parts)

    result["disclaimer"] = (
        "All prices are 15-minute delayed via Yahoo Finance. "
        "Not suitable for real-time trading decisions."
    )
    return result


# -----------------------------------------------------------------------------
# VIOP IV surface + spread screener (v0.3)
# -----------------------------------------------------------------------------
async def get_viop_iv_surface(
    underlying: str,
    spot_price: float,
    risk_free_rate_pct: float,
    dividend_yield_pct: float = 0.0,
    expiry_year: int | None = None,
    expiry_month: int | None = None,
    min_price: float = 0.01,
) -> dict[str, Any]:
    """Build a full IV surface from the live VIOP option chain.

    Returns per-quote IV + delta + moneyness, an ATM term structure,
    25-delta skew on the front month, and the front-vs-back vol slope.
    Pair this output with `find_viop_spread_opportunities` to scan for
    calendar / vertical / butterfly dislocations.

    Args:
        underlying: VIOP underlying (e.g. "XU030", "USD", "GARAN").
        spot_price: cash price in the same units as strikes.
        risk_free_rate_pct: TL risk-free at the option tenor (TLREF).
        dividend_yield_pct: usually 0 for indices / FX.
        expiry_year, expiry_month: pin to one expiry, else all expiries.
        min_price: skip option quotes below this last_price (illiquid noise).
    """
    try:
        chain = await fetch_option_chain(
            underlying=underlying,
            expiry_year=expiry_year,
            expiry_month=expiry_month,
        )
    except SourceError as e:
        return {"error": "viop_error", "detail": str(e)}

    surface = build_iv_surface(
        chain=chain,
        spot=float(spot_price),
        risk_free_rate_pct=float(risk_free_rate_pct),
        dividend_yield_pct=float(dividend_yield_pct),
        min_price=float(min_price),
    )
    surface["source"] = "bist-trader-mcp — iv_surface.build_iv_surface"
    surface["underlying"] = underlying.upper()
    return surface


def find_viop_spread_opportunities(
    surface: dict[str, Any],
    strategy: str = "calendar",
    min_edge_vol_pts: float = 3.0,
    max_results: int = 20,
) -> dict[str, Any]:
    """Scan an IV surface for calendar / vertical / butterfly dislocations.

    Call `get_viop_iv_surface` first and pass its return value as `surface`.

    Args:
        surface: output of get_viop_iv_surface.
        strategy: "calendar" | "vertical" | "butterfly".
        min_edge_vol_pts: ignore candidates with smaller IV dispersion.
        max_results: cap on returned candidates.
    """
    try:
        cands = find_spread_opportunities(
            surface=surface,
            strategy=strategy,
            min_edge_vol_pts=float(min_edge_vol_pts),
            max_results=int(max_results),
        )
    except ValueError as e:
        return {"error": "bad_input", "detail": str(e)}
    return {
        "strategy": strategy,
        "min_edge_vol_pts": min_edge_vol_pts,
        "underlying": surface.get("underlying"),
        "candidates": cands,
        "notes": (
            "Edge is in vol points (e.g. 5.0 = 5 IV%). Positive 'edge_vol_pts' "
            "for calendars/butterflies means the front/wings are rich; for "
            "verticals it's just the |Δσ| magnitude. These are candidates — "
            "validate liquidity, bid-ask, and pin risk before trading."
        ),
    }


# -----------------------------------------------------------------------------
# Portfolio VaR + stress testing (v0.3)
# -----------------------------------------------------------------------------
def calculate_portfolio_var(
    positions: list[dict[str, Any]],
    confidence: float = 0.99,
    horizon_days: int = 1,
    annual_volatility_pct: float = 30.0,
    method: str = "parametric",
    historical_returns: list[float] | None = None,
) -> dict[str, Any]:
    """Portfolio Value-at-Risk under parametric or historical method.

    Parametric: assumes normal returns at `annual_volatility_pct`. Adds a
    gamma adjustment for short-convexity portfolios.

    Historical: uses `historical_returns` (decimal daily returns of a
    representative underlying) to compute the empirical quantile loss on
    the delta-equivalent notional.

    See `portfolio.calculate_portfolio_var` for full semantics.
    """
    try:
        return {
            "source": "bist-trader-mcp — portfolio.calculate_portfolio_var",
            **_calc_var(
                positions or [],
                confidence=float(confidence),
                horizon_days=int(horizon_days),
                annual_volatility_pct=float(annual_volatility_pct),
                method=str(method),
                historical_returns=historical_returns,
            ),
            "notes": (
                "Parametric VaR is a first-order risk number — pair with "
                "stress_test_portfolio for non-linear scenarios. ES (Expected "
                "Shortfall) is the average loss conditional on exceeding VaR."
            ),
        }
    except (TypeError, ValueError) as e:
        return {"error": "bad_input", "detail": str(e)}


def stress_test_portfolio(
    positions: list[dict[str, Any]],
    scenarios: list[str] | None = None,
    custom_scenarios: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Reprice the portfolio under named shock scenarios.

    Built-in scenarios: rates+200bp, rates-200bp, tl_devalue_20pct,
    xu030_-10pct, xu030_+10pct, vol_crush_-30pct_rel, vol_spike_+50pct_rel,
    broad_-5pct, broad_+5pct.

    Each result row contains pnl_amount, pnl_pct_of_gross, and the shock
    spec applied. Results are sorted from worst to best P&L.
    """
    try:
        return {
            "source": "bist-trader-mcp — portfolio.stress_test_portfolio",
            **_stress_test(
                positions or [],
                scenarios=scenarios,
                custom_scenarios=custom_scenarios,
            ),
        }
    except (TypeError, ValueError) as e:
        return {"error": "bad_input", "detail": str(e)}


# -----------------------------------------------------------------------------
# Observability — cache + source health
# -----------------------------------------------------------------------------
def get_health_status() -> dict[str, Any]:
    """Report freshness of cached data sources + Playwright availability.

    Returns each known cache key's age + TTL, and a summary of whether the
    optional browser-automation extras are installed.
    """
    from datetime import datetime, timezone

    from ._browser import playwright_available
    from ._cache import cache_path_for

    tracked = [
        ("takasbank.viop_margin_snapshot", 6 * 3600, "Takasbank VIOP dashboard"),
        ("viop.snapshot", 3600, "İş Yatırım VIOP per-contract"),
        ("mkk.market_stats:auto", 24 * 3600, "MKK monthly system stats"),
    ]
    rows = []
    now = datetime.now(timezone.utc)
    for key, ttl, label in tracked:
        path = cache_path_for(key)
        entry = {"key": key, "label": label, "ttl_seconds": ttl}
        if not path.is_file():
            entry["status"] = "no_cache"
            entry["age_seconds"] = None
            entry["fresh"] = False
        else:
            try:
                import json as _json
                with path.open("r", encoding="utf-8") as f:
                    data = _json.load(f)
                saved_at = datetime.fromisoformat(str(data.get("saved_at", "")))
                if saved_at.tzinfo is None:
                    saved_at = saved_at.replace(tzinfo=timezone.utc)
                age = int((now - saved_at).total_seconds())
                entry["status"] = "cached"
                entry["age_seconds"] = age
                entry["saved_at"] = saved_at.isoformat()
                entry["fresh"] = age <= ttl
            except Exception as e:
                entry["status"] = f"cache_unreadable: {type(e).__name__}"
                entry["age_seconds"] = None
                entry["fresh"] = False
        rows.append(entry)

    return {
        "source": "bist-trader-mcp — health",
        "as_of": now.isoformat(),
        "playwright_available": playwright_available(),
        "evds_api_key_set": _evds_key_present(),
        "caches": rows,
        "notes": (
            "fresh=true → most recent fetch is within TTL; false → next call "
            "will hit the upstream. playwright_available=false disables the "
            "Takasbank dashboard scraper."
        ),
    }


def _evds_key_present() -> bool:
    import os
    return bool(os.environ.get("TCMB_EVDS_API_KEY"))


# -----------------------------------------------------------------------------
# Crypto — CoinGecko spot + Binance klines / funding / OI (v0.4)
# -----------------------------------------------------------------------------
async def get_crypto_spots(
    coin_ids: list[str],
    vs_currency: str = "usd",
) -> dict[str, Any]:
    """Spot snapshots for a list of CoinGecko coin slugs.

    Examples: ["bitcoin", "ethereum", "solana", "binancecoin"].
    Returns price, market cap, 24h volume, 24h and 7d % changes, ATH.
    """
    try:
        spots = await fetch_coin_spots(coin_ids=coin_ids or [],
                                       vs_currency=vs_currency)
    except SourceError as e:
        return {"error": "coingecko_error", "detail": str(e)}
    return {
        "source": "CoinGecko",
        "vs_currency": vs_currency,
        "coins": [s.__dict__ for s in spots],
    }


async def get_crypto_klines(
    symbol: str,
    interval: str = "1d",
    limit: int = 200,
) -> dict[str, Any]:
    """OHLCV klines from Binance spot. Symbol e.g. 'BTCUSDT', 'ETHUSDT'.
    Intervals: 1m,5m,15m,1h,4h,1d,1w. Max 1000 bars."""
    try:
        klines = await fetch_binance_klines(symbol=symbol, interval=interval,
                                             limit=limit)
    except SourceError as e:
        return {"error": "binance_error", "detail": str(e)}
    return {
        "source": "Binance Spot",
        "symbol": symbol.upper(),
        "interval": interval,
        "count": len(klines),
        "klines": [k.__dict__ for k in klines],
    }


async def get_crypto_funding_rates(
    symbol: str,
    limit: int = 30,
) -> dict[str, Any]:
    """Recent funding rate history for a Binance USD-M perp.

    A high positive funding rate means longs are paying shorts — typically
    a sign of bullish leverage. Persistent positive funding often precedes
    long squeezes.
    """
    try:
        rates = await fetch_funding_rates(symbol=symbol, limit=limit)
    except SourceError as e:
        return {"error": "binance_fapi_error", "detail": str(e)}
    avg = sum(r.funding_rate for r in rates) / len(rates) if rates else None
    return {
        "source": "Binance USD-M Futures",
        "symbol": symbol.upper(),
        "count": len(rates),
        "average_funding_rate": avg,
        "annualised_avg_pct": (avg * 3 * 365 * 100) if avg is not None else None,
        "rates": [r.__dict__ for r in rates],
    }


async def get_crypto_open_interest(
    symbol: str,
    period: str = "1h",
    limit: int = 30,
) -> dict[str, Any]:
    """Open interest history for a Binance USD-M perp."""
    try:
        oi = await fetch_open_interest_history(symbol=symbol, period=period,
                                                limit=limit)
    except SourceError as e:
        return {"error": "binance_fapi_error", "detail": str(e)}
    return {
        "source": "Binance USD-M Futures",
        "symbol": symbol.upper(),
        "period": period,
        "count": len(oi),
        "open_interest_history": oi,
    }


# -----------------------------------------------------------------------------
# Global spot FX (Frankfurter / ECB) — v0.4
# -----------------------------------------------------------------------------
async def get_global_fx_spot(pair: str) -> dict[str, Any]:
    """Latest ECB reference rate for a major FX pair (e.g. EURUSD)."""
    try:
        spot = await fetch_fx_spot(pair=pair)
    except SourceError as e:
        return {"error": "fx_error", "detail": str(e)}
    return {
        "source": "ECB via Frankfurter",
        "pair": f"{spot.base}{spot.quote}",
        "rate": spot.rate,
        "as_of": spot.as_of,
        "notes": "Daily ECB reference, updated ~16:00 CET; not intraday.",
    }


async def get_global_fx_history(pair: str, days: int = 30) -> dict[str, Any]:
    """Daily history of a major FX pair (ECB reference rates)."""
    try:
        rows = await fetch_fx_history(pair=pair, days=days)
    except SourceError as e:
        return {"error": "fx_error", "detail": str(e)}
    return {
        "source": "ECB via Frankfurter",
        "pair": pair.upper(),
        "count": len(rows),
        "history": rows,
    }


async def get_global_fx_matrix(
    bases: list[str] | None = None,
    quotes: list[str] | None = None,
) -> dict[str, Any]:
    """N×M FX rate matrix for G10/EM screening. Defaults to G10 × EM majors."""
    from .global_fx import EM_QUOTES, G10_BASES
    bs = bases or G10_BASES
    qs = quotes or EM_QUOTES
    try:
        matrix = await fetch_fx_matrix(bases=bs, quotes=qs)
    except SourceError as e:
        return {"error": "fx_error", "detail": str(e)}
    return {
        "source": "ECB via Frankfurter",
        "bases": bs,
        "quotes": qs,
        "matrix": matrix,
    }


# -----------------------------------------------------------------------------
# Global markets pulse — indices, treasuries, commodities, crypto (v0.4)
# -----------------------------------------------------------------------------
async def get_global_pulse(
    categories: list[str] | None = None,
) -> dict[str, Any]:
    """One-shot global market snapshot bucketed by category.

    Categories: indices | treasuries | commodities | crypto.
    Default: all four.

    Returns SPX/NDX/DAX/FTSE/N225/HSI for indices,
    UST 3M/5Y/10Y/30Y yields, WTI/Brent/Gold/Silver/Copper/Natgas, and
    BTC/ETH/SOL/etc. Each with last price, change, % change.
    """
    try:
        pulse = await fetch_global_pulse(categories=categories)
    except SourceError as e:
        return {"error": "global_pulse_error", "detail": str(e)}

    out: dict[str, Any] = {
        "source": "Yahoo Finance (delayed)",
        "categories": {},
    }
    for cat, bucket in pulse.items():
        rendered = {}
        for alias, snap in bucket.items():
            rendered[alias] = {
                "last": snap.last_price,
                "change": snap.change,
                "change_pct": snap.change_pct,
                "day_high": snap.day_high,
                "day_low": snap.day_low,
                "currency": snap.currency,
                "market_state": snap.market_state,
            }
        out["categories"][cat] = rendered
    return out


# -----------------------------------------------------------------------------
# Technical indicators — pure math on any OHLCV series (v0.4)
# -----------------------------------------------------------------------------
def calculate_technicals(
    closes: list[float],
    highs: list[float] | None = None,
    lows: list[float] | None = None,
) -> dict[str, Any]:
    """Standard indicator snapshot from a closes series (and optional H/L).

    Indicators returned at the last bar:
      - SMA 20/50/200, EMA 12/26
      - RSI(14) + label (overbought/oversold/neutral)
      - MACD (12/26/9): macd line, signal, histogram
      - Bollinger Bands (20, 2σ): upper/lower/%B + label
      - ATR(14) if H/L provided

    Plus three categorical labels: trend (bullish/bearish/neutral),
    rsi (overbought/oversold/neutral), and bb (upper/lower/mid_band).
    """
    try:
        snap = _tech_snapshot(closes=closes or [], highs=highs, lows=lows)
    except (TypeError, ValueError) as e:
        return {"error": "bad_input", "detail": str(e)}
    return {
        "source": "bist-trader-mcp — technicals.compute_snapshot",
        "bars_in": len(closes or []),
        "snapshot": snap.__dict__,
        "notes": (
            "All indicators evaluated at the last bar of `closes`. Pass H/L "
            "of equal length to enable ATR. RSI labels use 30/70 default "
            "thresholds; BB labels at %B 0.05/0.95."
        ),
    }


# -----------------------------------------------------------------------------
# Crypto Fear & Greed (v0.5)
# -----------------------------------------------------------------------------
async def get_crypto_fear_greed(limit: int = 30) -> dict[str, Any]:
    """Crypto Fear & Greed Index history (alternative.me).

    0-25 Extreme Fear → 75-100 Extreme Greed. A composite of momentum,
    volume, social, dominance, and Google Trends. Contrarian signal.
    """
    try:
        points = await fetch_fear_greed(limit=limit)
    except SourceError as e:
        return {"error": "fng_error", "detail": str(e)}
    latest = points[0] if points else None
    return {
        "source": "alternative.me",
        "latest": latest.__dict__ if latest else None,
        "count": len(points),
        "history": [p.__dict__ for p in points],
        "notes": (
            "Data is daily. 'Extreme Fear' (≤25) historically a buy zone, "
            "'Extreme Greed' (≥75) a caution zone — both contrarian signals."
        ),
    }


# -----------------------------------------------------------------------------
# Deribit BTC/ETH option chain + surface (v0.5)
# -----------------------------------------------------------------------------
async def get_deribit_iv_surface(
    currency: str = "BTC",
    spot_price: float | None = None,
) -> dict[str, Any]:
    """Build the live IV surface for BTC or ETH options on Deribit.

    Deribit publishes server-computed mark_iv already, so this is fast.
    If `spot_price` is omitted, the latest Binance perp price is fetched.

    Output shape mirrors get_viop_iv_surface so the same prompts /
    Pine recipes work for crypto.
    """
    try:
        chain = await fetch_deribit_option_chain(currency=currency)
    except SourceError as e:
        return {"error": "deribit_error", "detail": str(e)}

    # If user didn't supply spot, infer via Binance index price
    if spot_price is None:
        from .crypto import fetch_binance_klines
        try:
            klines = await fetch_binance_klines(
                symbol=f"{currency}USDT", interval="1m", limit=1,
            )
            spot_price = klines[-1].close if klines else None
        except SourceError:
            spot_price = None

    if not spot_price:
        return {"error": "no_spot", "detail":
                "spot_price unavailable; pass spot_price explicitly"}

    surface = build_deribit_surface(chain=chain, spot=float(spot_price))
    surface["source"] = "Deribit"
    return surface


# -----------------------------------------------------------------------------
# Correlation analytics (v0.5)
# -----------------------------------------------------------------------------
def calculate_correlation_matrix(
    series: dict[str, list[float]],
    method: str = "log",
) -> dict[str, Any]:
    """Pairwise correlation matrix of returns across multiple assets.

    Args:
        series: {asset_name: closes_list}. All inputs trimmed to the
            common minimum length.
        method: 'log' (default) or 'simple' return method.

    Returns the full N×N matrix, plus a top-10 by |ρ| and a bottom-10
    (most diversifying) ranking.
    """
    try:
        out = _correlation_matrix(series=series or {}, method=method)
    except (TypeError, ValueError) as e:
        return {"error": "bad_input", "detail": str(e)}
    return {
        "source": "bist-trader-mcp — correlation.correlation_matrix",
        **out,
    }


# -----------------------------------------------------------------------------
# Option strategy P&L simulator (v0.6)
# -----------------------------------------------------------------------------
def simulate_option_strategy(
    template: str | None = None,
    template_args: dict[str, Any] | None = None,
    legs: list[dict[str, Any]] | None = None,
    spot_low: float = 0.0,
    spot_high: float = 0.0,
    spot_steps: int = 41,
    risk_free_rate_pct: float = 0.0,
    dividend_yield_pct: float = 0.0,
    days_forward: float = 0,
    at_expiry: bool = True,
) -> dict[str, Any]:
    """Simulate an option strategy's P&L across a spot range.

    Two ways to define the strategy:
    1. Use a template: `template='long_straddle'`, `template_args={...}`.
       Available templates: long_straddle, short_straddle, long_strangle,
       iron_condor, butterfly, vertical_spread.
    2. Pass custom `legs` directly (dicts with instrument_type, qty,
       strike, right, days_to_expiry, volatility_pct, entry_price).

    Returns the full P&L grid plus max profit/loss, breakevens, and net
    debit/credit. Use `at_expiry=False` with `days_forward=N` to see
    P&L mid-life rather than at expiry.
    """
    try:
        if template:
            tmpl = STRATEGY_TEMPLATES.get(template)
            if tmpl is None:
                return {"error": "unknown_template",
                        "detail": f"templates: {list(STRATEGY_TEMPLATES)}"}
            strat_legs = tmpl(**(template_args or {}))
        elif legs:
            strat_legs = [
                StrategyLeg(
                    instrument_type=str(leg.get("instrument_type", "option")),
                    qty=float(leg.get("qty", 0)),
                    strike=leg.get("strike"),
                    right=leg.get("right"),
                    days_to_expiry=leg.get("days_to_expiry"),
                    volatility_pct=leg.get("volatility_pct"),
                    entry_price=leg.get("entry_price"),
                    multiplier=float(leg.get("multiplier", 1.0)),
                )
                for leg in legs
            ]
        else:
            return {"error": "missing_input",
                    "detail": "pass either template+template_args or legs"}

        if spot_low <= 0 or spot_high <= 0:
            # Auto-range from strikes
            strikes = [leg.strike for leg in strat_legs if leg.strike]
            if strikes:
                mid = sum(strikes) / len(strikes)
                spot_low = mid * 0.7
                spot_high = mid * 1.3
            else:
                return {"error": "missing_input",
                        "detail": "spot_low/spot_high required when no strikes"}

        result = simulate_strategy(
            legs=strat_legs,
            spot_range=(spot_low, spot_high),
            spot_steps=int(spot_steps),
            risk_free_rate_pct=float(risk_free_rate_pct),
            dividend_yield_pct=float(dividend_yield_pct),
            days_forward=float(days_forward),
            at_expiry=bool(at_expiry),
        )
        return {
            "source": "bist-trader-mcp — strategies.simulate_strategy",
            "template": template,
            **result,
        }
    except (TypeError, ValueError) as e:
        return {"error": "bad_input", "detail": str(e)}


def list_strategy_templates() -> dict[str, Any]:
    """List available strategy templates with their required args."""
    return {
        "templates": list(STRATEGY_TEMPLATES.keys()),
        "details": {
            "long_straddle": "strike, dte, vol_pct, [qty, multiplier, entry_call, entry_put]",
            "short_straddle": "strike, dte, vol_pct, [qty, multiplier, entry_call, entry_put]",
            "long_strangle": "put_strike, call_strike, dte, vol_pct, [...]",
            "iron_condor": "put_low, put_high, call_low, call_high, dte, vol_pct, [...]",
            "butterfly": "low, mid, high, right ('call'|'put'), dte, vol_pct, [...]",
            "vertical_spread":
                "low_strike, high_strike, right, direction ('bull'|'bear'), dte, vol_pct",
        },
    }


# -----------------------------------------------------------------------------
# Realized volatility (v0.6)
# -----------------------------------------------------------------------------
def calculate_realized_vol(
    closes: list[float],
    opens: list[float] | None = None,
    highs: list[float] | None = None,
    lows: list[float] | None = None,
    period: int = 30,
    annualise_days: int = 252,
    iv_atm_pct: float | None = None,
) -> dict[str, Any]:
    """Realized volatility panel: close-to-close, Parkinson, Garman-Klass.

    Provide just `closes` for CC; add highs+lows for Parkinson; add opens
    too for Garman-Klass. If `iv_atm_pct` (e.g. from get_viop_iv_surface
    or get_deribit_iv_surface) is supplied, returns IV/RV ratio and
    spread in vol points — the classic option mean-reversion signal.

    For crypto, set `annualise_days=365` (24/7 trading).
    """
    try:
        out = realized_vol_panel(
            opens=opens, highs=highs, lows=lows,
            closes=closes or [],
            period=int(period),
            annualise_days=int(annualise_days),
            iv_atm_pct=iv_atm_pct,
        )
    except (TypeError, ValueError) as e:
        return {"error": "bad_input", "detail": str(e)}
    return {
        "source": "bist-trader-mcp — realized_vol.realized_vol_panel",
        "bars_in": len(closes or []),
        **out,
        "notes": (
            "All vols annualised, percent units. CC underestimates intraday "
            "moves; Parkinson is ~5x more efficient; GK ~7x. Use the most "
            "data-rich estimator available."
        ),
    }


# -----------------------------------------------------------------------------
# News headlines (v0.6)
# -----------------------------------------------------------------------------
async def get_news_headlines(
    feeds: list[str] | None = None,
    limit_per_feed: int = 10,
) -> dict[str, Any]:
    """Financial news headlines from curated free RSS feeds.

    Available feeds: investing_top, investing_commodities, investing_fx,
    investing_economy, investing_crypto, yahoo_markets, reuters_business,
    coindesk. Default: investing_top + investing_economy + yahoo_markets.
    """
    try:
        items = await fetch_news(feeds=feeds, limit_per_feed=limit_per_feed)
    except SourceError as e:
        return {"error": "news_error", "detail": str(e)}
    return {
        "source": "RSS aggregator",
        "feeds_available": list(NEWS_FEEDS.keys()),
        "feeds_used": feeds or ["investing_top", "investing_economy", "yahoo_markets"],
        "count": len(items),
        "headlines": [i.__dict__ for i in items],
    }


# -----------------------------------------------------------------------------
# Backtest + performance + optimizer + Kelly (v0.8)
# -----------------------------------------------------------------------------
def backtest_strategy(
    closes: list[float],
    signals: list[float] | None = None,
    signal_generator: str | None = None,
    signal_args: dict[str, Any] | None = None,
    initial_equity: float = 100000.0,
    commission_pct: float = 0.05,
    slippage_pct: float = 0.05,
    risk_free_pct: float = 0.0,
    periods_per_year: int = 252,
) -> dict[str, Any]:
    """Event-driven backtest with cost model + full performance panel.

    Provide either `signals` directly, or `signal_generator` name from
    {sma_crossover, rsi_thresholds, bollinger_mean_reversion} with
    `signal_args` (e.g. {fast: 20, slow: 50}).

    Returns the full equity curve, returns, trades, and a performance
    panel (Sharpe, Sortino, Calmar, max drawdown, trade stats).
    """
    try:
        if signals is None:
            if signal_generator is None:
                return {"error": "missing_input",
                        "detail": "pass either signals or signal_generator"}
            gen = SIGNAL_GENERATORS.get(signal_generator)
            if gen is None:
                return {"error": "unknown_generator",
                        "detail": f"available: {list(SIGNAL_GENERATORS)}"}
            signals = gen(closes=closes or [], **(signal_args or {}))

        result = run_backtest(
            closes=closes or [],
            signals=signals or [],
            initial_equity=float(initial_equity),
            commission_pct=float(commission_pct),
            slippage_pct=float(slippage_pct),
            risk_free_pct=float(risk_free_pct),
            periods_per_year=int(periods_per_year),
        )
        return {
            "source": "bist-trader-mcp — backtest.run_backtest",
            "signal_generator": signal_generator,
            **result,
        }
    except (TypeError, ValueError) as e:
        return {"error": "bad_input", "detail": str(e)}


def list_signal_generators() -> dict[str, Any]:
    """List available built-in signal generators and their args."""
    return {
        "generators": list(SIGNAL_GENERATORS.keys()),
        "details": {
            "sma_crossover": "fast (int), slow (int), allow_short (bool)",
            "rsi_thresholds":
                "period (int=14), oversold (float=30), overbought (float=70), allow_short",
            "bollinger_mean_reversion": "period (int=20), std_dev (float=2.0), allow_short",
        },
    }


def calculate_performance_panel(
    returns: list[float],
    equity_curve: list[float] | None = None,
    trade_pnls: list[float] | None = None,
    risk_free_pct: float = 0.0,
    periods_per_year: int = 252,
) -> dict[str, Any]:
    """Standalone performance panel: Sharpe, Sortino, Calmar, max drawdown,
    annualised return/vol, trade stats (win rate, profit factor, expectancy).
    """
    try:
        panel = performance_panel(
            returns=returns or [],
            equity_curve=equity_curve,
            trade_pnls=trade_pnls,
            risk_free_pct=float(risk_free_pct),
            periods_per_year=int(periods_per_year),
        )
    except (TypeError, ValueError) as e:
        return {"error": "bad_input", "detail": str(e)}
    return {
        "source": "bist-trader-mcp — performance.performance_panel",
        **panel,
    }


def optimize_portfolio_markowitz(
    series: dict[str, list[float]],
    target_return_pct: float | None = None,
    risk_free_pct: float = 0.0,
    periods_per_year: int = 252,
) -> dict[str, Any]:
    """Markowitz portfolio optimization.

    Returns min-variance portfolio, max-Sharpe (tangency) portfolio, an
    optional target-return portfolio, and a 25-point efficient frontier.

    Shorting is allowed (unconstrained closed-form). For long-only, pick
    points from the frontier where all weights are positive.

    Pass {asset_name: closes_list} — sample covariance is computed from
    log returns. Min sample size: 30 observations per asset.
    """
    try:
        return {
            "source": "bist-trader-mcp — portfolio_opt.optimize_portfolio",
            **optimize_portfolio(
                series=series or {},
                target_return_pct=target_return_pct,
                risk_free_pct=float(risk_free_pct),
                periods_per_year=int(periods_per_year),
            ),
        }
    except (TypeError, ValueError) as e:
        return {"error": "bad_input", "detail": str(e)}


def calculate_kelly_sizing(
    win_probability: float | None = None,
    win_loss_ratio: float | None = None,
    annualised_return_pct: float | None = None,
    annualised_volatility_pct: float | None = None,
    risk_free_pct: float = 0.0,
    kelly_fractions: list[float] | None = None,
) -> dict[str, Any]:
    """Kelly sizing panel — bet Kelly + continuous Kelly + fractional.

    Provide either (win_probability, win_loss_ratio) for bet Kelly, or
    (annualised_return_pct, annualised_volatility_pct) for continuous,
    or both for cross-check.
    """
    try:
        return {
            "source": "bist-trader-mcp — kelly.kelly_panel",
            **kelly_panel(
                win_probability=win_probability,
                win_loss_ratio=win_loss_ratio,
                annualised_return_pct=annualised_return_pct,
                annualised_volatility_pct=annualised_volatility_pct,
                risk_free_pct=float(risk_free_pct),
                kelly_fractions=kelly_fractions,
            ),
        }
    except (TypeError, ValueError) as e:
        return {"error": "bad_input", "detail": str(e)}


def calculate_atr_position_size(
    equity: float,
    entry_price: float,
    atr: float,
    atr_multiple_stop: float = 2.0,
    risk_per_trade_pct: float = 1.0,
) -> dict[str, Any]:
    """Volatility-based position sizing using ATR-based stop loss.

    Sizes a trade so a loss at the ATR-multiple stop equals
    `risk_per_trade_pct`% of equity. Canonical "1% rule" for trend-following.
    """
    try:
        return {
            "source": "bist-trader-mcp — kelly.position_size_from_atr",
            **position_size_from_atr(
                equity=float(equity),
                entry_price=float(entry_price),
                atr=float(atr),
                atr_multiple_stop=float(atr_multiple_stop),
                risk_per_trade_pct=float(risk_per_trade_pct),
            ),
        }
    except (TypeError, ValueError) as e:
        return {"error": "bad_input", "detail": str(e)}


# -----------------------------------------------------------------------------
# Volatility forecasting (v0.7)
# -----------------------------------------------------------------------------
def calculate_ewma_volatility(
    returns: list[float],
    decay: float = 0.94,
    annualise_days: int = 252,
) -> dict[str, Any]:
    """EWMA (RiskMetrics) volatility forecast on a returns series.

    Pass log returns (use calculate_correlation_matrix's helper or just
    diff(log(closes))). Default decay 0.94 is the RiskMetrics convention
    for daily; use 0.97 for higher persistence. For crypto set
    annualise_days=365.
    """
    try:
        out = ewma_volatility(
            returns=returns or [],
            decay=float(decay),
            annualise_days=int(annualise_days),
        )
    except (TypeError, ValueError) as e:
        return {"error": "bad_input", "detail": str(e)}
    return {
        "source": "bist-trader-mcp — vol_forecast.ewma_volatility",
        **out,
    }


def calculate_garch_forecast(
    returns: list[float],
    horizon_days: int = 20,
    annualise_days: int = 252,
) -> dict[str, Any]:
    """Fit GARCH(1,1) (coarse grid MLE) and forecast a `horizon_days` vol path.

    Returns the fitted (ω, α, β), the stationary long-run vol, the 1-step
    forecast, and the full forecast path in annualised %.
    """
    try:
        out = garch_forecast(
            returns=returns or [],
            horizon_days=int(horizon_days),
            annualise_days=int(annualise_days),
        )
    except (TypeError, ValueError) as e:
        return {"error": "bad_input", "detail": str(e)}
    return {
        "source": "bist-trader-mcp — vol_forecast.garch_forecast",
        **out,
        "notes": (
            "GARCH parameters are coarse grid MLE (8³ trials). Adequate for "
            "risk overlays and IV/RV comparison but not portfolio-grade. "
            "α+β close to 1 → highly persistent vol; stationary_vol_pct is "
            "the unconditional long-run level."
        ),
    }


# -----------------------------------------------------------------------------
# BIST sector rotation (v0.7)
# -----------------------------------------------------------------------------
async def get_bist_sector_rotation(
    sectors: list[str] | None = None,
    period: str = "3mo",
    lookback_bars: int = 21,
    include_benchmark: bool = True,
) -> dict[str, Any]:
    """Rotation analytics across BIST sector indices.

    Computes total return, recent (5-bar) return, and relative strength vs.
    XU100 over `lookback_bars` for each sector. Returns ranked sectors
    (strongest first), top-3 + bottom-3 lists.

    Args:
        sectors: subset of BIST sectors (XBANK, XUSIN, XGIDA, ...).
            Defaults to all 17 sector indices.
        period: Yahoo Finance EOD range (1mo, 3mo, 6mo, 1y).
        lookback_bars: window for total return ranking (default 21).
        include_benchmark: pull XU100 too for relative-strength calc.
    """
    try:
        sector_closes = await fetch_sector_closes(sectors=sectors, period=period)
    except SourceError as e:
        return {"error": "bist_eod_error", "detail": str(e)}

    benchmark_closes = None
    if include_benchmark:
        try:
            from .bist_eod import fetch_eod_ohlcv
            bench = await fetch_eod_ohlcv("^XU100", period=period)
            benchmark_closes = [
                float(b.close)
                for b in bench
                if getattr(b, "close", None) is not None
            ]
        except SourceError:
            benchmark_closes = None

    metrics = compute_rotation_metrics(
        sector_closes=sector_closes,
        benchmark_closes=benchmark_closes,
        lookback_bars=int(lookback_bars),
    )
    return {
        "source": "bist-trader-mcp — bist_sectors",
        "benchmark": "XU100" if benchmark_closes else None,
        "available_sectors": list(BIST_SECTORS),
        **metrics,
    }


# -----------------------------------------------------------------------------
# On-chain — ETH gas + BTC network stats (v0.7)
# -----------------------------------------------------------------------------
async def get_eth_gas_oracle() -> dict[str, Any]:
    """Etherscan gas oracle — safe/propose/fast gas in Gwei + base fee.

    High fast gas (>50 Gwei) often coincides with NFT/airdrop activity or
    risk-on flow; sub-15 Gwei signals quiet markets. Optional
    ETHERSCAN_API_KEY env raises rate limit but no key works at 1 req/5s.
    """
    try:
        snap = await fetch_eth_gas_oracle()
    except SourceError as e:
        return {"error": "etherscan_error", "detail": str(e)}
    return {
        "source": "Etherscan",
        **snap.__dict__,
        "notes": (
            "Gas in Gwei. Suggested base fee is the EIP-1559 baseline. "
            "Rapid gas spikes can indicate large on-chain activity."
        ),
    }


async def get_btc_network_stats() -> dict[str, Any]:
    """Bitcoin network: hashrate, difficulty, supply, mempool.

    From blockchain.info public endpoints — no auth needed.
    """
    try:
        snap = await fetch_btc_network_stats()
    except SourceError as e:
        return {"error": "blockchain_info_error", "detail": str(e)}
    return {
        "source": "blockchain.info",
        **snap.__dict__,
    }


# -----------------------------------------------------------------------------
# Nelson-Siegel-Svensson yield curve fitting (v0.7)
# -----------------------------------------------------------------------------
def fit_yield_curve_nss(
    maturities_years: list[float],
    yields_pct: list[float],
    use_svensson: bool = True,
    output_tenors_years: list[float] | None = None,
) -> dict[str, Any]:
    """Fit Nelson-Siegel (3 betas + 1 λ) or NSS (4 betas + 2 λs) to a
    discrete yield curve and evaluate at any tenor.

    Used to derive a 3.5Y yield when only 2Y/5Y are observed, or to
    smooth noisy DİBS auction yields into a continuous curve.

    Args:
        maturities_years: list of observed τ in years.
        yields_pct: matching yields in percent.
        use_svensson: True → NSS (better fits for two humps), False → NS.
        output_tenors_years: list of tenors to evaluate. Default: 0.25, 0.5,
            1, 2, 3, 5, 7, 10, 15, 20, 30.
    """
    if output_tenors_years is None:
        output_tenors_years = [0.25, 0.5, 1, 2, 3, 5, 7, 10, 15, 20, 30]
    try:
        params = fit_nelson_siegel(
            maturities_years=maturities_years or [],
            yields_pct=yields_pct or [],
            use_svensson=bool(use_svensson),
        )
    except (TypeError, ValueError) as e:
        return {"error": "bad_input", "detail": str(e)}

    grid = evaluate_curve_grid(params, output_tenors_years)
    return {
        "source": "bist-trader-mcp — yield_fitter (NSS)",
        "params": params.__dict__,
        "fitted_curve": grid,
        "model": "NSS" if use_svensson else "NS",
        "notes": (
            "β₀ = long-rate, -β₁ = slope, β₂ = curvature near λ₁, β₃ = "
            "second curvature near λ₂ (NSS only). RMSE in percent."
        ),
    }


def calculate_rolling_correlation(
    series_a: list[float],
    series_b: list[float],
    window: int = 30,
    method: str = "log",
) -> dict[str, Any]:
    """Rolling correlation between two return series.

    Useful for spotting regime changes: e.g. when BTC-SPX correlation
    flips from -0.3 to +0.6 it suggests risk-on/risk-off behaviour has
    started dominating crypto.
    """
    try:
        vals = _rolling_correlation(
            series_a=series_a or [],
            series_b=series_b or [],
            window=int(window),
            method=method,
        )
    except (TypeError, ValueError) as e:
        return {"error": "bad_input", "detail": str(e)}
    return {
        "source": "bist-trader-mcp — correlation.rolling_correlation",
        "window": window,
        "method": method,
        "rolling_correlation": vals,
        "latest": next((v for v in reversed(vals) if v is not None), None),
    }


# -----------------------------------------------------------------------------
# Price action + position design (v0.9)
# -----------------------------------------------------------------------------
def analyze_price_action(
    closes: list[float],
    highs: list[float],
    lows: list[float],
    swing_lookback: int = 5,
    sr_tolerance_pct: float = 0.003,
) -> dict[str, Any]:
    """Swing structure, S/R clusters, bias, and suggested long/short setups."""
    try:
        return {
            "source": "bist-trader-mcp — price_action.analyze_price_action",
            **_analyze_price_action(
                closes=closes or [],
                highs=highs or [],
                lows=lows or [],
                swing_lookback=int(swing_lookback),
                sr_tolerance_pct=float(sr_tolerance_pct),
            ),
        }
    except (TypeError, ValueError) as e:
        return {"error": "bad_input", "detail": str(e)}


def analyze_range_imbalance(
    closes: list[float],
    highs: list[float],
    lows: list[float],
    *,
    volumes: list[float] | None = None,
    swing_lookback: int = 5,
    range_window: int = 48,
    market: str | None = None,
    symbol: str | None = None,
) -> dict[str, Any]:
    """Range box + FVG/IFVG stacks + liquidity sweeps — range-trade specialist view."""
    from .market_profiles import resolve_assistant_config
    from .pa_imbalances import build_imbalance_panel
    from .pa_range import build_range_panel
    from .price_action import analyze_price_action as _core_pa
    from .technicals import atr

    try:
        cfg = resolve_assistant_config(symbol or "SYNTH", market=market) if symbol else {}
        rw = int(cfg.get("range_window_bars", range_window)) if cfg else range_window
        pa = _core_pa(
            closes, highs, lows,
            volumes=volumes,
            swing_lookback=swing_lookback,
        )
        atr_val = pa.get("atr_14")
        if atr_val is None:
            series = atr(highs, lows, closes, 14)
            atr_val = next((v for v in reversed(series) if v is not None), None)
        range_panel = build_range_panel(
            highs, lows, closes,
            atr_val=atr_val,
            swing_high_prices=[s["price"] for s in pa.get("swing_highs", [])],
            swing_low_prices=[s["price"] for s in pa.get("swing_lows", [])],
            structure=pa.get("market_structure", "ranging"),
            window=rw,
        )
        box = range_panel.get("box") or {}
        imb = build_imbalance_panel(highs, lows, closes, atr_val=atr_val, range_box=box)
        return {
            "source": "bist-trader-mcp — analyze_range_imbalance",
            "symbol": symbol,
            "market_structure": pa.get("market_structure"),
            "bias": pa.get("bias"),
            "range": range_panel,
            "imbalances": imb,
            "suggested_long": pa.get("suggested_long_setup"),
            "suggested_short": pa.get("suggested_short_setup"),
            "notes": (
                "Range-trade mode: fade discount/premium, sweep fades, breakout at box break. "
                "Stacked FVGs in range_aligned boost confluence."
            ),
        }
    except (TypeError, ValueError) as e:
        return {"error": "bad_input", "detail": str(e)}


def design_trade_setup(
    symbol: str,
    direction: str,
    entry_price: float,
    stop_price: float,
    target_prices: list[float],
    equity: float = 100_000.0,
    risk_per_trade_pct: float = 1.0,
    min_risk_reward: float = 2.0,
    closes: list[float] | None = None,
    highs: list[float] | None = None,
    lows: list[float] | None = None,
) -> dict[str, Any]:
    """Full trade plan: R:R check, position sizing, approval gate."""
    if direction not in ("long", "short"):
        return {"error": "bad_input", "detail": "direction must be long or short"}
    return _design_trade_setup(
        symbol=symbol,
        direction=direction,  # type: ignore[arg-type]
        entry_price=float(entry_price),
        stop_price=float(stop_price),
        target_prices=target_prices or [],
        equity=float(equity),
        risk_per_trade_pct=float(risk_per_trade_pct),
        min_risk_reward=float(min_risk_reward),
        closes=closes,
        highs=highs,
        lows=lows,
    )


def design_from_price_action(
    symbol: str,
    closes: list[float],
    highs: list[float],
    lows: list[float],
    direction: str | None = None,
    equity: float = 100_000.0,
    risk_per_trade_pct: float = 1.0,
    min_risk_reward: float = 2.0,
) -> dict[str, Any]:
    """Analyze OHLCV, pick setup from structure, size and validate the plan."""
    dir_arg = None
    if direction is not None:
        if direction not in ("long", "short"):
            return {"error": "bad_input", "detail": "direction must be long or short"}
        dir_arg = direction  # type: ignore[assignment]
    return _design_from_price_action(
        symbol=symbol,
        closes=closes or [],
        highs=highs or [],
        lows=lows or [],
        direction=dir_arg,
        equity=float(equity),
        risk_per_trade_pct=float(risk_per_trade_pct),
        min_risk_reward=float(min_risk_reward),
    )


def portfolio_risk_check(
    equity: float,
    open_positions: list[dict[str, Any]] | None = None,
    proposed_trade: dict[str, Any] | None = None,
    rules: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Portfolio gate: max positions, total risk, single-asset exposure."""
    return _portfolio_risk_check(
        equity=float(equity),
        open_positions=open_positions,
        proposed_trade=proposed_trade,
        rules=rules,
    )


def pine_payload_from_trade_plan(
    plan: dict[str, Any],
    as_of_date: str | None = None,
) -> dict[str, Any]:
    """Build render_pine_recipe('pa_trade_overlay') placeholders from a trade plan."""
    from datetime import date

    if plan.get("error"):
        return {"error": "invalid_plan", "detail": str(plan.get("detail", plan["error"]))}
    targets = plan.get("targets") or []
    tp1 = targets[0]["price"] if len(targets) > 0 else 0
    tp2 = targets[1]["price"] if len(targets) > 1 else 0
    sizing = plan.get("sizing") or {}
    return {
        "SYMBOL": plan.get("symbol", "UNKNOWN"),
        "DIRECTION": plan.get("direction", "long"),
        "ENTRY": plan.get("entry", 0),
        "STOP": plan.get("stop", 0),
        "TP1": tp1,
        "TP2": tp2,
        "RISK_PCT": sizing.get("risk_per_trade_pct", 1.0),
        "UNITS": round(float(sizing.get("units") or 0), 4),
        "RISK_REWARD": plan.get("best_risk_reward", 0),
        "AS_OF_DATE": as_of_date or date.today().isoformat(),
    }


def analyze_mtf_price_action(
    htf_closes: list[float],
    htf_highs: list[float],
    htf_lows: list[float],
    ltf_closes: list[float],
    ltf_highs: list[float],
    ltf_lows: list[float],
    htf_label: str = "HTF",
    ltf_label: str = "LTF",
) -> dict[str, Any]:
    """HTF bias + LTF entry alignment (A+ / conflict grading)."""
    try:
        return {
            "source": "bist-trader-mcp — mtf_analysis.analyze_mtf_price_action",
            **_analyze_mtf_price_action(
                htf_closes=htf_closes or [],
                htf_highs=htf_highs or [],
                htf_lows=htf_lows or [],
                ltf_closes=ltf_closes or [],
                ltf_highs=ltf_highs or [],
                ltf_lows=ltf_lows or [],
                htf_label=htf_label,
                ltf_label=ltf_label,
            ),
        }
    except (TypeError, ValueError) as e:
        return {"error": "bad_input", "detail": str(e)}


def scan_price_action_watchlist(
    series: dict[str, dict[str, list[float]]],
    directions: list[str] | None = None,
    equity: float = 100_000.0,
    min_risk_reward: float = 2.0,
    min_score: float = 0.0,
) -> dict[str, Any]:
    """Rank PA setups across a watchlist (pre-fetched OHLCV per symbol)."""
    dirs = None
    if directions:
        dirs = [d for d in directions if d in ("long", "short")]
    return _scan_price_action_watchlist(
        series=series or {},
        directions=dirs,  # type: ignore[arg-type]
        equity=float(equity),
        min_risk_reward=float(min_risk_reward),
        min_score=float(min_score),
    )


def scan_mtf_watchlist(
    series: dict[str, dict[str, dict[str, list[float]]]],
    equity: float = 100_000.0,
    min_risk_reward: float = 2.0,
    min_quality: str = "a",
) -> dict[str, Any]:
    """MTF watchlist scan — HTF bias + LTF setup per symbol."""
    return _scan_mtf_watchlist(
        series=series or {},
        equity=float(equity),
        min_risk_reward=float(min_risk_reward),
        min_quality=str(min_quality),
    )


def log_trade_plan(
    plan: dict[str, Any],
    status: str = "planned",
    notes: str | None = None,
    journal_path: str | None = None,
) -> dict[str, Any]:
    """Save trade plan to local journal JSON."""
    if status not in ("planned", "open", "closed", "cancelled"):
        return {"error": "bad_input", "detail": "invalid status"}
    return _log_trade_plan(
        plan=_unwrap_trade_plan(plan),
        status=status,  # type: ignore[arg-type]
        notes=notes,
        journal_path=journal_path,
    )


def list_trade_journal(
    status: str | None = None,
    symbol: str | None = None,
    limit: int = 50,
    journal_path: str | None = None,
) -> dict[str, Any]:
    """List journal entries; filter by status or symbol."""
    st = status if status in ("planned", "open", "closed", "cancelled") else None
    return _list_trade_journal(
        status=st,  # type: ignore[arg-type]
        symbol=symbol,
        limit=int(limit),
        journal_path=journal_path,
    )


def update_trade_status(
    trade_id: str,
    status: str,
    exit_price: float | None = None,
    pnl: float | None = None,
    notes: str | None = None,
    journal_path: str | None = None,
) -> dict[str, Any]:
    """Update journal trade status (open / closed / cancelled)."""
    if status not in ("planned", "open", "closed", "cancelled"):
        return {"error": "bad_input", "detail": "invalid status"}
    return _update_trade_status(
        trade_id=trade_id,
        status=status,  # type: ignore[arg-type]
        exit_price=exit_price,
        pnl=pnl,
        notes=notes,
        journal_path=journal_path,
    )


def monitor_open_trades(
    mark_prices: dict[str, float] | None = None,
    journal_path: str | None = None,
) -> dict[str, Any]:
    """Monitor open journal trades vs latest mark prices."""
    return _monitor_open_trades(
        mark_prices=mark_prices,
        journal_path=journal_path,
    )


def _unwrap_trade_plan(payload: dict[str, Any]) -> dict[str, Any]:
    """Accept flat plan or design_mtf_trade_plan / design_ltf_trade_plan wrapper."""
    if payload.get("plan") and isinstance(payload["plan"], dict):
        inner = payload["plan"]
        if inner.get("entry") is not None:
            return inner
    return payload


def get_trade_playbook_rules() -> dict[str, Any]:
    """Canonical consistency rules — AI must follow for every trade."""
    return _get_trade_playbook_rules()


def validate_trade_consistency(
    plan: dict[str, Any],
    mtf: dict[str, Any] | None = None,
    open_trades: list[dict[str, Any]] | None = None,
    journal_path: str | None = None,
    rules: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Same checklist every time: MTF quality, structure, R:R, journal conflict."""
    return _validate_trade_consistency(
        _unwrap_trade_plan(plan),
        mtf=mtf,
        open_trades=open_trades,
        journal_path=journal_path,
        rules=rules,
    )


def enrich_trade_plan(
    plan: dict[str, Any],
    mtf: dict[str, Any] | None = None,
    rules: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Add thesis, execution_plan, partial TP rules to a base plan."""
    p = _unwrap_trade_plan(plan)
    pa = p.get("price_action")
    return _enrich_trade_plan(p, mtf=mtf, pa=pa, rules=rules)


def design_mtf_trade_plan(
    symbol: str,
    htf_closes: list[float],
    htf_highs: list[float],
    htf_lows: list[float],
    ltf_closes: list[float],
    ltf_highs: list[float],
    ltf_lows: list[float],
    htf_label: str = "HTF",
    ltf_label: str = "LTF",
    equity: float = 100_000.0,
    risk_per_trade_pct: float = 1.0,
    min_risk_reward: float = 2.0,
    open_positions: list[dict[str, Any]] | None = None,
    rules: dict[str, Any] | None = None,
    journal_path: str | None = None,
) -> dict[str, Any]:
    """Primary tool: MTF analysis + detailed plan + validation + portfolio gate."""
    return _design_mtf_trade_plan(
        symbol=symbol,
        htf_closes=htf_closes or [],
        htf_highs=htf_highs or [],
        htf_lows=htf_lows or [],
        ltf_closes=ltf_closes or [],
        ltf_highs=ltf_highs or [],
        ltf_lows=ltf_lows or [],
        htf_label=htf_label,
        ltf_label=ltf_label,
        equity=float(equity),
        risk_per_trade_pct=float(risk_per_trade_pct),
        min_risk_reward=float(min_risk_reward),
        open_positions=open_positions,
        rules=rules,
        journal_path=journal_path,
    )


def design_ltf_trade_plan(
    symbol: str,
    closes: list[float],
    highs: list[float],
    lows: list[float],
    direction: str | None = None,
    equity: float = 100_000.0,
    risk_per_trade_pct: float = 1.0,
    min_risk_reward: float = 2.0,
    open_positions: list[dict[str, Any]] | None = None,
    rules: dict[str, Any] | None = None,
    journal_path: str | None = None,
) -> dict[str, Any]:
    """Single-TF plan with same enrich + validate + portfolio pipeline."""
    dir_arg = direction if direction in ("long", "short") else None
    return _design_ltf_trade_plan(
        symbol=symbol,
        closes=closes or [],
        highs=highs or [],
        lows=lows or [],
        direction=dir_arg,
        equity=float(equity),
        risk_per_trade_pct=float(risk_per_trade_pct),
        min_risk_reward=float(min_risk_reward),
        open_positions=open_positions,
        rules=rules,
        journal_path=journal_path,
    )


def analyze_elliott_wave(
    closes: list[float],
    highs: list[float],
    lows: list[float],
    times: list[int] | None = None,
    swing_lookback: int = 5,
) -> dict[str, Any]:
    """Elliott Wave hypotheses (impulse / ABC) on one OHLCV series — typically HTF."""
    return _analyze_elliott_wave(
        closes, highs, lows, times=times, swing_lookback=swing_lookback,
    )


def get_market_profile(symbol: str, market: str | None = None) -> dict[str, Any]:
    """BIST / VIOP / crypto tuned defaults for PA, Elliott, and assistants."""
    return _get_market_profile(symbol, market=market)


def resolve_assistant_config(
    symbol: str,
    market: str | None = None,
    ltf_timeframe: str | None = None,
    htf_timeframe: str | None = None,
    rules: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Merged TV symbol, timeframes, bars, rules for assistant flows."""
    return _resolve_assistant_config(
        symbol,
        market=market,
        ltf_timeframe=ltf_timeframe,
        htf_timeframe=htf_timeframe,
        rules=rules,
    )


def analyze_market_context(
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
) -> dict[str, Any]:
    """Technical (PA + range + FVG + EW MTF) + fundamental research checklist."""
    return _analyze_market_context(
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
        market=market,
        min_ew_score=min_ew_score,
    )


def analyze_chart_scenarios(
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
    data_quality: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """PA + MTF + Elliott scenario pack with primary/alternate counts."""
    return _analyze_chart_scenarios(
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
        min_ew_score=min_ew_score,
        market=market,
        data_quality=data_quality,
    )


def design_scenario_trade_plan(
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
) -> dict[str, Any]:
    """MTF plan only when PA+EW scenarios align."""
    return _design_scenario_trade_plan(
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
        equity=float(equity),
        risk_per_trade_pct=risk_per_trade_pct,
        min_risk_reward=min_risk_reward,
        min_ew_score=min_ew_score,
        market=market,
        open_positions=open_positions,
        rules=rules,
        journal_path=journal_path,
        max_notional_pct=max_notional_pct,
    )


def run_market_assistant(
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
    """Trade assistant: TV + temel (KAP/funding) + teknik + chat_report + chart."""
    return _run_market_assistant(
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
        fetch_fundamentals=fetch_fundamentals,
        draw_on_chart=draw_on_chart,
        draw_when_no_trade=draw_when_no_trade,
        log_journal=log_journal,
    )


def run_scenario_assistant(
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
    draw_on_chart: bool = True,
    log_journal: bool = True,
) -> dict[str, Any]:
    """Alias of run_market_assistant (PA + EW + temel + TV)."""
    return run_market_assistant(
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
        draw_on_chart=draw_on_chart,
        log_journal=log_journal,
    )


def apply_scenario_to_chart(
    scenario: dict[str, Any],
    symbol: str | None = None,
    timeframe: str | None = None,
    htf_timeframe: str | None = None,
    ltf_timeframe: str | None = None,
    bar_times: list[int] | None = None,
    ltf_times: list[int] | None = None,
    ltf_closes: list[float] | None = None,
    ltf_highs: list[float] | None = None,
    mtf: dict[str, Any] | None = None,
    plan: dict[str, Any] | None = None,
    clear_drawings: bool = True,
    draw_pa: bool = True,
    draw_position: bool = True,
) -> dict[str, Any]:
    """Draw PA S/R + structure label, EW lines, optional position from plan."""
    return _apply_scenario_to_chart(
        scenario,
        symbol=symbol,
        timeframe=timeframe,
        htf_timeframe=htf_timeframe,
        ltf_timeframe=ltf_timeframe,
        bar_times=bar_times,
        ltf_times=ltf_times,
        ltf_closes=ltf_closes,
        ltf_highs=ltf_highs,
        mtf=mtf,
        plan=plan,
        clear_drawings=clear_drawings,
        draw_pa=draw_pa,
        draw_position=draw_position,
    )


def run_trade_assistant(
    symbol: str,
    ltf_timeframe: str | None = None,
    htf_timeframe: str | None = None,
    market: str | None = None,
    equity: float = 100_000.0,
    risk_per_trade_pct: float | None = None,
    min_risk_reward: float | None = None,
    open_positions: list[dict[str, Any]] | None = None,
    rules: dict[str, Any] | None = None,
    journal_path: str | None = None,
    draw_on_chart: bool = True,
    log_journal: bool = True,
    set_alerts: bool = False,
) -> dict[str, Any]:
    """Unified assistant: TV data + MTF plan + chart draw + journal (one MCP)."""
    return _run_trade_assistant(
        symbol=symbol,
        ltf_timeframe=ltf_timeframe,
        htf_timeframe=htf_timeframe,
        market=market,
        equity=float(equity),
        risk_per_trade_pct=risk_per_trade_pct,
        min_risk_reward=min_risk_reward,
        open_positions=open_positions,
        rules=rules,
        journal_path=journal_path,
        draw_on_chart=draw_on_chart,
        log_journal=log_journal,
        set_alerts=set_alerts,
    )


def tv_health_check() -> dict[str, Any]:
    """TradingView CDP health (proxied — no second MCP in Cursor)."""
    return _tv_health_check()


def tv_fetch_mtf_ohlcv(
    symbol: str,
    ltf_timeframe: str,
    htf_timeframe: str,
    bars: int | None = None,
    market: str | None = None,
) -> dict[str, Any]:
    """Pull LTF + HTF OHLCV from TradingView chart."""
    return _tv_fetch_mtf_ohlcv(
        symbol, ltf_timeframe, htf_timeframe, bars=bars, market=market,
    )


def tv_chart_set_symbol(symbol: str) -> dict[str, Any]:
    return _tv_chart_set_symbol(symbol)


def tv_chart_set_timeframe(timeframe: str) -> dict[str, Any]:
    return _tv_chart_set_timeframe(timeframe)


def tv_chart_get_state() -> dict[str, Any]:
    return _tv_chart_get_state()


def tv_data_get_ohlcv(count: int = 200, summary: bool = False) -> dict[str, Any]:
    return _tv_data_get_ohlcv(count=int(count), summary=bool(summary))


def tv_draw_clear() -> dict[str, Any]:
    return _tv_draw_clear()


def tv_alert_create(
    price: float,
    condition: str = "crossing",
    message: str | None = None,
) -> dict[str, Any]:
    return _tv_alert_create(price, condition=condition, message=message)


def tv_capture_screenshot(region: str = "chart") -> dict[str, Any]:
    return _tv_capture_screenshot(region=region)


def apply_trade_to_chart(
    plan: dict[str, Any],
    symbol: str | None = None,
    timeframe: str | None = None,
    clear_drawings: bool = True,
    inject_pine: bool = False,
    draw_levels: bool = True,
) -> dict[str, Any]:
    """Draw trade on chart via TradingView Long/Short position tool.

    Requires TradingView Desktop with CDP (--remote-debugging-port=9222)
    and tradingview-mcp CLI on TRADINGVIEW_MCP_PATH (default sibling folder).
    """
    if plan.get("error"):
        return {"error": "invalid_plan", "detail": str(plan.get("detail", plan["error"]))}
    trade_plan = _unwrap_trade_plan(plan)
    if trade_plan.get("error") or trade_plan.get("entry") is None:
        return {"error": "invalid_plan", "detail": "missing entry/stop in plan"}
    try:
        return {
            "source": "bist-trader-mcp — apply_trade_to_chart",
            **_apply_trade_plan_to_chart(
                plan=trade_plan,
                symbol=symbol,
                timeframe=timeframe,
                clear_drawings=clear_drawings,
                inject_pine=inject_pine,
                draw_levels=draw_levels,
                render_pine=render_recipe,
                pine_payload_fn=pine_payload_from_trade_plan,
            ),
        }
    except Exception as e:
        return {"error": "tv_bridge_failed", "detail": str(e)}

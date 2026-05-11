"""High-level tool functions exposed via MCP.

Each function returns a JSON-serialisable dict. Errors are converted to a
structured `{"error": ..., "detail": ...}` payload so the LLM can reason about
them instead of receiving an opaque exception.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import math

from ._wip import wip_payload
from .bist_eod import fetch_eod_ohlcv
from .bond_math import bond_metrics
from .evds import EVDSClient, EVDSError, EVDSObservation
from .hazine import fetch_auctions
from .http_utils import SourceError
from .kap import fetch_disclosures
from .mkk import fetch_foreign_ownership
from .options_math import black_scholes, implied_volatility
from .recipes import list_recipes, render_recipe
from .series_catalog import (
    CPI_HEADLINE,
    DIBS_YIELD_SERIES,
    POLICY_RATE_SERIES,
    list_known_series,
)
from .takasbank import (
    fetch_margin_change_alerts,
    fetch_margin_parameters,
    fetch_viop_margin_snapshot,
)
from .viop import fetch_daily_settlement, fetch_term_structure


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
) -> dict[str, Any]:
    """Daily OHLCV bars for a BIST symbol (Yahoo Finance backend, free, EOD)."""
    try:
        bars = await fetch_eod_ohlcv(ticker, since=since, until=until)
    except SourceError as e:
        return {"error": "bist_eod_error", "detail": str(e)}

    return {
        "source": "Yahoo Finance (BIST EOD)",
        "ticker": ticker,
        "count": len(bars),
        "bars": [
            {
                "date": b.date,
                "open": b.open,
                "high": b.high,
                "low": b.low,
                "close": b.close,
                "volume": b.volume,
            }
            for b in bars
        ],
        "disclaimer": (
            "EOD data is sourced from Yahoo Finance, which mirrors official "
            "BIST closing prices but is not the primary source. Do not use "
            "for clearing/settlement reconciliation."
        ),
    }


# -----------------------------------------------------------------------------
# VIOP — derivatives settlement & term structure
# -----------------------------------------------------------------------------
async def get_viop_settlement(
    trade_date: str | None = None,
    underlying: str | None = None,
) -> dict[str, Any]:
    """All VIOP contract settlement rows for one trade date (with optional underlying filter)."""
    try:
        rows = await fetch_daily_settlement(
            trade_date=trade_date, underlying_filter=underlying
        )
    except SourceError as e:
        if "endpoint discovery pending" in str(e):
            return wip_payload("viop", str(e))
        return {"error": "viop_error", "detail": str(e)}

    return {
        "source": "Borsa İstanbul — VIOP daily bulletin",
        "trade_date": rows[0].trade_date if rows else trade_date,
        "underlying_filter": underlying,
        "count": len(rows),
        "rows": [
            {
                "contract_code": r.contract.contract_code,
                "underlying": r.contract.underlying,
                "contract_type": r.contract.contract_type,
                "expiry_year": r.contract.expiry_year,
                "expiry_month": r.contract.expiry_month,
                "option_strike": r.contract.option_strike,
                "option_right": r.contract.option_right,
                "settle_price": r.settle_price,
                "reference_price": r.reference_price,
                "open_interest": r.open_interest,
                "volume": r.volume,
                "high": r.high,
                "low": r.low,
            }
            for r in rows
        ],
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
        "source": "Borsa İstanbul — VIOP daily bulletin (futures only)",
        "underlying": underlying,
        "as_of": rows[0].trade_date if rows else as_of,
        "count": len(rows),
        "term_structure": [
            {
                "contract_code": r.contract.contract_code,
                "expiry_year": r.contract.expiry_year,
                "expiry_month": r.contract.expiry_month,
                "settle_price": r.settle_price,
                "open_interest": r.open_interest,
                "volume": r.volume,
            }
            for r in rows
        ],
        "notes": (
            "Adjacent-month basis can be inferred from settle prices. For a "
            "spot/futures basis or fair-value calculation, combine with "
            "get_yield_curve and a spot data source."
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
# Hazine — DİBS auctions
# -----------------------------------------------------------------------------
async def get_dibs_auctions(
    since: str | None = None,
    until: str | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    """DİBS auction calendar + results. Default window: -30d to +60d."""
    try:
        auctions = await fetch_auctions(since=since, until=until, status=status)
    except SourceError as e:
        if "endpoint discovery pending" in str(e):
            return wip_payload("hazine", str(e))
        return {"error": "hazine_error", "detail": str(e)}

    return {
        "source": "Hazine ve Maliye Bakanlığı — DİBS auction calendar",
        "status_filter": status,
        "count": len(auctions),
        "auctions": [
            {
                "auction_id": a.auction_id,
                "auction_date": a.auction_date,
                "settlement_date": a.settlement_date,
                "instrument": a.instrument,
                "tenor_months": a.tenor_months,
                "coupon_pct": a.coupon_pct,
                "status": a.status,
                "avg_yield_pct": a.avg_yield_pct,
                "cut_off_yield_pct": a.cut_off_yield_pct,
                "bid_amount": a.bid_amount,
                "accepted_amount": a.accepted_amount,
                "bid_to_cover": a.bid_to_cover,
            }
            for a in auctions
        ],
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

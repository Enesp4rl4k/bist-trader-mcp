"""Portfolio Greeks aggregator — pure math, no network.

Takes a list of positions (futures + options + underlying spot) and
returns net delta / gamma / vega / theta, both portfolio-wide and broken
down by underlying. Each option position is repriced with Black-Scholes
to give a consistent set of greeks regardless of whether the caller
provided a market IV or wants the model to solve one.

Position schema:
    {
      "symbol": str,                  # free-form, e.g. "F_XU0300626"
      "underlying": str,              # e.g. "XU030" — used for grouping
      "qty": float,                   # signed; negative = short
      "instrument_type": str,         # "future" | "option" | "spot"
      # option-only fields:
      "strike": float | None,
      "days_to_expiry": float | None,
      "right": "call" | "put" | None,
      "volatility_pct": float | None, # if None and market_price set → solve IV
      "market_price": float | None,
      # market context (option + future repricing inputs):
      "spot": float | None,           # mandatory for option / future
      "risk_free_rate_pct": float | None,
      "dividend_yield_pct": float | None,
      "multiplier": float | None,     # contract size; defaults to 1.0
    }

Underlying / futures contribute delta = qty * multiplier * (spot or 1).
Spot contributes delta = qty (treated as 1:1 with underlying).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from .options_math import black_scholes, implied_volatility


@dataclass
class LegRisk:
    symbol: str
    underlying: str
    instrument_type: str
    qty: float
    multiplier: float
    delta: float
    gamma: float
    vega: float
    theta_per_year: float
    theta_per_day: float
    notional: float
    iv_pct: float | None
    note: str | None = None


def _f(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default
    return float(value)


def _price_leg(pos: dict[str, Any]) -> LegRisk:
    symbol = str(pos.get("symbol") or "")
    underlying = str(pos.get("underlying") or symbol or "UNKNOWN")
    instrument = str(pos.get("instrument_type") or "").lower().strip()
    qty = _f(pos.get("qty"))
    mult = _f(pos.get("multiplier"), 1.0) or 1.0
    spot = pos.get("spot")
    note: str | None = None

    if instrument in ("spot", "equity", "stock", "underlying"):
        # 1:1 delta with underlying, no convexity, no vol exposure.
        spot_val = _f(spot, 1.0)
        return LegRisk(
            symbol=symbol,
            underlying=underlying,
            instrument_type="spot",
            qty=qty,
            multiplier=mult,
            delta=qty * mult,
            gamma=0.0,
            vega=0.0,
            theta_per_year=0.0,
            theta_per_day=0.0,
            notional=qty * mult * spot_val,
            iv_pct=None,
        )

    if instrument in ("future", "futures", "fut"):
        if spot is None:
            note = "spot missing; notional reported as 0"
        spot_val = _f(spot)
        # Future delta is 1 per contract per unit underlying movement.
        return LegRisk(
            symbol=symbol,
            underlying=underlying,
            instrument_type="future",
            qty=qty,
            multiplier=mult,
            delta=qty * mult,
            gamma=0.0,
            vega=0.0,
            theta_per_year=0.0,
            theta_per_day=0.0,
            notional=qty * mult * spot_val,
            iv_pct=None,
            note=note,
        )

    if instrument in ("option", "opt"):
        strike = pos.get("strike")
        dte = pos.get("days_to_expiry")
        right = str(pos.get("right") or "call").lower().strip()
        r_pct = _f(pos.get("risk_free_rate_pct"))
        q_pct = _f(pos.get("dividend_yield_pct"))
        vol_pct = pos.get("volatility_pct")
        market_price = pos.get("market_price")

        if spot is None or strike is None or dte is None or float(dte) <= 0:
            return LegRisk(
                symbol=symbol,
                underlying=underlying,
                instrument_type="option",
                qty=qty,
                multiplier=mult,
                delta=0.0,
                gamma=0.0,
                vega=0.0,
                theta_per_year=0.0,
                theta_per_day=0.0,
                notional=0.0,
                iv_pct=None,
                note="missing spot/strike/days_to_expiry; greeks zeroed",
            )

        t = float(dte) / 365.0
        r = r_pct / 100.0
        qd = q_pct / 100.0
        s = float(spot)
        k = float(strike)

        iv_decimal: float | None = None
        if vol_pct is None and market_price is not None:
            try:
                iv_decimal = implied_volatility(
                    market_price=float(market_price),
                    spot=s,
                    strike=k,
                    time_to_expiry=t,
                    risk_free_rate=r,
                    dividend_yield=qd,
                    style=right,
                )
                note = "iv solved from market_price"
            except (ValueError, ArithmeticError) as e:
                return LegRisk(
                    symbol=symbol,
                    underlying=underlying,
                    instrument_type="option",
                    qty=qty,
                    multiplier=mult,
                    delta=0.0,
                    gamma=0.0,
                    vega=0.0,
                    theta_per_year=0.0,
                    theta_per_day=0.0,
                    notional=0.0,
                    iv_pct=None,
                    note=f"iv solve failed: {e}",
                )
        elif vol_pct is not None:
            iv_decimal = float(vol_pct) / 100.0
        else:
            return LegRisk(
                symbol=symbol,
                underlying=underlying,
                instrument_type="option",
                qty=qty,
                multiplier=mult,
                delta=0.0,
                gamma=0.0,
                vega=0.0,
                theta_per_year=0.0,
                theta_per_day=0.0,
                notional=0.0,
                iv_pct=None,
                note="neither volatility_pct nor market_price provided",
            )

        try:
            g = black_scholes(
                spot=s,
                strike=k,
                time_to_expiry=t,
                volatility=iv_decimal,
                risk_free_rate=r,
                dividend_yield=qd,
                style=right,
            )
        except (ValueError, ArithmeticError) as e:
            return LegRisk(
                symbol=symbol,
                underlying=underlying,
                instrument_type="option",
                qty=qty,
                multiplier=mult,
                delta=0.0,
                gamma=0.0,
                vega=0.0,
                theta_per_year=0.0,
                theta_per_day=0.0,
                notional=0.0,
                iv_pct=iv_decimal * 100.0 if iv_decimal else None,
                note=f"bs pricing failed: {e}",
            )

        signed = qty * mult
        return LegRisk(
            symbol=symbol,
            underlying=underlying,
            instrument_type="option",
            qty=qty,
            multiplier=mult,
            delta=signed * g.delta,
            gamma=signed * g.gamma,
            vega=signed * g.vega,
            theta_per_year=signed * g.theta_per_year,
            theta_per_day=signed * g.theta_per_year / 365.0,
            notional=signed * g.price,
            iv_pct=iv_decimal * 100.0,
            note=note,
        )

    return LegRisk(
        symbol=symbol,
        underlying=underlying,
        instrument_type=instrument or "unknown",
        qty=qty,
        multiplier=mult,
        delta=0.0,
        gamma=0.0,
        vega=0.0,
        theta_per_year=0.0,
        theta_per_day=0.0,
        notional=0.0,
        iv_pct=None,
        note=f"unknown instrument_type: {instrument!r}",
    )


def aggregate_portfolio_greeks(positions: list[dict[str, Any]]) -> dict[str, Any]:
    """Repriced per-leg greeks plus totals and per-underlying rollup."""
    if not positions:
        return {
            "count": 0,
            "totals": {
                "delta": 0.0,
                "gamma": 0.0,
                "vega": 0.0,
                "theta_per_year": 0.0,
                "theta_per_day": 0.0,
                "gross_notional": 0.0,
                "net_notional": 0.0,
            },
            "by_underlying": {},
            "legs": [],
        }

    legs = [_price_leg(p) for p in positions]

    totals = {
        "delta": 0.0,
        "gamma": 0.0,
        "vega": 0.0,
        "theta_per_year": 0.0,
        "theta_per_day": 0.0,
        "gross_notional": 0.0,
        "net_notional": 0.0,
    }
    by_under: dict[str, dict[str, float]] = {}

    for leg in legs:
        totals["delta"] += leg.delta
        totals["gamma"] += leg.gamma
        totals["vega"] += leg.vega
        totals["theta_per_year"] += leg.theta_per_year
        totals["theta_per_day"] += leg.theta_per_day
        totals["gross_notional"] += abs(leg.notional)
        totals["net_notional"] += leg.notional

        bucket = by_under.setdefault(
            leg.underlying,
            {
                "delta": 0.0,
                "gamma": 0.0,
                "vega": 0.0,
                "theta_per_year": 0.0,
                "theta_per_day": 0.0,
                "net_notional": 0.0,
            },
        )
        bucket["delta"] += leg.delta
        bucket["gamma"] += leg.gamma
        bucket["vega"] += leg.vega
        bucket["theta_per_year"] += leg.theta_per_year
        bucket["theta_per_day"] += leg.theta_per_day
        bucket["net_notional"] += leg.notional

    return {
        "count": len(legs),
        "totals": totals,
        "by_underlying": by_under,
        "legs": [
            {
                "symbol": leg.symbol,
                "underlying": leg.underlying,
                "instrument_type": leg.instrument_type,
                "qty": leg.qty,
                "multiplier": leg.multiplier,
                "delta": leg.delta,
                "gamma": leg.gamma,
                "vega": leg.vega,
                "theta_per_year": leg.theta_per_year,
                "theta_per_day": leg.theta_per_day,
                "notional": leg.notional,
                "iv_pct": leg.iv_pct,
                "note": leg.note,
            }
            for leg in legs
        ],
    }


# ---------------------------------------------------------------------------
# Portfolio VaR + stress testing — pure math, no network.
# ---------------------------------------------------------------------------

# Inverse standard-normal CDF for common confidence levels (one-sided).
_Z_SCORE = {
    0.90: 1.2816,
    0.95: 1.6449,
    0.975: 1.9600,
    0.99: 2.3263,
    0.995: 2.5758,
    0.999: 3.0902,
}


def _z_for(confidence: float) -> float:
    """Return the one-sided z-score for the requested confidence level.

    Falls back to a rational approximation (Beasley-Springer-Moro) for
    arbitrary confidence; uses cached values for common ones.
    """
    if confidence in _Z_SCORE:
        return _Z_SCORE[confidence]
    # Beasley-Springer-Moro approximation
    p = 1.0 - confidence
    a = (-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
         1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00)
    b = (-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
         6.680131188771972e+01, -1.328068155288572e+01)
    q = p - 0.5
    if abs(q) <= 0.425:
        r = q * q
        num = (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q
        den = ((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1.0
        return -num / den
    # tail
    r = math.sqrt(-math.log(min(p, 1 - p)))
    sign = 1.0 if p > 0.5 else -1.0
    return sign * r  # rough; only used outside common confidences


def calculate_portfolio_var(
    positions: list[dict[str, Any]],
    confidence: float = 0.99,
    horizon_days: int = 1,
    annual_volatility_pct: float = 30.0,
    method: str = "parametric",
    historical_returns: list[float] | None = None,
) -> dict[str, Any]:
    """Compute portfolio Value-at-Risk under simple assumptions.

    Methods:
      - "parametric": net delta-notional * σ_horizon * z_conf. Assumes a
        single-factor (underlying-driven) move with normally distributed
        returns. Adds a gamma adjustment using net Γ for convexity.
      - "historical": consume `historical_returns` (decimal daily returns
        of a representative underlying), compute the empirical
        confidence-quantile loss on the delta-equivalent notional.

    Args:
        positions: same schema as `aggregate_portfolio_greeks`.
        confidence: e.g. 0.99 for 99% VaR.
        horizon_days: VaR horizon in days.
        annual_volatility_pct: σ for parametric method (e.g. 30 for XU030).
        method: "parametric" | "historical".
        historical_returns: required for the historical method.

    Returns dict with var_amount (positive = loss), expected_shortfall,
    inputs, and the underlying breakdown.
    """
    agg = aggregate_portfolio_greeks(positions)
    delta_notional = agg["totals"]["delta"]
    gamma = agg["totals"]["gamma"]

    if horizon_days <= 0:
        raise ValueError("horizon_days must be > 0")
    if confidence <= 0 or confidence >= 1:
        raise ValueError("confidence must be in (0,1)")

    if method == "parametric":
        sigma_annual = annual_volatility_pct / 100.0
        sigma_horizon = sigma_annual * math.sqrt(horizon_days / 252.0)
        z = _z_for(confidence)
        # First-order: |Δ| * σ * z (in % of notional). delta_notional already
        # has units of price * qty * mult, so we multiply by sigma_horizon * z.
        var_linear = abs(delta_notional) * sigma_horizon * z
        # Gamma adjustment (negative gamma = additional loss tail).
        # ΔV ≈ Δ * dS + 0.5 * Γ * dS². For VaR we take dS = z*σ*S — but we
        # don't have spot here generically, so we estimate via gamma * (z*σ)²
        # times average underlying notional. Conservative: only subtract
        # when gamma is negative (short gamma).
        var_gamma_adj = 0.0
        if gamma < 0:
            avg_notional = abs(agg["totals"]["gross_notional"]) / max(agg["count"], 1)
            var_gamma_adj = 0.5 * abs(gamma) * (sigma_horizon * z * avg_notional) ** 2
        var_amount = var_linear + var_gamma_adj
        # Parametric ES at given confidence ≈ σ * φ(z)/(1-c) * |Δ|
        from math import exp, pi, sqrt
        phi_z = exp(-0.5 * z * z) / sqrt(2 * pi)
        es_amount = abs(delta_notional) * sigma_horizon * phi_z / (1.0 - confidence)
        return {
            "method": "parametric",
            "confidence": confidence,
            "horizon_days": horizon_days,
            "annual_volatility_pct": annual_volatility_pct,
            "delta_notional": delta_notional,
            "gamma": gamma,
            "var_amount": var_amount,
            "var_linear_component": var_linear,
            "var_gamma_adjustment": var_gamma_adj,
            "expected_shortfall": es_amount,
            "z_score": z,
            "sigma_horizon": sigma_horizon,
            "by_underlying": agg["by_underlying"],
        }

    if method == "historical":
        if not historical_returns:
            raise ValueError("historical_returns required for method='historical'")
        # Scale returns to horizon
        scaled = [r * math.sqrt(horizon_days) for r in historical_returns]
        scaled.sort()
        idx = int((1.0 - confidence) * len(scaled))
        idx = max(0, min(idx, len(scaled) - 1))
        worst_pct = scaled[idx]   # negative number
        # P&L at portfolio level via delta exposure
        var_amount = abs(delta_notional * worst_pct)
        # ES: average of all losses worse than the VaR quantile
        tail = scaled[: idx + 1]
        es_pct = sum(tail) / len(tail) if tail else worst_pct
        es_amount = abs(delta_notional * es_pct)
        return {
            "method": "historical",
            "confidence": confidence,
            "horizon_days": horizon_days,
            "sample_size": len(historical_returns),
            "delta_notional": delta_notional,
            "worst_return_at_quantile": worst_pct,
            "var_amount": var_amount,
            "expected_shortfall": es_amount,
            "by_underlying": agg["by_underlying"],
        }

    raise ValueError(f"unknown method: {method!r}")


# ---------------------------------------------------------------------------
# Stress testing — apply named scenarios and report repriced P&L.
# ---------------------------------------------------------------------------

# Canonical scenarios. Each scenario is a dict of shocks keyed by axis:
#   spot_pct: percent move in underlying (per underlying or "*" for all)
#   vol_pct_abs: additive bump to IV in vol points (45% IV + 10 → 55%)
#   rate_bp: additive bump to risk-free rate in basis points
# Users can pass their own dicts as well.
BUILTIN_SCENARIOS: dict[str, dict[str, Any]] = {
    "rates+200bp":     {"rate_bp": 200},
    "rates-200bp":     {"rate_bp": -200},
    "tl_devalue_20pct": {"spot_pct": {"USD": 20, "EUR": 20, "USDTRY": 20, "EURTRY": 20}},
    "xu030_-10pct":    {"spot_pct": {"XU030": -10}, "vol_pct_abs": 5},
    "xu030_+10pct":    {"spot_pct": {"XU030": 10}, "vol_pct_abs": -3},
    "vol_crush_-30pct_rel": {"vol_pct_rel": -30},
    "vol_spike_+50pct_rel": {"vol_pct_rel": 50},
    "broad_-5pct":     {"spot_pct": {"*": -5}, "vol_pct_abs": 3},
    "broad_+5pct":     {"spot_pct": {"*": 5}},
}


def _apply_shock_to_position(
    pos: dict[str, Any],
    shock: dict[str, Any],
) -> dict[str, Any]:
    """Return a shocked copy of `pos` with spot/vol/rate adjusted in place."""
    shocked = dict(pos)
    spot = shocked.get("spot")
    if spot is not None:
        spot_shock = shock.get("spot_pct")
        if isinstance(spot_shock, dict):
            u = shocked.get("underlying", "")
            pct = spot_shock.get(u, spot_shock.get("*", 0))
        else:
            pct = spot_shock or 0
        shocked["spot"] = float(spot) * (1.0 + pct / 100.0)

    vol = shocked.get("volatility_pct")
    if vol is not None:
        v = float(vol)
        v += shock.get("vol_pct_abs", 0) or 0
        rel = shock.get("vol_pct_rel")
        if rel is not None:
            v *= (1.0 + rel / 100.0)
        shocked["volatility_pct"] = max(v, 0.01)
        # If we shocked vol, clear the market_price so the IV-solve path
        # is not taken on the shocked snapshot.
        shocked["market_price"] = None

    rate = shocked.get("risk_free_rate_pct")
    if rate is not None and shock.get("rate_bp"):
        shocked["risk_free_rate_pct"] = float(rate) + shock["rate_bp"] / 100.0

    return shocked


def stress_test_portfolio(
    positions: list[dict[str, Any]],
    scenarios: list[str] | None = None,
    custom_scenarios: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Reprice the portfolio under each scenario and report P&L delta.

    Args:
        positions: standard position list.
        scenarios: list of built-in scenario names. Defaults to all.
        custom_scenarios: extra `{name: shock_dict}` users can add ad-hoc.

    Returns dict with baseline net_notional and per-scenario:
        - net_notional_shocked
        - pnl_amount
        - pnl_pct (vs baseline gross notional)
        - delta_change, vega_change
    """
    catalog = dict(BUILTIN_SCENARIOS)
    if custom_scenarios:
        catalog.update(custom_scenarios)
    selected = scenarios or list(catalog.keys())

    baseline = aggregate_portfolio_greeks(positions)
    base_notional = baseline["totals"]["net_notional"]
    base_gross = baseline["totals"]["gross_notional"] or 1.0
    base_delta = baseline["totals"]["delta"]
    base_vega = baseline["totals"]["vega"]

    results = []
    for name in selected:
        shock = catalog.get(name)
        if shock is None:
            results.append({
                "scenario": name,
                "error": f"unknown scenario; known: {list(catalog)}",
            })
            continue
        shocked_pos = [_apply_shock_to_position(p, shock) for p in positions]
        shocked = aggregate_portfolio_greeks(shocked_pos)
        new_notional = shocked["totals"]["net_notional"]
        pnl = new_notional - base_notional
        results.append({
            "scenario": name,
            "shock": shock,
            "net_notional_baseline": base_notional,
            "net_notional_shocked": new_notional,
            "pnl_amount": pnl,
            "pnl_pct_of_gross": round(100.0 * pnl / base_gross, 4),
            "delta_change": shocked["totals"]["delta"] - base_delta,
            "vega_change": shocked["totals"]["vega"] - base_vega,
        })

    results.sort(key=lambda r: r.get("pnl_amount", 0.0))
    return {
        "baseline": {
            "net_notional": base_notional,
            "gross_notional": baseline["totals"]["gross_notional"],
            "delta": base_delta,
            "vega": base_vega,
        },
        "scenarios": results,
    }

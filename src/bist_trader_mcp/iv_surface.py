"""VIOP implied-volatility surface + spread opportunity screener.

Pure math on top of `viop.fetch_option_chain` (live snapshot) and
`options_math.implied_volatility` (BS solver). No new HTTP.

Surface contract
----------------
A surface is a list of `IVPoint` rows — one per (expiry, strike, right)
quote that successfully solved an IV. Aggregated views are computed on
top of the raw points:

- ATM term structure: nearest-strike call IV per expiry (interpolated
  between the two strikes bracketing spot).
- 25-delta skew: for the nearest expiry with ≥4 strikes per side, the
  difference between the 25-delta put IV and 25-delta call IV (in vol
  points). A positive number means the market is paying up for
  downside protection — the classic "fear skew".
- Term structure slope: front-month ATM IV minus back-month ATM IV.

Screener
--------
`find_spread_opportunities(strategy=...)` walks the surface and lists
"obvious" no-arb violations or rich/cheap structures. We deliberately
keep this conservative — the goal is to surface candidates a human can
sanity-check, not to fire orders.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Literal

from .options_math import black_scholes, implied_volatility
from .viop import VIOPSettlement


@dataclass
class IVPoint:
    """One quote on the IV surface."""
    expiry_year: int
    expiry_month: int
    days_to_expiry: int
    strike: float
    right: str  # "C" or "P"
    last_price: float
    iv_pct: float            # decimal as percent (45.0 = 45%)
    delta: float
    moneyness: float         # ln(K / F), where F = forward price
    note: str | None = None


def _expiry_date(year: int, month: int) -> date:
    """VIOP contracts settle on the last business day of the month — for
    DTE purposes we approximate as the last calendar day."""
    if month == 12:
        return date(year + 1, 1, 1) - _one_day()
    return date(year, month + 1, 1) - _one_day()


def _one_day():
    from datetime import timedelta
    return timedelta(days=1)


def build_iv_surface(
    chain: list[VIOPSettlement],
    spot: float,
    risk_free_rate_pct: float,
    dividend_yield_pct: float = 0.0,
    as_of: date | None = None,
    min_price: float = 0.01,
) -> dict[str, Any]:
    """Solve IV for every option in `chain` and return a structured surface.

    Args:
        chain: result of `viop.fetch_option_chain(underlying, ...)`.
        spot: underlying spot price in the same units as strikes.
        risk_free_rate_pct: TR risk-free rate (e.g. TLREF) in percent.
        dividend_yield_pct: 0 for equity indices, 0 for USDTRY, etc.
        as_of: snapshot date (defaults to today).
        min_price: skip quotes below this last_price (illiquid / noise).

    Returns dict with:
        - points: list of IVPoint as dicts
        - by_expiry: {YYYY-MM: { calls: [...], puts: [...], atm_iv_pct, dte }}
        - atm_term_structure: [{expiry: 'YYYY-MM', dte, atm_iv_pct}, ...]
        - skew_25d: {expiry: 'YYYY-MM', dte, put_iv_pct, call_iv_pct, skew_vol_pts}
        - meta: counts and inputs.
    """
    as_of = as_of or date.today()
    r = risk_free_rate_pct / 100.0
    q = dividend_yield_pct / 100.0

    points: list[IVPoint] = []
    skipped = {"no_price": 0, "no_strike": 0, "expired": 0, "iv_failed": 0}

    for row in chain:
        c = row.contract
        if c.contract_type != "option":
            continue
        if c.option_strike is None or c.option_right is None:
            skipped["no_strike"] += 1
            continue
        if row.last_price is None or row.last_price < min_price:
            skipped["no_price"] += 1
            continue

        exp = _expiry_date(c.expiry_year, c.expiry_month)
        dte = (exp - as_of).days
        if dte <= 0:
            skipped["expired"] += 1
            continue
        t = dte / 365.0

        try:
            iv = implied_volatility(
                market_price=float(row.last_price),
                spot=spot,
                strike=float(c.option_strike),
                time_to_expiry=t,
                risk_free_rate=r,
                dividend_yield=q,
                style="call" if c.option_right == "C" else "put",
            )
        except (ValueError, ArithmeticError):
            skipped["iv_failed"] += 1
            continue

        try:
            greeks = black_scholes(
                spot=spot,
                strike=float(c.option_strike),
                time_to_expiry=t,
                volatility=iv,
                risk_free_rate=r,
                dividend_yield=q,
                style="call" if c.option_right == "C" else "put",
            )
        except (ValueError, ArithmeticError):
            skipped["iv_failed"] += 1
            continue

        forward = spot * pow(2.71828182846, (r - q) * t)
        import math
        moneyness = math.log(float(c.option_strike) / forward)

        points.append(IVPoint(
            expiry_year=c.expiry_year,
            expiry_month=c.expiry_month,
            days_to_expiry=dte,
            strike=float(c.option_strike),
            right=str(c.option_right),
            last_price=float(row.last_price),
            iv_pct=iv * 100.0,
            delta=greeks.delta,
            moneyness=moneyness,
        ))

    by_expiry = _group_by_expiry(points, spot)
    atm_ts = _atm_term_structure(by_expiry)
    skew = _front_month_25d_skew(by_expiry)
    slope = _term_structure_slope(atm_ts)

    return {
        "as_of": as_of.isoformat(),
        "spot": spot,
        "risk_free_pct": risk_free_rate_pct,
        "dividend_yield_pct": dividend_yield_pct,
        "meta": {
            "total_chain_rows": len(chain),
            "points_solved": len(points),
            "skipped": skipped,
        },
        "points": [_point_to_dict(p) for p in points],
        "by_expiry": by_expiry,
        "atm_term_structure": atm_ts,
        "skew_25d_front_month": skew,
        "term_structure_slope_vol_pts": slope,
    }


def _point_to_dict(p: IVPoint) -> dict[str, Any]:
    return {
        "expiry": f"{p.expiry_year:04d}-{p.expiry_month:02d}",
        "expiry_year": p.expiry_year,
        "expiry_month": p.expiry_month,
        "days_to_expiry": p.days_to_expiry,
        "strike": p.strike,
        "right": p.right,
        "last_price": p.last_price,
        "iv_pct": round(p.iv_pct, 3),
        "delta": round(p.delta, 4),
        "moneyness": round(p.moneyness, 4),
    }


def _group_by_expiry(points: list[IVPoint], spot: float) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for p in points:
        key = f"{p.expiry_year:04d}-{p.expiry_month:02d}"
        bucket = out.setdefault(key, {
            "expiry": key,
            "days_to_expiry": p.days_to_expiry,
            "calls": [],
            "puts": [],
            "atm_iv_pct": None,
        })
        if p.right == "C":
            bucket["calls"].append(_point_to_dict(p))
        else:
            bucket["puts"].append(_point_to_dict(p))
    for bucket in out.values():
        bucket["calls"].sort(key=lambda r: r["strike"])
        bucket["puts"].sort(key=lambda r: r["strike"])
        bucket["atm_iv_pct"] = _interp_atm_iv(bucket["calls"], spot)
    return out


def _interp_atm_iv(calls: list[dict[str, Any]], spot: float) -> float | None:
    """Linear-interpolate the ATM call IV between the two strikes bracketing spot."""
    if not calls:
        return None
    below = [c for c in calls if c["strike"] <= spot]
    above = [c for c in calls if c["strike"] >= spot]
    if not below and not above:
        return None
    if not below:
        return above[0]["iv_pct"]
    if not above:
        return below[-1]["iv_pct"]
    k_lo = below[-1]["strike"]
    k_hi = above[0]["strike"]
    if k_lo == k_hi:
        return below[-1]["iv_pct"]
    iv_lo = below[-1]["iv_pct"]
    iv_hi = above[0]["iv_pct"]
    w = (spot - k_lo) / (k_hi - k_lo)
    return iv_lo + w * (iv_hi - iv_lo)


def _atm_term_structure(by_expiry: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    rows = [
        {
            "expiry": k,
            "days_to_expiry": v["days_to_expiry"],
            "atm_iv_pct": v["atm_iv_pct"],
        }
        for k, v in by_expiry.items()
        if v["atm_iv_pct"] is not None
    ]
    rows.sort(key=lambda r: r["days_to_expiry"])
    return rows


def _front_month_25d_skew(by_expiry: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    """Find expiry with ≥3 strikes per side, return 25Δ put - 25Δ call IV."""
    candidates = sorted(
        [v for v in by_expiry.values() if len(v["calls"]) >= 3 and len(v["puts"]) >= 3],
        key=lambda v: v["days_to_expiry"],
    )
    if not candidates:
        return None
    bucket = candidates[0]

    def closest_to_delta(rows: list[dict[str, Any]], target: float) -> dict[str, Any] | None:
        if not rows:
            return None
        return min(rows, key=lambda r: abs(abs(r["delta"]) - abs(target)))

    call_25 = closest_to_delta(bucket["calls"], 0.25)
    put_25 = closest_to_delta(bucket["puts"], -0.25)
    if call_25 is None or put_25 is None:
        return None
    return {
        "expiry": bucket["expiry"],
        "days_to_expiry": bucket["days_to_expiry"],
        "call_25d_iv_pct": call_25["iv_pct"],
        "call_25d_strike": call_25["strike"],
        "put_25d_iv_pct": put_25["iv_pct"],
        "put_25d_strike": put_25["strike"],
        "skew_vol_pts": put_25["iv_pct"] - call_25["iv_pct"],
    }


def _term_structure_slope(ts: list[dict[str, Any]]) -> float | None:
    if len(ts) < 2:
        return None
    front = ts[0]["atm_iv_pct"]
    back = ts[-1]["atm_iv_pct"]
    if front is None or back is None:
        return None
    return front - back


# ---------------------------------------------------------------------------
# Spread opportunity screener — calendar, vertical, butterfly.
# ---------------------------------------------------------------------------

StrategyT = Literal["calendar", "vertical", "butterfly"]


def find_spread_opportunities(
    surface: dict[str, Any],
    strategy: StrategyT = "calendar",
    min_edge_vol_pts: float = 3.0,
    max_results: int = 20,
) -> list[dict[str, Any]]:
    """Walk the surface and surface candidate spreads where IV dispersion
    exceeds `min_edge_vol_pts`.

    - calendar: same strike + right, different expiries. Edge = front_iv - back_iv.
      Positive = front rich → sell front / buy back.
    - vertical: same expiry + right, different strikes. Edge = |iv_low - iv_high|
      (skew dispersion within an expiry).
    - butterfly: same expiry + right, three strikes equally spaced. Edge = wing IV
      average minus body IV (positive = wings rich vs body → sell butterfly).

    Returns at most `max_results` candidates sorted by absolute edge descending.
    """
    points = surface.get("points") or []
    if strategy == "calendar":
        return _find_calendars(points, min_edge_vol_pts, max_results)
    if strategy == "vertical":
        return _find_verticals(points, min_edge_vol_pts, max_results)
    if strategy == "butterfly":
        return _find_butterflies(points, min_edge_vol_pts, max_results)
    raise ValueError(f"unknown strategy: {strategy}")


def _find_calendars(points, min_edge, max_results):
    by_key: dict[tuple[float, str], list[dict[str, Any]]] = {}
    for p in points:
        by_key.setdefault((p["strike"], p["right"]), []).append(p)
    out = []
    for (strike, right), legs in by_key.items():
        legs.sort(key=lambda r: r["days_to_expiry"])
        for i in range(len(legs) - 1):
            front, back = legs[i], legs[i + 1]
            edge = front["iv_pct"] - back["iv_pct"]
            if abs(edge) < min_edge:
                continue
            out.append({
                "strategy": "calendar",
                "strike": strike,
                "right": right,
                "front_expiry": front["expiry"],
                "front_dte": front["days_to_expiry"],
                "front_iv_pct": front["iv_pct"],
                "back_expiry": back["expiry"],
                "back_dte": back["days_to_expiry"],
                "back_iv_pct": back["iv_pct"],
                "edge_vol_pts": round(edge, 3),
                "direction": "sell_front_buy_back" if edge > 0 else "buy_front_sell_back",
            })
    out.sort(key=lambda r: abs(r["edge_vol_pts"]), reverse=True)
    return out[:max_results]


def _find_verticals(points, min_edge, max_results):
    by_key: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for p in points:
        by_key.setdefault((p["expiry"], p["right"]), []).append(p)
    out = []
    for (expiry, right), legs in by_key.items():
        if len(legs) < 2:
            continue
        legs.sort(key=lambda r: r["strike"])
        for i in range(len(legs)):
            for j in range(i + 1, len(legs)):
                lo, hi = legs[i], legs[j]
                edge = lo["iv_pct"] - hi["iv_pct"]
                if abs(edge) < min_edge:
                    continue
                out.append({
                    "strategy": "vertical",
                    "expiry": expiry,
                    "right": right,
                    "low_strike": lo["strike"],
                    "low_iv_pct": lo["iv_pct"],
                    "high_strike": hi["strike"],
                    "high_iv_pct": hi["iv_pct"],
                    "edge_vol_pts": round(edge, 3),
                })
    out.sort(key=lambda r: abs(r["edge_vol_pts"]), reverse=True)
    return out[:max_results]


def _find_butterflies(points, min_edge, max_results):
    by_key: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for p in points:
        by_key.setdefault((p["expiry"], p["right"]), []).append(p)
    out = []
    for (expiry, right), legs in by_key.items():
        if len(legs) < 3:
            continue
        legs.sort(key=lambda r: r["strike"])
        for i in range(len(legs) - 2):
            lo, mid, hi = legs[i], legs[i + 1], legs[i + 2]
            spacing_lo = mid["strike"] - lo["strike"]
            spacing_hi = hi["strike"] - mid["strike"]
            if spacing_lo <= 0 or spacing_hi <= 0:
                continue
            if abs(spacing_lo - spacing_hi) / max(spacing_lo, spacing_hi) > 0.10:
                continue
            wing_avg = 0.5 * (lo["iv_pct"] + hi["iv_pct"])
            edge = wing_avg - mid["iv_pct"]
            if abs(edge) < min_edge:
                continue
            out.append({
                "strategy": "butterfly",
                "expiry": expiry,
                "right": right,
                "low_strike": lo["strike"],
                "mid_strike": mid["strike"],
                "high_strike": hi["strike"],
                "low_iv_pct": lo["iv_pct"],
                "mid_iv_pct": mid["iv_pct"],
                "high_iv_pct": hi["iv_pct"],
                "wing_avg_iv_pct": round(wing_avg, 3),
                "edge_vol_pts": round(edge, 3),
                "direction": "sell_wings_buy_body" if edge > 0 else "buy_wings_sell_body",
            })
    out.sort(key=lambda r: abs(r["edge_vol_pts"]), reverse=True)
    return out[:max_results]


__all__ = [
    "IVPoint",
    "build_iv_surface",
    "find_spread_opportunities",
]

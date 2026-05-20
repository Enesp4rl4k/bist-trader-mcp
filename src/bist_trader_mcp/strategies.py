"""Option strategy P&L simulator.

Pure-math module. Given a spot range, a list of "legs" (each a long/short
option or future or spot), and optional time decay parameters, returns
a P&L grid plus key metrics (max profit, max loss, breakevens, payoff at
specific spots, P&L at expiry vs P&L now).

Templates for common strategies are exposed as helpers:
    - long_straddle
    - short_straddle
    - long_strangle
    - iron_condor
    - butterfly
    - calendar_spread (single-strike, two expiries)
    - vertical_spread (bull call, bear put)

All prices in same units as underlying. Volatility in % (45 = 45%).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .options_math import black_scholes


@dataclass
class StrategyLeg:
    """One leg in a strategy.

    instrument_type: "option" | "future" | "spot"
    For options: right, strike, days_to_expiry, volatility_pct must be set.
    For futures/spot: just qty (delta-one).
    """
    instrument_type: str
    qty: float
    strike: float | None = None
    right: str | None = None   # "call" | "put"
    days_to_expiry: float | None = None
    volatility_pct: float | None = None
    entry_price: float | None = None  # what you paid (or received) per unit
    multiplier: float = 1.0


def _price_leg_at(
    leg: StrategyLeg,
    spot: float,
    r_pct: float = 0.0,
    q_pct: float = 0.0,
    dte_override: float | None = None,
) -> float:
    """Theoretical mid price of one leg at given spot, with optional DTE shift."""
    itype = leg.instrument_type.lower()
    if itype in ("spot", "equity", "stock"):
        return spot
    if itype in ("future", "futures"):
        # Assume cost-of-carry; for simplicity treat as spot (instant settle)
        return spot
    if itype in ("option", "opt"):
        if leg.strike is None or leg.right is None:
            return 0.0
        dte = dte_override if dte_override is not None else (leg.days_to_expiry or 0)
        if dte <= 0:
            # Intrinsic at expiry
            if leg.right.lower().startswith("c"):
                return max(spot - leg.strike, 0.0)
            return max(leg.strike - spot, 0.0)
        try:
            g = black_scholes(
                spot=spot,
                strike=leg.strike,
                time_to_expiry=dte / 365.0,
                volatility=(leg.volatility_pct or 30.0) / 100.0,
                risk_free_rate=r_pct / 100.0,
                dividend_yield=q_pct / 100.0,
                style=leg.right.lower(),
            )
            return g.price
        except (ValueError, ArithmeticError):
            return 0.0
    return 0.0


def simulate_strategy(
    legs: list[StrategyLeg],
    spot_range: tuple[float, float],
    spot_steps: int = 41,
    risk_free_rate_pct: float = 0.0,
    dividend_yield_pct: float = 0.0,
    days_forward: float = 0,
    at_expiry: bool = True,
) -> dict[str, Any]:
    """Simulate strategy P&L across a spot range.

    Args:
        legs: list of StrategyLeg.
        spot_range: (low, high) underlying price range to scan.
        spot_steps: number of grid points (default 41).
        risk_free_rate_pct: discount rate for BS pricing.
        dividend_yield_pct: 0 for non-dividend / index futures.
        days_forward: simulate `days_forward` days from now (subtract from
            each leg's DTE). Set to 0 for "now". Ignored when at_expiry=True.
        at_expiry: if True, evaluate each option at intrinsic (DTE = 0).

    Returns dict with:
        - grid: list of {spot, pnl, leg_pnls}
        - max_profit / max_loss (within scanned range; may be capped)
        - breakevens: spot values where pnl crosses 0
        - net_debit_credit: total premium paid (negative = received)
        - leg_summary: per-leg pricing
    """
    if spot_steps < 2:
        raise ValueError("spot_steps must be >= 2")
    low, high = spot_range
    if low >= high:
        raise ValueError("spot_range low must be < high")

    # Per-leg entry cost: if entry_price given, use it; otherwise compute mid
    leg_entry: list[float] = []
    leg_summary: list[dict[str, Any]] = []
    for leg in legs:
        if leg.entry_price is not None:
            entry = float(leg.entry_price)
        else:
            # Use current spot mid as a fallback — but caller usually passes entry
            mid_spot = 0.5 * (low + high)
            entry = _price_leg_at(leg, mid_spot, risk_free_rate_pct,
                                   dividend_yield_pct)
        leg_entry.append(entry)
        leg_summary.append({
            "instrument_type": leg.instrument_type,
            "qty": leg.qty,
            "strike": leg.strike,
            "right": leg.right,
            "days_to_expiry": leg.days_to_expiry,
            "volatility_pct": leg.volatility_pct,
            "entry_price": entry,
            "multiplier": leg.multiplier,
        })

    net_debit_credit = sum(
        leg.qty * leg.multiplier * leg_entry[i]
        for i, leg in enumerate(legs)
    )

    grid = []
    pnls = []
    step = (high - low) / (spot_steps - 1)
    for i in range(spot_steps):
        s = low + i * step
        leg_pnls = []
        total = 0.0
        for j, leg in enumerate(legs):
            if at_expiry:
                cur = _price_leg_at(leg, s, risk_free_rate_pct,
                                     dividend_yield_pct, dte_override=0)
            else:
                dte_now = (leg.days_to_expiry or 0) - days_forward
                cur = _price_leg_at(leg, s, risk_free_rate_pct,
                                     dividend_yield_pct,
                                     dte_override=max(dte_now, 0))
            leg_pnl = leg.qty * leg.multiplier * (cur - leg_entry[j])
            leg_pnls.append({
                "leg_index": j,
                "value_at_spot": cur,
                "leg_pnl": leg_pnl,
            })
            total += leg_pnl
        grid.append({"spot": s, "pnl": total, "leg_pnls": leg_pnls})
        pnls.append(total)

    # Breakevens: spot values where pnl sign changes
    breakevens: list[float] = []
    for i in range(1, len(grid)):
        prev = grid[i - 1]["pnl"]
        cur = grid[i]["pnl"]
        if prev == 0:
            breakevens.append(grid[i - 1]["spot"])
            continue
        if (prev < 0 < cur) or (prev > 0 > cur):
            # Linear interp
            s0 = grid[i - 1]["spot"]
            s1 = grid[i]["spot"]
            be = s0 - prev * (s1 - s0) / (cur - prev)
            breakevens.append(be)

    return {
        "legs": leg_summary,
        "net_debit_credit": net_debit_credit,
        "max_profit": max(pnls),
        "max_loss": min(pnls),
        "max_profit_at_spot": grid[pnls.index(max(pnls))]["spot"],
        "max_loss_at_spot": grid[pnls.index(min(pnls))]["spot"],
        "breakevens": breakevens,
        "spot_range": [low, high],
        "spot_steps": spot_steps,
        "at_expiry": at_expiry,
        "days_forward": 0 if at_expiry else days_forward,
        "grid": grid,
    }


# ---------------------------------------------------------------------------
# Strategy templates — common multi-leg structures.
# Each template returns a list[StrategyLeg] ready to feed into simulate_strategy.
# Pricing happens inside simulate_strategy; templates just define geometry.
# ---------------------------------------------------------------------------

def long_straddle(strike: float, dte: float, vol_pct: float,
                   qty: int = 1, multiplier: float = 1.0,
                   entry_call: float | None = None,
                   entry_put: float | None = None) -> list[StrategyLeg]:
    """Long call + long put at same strike. Profits from large moves either way."""
    return [
        StrategyLeg("option", qty, strike, "call", dte, vol_pct,
                     entry_price=entry_call, multiplier=multiplier),
        StrategyLeg("option", qty, strike, "put", dte, vol_pct,
                     entry_price=entry_put, multiplier=multiplier),
    ]


def short_straddle(strike: float, dte: float, vol_pct: float,
                    qty: int = 1, multiplier: float = 1.0,
                    entry_call: float | None = None,
                    entry_put: float | None = None) -> list[StrategyLeg]:
    """Short call + short put. Profits if underlying stays near strike."""
    return [
        StrategyLeg("option", -qty, strike, "call", dte, vol_pct,
                     entry_price=entry_call, multiplier=multiplier),
        StrategyLeg("option", -qty, strike, "put", dte, vol_pct,
                     entry_price=entry_put, multiplier=multiplier),
    ]


def long_strangle(put_strike: float, call_strike: float, dte: float,
                   vol_pct: float, qty: int = 1, multiplier: float = 1.0,
                   entry_call: float | None = None,
                   entry_put: float | None = None) -> list[StrategyLeg]:
    """Long OTM call + long OTM put. Cheaper than straddle, needs bigger move."""
    if put_strike >= call_strike:
        raise ValueError("put_strike must be < call_strike")
    return [
        StrategyLeg("option", qty, call_strike, "call", dte, vol_pct,
                     entry_price=entry_call, multiplier=multiplier),
        StrategyLeg("option", qty, put_strike, "put", dte, vol_pct,
                     entry_price=entry_put, multiplier=multiplier),
    ]


def iron_condor(put_low: float, put_high: float, call_low: float,
                 call_high: float, dte: float, vol_pct: float,
                 qty: int = 1, multiplier: float = 1.0) -> list[StrategyLeg]:
    """Sell put_high + buy put_low + sell call_low + buy call_high.

    Strike order: put_low < put_high < call_low < call_high.
    Profits if underlying stays between put_high and call_low.
    """
    if not (put_low < put_high < call_low < call_high):
        raise ValueError(
            "strikes must satisfy put_low < put_high < call_low < call_high")
    return [
        StrategyLeg("option", qty, put_low, "put", dte, vol_pct,
                     multiplier=multiplier),
        StrategyLeg("option", -qty, put_high, "put", dte, vol_pct,
                     multiplier=multiplier),
        StrategyLeg("option", -qty, call_low, "call", dte, vol_pct,
                     multiplier=multiplier),
        StrategyLeg("option", qty, call_high, "call", dte, vol_pct,
                     multiplier=multiplier),
    ]


def butterfly(low: float, mid: float, high: float, right: str, dte: float,
               vol_pct: float, qty: int = 1, multiplier: float = 1.0) -> list[StrategyLeg]:
    """Buy 1 low + sell 2 mid + buy 1 high — same right (call or put).

    Profits if underlying lands near `mid` at expiry.
    """
    if not (low < mid < high):
        raise ValueError("strikes must satisfy low < mid < high")
    return [
        StrategyLeg("option", qty, low, right, dte, vol_pct, multiplier=multiplier),
        StrategyLeg("option", -2 * qty, mid, right, dte, vol_pct, multiplier=multiplier),
        StrategyLeg("option", qty, high, right, dte, vol_pct, multiplier=multiplier),
    ]


def vertical_spread(low_strike: float, high_strike: float, right: str,
                     direction: str, dte: float, vol_pct: float,
                     qty: int = 1, multiplier: float = 1.0) -> list[StrategyLeg]:
    """Vertical spread.

    direction='bull': buy low_strike, sell high_strike (bullish on calls,
                     bearish premium on puts).
    direction='bear': opposite.
    """
    if low_strike >= high_strike:
        raise ValueError("low_strike must be < high_strike")
    direction_l = direction.lower()
    if direction_l == "bull":
        return [
            StrategyLeg("option", qty, low_strike, right, dte, vol_pct,
                         multiplier=multiplier),
            StrategyLeg("option", -qty, high_strike, right, dte, vol_pct,
                         multiplier=multiplier),
        ]
    if direction_l == "bear":
        return [
            StrategyLeg("option", -qty, low_strike, right, dte, vol_pct,
                         multiplier=multiplier),
            StrategyLeg("option", qty, high_strike, right, dte, vol_pct,
                         multiplier=multiplier),
        ]
    raise ValueError(f"direction must be 'bull' or 'bear', got {direction!r}")


STRATEGY_TEMPLATES = {
    "long_straddle": long_straddle,
    "short_straddle": short_straddle,
    "long_strangle": long_strangle,
    "iron_condor": iron_condor,
    "butterfly": butterfly,
    "vertical_spread": vertical_spread,
}


__all__ = [
    "StrategyLeg",
    "simulate_strategy",
    "long_straddle",
    "short_straddle",
    "long_strangle",
    "iron_condor",
    "butterfly",
    "vertical_spread",
    "STRATEGY_TEMPLATES",
]

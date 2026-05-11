"""Black-Scholes option pricing + greeks.

Pure-math module, no network. Used by `calculate_option_greeks` tool to
price VIOP options and surface delta/gamma/theta/vega/rho for risk and
sizing decisions.

Conventions:
- All rates (`r`, `q`, `sigma`) passed as DECIMALS (0.45 = %45).
- `T` is in years (so 30 days = 30/365).
- `style` accepts "call" or "put" (case-insensitive).
- Theta is per-year; divide by 365 for daily decay.
- IV solver supports a -50% to 500% bracket — wide enough for distressed
  TR equity options without false-bracket failures.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass
class OptionGreeks:
    price: float
    delta: float
    gamma: float
    theta_per_year: float
    vega: float
    rho: float


def _phi(x: float) -> float:
    """Standard-normal pdf."""
    return math.exp(-0.5 * x * x) / math.sqrt(2 * math.pi)


def _N(x: float) -> float:
    """Standard-normal cdf via the error function."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def black_scholes(
    spot: float,
    strike: float,
    time_to_expiry: float,
    volatility: float,
    risk_free_rate: float,
    dividend_yield: float = 0.0,
    style: str = "call",
) -> OptionGreeks:
    """Return price + greeks for a European option."""
    if spot <= 0 or strike <= 0:
        raise ValueError("spot and strike must be positive")
    if time_to_expiry <= 0:
        raise ValueError("time_to_expiry must be > 0")
    if volatility <= 0:
        raise ValueError("volatility must be > 0")

    s = float(spot)
    k = float(strike)
    t = float(time_to_expiry)
    sigma = float(volatility)
    r = float(risk_free_rate)
    q = float(dividend_yield)
    style_l = style.lower().strip()

    d1 = (math.log(s / k) + (r - q + 0.5 * sigma * sigma) * t) / (sigma * math.sqrt(t))
    d2 = d1 - sigma * math.sqrt(t)

    if style_l in ("call", "c"):
        price = s * math.exp(-q * t) * _N(d1) - k * math.exp(-r * t) * _N(d2)
        delta = math.exp(-q * t) * _N(d1)
        theta = (
            -(s * _phi(d1) * sigma * math.exp(-q * t)) / (2 * math.sqrt(t))
            - r * k * math.exp(-r * t) * _N(d2)
            + q * s * math.exp(-q * t) * _N(d1)
        )
        rho = k * t * math.exp(-r * t) * _N(d2)
    elif style_l in ("put", "p"):
        price = k * math.exp(-r * t) * _N(-d2) - s * math.exp(-q * t) * _N(-d1)
        delta = -math.exp(-q * t) * _N(-d1)
        theta = (
            -(s * _phi(d1) * sigma * math.exp(-q * t)) / (2 * math.sqrt(t))
            + r * k * math.exp(-r * t) * _N(-d2)
            - q * s * math.exp(-q * t) * _N(-d1)
        )
        rho = -k * t * math.exp(-r * t) * _N(-d2)
    else:
        raise ValueError(f"unknown style: {style!r} (use 'call' or 'put')")

    gamma = (math.exp(-q * t) * _phi(d1)) / (s * sigma * math.sqrt(t))
    vega = s * math.exp(-q * t) * _phi(d1) * math.sqrt(t)

    return OptionGreeks(
        price=price,
        delta=delta,
        gamma=gamma,
        theta_per_year=theta,
        vega=vega,
        rho=rho,
    )


def implied_volatility(
    market_price: float,
    spot: float,
    strike: float,
    time_to_expiry: float,
    risk_free_rate: float,
    dividend_yield: float = 0.0,
    style: str = "call",
    tol: float = 1e-6,
    max_iter: int = 200,
) -> float:
    """Solve for sigma by bisection. Returns IV as a decimal (0.45 = %45).

    Bracket is intentionally wide (1bp to 500%) to handle distressed TR
    equity options without false-bracket failures.
    """
    if market_price <= 0:
        raise ValueError("market_price must be positive")

    def diff(vol: float) -> float:
        try:
            g = black_scholes(
                spot, strike, time_to_expiry, vol, risk_free_rate, dividend_yield, style
            )
        except ValueError:
            return float("nan")
        return g.price - market_price

    low, high = 0.0001, 5.0
    f_low = diff(low)
    f_high = diff(high)
    if math.isnan(f_low) or math.isnan(f_high):
        raise ArithmeticError("IV bisection: NaN at bracket endpoints")
    if f_low * f_high > 0:
        raise ArithmeticError(
            "IV not bracketed in (1bp, 500%) — check market_price vs intrinsic"
        )

    for _ in range(max_iter):
        mid = 0.5 * (low + high)
        f_mid = diff(mid)
        if abs(f_mid) < tol:
            return mid
        if f_mid * f_low < 0:
            high = mid
            f_high = f_mid
        else:
            low = mid
            f_low = f_mid
    return 0.5 * (low + high)

"""Closed-form bond pricing math.

Conventions:
- Rates passed in as percent (e.g. coupon 25.0 = %25 annual coupon).
- Returned YTM is a decimal (e.g. 0.42 = %42).
- Coupon frequency is the number of coupon payments per year.
- We assume settlement is exactly at the previous coupon (no accrued / clean
  price). Sufficient for a research tool; full ISMA / accrual conventions can
  be added later.
"""

from __future__ import annotations


def _price_from_ytm(
    face_value: float,
    coupon_rate: float,
    years_to_maturity: float,
    ytm: float,
    coupon_frequency: int,
) -> float:
    """Price of a coupon bond given a periodic yield."""
    n_periods = int(round(years_to_maturity * coupon_frequency))
    if n_periods <= 0:
        raise ValueError("years_to_maturity * coupon_frequency must yield >= 1 period")
    periodic_coupon = face_value * coupon_rate / coupon_frequency
    periodic_yield = ytm / coupon_frequency

    price = 0.0
    for t in range(1, n_periods + 1):
        discount = (1 + periodic_yield) ** t
        price += periodic_coupon / discount
    price += face_value / ((1 + periodic_yield) ** n_periods)
    return price


def _solve_ytm(
    face_value: float,
    coupon_rate: float,
    years_to_maturity: float,
    market_price: float,
    coupon_frequency: int,
    tol: float = 1e-8,
    max_iter: int = 200,
) -> float:
    """Bisection solver for YTM (annualised, decimal)."""
    if market_price <= 0:
        raise ValueError("market_price must be positive")

    low, high = -0.5, 5.0  # Wide bracket: -50% to 500% (TR yields can be extreme)
    p_low = _price_from_ytm(face_value, coupon_rate, years_to_maturity, low, coupon_frequency)
    p_high = _price_from_ytm(face_value, coupon_rate, years_to_maturity, high, coupon_frequency)

    if (p_low - market_price) * (p_high - market_price) > 0:
        raise ArithmeticError(
            "YTM not bracketed in [-50%, 500%]; check inputs (price possibly inconsistent)"
        )

    for _ in range(max_iter):
        mid = 0.5 * (low + high)
        p_mid = _price_from_ytm(face_value, coupon_rate, years_to_maturity, mid, coupon_frequency)
        if abs(p_mid - market_price) < tol:
            return mid
        if (p_mid - market_price) * (p_low - market_price) < 0:
            high = mid
            p_high = p_mid
        else:
            low = mid
            p_low = p_mid
    return 0.5 * (low + high)


def _macaulay_duration(
    face_value: float,
    coupon_rate: float,
    years_to_maturity: float,
    ytm: float,
    coupon_frequency: int,
) -> float:
    n_periods = int(round(years_to_maturity * coupon_frequency))
    periodic_coupon = face_value * coupon_rate / coupon_frequency
    periodic_yield = ytm / coupon_frequency

    pv_weighted = 0.0
    pv_total = 0.0
    for t in range(1, n_periods + 1):
        cf = periodic_coupon + (face_value if t == n_periods else 0.0)
        pv = cf / ((1 + periodic_yield) ** t)
        pv_weighted += t * pv
        pv_total += pv
    if pv_total == 0:
        raise ArithmeticError("Zero present value; cannot compute duration")
    return (pv_weighted / pv_total) / coupon_frequency  # back to years


def _convexity(
    face_value: float,
    coupon_rate: float,
    years_to_maturity: float,
    ytm: float,
    coupon_frequency: int,
) -> float:
    n_periods = int(round(years_to_maturity * coupon_frequency))
    periodic_coupon = face_value * coupon_rate / coupon_frequency
    periodic_yield = ytm / coupon_frequency

    pv_total = 0.0
    convex_sum = 0.0
    for t in range(1, n_periods + 1):
        cf = periodic_coupon + (face_value if t == n_periods else 0.0)
        pv = cf / ((1 + periodic_yield) ** t)
        pv_total += pv
        convex_sum += cf * t * (t + 1) / ((1 + periodic_yield) ** (t + 2))
    if pv_total == 0:
        raise ArithmeticError("Zero present value; cannot compute convexity")
    return (convex_sum / pv_total) / (coupon_frequency ** 2)


def bond_metrics(
    face_value: float,
    coupon_rate_pct: float,
    years_to_maturity: float,
    market_price: float,
    coupon_frequency: int = 2,
) -> tuple[float, float, float]:
    """Return (ytm_decimal, modified_duration_years, convexity_years_sq)."""
    if face_value <= 0:
        raise ValueError("face_value must be positive")
    if years_to_maturity <= 0:
        raise ValueError("years_to_maturity must be positive")
    if coupon_frequency <= 0:
        raise ValueError("coupon_frequency must be positive")

    coupon_rate = coupon_rate_pct / 100.0
    ytm = _solve_ytm(
        face_value=face_value,
        coupon_rate=coupon_rate,
        years_to_maturity=years_to_maturity,
        market_price=market_price,
        coupon_frequency=coupon_frequency,
    )
    mac_dur = _macaulay_duration(
        face_value, coupon_rate, years_to_maturity, ytm, coupon_frequency
    )
    mod_dur = mac_dur / (1 + ytm / coupon_frequency)
    convex = _convexity(
        face_value, coupon_rate, years_to_maturity, ytm, coupon_frequency
    )
    return ytm, mod_dur, convex

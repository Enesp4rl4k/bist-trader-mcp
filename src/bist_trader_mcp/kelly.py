"""Kelly criterion + position sizing helpers — pure math.

Three variants:

1. **Bet Kelly** (discrete): f* = (p·b - q) / b
   where p=win probability, q=1-p, b=win/loss ratio.

2. **Continuous Kelly** (returns-based): f* = μ / σ²
   for a single asset with normal returns; classic for swing trades.

3. **Fractional Kelly**: f_frac = k · f* (typically k=0.25-0.5)
   to dampen variance — the canonical practitioner approach.

All return a position size as a *fraction of equity* (0.0-1.0+).
Values >1 indicate the math says lever up; cap at user's max leverage.

Practical addition: `position_size_from_atr` — sizes a trade so a fixed
% of equity is at risk per ATR multiple of stop loss.
"""

from __future__ import annotations

from typing import Any


def kelly_bet(
    win_probability: float,
    win_loss_ratio: float,
) -> float:
    """Discrete Kelly: f* = (p·b - q) / b.

    Args:
        win_probability: 0-1.
        win_loss_ratio: avg_win / avg_loss (both positive).
    """
    if not 0 < win_probability < 1:
        raise ValueError("win_probability must be in (0,1)")
    if win_loss_ratio <= 0:
        raise ValueError("win_loss_ratio must be > 0")
    p = win_probability
    q = 1 - p
    return (p * win_loss_ratio - q) / win_loss_ratio


def kelly_continuous(
    annualised_return_pct: float,
    annualised_volatility_pct: float,
    risk_free_pct: float = 0.0,
) -> float:
    """Continuous Kelly: f* = (μ - rf) / σ². Returns position fraction."""
    if annualised_volatility_pct <= 0:
        raise ValueError("annualised_volatility_pct must be > 0")
    mu = (annualised_return_pct - risk_free_pct) / 100.0
    sigma = annualised_volatility_pct / 100.0
    return mu / (sigma * sigma)


def kelly_panel(
    win_probability: float | None = None,
    win_loss_ratio: float | None = None,
    annualised_return_pct: float | None = None,
    annualised_volatility_pct: float | None = None,
    risk_free_pct: float = 0.0,
    kelly_fractions: list[float] | None = None,
) -> dict[str, Any]:
    """One-shot Kelly panel: bet Kelly + continuous Kelly + fractional variants.

    Either provide (win_probability, win_loss_ratio) for bet Kelly, or
    (annualised_return_pct, annualised_volatility_pct) for continuous,
    or both for cross-check.
    """
    out: dict[str, Any] = {"inputs": {
        "win_probability": win_probability,
        "win_loss_ratio": win_loss_ratio,
        "annualised_return_pct": annualised_return_pct,
        "annualised_volatility_pct": annualised_volatility_pct,
        "risk_free_pct": risk_free_pct,
    }}

    if win_probability is not None and win_loss_ratio is not None:
        try:
            f_bet = kelly_bet(win_probability, win_loss_ratio)
            out["bet_kelly_fraction"] = f_bet
        except ValueError as e:
            out["bet_kelly_error"] = str(e)

    if (annualised_return_pct is not None and
            annualised_volatility_pct is not None):
        try:
            f_cont = kelly_continuous(annualised_return_pct,
                                       annualised_volatility_pct, risk_free_pct)
            out["continuous_kelly_fraction"] = f_cont
        except ValueError as e:
            out["continuous_kelly_error"] = str(e)

    fractions = kelly_fractions or [0.25, 0.5, 1.0]
    full = out.get("bet_kelly_fraction") or out.get("continuous_kelly_fraction")
    if full is not None:
        out["fractional_kelly"] = {
            f"fraction_{int(f * 100)}pct": full * f for f in fractions
        }
    return out


def position_size_from_atr(
    equity: float,
    entry_price: float,
    atr: float,
    atr_multiple_stop: float = 2.0,
    risk_per_trade_pct: float = 1.0,
) -> dict[str, Any]:
    """Volatility-based position sizing.

    Sizes a trade so that, if stopped out at `atr_multiple_stop` ATRs from
    entry, the loss equals `risk_per_trade_pct`% of equity. This is the
    canonical "1% rule" sizing for trend-following.

    Args:
        equity: total account equity.
        entry_price: planned entry.
        atr: ATR(14) or similar volatility measure in the same units as price.
        atr_multiple_stop: stop distance in ATR multiples (default 2).
        risk_per_trade_pct: % of equity to risk per trade (default 1%).

    Returns dict with shares, stop_price, stop_distance, and risk_amount.
    """
    if equity <= 0:
        raise ValueError("equity must be > 0")
    if entry_price <= 0:
        raise ValueError("entry_price must be > 0")
    if atr <= 0:
        raise ValueError("atr must be > 0")
    if atr_multiple_stop <= 0:
        raise ValueError("atr_multiple_stop must be > 0")
    if risk_per_trade_pct <= 0:
        raise ValueError("risk_per_trade_pct must be > 0")

    risk_amount = equity * (risk_per_trade_pct / 100.0)
    stop_distance = atr * atr_multiple_stop
    shares = risk_amount / stop_distance
    notional = shares * entry_price

    return {
        "equity": equity,
        "entry_price": entry_price,
        "atr": atr,
        "atr_multiple_stop": atr_multiple_stop,
        "stop_distance": stop_distance,
        "stop_price_long": entry_price - stop_distance,
        "stop_price_short": entry_price + stop_distance,
        "risk_amount": risk_amount,
        "risk_per_trade_pct": risk_per_trade_pct,
        "shares": shares,
        "notional": notional,
        "leverage": notional / equity,
    }


__all__ = [
    "kelly_bet",
    "kelly_continuous",
    "kelly_panel",
    "position_size_from_atr",
]

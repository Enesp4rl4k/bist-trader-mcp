"""Performance metrics — Sharpe, Sortino, Calmar, max drawdown, win rate.

Pure-math module. Takes either a returns series or an equity curve and
returns standard portfolio performance statistics. Used by `backtest`
output and as a standalone tool.

All annualisation defaults to 252 trading days; use 365 for 24/7 crypto.
"""

from __future__ import annotations

import math
from typing import Any


def annualised_return(returns: list[float], periods_per_year: int = 252) -> float | None:
    """Geometric mean return × periods_per_year."""
    if not returns:
        return None
    cum = 1.0
    for r in returns:
        cum *= (1 + r)
    n = len(returns)
    if cum <= 0:
        return None
    return (cum ** (periods_per_year / n) - 1) * 100.0


def annualised_volatility(returns: list[float], periods_per_year: int = 252) -> float | None:
    """Stdev of returns × sqrt(periods_per_year)."""
    if len(returns) < 2:
        return None
    mean = sum(returns) / len(returns)
    var = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
    return math.sqrt(var * periods_per_year) * 100.0


def sharpe_ratio(
    returns: list[float],
    risk_free_pct: float = 0.0,
    periods_per_year: int = 252,
) -> float | None:
    """Standard Sharpe: (μ - rf) / σ, annualised."""
    if len(returns) < 2:
        return None
    rf_per_period = (risk_free_pct / 100.0) / periods_per_year
    excess = [r - rf_per_period for r in returns]
    mean = sum(excess) / len(excess)
    var = sum((r - mean) ** 2 for r in excess) / (len(excess) - 1)
    sd = math.sqrt(var)
    if sd == 0:
        return None
    return (mean / sd) * math.sqrt(periods_per_year)


def sortino_ratio(
    returns: list[float],
    risk_free_pct: float = 0.0,
    periods_per_year: int = 252,
) -> float | None:
    """Sortino: (μ - rf) / downside_deviation, annualised."""
    if len(returns) < 2:
        return None
    rf_per_period = (risk_free_pct / 100.0) / periods_per_year
    excess = [r - rf_per_period for r in returns]
    mean = sum(excess) / len(excess)
    downside = [r for r in excess if r < 0]
    if not downside:
        return None
    dd = math.sqrt(sum(r ** 2 for r in downside) / len(downside))
    if dd == 0:
        return None
    return (mean / dd) * math.sqrt(periods_per_year)


def max_drawdown(equity_curve: list[float]) -> dict[str, Any]:
    """Max drawdown depth, duration, and peak/trough indices."""
    if not equity_curve:
        return {"max_drawdown_pct": None, "peak_index": None,
                "trough_index": None, "duration_bars": None}
    peak = equity_curve[0]
    peak_idx = 0
    max_dd = 0.0
    dd_peak_idx = 0
    dd_trough_idx = 0
    for i, v in enumerate(equity_curve):
        if v > peak:
            peak = v
            peak_idx = i
        if peak > 0:
            dd = (v - peak) / peak
            if dd < max_dd:
                max_dd = dd
                dd_peak_idx = peak_idx
                dd_trough_idx = i
    return {
        "max_drawdown_pct": max_dd * 100.0,
        "peak_index": dd_peak_idx,
        "trough_index": dd_trough_idx,
        "duration_bars": dd_trough_idx - dd_peak_idx if max_dd < 0 else 0,
    }


def calmar_ratio(
    returns: list[float],
    equity_curve: list[float] | None = None,
    periods_per_year: int = 252,
) -> float | None:
    """Calmar: annualised return / |max drawdown|."""
    ann_ret = annualised_return(returns, periods_per_year)
    if ann_ret is None:
        return None
    if equity_curve is None:
        # Build implicit curve
        eq = [1.0]
        for r in returns:
            eq.append(eq[-1] * (1 + r))
        equity_curve = eq
    dd = max_drawdown(equity_curve)
    if dd["max_drawdown_pct"] is None or dd["max_drawdown_pct"] == 0:
        return None
    return ann_ret / abs(dd["max_drawdown_pct"])


def trade_statistics(trade_pnls: list[float]) -> dict[str, Any]:
    """Trade-level stats: win rate, profit factor, avg win/loss."""
    if not trade_pnls:
        return {"trades": 0, "win_rate_pct": None, "profit_factor": None,
                "avg_win": None, "avg_loss": None, "expectancy": None}
    wins = [t for t in trade_pnls if t > 0]
    losses = [t for t in trade_pnls if t < 0]
    gross_win = sum(wins)
    gross_loss = -sum(losses)
    pf = (gross_win / gross_loss) if gross_loss > 0 else None
    win_rate = (len(wins) / len(trade_pnls)) * 100.0
    avg_win = (sum(wins) / len(wins)) if wins else None
    avg_loss = (sum(losses) / len(losses)) if losses else None
    expectancy = sum(trade_pnls) / len(trade_pnls)
    return {
        "trades": len(trade_pnls),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate_pct": win_rate,
        "profit_factor": pf,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "expectancy": expectancy,
        "gross_profit": gross_win,
        "gross_loss": -gross_loss,
    }


def performance_panel(
    returns: list[float],
    equity_curve: list[float] | None = None,
    trade_pnls: list[float] | None = None,
    risk_free_pct: float = 0.0,
    periods_per_year: int = 252,
) -> dict[str, Any]:
    """One-shot performance panel."""
    if equity_curve is None:
        eq = [1.0]
        for r in returns:
            eq.append(eq[-1] * (1 + r))
        equity_curve = eq

    return {
        "periods_per_year": periods_per_year,
        "bars": len(returns),
        "annualised_return_pct": annualised_return(returns, periods_per_year),
        "annualised_volatility_pct": annualised_volatility(returns, periods_per_year),
        "sharpe_ratio": sharpe_ratio(returns, risk_free_pct, periods_per_year),
        "sortino_ratio": sortino_ratio(returns, risk_free_pct, periods_per_year),
        "calmar_ratio": calmar_ratio(returns, equity_curve, periods_per_year),
        "drawdown": max_drawdown(equity_curve),
        "final_equity": equity_curve[-1] if equity_curve else None,
        "total_return_pct": (
            (equity_curve[-1] / equity_curve[0] - 1) * 100.0
            if equity_curve and equity_curve[0] > 0 else None
        ),
        "trade_stats": trade_statistics(trade_pnls) if trade_pnls else None,
    }


__all__ = [
    "annualised_return",
    "annualised_volatility",
    "sharpe_ratio",
    "sortino_ratio",
    "max_drawdown",
    "calmar_ratio",
    "trade_statistics",
    "performance_panel",
]

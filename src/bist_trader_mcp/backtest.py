"""Backtester — signals → trades → equity curve.

Pure-math. Takes a closes series + a signal series (+1 long, -1 short,
0 flat) and produces a full backtest output:
- equity curve
- per-trade P&L
- transaction-cost-adjusted returns
- full performance panel (Sharpe, Sortino, drawdown, etc.)

Signals are expected to be aligned with closes (signal[t] = position
held at the end of bar t, applied to bar t+1's return — standard
event-driven backtest convention).

Cost model:
- `commission_pct`: per-trade cost as % of notional (one-way).
- `slippage_pct`: additional cost simulating market impact.

For long-only equity backtests pass signals ∈ {0, 1}. For long/short
strategies pass {-1, 0, 1}. Fractional sizing (e.g. 0.5) is allowed.
"""

from __future__ import annotations

import math
from typing import Any

from .performance import performance_panel


def run_backtest(
    closes: list[float],
    signals: list[float],
    initial_equity: float = 100000.0,
    commission_pct: float = 0.05,
    slippage_pct: float = 0.05,
    risk_free_pct: float = 0.0,
    periods_per_year: int = 252,
) -> dict[str, Any]:
    """Run an event-driven backtest.

    Args:
        closes: price series (length N).
        signals: position size per bar (length N or N-1). signal[t] is
            the position held during bar t→t+1.
        initial_equity: starting cash.
        commission_pct: one-way commission as % of notional (per trade leg).
        slippage_pct: extra cost per leg (simulates market impact).
        risk_free_pct: annual risk-free for Sharpe.
        periods_per_year: 252 equity / 365 crypto.

    Returns dict with equity_curve, returns, trades, and a full
    performance_panel.
    """
    if len(closes) < 2:
        return {"error": "bad_input", "detail": "need at least 2 closes"}
    if len(signals) < len(closes) - 1:
        # Pad with last signal (or zero)
        last = signals[-1] if signals else 0.0
        signals = list(signals) + [last] * (len(closes) - 1 - len(signals))

    cost_per_leg = (commission_pct + slippage_pct) / 100.0
    equity_curve: list[float] = [initial_equity]
    returns: list[float] = []
    trades: list[dict[str, Any]] = []

    prev_signal = 0.0
    open_trade: dict[str, Any] | None = None
    cur_equity = initial_equity

    for t in range(len(closes) - 1):
        signal = signals[t]
        price_t = closes[t]
        price_next = closes[t + 1]
        if price_t <= 0:
            equity_curve.append(cur_equity)
            returns.append(0.0)
            prev_signal = signal
            continue

        bar_ret = (price_next - price_t) / price_t
        position_ret = signal * bar_ret

        # Transaction cost on signal change
        position_change = abs(signal - prev_signal)
        cost = position_change * cost_per_leg
        net_ret = position_ret - cost

        cur_equity *= (1 + net_ret)
        equity_curve.append(cur_equity)
        returns.append(net_ret)

        # Trade lifecycle tracking
        if open_trade is None and signal != 0:
            open_trade = {
                "entry_bar": t,
                "entry_price": price_t,
                "signal": signal,
                "entry_equity": cur_equity / (1 + net_ret),
            }
        elif open_trade is not None and (signal == 0 or
                                          (signal * open_trade["signal"]) < 0):
            # Closed (flat) or flipped
            exit_price = price_t
            entry_price = open_trade["entry_price"]
            sig = open_trade["signal"]
            trade_pnl_pct = sig * (exit_price / entry_price - 1) - cost_per_leg * 2
            trade_pnl_amt = open_trade["entry_equity"] * trade_pnl_pct
            trades.append({
                "entry_bar": open_trade["entry_bar"],
                "exit_bar": t,
                "entry_price": entry_price,
                "exit_price": exit_price,
                "signal": sig,
                "pnl_pct": trade_pnl_pct * 100.0,
                "pnl_amount": trade_pnl_amt,
                "duration_bars": t - open_trade["entry_bar"],
            })
            # If flipped, open new trade
            if signal != 0:
                open_trade = {
                    "entry_bar": t,
                    "entry_price": price_t,
                    "signal": signal,
                    "entry_equity": cur_equity,
                }
            else:
                open_trade = None

        prev_signal = signal

    # Close any still-open trade at the last bar
    if open_trade is not None:
        exit_price = closes[-1]
        entry_price = open_trade["entry_price"]
        sig = open_trade["signal"]
        trade_pnl_pct = sig * (exit_price / entry_price - 1) - cost_per_leg * 2
        trades.append({
            "entry_bar": open_trade["entry_bar"],
            "exit_bar": len(closes) - 1,
            "entry_price": entry_price,
            "exit_price": exit_price,
            "signal": sig,
            "pnl_pct": trade_pnl_pct * 100.0,
            "pnl_amount": open_trade["entry_equity"] * trade_pnl_pct,
            "duration_bars": len(closes) - 1 - open_trade["entry_bar"],
            "status": "open_at_end",
        })

    trade_pnls = [t["pnl_amount"] for t in trades]
    panel = performance_panel(
        returns=returns,
        equity_curve=equity_curve,
        trade_pnls=trade_pnls if trade_pnls else None,
        risk_free_pct=risk_free_pct,
        periods_per_year=periods_per_year,
    )

    return {
        "config": {
            "initial_equity": initial_equity,
            "commission_pct": commission_pct,
            "slippage_pct": slippage_pct,
            "bars": len(closes),
        },
        "equity_curve": equity_curve,
        "returns": returns,
        "trades": trades,
        "performance": panel,
    }


# ---------------------------------------------------------------------------
# Common signal generators — useful primitives to feed into run_backtest
# ---------------------------------------------------------------------------

def signal_from_sma_crossover(
    closes: list[float],
    fast: int = 20,
    slow: int = 50,
    allow_short: bool = False,
) -> list[float]:
    """Classic SMA fast/slow crossover. +1 when fast > slow, else 0 (or -1)."""
    from .technicals import sma
    sma_fast = sma(closes, fast)
    sma_slow = sma(closes, slow)
    out: list[float] = []
    for f, s in zip(sma_fast, sma_slow, strict=False):
        if f is None or s is None:
            out.append(0.0)
        elif f > s:
            out.append(1.0)
        else:
            out.append(-1.0 if allow_short else 0.0)
    return out


def signal_from_rsi_thresholds(
    closes: list[float],
    period: int = 14,
    oversold: float = 30.0,
    overbought: float = 70.0,
    allow_short: bool = False,
) -> list[float]:
    """Long when RSI < oversold, exit (or short) when RSI > overbought."""
    from .technicals import rsi
    rsi_vals = rsi(closes, period)
    out: list[float] = []
    position = 0.0
    for r in rsi_vals:
        if r is None:
            out.append(position)
            continue
        if r < oversold:
            position = 1.0
        elif r > overbought:
            position = -1.0 if allow_short else 0.0
        out.append(position)
    return out


def signal_from_bollinger_mean_reversion(
    closes: list[float],
    period: int = 20,
    std_dev: float = 2.0,
    allow_short: bool = False,
) -> list[float]:
    """Long when price < lower band, flat/short when price > upper band."""
    from .technicals import bollinger_bands
    bb = bollinger_bands(closes, period, std_dev)
    out: list[float] = []
    position = 0.0
    for i, price in enumerate(closes):
        upper = bb.upper[i]
        lower = bb.lower[i]
        middle = bb.middle[i]
        if upper is None or lower is None:
            out.append(position)
            continue
        if price < lower:
            position = 1.0
        elif price > upper:
            position = -1.0 if allow_short else 0.0
        elif middle is not None and ((position > 0 and price >= middle) or
                                       (position < 0 and price <= middle)):
            position = 0.0
        out.append(position)
    return out


SIGNAL_GENERATORS = {
    "sma_crossover": signal_from_sma_crossover,
    "rsi_thresholds": signal_from_rsi_thresholds,
    "bollinger_mean_reversion": signal_from_bollinger_mean_reversion,
}


__all__ = [
    "run_backtest",
    "signal_from_sma_crossover",
    "signal_from_rsi_thresholds",
    "signal_from_bollinger_mean_reversion",
    "SIGNAL_GENERATORS",
]


# Required for math import in signal generators
_ = math

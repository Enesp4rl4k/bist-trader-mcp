"""Tests for backtester — pure math."""

from __future__ import annotations

import pytest

from bist_trader_mcp.backtest import (
    SIGNAL_GENERATORS,
    run_backtest,
    signal_from_rsi_thresholds,
    signal_from_sma_crossover,
)


def test_backtest_long_perfect_uptrend():
    closes = [100.0 + i for i in range(50)]
    signals = [1.0] * 50
    result = run_backtest(closes, signals, commission_pct=0.0, slippage_pct=0.0)
    perf = result["performance"]
    assert perf["total_return_pct"] > 0
    # Equity curve should monotonically increase
    eq = result["equity_curve"]
    for i in range(1, len(eq)):
        assert eq[i] >= eq[i - 1]


def test_backtest_flat_signal_no_pnl():
    closes = [100.0 + i for i in range(50)]
    signals = [0.0] * 50
    result = run_backtest(closes, signals)
    eq = result["equity_curve"]
    assert eq[-1] == pytest.approx(eq[0])


def test_backtest_short_in_uptrend_loses_money():
    closes = [100.0 + i for i in range(50)]
    signals = [-1.0] * 50
    result = run_backtest(closes, signals, commission_pct=0.0, slippage_pct=0.0)
    assert result["performance"]["total_return_pct"] < 0


def test_backtest_commission_drag():
    closes = [100.0 + (i % 5) for i in range(50)]
    signals = [1.0 if i % 2 == 0 else 0.0 for i in range(50)]
    with_cost = run_backtest(closes, signals, commission_pct=0.5, slippage_pct=0.5)
    no_cost = run_backtest(closes, signals, commission_pct=0.0, slippage_pct=0.0)
    # Heavy commission should reduce P&L
    assert with_cost["performance"]["final_equity"] < no_cost["performance"]["final_equity"]


def test_backtest_records_trades():
    closes = [100.0, 102.0, 105.0, 103.0, 108.0, 106.0]
    signals = [1.0, 1.0, 0.0, 1.0, 0.0, 0.0]
    result = run_backtest(closes, signals, commission_pct=0.0, slippage_pct=0.0)
    assert len(result["trades"]) >= 2


def test_sma_crossover_generates_signals():
    closes = [100.0] * 30 + [100.0 + i for i in range(30)]
    sig = signal_from_sma_crossover(closes, fast=5, slow=20)
    assert len(sig) == len(closes)
    # In the rising portion fast > slow → +1
    assert sig[-1] == 1.0


def test_rsi_thresholds_signal_changes():
    closes = [100.0 + i for i in range(30)] + [130.0 - i for i in range(30)]
    sig = signal_from_rsi_thresholds(closes, period=14, oversold=30, overbought=70)
    # Should produce at least one position change
    assert len(set(sig)) >= 2


def test_signal_generators_registered():
    assert "sma_crossover" in SIGNAL_GENERATORS
    assert "rsi_thresholds" in SIGNAL_GENERATORS
    assert "bollinger_mean_reversion" in SIGNAL_GENERATORS


def test_backtest_returns_error_on_short_input():
    out = run_backtest([100.0], [1.0])
    assert "error" in out

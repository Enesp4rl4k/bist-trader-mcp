"""Tests for technicals — pure math, no network."""

from __future__ import annotations

import pytest

from bist_trader_mcp.technicals import (
    atr,
    bollinger_bands,
    compute_snapshot,
    ema,
    macd,
    rsi,
    sma,
)


def test_sma_basic():
    out = sma([1.0, 2.0, 3.0, 4.0, 5.0], 3)
    assert out[:2] == [None, None]
    assert out[2] == pytest.approx(2.0)
    assert out[3] == pytest.approx(3.0)
    assert out[4] == pytest.approx(4.0)


def test_sma_period_validation():
    with pytest.raises(ValueError):
        sma([1.0, 2.0], 0)


def test_ema_converges_for_constant_series():
    vals = [10.0] * 50
    out = ema(vals, 9)
    # After seeding, every subsequent value should be 10
    assert out[8] == pytest.approx(10.0)
    assert out[-1] == pytest.approx(10.0)


def test_rsi_strong_uptrend_above_70():
    # Monotone increasing prices → RSI should saturate near 100
    vals = list(range(1, 50))
    out = rsi([float(v) for v in vals], period=14)
    assert out[14] is not None
    # After 14 strictly-positive deltas, RSI should be > 70 (overbought)
    assert out[-1] > 70


def test_rsi_strong_downtrend_below_30():
    vals = list(range(50, 1, -1))
    out = rsi([float(v) for v in vals], period=14)
    assert out[-1] < 30


def test_macd_signal_lengths_match():
    vals = [float(i) for i in range(60)]
    res = macd(vals)
    assert len(res.macd_line) == 60
    assert len(res.signal_line) == 60
    assert len(res.histogram) == 60


def test_macd_fast_must_be_less_than_slow():
    with pytest.raises(ValueError):
        macd([1.0, 2.0, 3.0], fast=26, slow=12)


def test_bollinger_bands_contain_price_within_2sigma_eventually():
    # Constant series → bands collapse onto mean
    vals = [100.0] * 30
    bb = bollinger_bands(vals, period=20, std_dev=2.0)
    # Last band: upper == lower == middle
    assert bb.middle[-1] == pytest.approx(100.0)
    assert bb.upper[-1] == pytest.approx(100.0)
    assert bb.lower[-1] == pytest.approx(100.0)


def test_atr_length_validation():
    with pytest.raises(ValueError):
        atr([1.0, 2.0], [0.5, 1.0], [1.0], period=14)


def test_atr_positive_on_real_volatility():
    highs = [100.0 + i * 2 for i in range(30)]
    lows = [98.0 + i * 2 for i in range(30)]
    closes = [99.0 + i * 2 for i in range(30)]
    out = atr(highs, lows, closes, period=14)
    assert out[-1] is not None
    assert out[-1] > 0


def test_snapshot_labels_uptrend():
    # Long monotone uptrend → trend bullish, RSI overbought, BB upper
    closes = [float(100 + i) for i in range(250)]
    highs = [c + 0.5 for c in closes]
    lows = [c - 0.5 for c in closes]
    snap = compute_snapshot(closes, highs, lows)
    assert snap.trend_label == "bullish"
    assert snap.rsi_label == "overbought"
    assert snap.rsi_14 > 70


def test_snapshot_empty_input():
    snap = compute_snapshot([])
    assert snap.close is None
    assert snap.trend_label == "neutral"

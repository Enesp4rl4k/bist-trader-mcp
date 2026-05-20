"""Tests for realized vol estimators — pure math."""

from __future__ import annotations

import math

import pytest

from bist_trader_mcp.realized_vol import (
    close_to_close_vol,
    garman_klass_vol,
    parkinson_vol,
    realized_vol_panel,
)


def test_close_to_close_zero_for_constant():
    closes = [100.0] * 50
    out = close_to_close_vol(closes, period=30)
    assert out == pytest.approx(0.0)


def test_close_to_close_known_volatility():
    # 30% annualised on a known series: alternating ±1% daily returns
    # Daily stdev = 0.01, annualised = 0.01 * sqrt(252) ≈ 0.1587 = 15.87%
    closes = [100.0]
    for i in range(50):
        mult = 1.01 if i % 2 == 0 else 1.0 / 1.01
        closes.append(closes[-1] * mult)
    out = close_to_close_vol(closes, period=30)
    expected = 0.01 * math.sqrt(252) * 100
    assert out == pytest.approx(expected, rel=0.05)


def test_close_to_close_insufficient_data():
    out = close_to_close_vol([100.0, 101.0], period=30)
    assert out is None


def test_parkinson_validates_lengths():
    with pytest.raises(ValueError):
        parkinson_vol([100, 101], [99], period=10)


def test_parkinson_positive_with_real_range():
    highs = [100.0 + i * 2 for i in range(50)]
    lows = [98.0 + i * 2 for i in range(50)]
    out = parkinson_vol(highs, lows, period=30)
    assert out is not None
    assert out > 0


def test_garman_klass_validates_lengths():
    with pytest.raises(ValueError):
        garman_klass_vol([100], [101, 102], [99], [100], period=10)


def test_garman_klass_positive_with_real_data():
    opens = [99.0 + i * 2 for i in range(50)]
    highs = [101.0 + i * 2 for i in range(50)]
    lows = [97.0 + i * 2 for i in range(50)]
    closes = [100.0 + i * 2 for i in range(50)]
    out = garman_klass_vol(opens, highs, lows, closes, period=30)
    assert out is not None
    assert out > 0


def test_realized_panel_iv_rv_ratio():
    # When iv = rv, ratio should be 1.0
    closes = [100.0]
    for i in range(50):
        mult = 1.01 if i % 2 == 0 else 1.0 / 1.01
        closes.append(closes[-1] * mult)
    rv_cc = close_to_close_vol(closes, period=30)
    panel = realized_vol_panel(
        opens=None, highs=None, lows=None, closes=closes,
        period=30, iv_atm_pct=rv_cc,
    )
    assert panel["iv_rv_ratio_cc"] == pytest.approx(1.0, abs=0.01)


def test_realized_panel_high_iv_low_rv():
    closes = [100.0] * 50  # zero realized vol
    panel = realized_vol_panel(
        opens=None, highs=None, lows=None, closes=closes,
        period=30, iv_atm_pct=40.0,
    )
    # RV is 0, ratio should be None (division avoided)
    assert panel["close_to_close_vol_pct"] == pytest.approx(0.0)
    assert panel["iv_rv_ratio_cc"] is None

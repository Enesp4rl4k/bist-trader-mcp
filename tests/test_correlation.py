"""Tests for correlation analytics — pure math, no network."""

from __future__ import annotations

import math

import pytest

from bist_trader_mcp.correlation import (
    correlation_matrix,
    pearson,
    returns_from_closes,
    rolling_correlation,
)


def test_returns_from_closes_log_simple_agree_for_small_moves():
    closes = [100.0, 101.0, 102.01, 100.99]
    log_r = returns_from_closes(closes, "log")
    simple_r = returns_from_closes(closes, "simple")
    # For small returns log ≈ simple
    for lg, sp in zip(log_r, simple_r, strict=False):
        assert abs(lg - sp) < 0.001


def test_returns_invalid_method():
    with pytest.raises(ValueError):
        returns_from_closes([1.0, 2.0], "exponential")


def test_pearson_perfect_correlation():
    x = [1.0, 2.0, 3.0, 4.0, 5.0]
    y = [2.0, 4.0, 6.0, 8.0, 10.0]
    rho = pearson(x, y)
    assert rho == pytest.approx(1.0)


def test_pearson_perfect_anti_correlation():
    x = [1.0, 2.0, 3.0, 4.0, 5.0]
    y = [5.0, 4.0, 3.0, 2.0, 1.0]
    rho = pearson(x, y)
    assert rho == pytest.approx(-1.0)


def test_pearson_constant_returns_none():
    x = [1.0, 1.0, 1.0]
    y = [2.0, 3.0, 4.0]
    assert pearson(x, y) is None


def test_correlation_matrix_diagonal_is_one():
    series = {
        "A": [100.0, 101.0, 102.0, 103.0, 104.0, 105.0],
        "B": [50.0, 51.0, 50.5, 52.0, 51.5, 53.0],
        "C": [200.0, 198.0, 199.0, 197.0, 196.0, 195.0],
    }
    res = correlation_matrix(series)
    n = len(res["assets"])
    for i in range(n):
        assert res["matrix"][i][i] == 1.0


def test_correlation_matrix_symmetric():
    series = {
        "A": [100.0, 101.0, 102.0, 103.0, 104.0],
        "B": [50.0, 51.0, 50.5, 52.0, 53.0],
    }
    res = correlation_matrix(series)
    assert res["matrix"][0][1] == res["matrix"][1][0]


def test_correlation_matrix_identifies_high_correlation():
    # Use varied non-monotone series so returns truly correlate / anti-correlate
    moves = [0.01, -0.02, 0.015, -0.005, 0.02, -0.015, 0.01, 0.005, -0.02, 0.01,
             -0.012, 0.008, 0.018, -0.025, 0.013, -0.007, 0.011, 0.006, -0.018, 0.009]
    a_closes = [100.0]
    for r in moves:
        a_closes.append(a_closes[-1] * (1 + r))
    # b moves identically — perfect correlation
    b_closes = [50.0]
    for r in moves:
        b_closes.append(b_closes[-1] * (1 + r))
    # c moves opposite — perfect anti-correlation
    c_closes = [200.0]
    for r in moves:
        c_closes.append(c_closes[-1] * (1 - r))

    res = correlation_matrix({
        "stock_a": a_closes,
        "stock_b": b_closes,
        "stock_c": c_closes,
    })
    top = res["top_correlations"]
    assert len(top) > 0
    assert abs(top[0]["correlation"]) > 0.99
    lowest = res["lowest_correlations"]
    assert lowest[0]["correlation"] < -0.99


def test_rolling_correlation_returns_length_matches():
    a = [100.0 + i for i in range(50)]
    b = [50.0 + 0.5 * i for i in range(50)]
    out = rolling_correlation(a, b, window=10)
    # Returns have len(a) - 1; rolling indexed by return index
    assert len(out) == len(a) - 1


def test_rolling_correlation_starts_none_until_window_full():
    a = [float(i) for i in range(50)]
    b = [float(i) for i in range(50)]
    out = rolling_correlation(a, b, window=20)
    # First 19 entries (window-1) should be None
    for i in range(19):
        assert out[i] is None
    # Subsequent should be 1.0 (perfect correlation)
    for i in range(19, len(out)):
        if out[i] is not None:
            assert math.isclose(out[i], 1.0, abs_tol=1e-6)


def test_empty_series_returns_empty_result():
    res = correlation_matrix({})
    assert res["assets"] == []
    assert res["matrix"] == []

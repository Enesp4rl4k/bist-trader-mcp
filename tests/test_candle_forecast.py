"""Candle forecast ('N possible futures') + simple PA + HTML chart tests."""

import math
import random

import pytest

from bist_trader_mcp.candle_forecast import forecast_candles
from bist_trader_mcp.forecast_chart import render_forecast_html
from bist_trader_mcp.pa_simple import simple_price_action


def _series(n=400, drift=0.0, vol=0.01, seed=1):
    rng = random.Random(seed)
    closes, opens, highs, lows = [], [], [], []
    p = 100.0
    for _ in range(n):
        o = p
        c = o * math.exp(drift + rng.gauss(0, vol))
        h = max(o, c) * (1 + abs(rng.gauss(0, vol / 2)))
        lo = min(o, c) * (1 - abs(rng.gauss(0, vol / 2)))
        opens.append(o)
        closes.append(c)
        highs.append(h)
        lows.append(lo)
        p = c
    return opens, highs, lows, closes


def test_forecast_shape_and_counts():
    o, h, lo, c = _series()
    fc = forecast_candles(c, h, lo, o, horizon=24, n_paths=30, seed=7)
    assert fc["candles"]["up_count"] + fc["candles"]["down_count"] == 30
    assert fc["candles"]["up_pct"] + fc["candles"]["down_pct"] == 100
    s = fc["series"]
    assert all(len(s[k]) == 24 for k in ("mean", "band_low", "band_high", "p10", "p90"))
    for lo_, m, hi_ in zip(s["band_low"], s["mean"], s["band_high"]):
        assert lo_ <= m <= hi_
    assert fc["full_range"]["lowest_run"] == pytest.approx(s["band_low"][-1], rel=1e-6)
    assert 0 <= fc["volatility_amplification"]["count"] <= 30
    assert "olası gelecek" in fc["summary_tr"]


def test_forecast_is_deterministic_with_seed():
    o, h, lo, c = _series()
    a = forecast_candles(c, h, lo, o, seed=3)
    b = forecast_candles(c, h, lo, o, seed=3)
    assert a["series"] == b["series"]


def test_forecast_paths_are_valid_candles():
    o, h, lo, c = _series()
    fc = forecast_candles(c, h, lo, o, horizon=10, n_paths=5, seed=1, include_paths=True)
    assert len(fc["paths"]) == 5
    for path in fc["paths"]:
        assert len(path) == 10
        for k in path:
            assert k["low"] <= min(k["open"], k["close"]) <= max(k["open"], k["close"]) <= k["high"]


def test_forecast_drift_follows_trend():
    o, h, lo, c = _series(drift=0.01, vol=0.005)
    fc = forecast_candles(c, h, lo, o, seed=2, n_paths=50)
    assert fc["candles"]["up_pct"] >= 80
    zero = forecast_candles(c, h, lo, o, seed=2, n_paths=50, drift="zero")
    assert zero["mean_forecast"]["change_pct"] < fc["mean_forecast"]["change_pct"]


def test_forecast_rejects_short_history():
    o, h, lo, c = _series(n=10)
    with pytest.raises(ValueError):
        forecast_candles(c, h, lo, o)


def test_render_html_contains_panel():
    o, h, lo, c = _series()
    fc = forecast_candles(c, h, lo, o, seed=5)
    page = render_forecast_html(fc, c, h, lo, o, symbol="THYAO")
    assert page.startswith("<!doctype html>")
    assert "<svg" in page and "THYAO" in page
    assert f"%{fc['candles']['up_pct']}" in page


def test_simple_price_action_is_compact():
    o, h, lo, c = _series(drift=0.003)
    res = simple_price_action(c, h, lo, o)
    assert set(res) == {
        "price", "trend", "trend_strength", "support", "resistance", "last_event",
        "zone", "verdict", "reason", "plan", "summary_tr",
    }
    assert res["trend"] in ("yükseliş", "düşüş", "yatay")
    assert res["verdict"] in ("AL", "SAT", "BEKLE")
    if res["support"]:
        assert res["support"]["price"] < res["price"]
    if res["resistance"]:
        assert res["resistance"]["price"] > res["price"]
    if res["plan"]:
        assert res["plan"]["risk_reward"] >= 1.5

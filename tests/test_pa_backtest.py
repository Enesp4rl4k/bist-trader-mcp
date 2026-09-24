"""Walk-forward PA backtest + forecast calibration + TradingView-first loading."""

import asyncio

import pytest

from bist_trader_mcp import tools
from bist_trader_mcp.forecast_eval import evaluate_forecast_calibration
from bist_trader_mcp.pa_backtest import (
    _exit,
    _fill,
    backtest_simple_pa,
    pa_factor_attribution,
    summarize_trades,
)
from bist_trader_mcp.pa_simple import simple_price_action

from .test_candle_forecast import _series


def test_same_bar_stop_and_target_counts_as_stop():
    opens, highs, lows, closes = [100, 100], [100, 110], [100, 90], [100, 100]
    bar, px, reason = _exit("long", 1, 95.0, 105.0, True, opens, highs, lows, closes, 5)
    assert (bar, px, reason) == (1, 95.0, "stop")


def test_gap_through_stop_exits_at_open():
    opens = [100, 100, 90]
    highs = [101, 101, 91]
    lows = [99, 99, 89]
    closes = [100, 100, 90]
    bar, px, reason = _exit("long", 1, 95.0, 110.0, True, opens, highs, lows, closes, 5)
    assert (bar, px, reason) == (2, 90, "stop_gap")


def test_limit_order_cancelled_when_not_touched():
    opens, highs, lows = [100] * 6, [101] * 6, [99] * 6
    assert _fill("long", 95.0, 90.0, False, 0, opens, highs, lows, 3) is None
    assert _fill("long", 99.5, 90.0, False, 0, opens, highs, lows, 3) == (1, 99.5)


def test_market_entry_skipped_when_gapping_through_stop():
    opens, highs, lows = [100, 89], [101, 90], [99, 88]
    assert _fill("long", 100.0, 90.0, True, 0, opens, highs, lows, 3) is None


def test_signal_uses_only_past_bars():
    """The decision at bar t must not change when future bars are appended."""
    o, h, l, c = _series(n=300, drift=0.002, seed=4)
    t = 200
    a = simple_price_action(c[: t + 1], h[: t + 1], l[: t + 1], o[: t + 1], debug=True)
    b = simple_price_action(c[: t + 1], h[: t + 1], l[: t + 1], o[: t + 1], debug=True)
    full = backtest_simple_pa(o, h, l, c, warmup=t, max_hold=5)
    cut = backtest_simple_pa(o[: t + 40], h[: t + 40], l[: t + 40], c[: t + 40],
                             warmup=t, max_hold=5)
    assert a == b
    first_full = full["trades"][0] if full["trades"] else None
    first_cut = cut["trades"][0] if cut["trades"] else None
    if first_full and first_cut and first_cut["exit_reason"] != "open":
        assert first_full["signal_bar"] == first_cut["signal_bar"]
        assert first_full["r"] == first_cut["r"]


def test_backtest_trend_beats_random_walk():
    trend = backtest_simple_pa(*_series(n=500, drift=0.004, vol=0.012, seed=3))
    rw = backtest_simple_pa(*_series(n=500, drift=0.0, vol=0.015, seed=3))
    assert trend["stats"]["trades"] > 0 and rw["stats"]["trades"] > 0
    assert trend["stats"]["expectancy_r"] > rw["stats"]["expectancy_r"]
    for tr in trend["trades"]:
        assert tr["entry_bar"] > tr["signal_bar"]
        assert tr["exit_bar"] >= tr["entry_bar"]
    # one position at a time
    for a, b in zip(trend["trades"], trend["trades"][1:]):
        assert b["signal_bar"] > a["exit_bar"]


def test_summarize_verdicts():
    assert summarize_trades([{"r": 1.0}] * 5)["verdict"] == "yetersiz örnek"
    assert summarize_trades([{"r": 1.0}, {"r": -0.5}] * 20)["verdict"] == "pozitif beklenti"
    assert summarize_trades([{"r": -1.0}, {"r": 0.5}] * 20)["verdict"] == "negatif beklenti"


def test_factor_attribution_finds_good_and_bad_factors():
    trades = (
        [{"r": 2.0, "factors": ["good"], "confluence_score": 80}] * 15
        + [{"r": -1.0, "factors": ["bad"], "confluence_score": 40}] * 15
    )
    fa = pa_factor_attribution(trades)
    assert fa["keep"] == ["good"]
    assert fa["drop"] == ["bad"]
    assert fa["confluence_score_check"]["rank_ic"] > 0


def test_forecast_calibration_on_random_walk():
    o, h, l, c = _series(n=500, drift=0.0, vol=0.015, seed=9)
    res = evaluate_forecast_calibration(o, h, l, c, horizon=10, step=10)
    assert res["test_points"] >= 30
    assert 50 <= res["p10_p90_coverage_pct"] <= 100
    assert res["full_band_coverage_pct"] >= res["p10_p90_coverage_pct"]


def test_forecast_calibration_needs_history():
    with pytest.raises(ValueError):
        evaluate_forecast_calibration(*_series(n=150), horizon=24, step=10)


def _fake_bars(n=300):
    o, h, l, c = _series(n=n, seed=2)
    return {"opens": o, "highs": h, "lows": l, "closes": c, "volumes": [1.0] * n,
            "times": list(range(n))}


def test_resolve_bars_prefers_tradingview(monkeypatch):
    import bist_trader_mcp.tv_tools as tvt

    monkeypatch.setattr(tvt, "tv_fetch_ohlcv", lambda *a, **k: {
        "success": True, "bars": _fake_bars(), "symbol_tv": "BIST:THYAO"})

    async def boom(*a, **k):
        raise AssertionError("public source must not be used when TV works")

    monkeypatch.setattr(tools, "_load_ohlcv_public", boom)
    bars = asyncio.run(tools._resolve_bars(None, None, None, None, "THYAO", "1D", 300))
    assert bars["data_source"] == "tradingview"
    assert len(bars["opens"]) == 300


def test_resolve_bars_falls_back_when_tv_down(monkeypatch):
    import bist_trader_mcp.tv_tools as tvt

    monkeypatch.setattr(tvt, "tv_fetch_ohlcv", lambda *a, **k: {
        "success": False, "error": "tv_unavailable", "detail": "no node"})

    async def public(*a, **k):
        return _fake_bars()

    monkeypatch.setattr(tools, "_load_ohlcv_public", public)
    bars = asyncio.run(tools._resolve_bars(None, None, None, None, "THYAO", "1D", 300))
    assert bars["data_source"] == "public"
    assert "tv_unavailable" in bars["tradingview_error"]
    with pytest.raises(ValueError):
        asyncio.run(tools._resolve_bars(None, None, None, None, "THYAO", "1D", 300,
                                        "tradingview"))


def test_backtest_tool_end_to_end(monkeypatch):
    import bist_trader_mcp.tv_tools as tvt

    monkeypatch.setattr(tvt, "tv_fetch_ohlcv", lambda *a, **k: {
        "success": True, "bars": _fake_bars(400), "symbol_tv": "BIST:X"})
    res = asyncio.run(tools.backtest_price_action(symbol="X"))
    assert res["data_source"] == "tradingview"
    assert "summary_tr" in res and "factor_attribution" in res
    uni = asyncio.run(tools.backtest_price_action_universe(["A", "B"]))
    assert uni["symbols_tested"] == 2
    ev = asyncio.run(tools.evaluate_forecast_accuracy(symbol="X"))
    assert "p10_p90_coverage_pct" in ev

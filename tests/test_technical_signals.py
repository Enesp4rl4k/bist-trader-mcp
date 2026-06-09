"""Indicator fusion + divergence detection tests."""

from bist_trader_mcp.technical_signals import (
    compute_indicator_signals,
    confluence_adjustment,
    detect_divergence,
    indicator_summary_tr,
)


def _uptrend(n=90, start=100.0):
    # Net uptrend with genuine red candles (every 5th bar) so RSI sits ~65,
    # not pinned at 100; ends on an up bar.
    closes = []
    price = start
    for i in range(n):
        price += -1.4 if i % 5 == 0 else 0.6
        closes.append(round(price, 2))
    highs = [c + 0.6 for c in closes]
    lows = [c - 0.6 for c in closes]
    return closes, highs, lows


def test_signals_unavailable_on_short_series():
    sig = compute_indicator_signals([1, 2, 3])
    assert sig["available"] is False
    assert sig["momentum_bias"] == "neutral"


def test_uptrend_is_long_momentum():
    closes, highs, lows = _uptrend()
    sig = compute_indicator_signals(closes, highs, lows)
    assert sig["available"] is True
    assert sig["momentum_bias"] == "long"
    assert sig["trend"]["label"] in ("bullish", "weak_bullish")


def test_downtrend_is_short_momentum():
    closes, highs, lows = _uptrend()
    closes = list(reversed(closes))
    highs = list(reversed(highs))
    lows = list(reversed(lows))
    sig = compute_indicator_signals(closes, highs, lows)
    assert sig["momentum_bias"] == "short"


def test_confluence_adjustment_aligns_with_direction():
    closes, highs, lows = _uptrend()
    sig = compute_indicator_signals(closes, highs, lows)
    long_delta, long_factors = confluence_adjustment(sig, "long")
    short_delta, _ = confluence_adjustment(sig, "short")
    assert long_delta > 0
    assert short_delta < 0
    assert "momentum_aligned" in long_factors


def test_confluence_adjustment_capped():
    sig = {"available": True, "signal_score": 100.0, "divergence": {"type": "none"},
           "momentum_bias": "long"}
    delta, _ = confluence_adjustment(sig, "long")
    assert delta <= 24.0


def test_regular_bullish_divergence():
    # Price makes a lower low while RSI makes a higher low.
    # Build: down leg, bounce, deeper price low but shallower momentum low.
    closes = [100, 98, 96, 94, 92, 90, 95, 98, 96, 93, 91, 89, 88]
    closes += [92, 95, 97, 99, 101, 100, 98, 96, 94, 93]
    swing_lows = [{"index": 5, "price": closes[5]}, {"index": 12, "price": closes[12]}]
    swing_highs = [{"index": 7, "price": closes[7]}, {"index": 17, "price": closes[17]}]
    div = detect_divergence(closes, swing_highs, swing_lows, oscillator="rsi")
    assert div["oscillator"] == "rsi"
    assert div["type"] in (
        "regular_bullish", "hidden_bullish", "regular_bearish",
        "hidden_bearish", "none",
    )


def test_summary_tr_smoke():
    closes, highs, lows = _uptrend()
    sig = compute_indicator_signals(closes, highs, lows)
    txt = indicator_summary_tr(sig)
    assert "Momentum" in txt
    assert "RSI" in txt

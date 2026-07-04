"""Swing-trade layer — regime, setups, holding horizon, fundamental gate."""

import math

from bist_trader_mcp.swing_trade import analyze_swing_trade


def _uptrend_then_pullback(n: int = 120) -> tuple[list, list, list]:
    """Smooth uptrend, then a few-bar pullback toward the moving averages."""
    closes = [50.0 + i * 0.5 for i in range(n - 6)]
    # pullback: drift down ~1.5 ATRs over the last 6 bars
    for _ in range(6):
        closes.append(closes[-1] - 0.7)
    highs = [c + 0.6 for c in closes]
    lows = [c - 0.6 for c in closes]
    return closes, highs, lows


def _breakout(n: int = 120) -> tuple[list, list, list]:
    """Long base/range, then a clean breakout on the last bar."""
    closes = [100.0 + math.sin(i / 5.0) * 2 for i in range(n - 1)]  # range ~98-102
    closes.append(108.0)  # breakout
    highs = [c + 0.5 for c in closes]
    lows = [c - 0.5 for c in closes]
    return closes, highs, lows


def _downtrend_pullback(n: int = 120) -> tuple[list, list, list]:
    closes = [120.0 - i * 0.5 for i in range(n - 6)]
    for _ in range(6):
        closes.append(closes[-1] + 0.7)  # bounce back toward EMA
    highs = [c + 0.6 for c in closes]
    lows = [c - 0.6 for c in closes]
    return closes, highs, lows


def test_insufficient_bars():
    out = analyze_swing_trade([1.0] * 30, [1.0] * 30, [1.0] * 30)
    assert out["setup"] == "no_setup"
    assert "60" in out["reason"]


def test_uptrend_pullback_long():
    c, h, l = _uptrend_then_pullback()
    out = analyze_swing_trade(c, h, l, symbol="TEST")
    assert out["direction"] == "long"
    assert out["regime"].startswith("uptrend")
    assert out["stop"] < out["entry"]
    assert out["targets_r_multiple"][0] > out["entry"]
    assert out["expected_holding_days"] >= 2
    assert out["time_stop_bars"] >= 10
    assert out["grade"] in ("A", "B", "C", "D")


def test_breakout_long_detected():
    c, h, l = _breakout()
    out = analyze_swing_trade(c, h, l, symbol="BRK")
    assert out["direction"] == "long"
    assert out["setup"] in ("breakout_long", "trend_pullback_long")
    assert out["rr_first_target"] > 0


def test_downtrend_pullback_short():
    c, h, l = _downtrend_pullback()
    out = analyze_swing_trade(c, h, l, symbol="DWN")
    assert out["direction"] == "short"
    assert out["regime"].startswith("downtrend")
    assert out["stop"] > out["entry"]
    assert out["targets_r_multiple"][0] < out["entry"]


def test_fundamental_gate_flags_weak_long():
    c, h, l = _uptrend_then_pullback()
    out = analyze_swing_trade(c, h, l, symbol="WEAK", fundamental_score=-50)
    if out["setup"] != "no_setup" and out["direction"] == "long":
        assert "weak_fundamentals_for_long" in out["flags"]


def test_sizing_when_equity_supplied():
    c, h, l = _uptrend_then_pullback()
    out = analyze_swing_trade(c, h, l, account_equity=100_000, risk_pct=1.0)
    if out["setup"] != "no_setup":
        assert out["sizing"] is not None
        # 1% of 100k = 1000 risk budget
        assert out["sizing"]["risk_amount"] == 1000.0
        assert out["sizing"]["units"] > 0


def test_summary_in_turkish():
    c, h, l = _uptrend_then_pullback()
    out = analyze_swing_trade(c, h, l, symbol="THYAO")
    if out["setup"] != "no_setup":
        assert "THYAO" in out["summary_tr"]
        assert "gün" in out["summary_tr"]

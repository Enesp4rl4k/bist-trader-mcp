"""Range trade + imbalance stack tests."""

from bist_trader_mcp.pa_imbalances import detect_fvgs, find_stacked_imbalances, update_fvg_lifecycle
from bist_trader_mcp.pa_range import (
    build_range_panel,
    detect_liquidity_sweep,
    detect_trading_range,
    recommend_range_play,
)


def _oscillating_range(n: int = 60) -> tuple[list[float], list[float], list[float]]:
    """Synthetic horizontal range ~102–106 (width ~4 ATR units at atr=2)."""
    closes, highs, lows = [], [], []
    for i in range(n):
        phase = i % 8
        if phase < 4:
            c = 102.0 + phase * 0.35
        else:
            c = 105.5 - (phase - 4) * 0.35
        closes.append(c)
        highs.append(c + 0.5)
        lows.append(c - 0.5)
    return closes, highs, lows


def test_detect_trading_range_active():
    c, h, l = _oscillating_range()
    box = detect_trading_range(h, l, c, atr_val=2.0, window=40)
    assert box["active"] is True
    assert box["zone"] in ("discount", "equilibrium", "premium")
    assert box["quality_score"] >= 55


def test_liquidity_sweep_below_range():
    c, h, l = _oscillating_range()
    box = detect_trading_range(h, l, c, atr_val=2.0, window=40)
    n = len(c)
    l[-1] = box["range_low"] - 1.5
    h[-1] = c[-1] + 0.5
    c[-1] = box["range_low"] + 0.3
    sweep = detect_liquidity_sweep(h, l, c, box, lookback=5)
    assert sweep is not None
    assert sweep["play"] == "sweep_fade_long"


def test_recommend_fade_long_in_discount():
    c, h, l = _oscillating_range()
    box = detect_trading_range(h, l, c, atr_val=2.0, window=40)
    box["zone"] = "discount"
    box["active"] = True
    play = recommend_range_play(box, None, close=box["range_low"] + 0.5, structure="ranging")
    assert play["play"] == "fade_long"
    assert play["direction"] == "long"


def test_build_range_panel():
    c, h, l = _oscillating_range()
    panel = build_range_panel(h, l, c, atr_val=2.0)
    assert "box" in panel
    assert "recommended_play" in panel
    assert panel.get("range_trade_mode") is True


def test_stacked_imbalances():
    highs = [100.0, 108.0, 110.0, 111.0, 112.0]
    lows = [98.0, 104.0, 112.0, 110.5, 111.5]
    closes = [99.0, 106.0, 113.0, 111.0, 112.0]
    gaps = update_fvg_lifecycle(
        detect_fvgs(highs, lows, closes, min_gap_pct=0.0, min_size_atr_ratio=0.0),
        highs,
        lows,
        closes,
    )
    stacks = find_stacked_imbalances(gaps, max_mid_distance_pct=0.05)
    assert isinstance(stacks, list)


def test_analyze_price_action_has_range_and_imbalances():
    from bist_trader_mcp.price_action import analyze_price_action

    c, h, l = _oscillating_range(80)
    out = analyze_price_action(c, h, l, swing_lookback=2)
    assert "range" in out
    assert "imbalances" in out
    assert "range_trade" in out

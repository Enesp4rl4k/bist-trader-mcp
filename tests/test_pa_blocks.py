"""Tests for Order Block and Breaker Block detection and lifecycle."""

from __future__ import annotations

from bist_trader_mcp.pa_blocks import detect_order_blocks, build_block_panel


def test_detect_order_blocks_bullish():
    # Synthetic dataset with a sharp bullish expansion (displacement)
    opens = [100.0, 101.0, 99.0, 103.0, 107.0, 108.0]
    highs = [101.5, 102.0, 100.5, 107.2, 108.0, 109.0]
    lows = [99.5, 100.0, 98.5, 102.8, 106.5, 107.5]
    closes = [100.8, 99.5, 100.2, 106.8, 107.8, 108.2]

    # atr is ~ 1.5, move from opens[3] (103) to closes[4] (107.8) is ~ 4.8 (> 3 * ATR)
    obs, breakers = detect_order_blocks(
        highs, lows, closes, opens, min_displacement_atr=0.5, atr_val=1.5
    )

    # We expect to find a Bullish OB
    assert len(obs) >= 1
    bullish_obs = [ob for ob in obs if ob.direction == "bullish"]
    assert len(bullish_obs) >= 1
    
    # Check that the OB is marked open or mitigated
    ob = bullish_obs[0]
    assert ob.top == highs[ob.index]
    assert ob.bottom == lows[ob.index]
    assert ob.status in ("open", "mitigated")


def test_detect_breaker_transition():
    # Setup Bullish OB, then subsequent close below its bottom to trigger Bearish Breaker
    opens = [100.0, 101.0, 99.0, 103.0, 107.0, 104.0, 95.0]
    highs = [101.5, 102.0, 100.5, 107.2, 108.0, 105.0, 96.0]
    lows = [99.5, 100.0, 98.5, 102.8, 106.5, 103.0, 94.0]
    closes = [100.8, 99.5, 100.2, 106.8, 107.8, 103.5, 94.5]

    obs, breakers = detect_order_blocks(
        highs, lows, closes, opens, min_displacement_atr=0.5, atr_val=1.5
    )

    # Bullish OB formed around index 2 (low=98.5).
    # Close at index 6 is 94.5 (< 98.5), which should break the bullish OB and spawn a Bearish Breaker.
    broken_obs = [ob for ob in obs if ob.status == "broken"]
    assert len(broken_obs) >= 1
    assert len(breakers) >= 1
    
    breaker = breakers[0]
    assert breaker.direction == "bearish"
    assert breaker.original_ob_index == broken_obs[0].index


def test_build_block_panel():
    opens = [100.0, 101.0, 99.0, 103.0, 107.0, 108.0]
    highs = [101.5, 102.0, 100.5, 107.2, 108.0, 109.0]
    lows = [99.5, 100.0, 98.5, 102.8, 106.5, 107.5]
    closes = [100.8, 99.5, 100.2, 106.8, 107.8, 108.2]

    panel = build_block_panel(highs, lows, closes, opens, atr_val=1.5)
    assert "order_blocks" in panel
    assert "breaker_blocks" in panel
    assert "raw_obs" in panel

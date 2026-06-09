"""FVG / IFVG detection tests."""

from bist_trader_mcp.pa_imbalances import (
    build_fvg_panel,
    detect_fvgs,
    nearest_fvg_for_direction,
    update_fvg_lifecycle,
)


def test_detect_bullish_fvg_three_bar_gap():
    highs = [100.0, 108.0, 110.0, 115.0]
    lows = [98.0, 104.0, 112.0, 111.0]
    closes = [99.0, 106.0, 113.0, 114.0]
    gaps = detect_fvgs(highs, lows, closes, min_gap_pct=0.0, min_size_atr_ratio=0.0)
    bull = [g for g in gaps if g.direction == "bullish"]
    assert len(bull) >= 1
    g = bull[0]
    assert g.bottom == 100.0
    assert g.top == 112.0


def test_bull_fvg_inverts_after_close_below():
    highs = [100.0, 108.0, 110.0, 108.0, 105.0]
    lows = [98.0, 104.0, 112.0, 100.0, 97.0]
    closes = [99.0, 106.0, 113.0, 101.0, 98.0]
    gaps = update_fvg_lifecycle(
        detect_fvgs(highs, lows, closes, min_gap_pct=0.0, min_size_atr_ratio=0.0),
        highs,
        lows,
        closes,
    )
    inv = [g for g in gaps if g.status == "inverted"]
    assert len(inv) >= 1
    assert inv[0].ifvg_side == "resistance"


def test_nearest_fvg_for_long_in_zone():
    highs = [100.0, 108.0, 110.0, 111.0]
    lows = [98.0, 104.0, 112.0, 110.5]
    closes = [99.0, 106.0, 113.0, 111.0]
    gaps = update_fvg_lifecycle(
        detect_fvgs(highs, lows, closes, min_gap_pct=0.0, min_size_atr_ratio=0.0),
        highs,
        lows,
        closes,
    )
    z = nearest_fvg_for_direction(gaps, 111.0, "long")
    assert z is not None


def test_displacement_filter_reduces_micro_fvgs():
    highs = [100.0, 100.2, 100.3, 100.5]
    lows = [99.8, 99.9, 100.0, 100.2]
    closes = [100.0, 100.1, 100.15, 100.4]
    with_disp = detect_fvgs(highs, lows, closes, min_gap_pct=0.0, min_size_atr_ratio=0.0)
    without = detect_fvgs(
        highs, lows, closes,
        min_gap_pct=0.0,
        min_size_atr_ratio=0.0,
        require_displacement=False,
    )
    assert len(without) >= len(with_disp)


def test_build_fvg_panel_summary():
    highs = [100.0, 108.0, 110.0, 115.0, 118.0]
    lows = [98.0, 104.0, 112.0, 114.0, 116.0]
    closes = [99.0, 106.0, 113.0, 116.0, 117.0]
    panel = build_fvg_panel(highs, lows, closes)
    assert "summary" in panel
    assert "fvgs" in panel

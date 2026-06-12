"""Adaptive swing detection — prominence filter and volatility-scaled lookback."""

from bist_trader_mcp.price_action import adaptive_swing_params, find_swings


def _noisy_with_one_real_peak() -> tuple[list[float], list[float]]:
    """Flat chop (±0.2) with a single prominent high in the middle."""
    highs: list[float] = []
    lows: list[float] = []
    for i in range(41):
        base = 100.0 + (0.2 if i % 2 == 0 else -0.2)
        if i == 20:
            base = 110.0  # the only meaningful swing high
        highs.append(base + 0.1)
        lows.append(base - 0.1)
    return highs, lows


def test_prominence_filters_micro_swings():
    highs, lows = _noisy_with_one_real_peak()
    plain_h, _ = find_swings(highs, lows, lookback=3)
    filtered_h, _ = find_swings(highs, lows, lookback=3, min_prominence=2.0)
    # Plain fractal picks up chop; prominence keeps only the real peak.
    assert len(filtered_h) < len(plain_h)
    assert any(s.price == 110.1 for s in filtered_h)
    assert all(s.price >= 100.0 for s in filtered_h)


def test_prominence_none_preserves_legacy_behaviour():
    highs, lows = _noisy_with_one_real_peak()
    a, b = find_swings(highs, lows, lookback=3)
    c, d = find_swings(highs, lows, lookback=3, min_prominence=None)
    assert [s.price for s in a] == [s.price for s in c]
    assert [s.price for s in b] == [s.price for s in d]


def test_adaptive_lookback_scales_with_volatility():
    calm_lb, calm_prom = adaptive_swing_params(0.5, 100.0, base_lookback=5)
    vol_lb, vol_prom = adaptive_swing_params(5.0, 100.0, base_lookback=5)
    assert calm_lb == 5
    assert vol_lb > calm_lb  # 5% ATR widens the window
    assert vol_prom and calm_prom and vol_prom > calm_prom


def test_adaptive_params_unknown_atr_is_noop():
    lb, prom = adaptive_swing_params(None, 100.0, base_lookback=5)
    assert lb == 5
    assert prom is None


def test_adaptive_lookback_capped_by_bar_count():
    lb, _ = adaptive_swing_params(8.0, 100.0, base_lookback=5, n_bars=11)
    assert lb <= (11 - 1) // 2

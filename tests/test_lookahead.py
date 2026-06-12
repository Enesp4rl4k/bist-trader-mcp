"""Look-ahead safety — confirm swing/structure computation never leaks future bars.

These lock in the causal guarantees a trading engine must hold: a value
attributed to bar *i* must depend only on bars at or before its confirmation
point, never on bars that print later.
"""

import random

from bist_trader_mcp.elliott_wave import build_zigzag_pivots
from bist_trader_mcp.price_action import find_swings


def _random_walk(n: int = 140, seed: int = 11) -> tuple[list[float], list[float]]:
    rng = random.Random(seed)
    highs: list[float] = []
    lows: list[float] = []
    p = 100.0
    for _ in range(n):
        p += rng.uniform(-2.0, 2.0)
        highs.append(p + 1.0)
        lows.append(p - 1.0)
    return highs, lows


def test_find_swings_no_swing_in_unconfirmed_tail():
    """The last `lookback` bars cannot yet be confirmed as swings."""
    highs, lows = _random_walk()
    lookback = 4
    sh, sl = find_swings(highs, lows, lookback=lookback)
    n = len(highs)
    assert all(s.index <= n - 1 - lookback for s in sh)
    assert all(s.index <= n - 1 - lookback for s in sl)


def test_find_swings_prefix_stable():
    """Swings confirmed within a prefix are identical whether computed on the
    prefix or on the full (future-extended) series — i.e. no look-ahead."""
    highs, lows = _random_walk()
    lookback = 4
    full_h, full_l = find_swings(highs, lows, lookback=lookback)
    for k in (60, 90, 120):
        pre_h, pre_l = find_swings(highs[:k], lows[:k], lookback=lookback)
        cutoff = k - 1 - lookback  # last index confirmable inside the prefix
        full_h_c = [(s.index, s.price) for s in full_h if s.index <= cutoff]
        pre_h_c = [(s.index, s.price) for s in pre_h if s.index <= cutoff]
        full_l_c = [(s.index, s.price) for s in full_l if s.index <= cutoff]
        pre_l_c = [(s.index, s.price) for s in pre_l if s.index <= cutoff]
        assert full_h_c == pre_h_c
        assert full_l_c == pre_l_c


def test_prominence_filter_stays_causal_with_fixed_threshold():
    """With a fixed prominence threshold, swing detection is still prefix-stable
    (the only future coupling is the ATR-derived threshold, tested separately)."""
    highs, lows = _random_walk()
    lookback = 4
    prom = 3.0
    full_h, _ = find_swings(highs, lows, lookback=lookback, min_prominence=prom)
    k = 100
    pre_h, _ = find_swings(highs[:k], lows[:k], lookback=lookback, min_prominence=prom)
    cutoff = k - 1 - lookback
    assert [(s.index, s.price) for s in full_h if s.index <= cutoff] == [
        (s.index, s.price) for s in pre_h if s.index <= cutoff
    ]


def test_zigzag_pivots_prefix_stable_without_prominence():
    """build_zigzag_pivots (plain) keeps historical pivots stable as bars are
    appended — the merge step never rewrites confirmed history."""
    highs, lows = _random_walk()
    lookback = 4
    full = build_zigzag_pivots(highs, lows, swing_lookback=lookback)
    k = 110
    pre = build_zigzag_pivots(highs[:k], lows[:k], swing_lookback=lookback)
    cutoff = k - 1 - 2 * lookback  # stay clear of the merge boundary
    full_c = [(p.index, p.price, p.kind) for p in full if p.index <= cutoff]
    pre_c = [(p.index, p.price, p.kind) for p in pre if p.index <= cutoff]
    assert full_c == pre_c

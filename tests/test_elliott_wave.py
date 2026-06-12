"""Elliott Wave engine tests — synthetic zigzag patterns."""

from bist_trader_mcp.elliott_wave import (
    analyze_elliott_wave,
    build_zigzag_pivots,
)


def _synthetic_bull_impulse_bars(n: int = 80) -> tuple[list[float], list[float], list[float]]:
    """Bars with clear L-H-L-H-L-H swing sequence for impulse bull labeling."""
    closes, highs, lows = [], [], []
    # Pivot targets at bar indices (approx): 10, 20, 30, 45, 55, 70
    pivot_plan = [
        (10, 100.0, "low"),
        (20, 115.0, "high"),
        (30, 105.0, "low"),
        (45, 125.0, "high"),
        (55, 112.0, "low"),
        (70, 135.0, "high"),
    ]
    pivots = {i: (p, k) for i, p, k in pivot_plan}

    for i in range(n):
        kind_at = pivots.get(i)
        if kind_at:
            p, kind = kind_at
            if kind == "high":
                c = p - 0.5
                closes.append(c)
                highs.append(p)
                lows.append(c - 1)
            else:
                c = p + 0.5
                closes.append(c)
                highs.append(c + 1)
                lows.append(p)
        else:
            c = 110.0 + (i % 7) * 0.3
            closes.append(c)
            highs.append(c + 1.2)
            lows.append(c - 1.2)
    return closes, highs, lows


def _synthetic_clean_bull_impulse_bars() -> tuple[list[float], list[float], list[float]]:
    """A structurally valid 5-wave bull impulse as the final pivots.

    Wave 4 stays above the wave 1 high and wave 3 is not the shortest, so the
    count survives hard-rule enforcement. Bars are linearly interpolated between
    anchors to avoid spurious intermediate swings.
    """
    anchors = [
        (0, 112.0),    # lead-in so the wave 0 low is a detectable swing
        (10, 100.0),   # wave 0 low
        (25, 120.0),   # wave 1 high
        (40, 108.0),   # wave 2 low (above wave 0)
        (60, 150.0),   # wave 3 high
        (75, 130.0),   # wave 4 low (above wave 1 high -> no overlap)
        (95, 165.0),   # wave 5 high
    ]
    closes: list[float] = []
    highs: list[float] = []
    lows: list[float] = []
    last_idx = anchors[-1][0]
    for seg_start, seg_end in zip(anchors, anchors[1:], strict=False):
        (i0, p0), (i1, p1) = seg_start, seg_end
        for i in range(i0, i1):
            frac = (i - i0) / (i1 - i0)
            p = p0 + (p1 - p0) * frac
            closes.append(p)
            highs.append(p + 0.4)
            lows.append(p - 0.4)
    # final wave-5 high anchor, then a gentle pullback so it registers as a swing
    closes.append(165.0)
    highs.append(165.4)
    lows.append(164.6)
    _ = last_idx  # final pullback below keeps the wave-5 high as a swing high
    for i in range(last_idx + 1, last_idx + 12):
        p = 165.0 - (i - last_idx) * 0.8
        closes.append(p)
        highs.append(p + 0.4)
        lows.append(p - 0.4)
    return closes, highs, lows


def test_build_zigzag_alternates():
    closes, highs, lows = _synthetic_bull_impulse_bars()
    pivots = build_zigzag_pivots(highs, lows, swing_lookback=3)
    assert len(pivots) >= 4
    kinds = [p.kind for p in pivots]
    for a, b in zip(kinds, kinds[1:]):
        assert a != b


def test_analyze_elliott_returns_hypotheses():
    closes, highs, lows = _synthetic_bull_impulse_bars(100)
    out = analyze_elliott_wave(closes, highs, lows, swing_lookback=3)
    assert "hypotheses" in out
    assert out.get("primary") is not None or len(out["hypotheses"]) == 0
    if out.get("primary"):
        assert out["primary"]["score"] > 0
        assert "invalidation_price" in out["primary"]


def test_insufficient_bars_error():
    out = analyze_elliott_wave([1, 2], [1, 2], [1, 2])
    assert out.get("error") == "insufficient_bars"


def test_clean_impulse_is_valid_primary():
    c, h, l = _synthetic_clean_bull_impulse_bars()
    out = analyze_elliott_wave(c, h, l, swing_lookback=3)
    primary = out["primary"]
    assert primary["name"] == "impulse_bull"
    assert primary["valid"] is True
    assert primary["hard_violations"] == []


def test_hard_rule_rejects_wave4_overlap():
    """Wave 4 overlapping wave 1 territory is an inviolable rule break."""
    # L0 H1 L2 H3 L4 H5 where L4 (118) dips below H1 (120) -> overlap.
    c, h, l = _bars_from_pivots(
        [
            (8, 100.0, "low"),
            (20, 120.0, "high"),   # wave 1 high
            (32, 110.0, "low"),
            (48, 140.0, "high"),
            (60, 118.0, "low"),    # wave 4 low BELOW wave 1 high -> overlap
            (78, 150.0, "high"),
        ]
    )
    out = analyze_elliott_wave(c, h, l, swing_lookback=3)
    rejected = {r["name"]: r["hard_violations"] for r in out["rejected_counts"]}
    assert "impulse_bull" in rejected
    assert "wave4_overlaps_wave1" in rejected["impulse_bull"]
    # The invalid impulse must never be the primary count.
    assert (out["primary"] or {}).get("name") != "impulse_bull"


def _bars_from_pivots(
    pivots: list[tuple[int, float, str]],
) -> tuple[list[float], list[float], list[float]]:
    """Linear-interpolated bars hitting each (index, price, kind) anchor.

    A short lead-in is prepended so the first anchor is a detectable swing
    (find_swings needs ``lookback`` bars on each side of an extreme).
    """
    closes: list[float] = []
    highs: list[float] = []
    lows: list[float] = []
    first_price = pivots[0][1]
    lead_from = first_price + (12.0 if pivots[0][2] == "low" else -12.0)
    for k in range(8):
        p = lead_from + (first_price - lead_from) * (k / 8)
        closes.append(p)
        highs.append(p + 0.4)
        lows.append(p - 0.4)
    for (i0, p0, _k0), (i1, p1, _k1) in zip(pivots, pivots[1:], strict=False):
        for i in range(i0, i1):
            frac = (i - i0) / (i1 - i0)
            p = p0 + (p1 - p0) * frac
            closes.append(p)
            highs.append(p + 0.4)
            lows.append(p - 0.4)
    last = pivots[-1]
    closes.append(last[1])
    highs.append(last[1] + 0.4)
    lows.append(last[1] - 0.4)
    for k in range(1, 12):
        p = last[1] - k * 0.8
        closes.append(p)
        highs.append(p + 0.4)
        lows.append(p - 0.4)
    return closes, highs, lows

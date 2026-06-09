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

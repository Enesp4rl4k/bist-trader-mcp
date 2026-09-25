"""Performance guards: O(n) indicators, bounded backtest cost, responsive loop."""

import asyncio
import math
import random
import time

import pytest

from bist_trader_mcp.technicals import bollinger_bands

from .test_candle_forecast import _series


def _bollinger_reference(values, period=20, k=2.0):
    """The original O(n·w) implementation, kept as the numerical reference."""
    out_u, out_l = [None] * len(values), [None] * len(values)
    for i in range(period - 1, len(values)):
        w = values[i - period + 1:i + 1]
        m = sum(w) / period
        sd = math.sqrt(sum((x - m) ** 2 for x in w) / period)
        out_u[i], out_l[i] = m + k * sd, m - k * sd
    return out_u, out_l


@pytest.mark.parametrize("scale", [1.0, 100.0, 100_000.0])
def test_rolling_bollinger_matches_reference(scale):
    rng = random.Random(4)
    vals = [scale * (1 + 0.1 * math.sin(i / 7) + rng.gauss(0, 0.01)) for i in range(600)]
    ref_u, ref_l = _bollinger_reference(vals)
    got = bollinger_bands(vals)
    for a, b in zip(ref_u + ref_l, got.upper + got.lower):
        if a is None:
            assert b is None
        else:
            assert b == pytest.approx(a, rel=1e-9, abs=1e-9 * scale)


def test_bollinger_flat_series_has_zero_width():
    bb = bollinger_bands([123.45] * 50)
    assert bb.upper[-1] == bb.lower[-1] == pytest.approx(123.45)
    assert bb.bandwidth[-1] == 0.0
    assert bollinger_bands([1.0, 2.0]).upper == [None, None]


def test_backtest_cost_is_linear_and_fast():
    from bist_trader_mcp.pa_backtest import backtest_simple_pa

    o, h, l, c = _series(n=500, drift=0.001, vol=0.015, seed=3)
    t0 = time.perf_counter()
    backtest_simple_pa(o, h, l, c)
    # ~0.2 s on a dev box; generous bound so slow CI runners don't flake
    assert time.perf_counter() - t0 < 2.0


def test_lookback_window_limits_what_each_decision_sees(monkeypatch):
    from bist_trader_mcp import pa_backtest

    seen = []
    real = pa_backtest.simple_price_action

    def spy(closes, *args, **kwargs):
        seen.append(len(closes))
        return real(closes, *args, **kwargs)

    monkeypatch.setattr(pa_backtest, "simple_price_action", spy)
    o, h, l, c = _series(n=700, drift=0.001, vol=0.015, seed=5)
    pa_backtest.backtest_simple_pa(o, h, l, c, lookback_bars=300, max_hold=5)
    assert seen and max(seen) == 300 and min(seen) == 121  # warmup 120 → 121 bars


def test_parallel_backtests_match_inline():
    from bist_trader_mcp.pa_backtest import run_backtests

    jobs = []
    for seed in (1, 2, 3):
        o, h, l, c = _series(n=320, drift=0.002, vol=0.014, seed=seed)
        jobs.append({"opens": o, "highs": h, "lows": l, "closes": c})
    par = run_backtests(jobs, workers=2)
    ser = run_backtests(jobs, workers=1)
    assert [r["stats"] for r in par] == [r["stats"] for r in ser]


def test_bad_job_is_reported_not_raised():
    from bist_trader_mcp.pa_backtest import run_backtests

    out = run_backtests([{"opens": [1.0], "highs": [1.0], "lows": [1.0], "closes": [1.0]}],
                        workers=1)
    assert isinstance(out[0], ValueError)


def test_dashboard_refresh_does_not_stall_event_loop():
    from bist_trader_mcp import dashboard_data as dd

    from .test_dashboard import Fakes

    f = Fakes()
    wl = ["A", "BB", "CCC", "DDDD", "EEEEE", "F", "GG", "HHH"]

    async def main():
        gaps = []
        done = asyncio.Event()

        async def tick():
            last = time.perf_counter()
            while not done.is_set():
                await asyncio.sleep(0.005)
                now = time.perf_counter()
                gaps.append(now - last)
                last = now

        t = asyncio.create_task(tick())
        await dd.build_snapshot({"watchlist": wl}, quotes=f.quotes, bars=f.bars,
                                news=f.news, risk=f.risk)
        done.set()
        await t
        return max(gaps)

    worst = asyncio.run(main())
    # was ~500 ms before CPU work moved to threads; GIL handoffs stay short
    assert worst < 0.15, f"event loop stalled {worst * 1000:.0f} ms"

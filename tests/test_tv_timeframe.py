"""Timeframe parsing + bar-spacing verification (switch/fetch race guard)."""

from bist_trader_mcp.tv_tools import timeframe_to_seconds, verify_bar_timeframe


def test_timeframe_to_seconds_variants():
    assert timeframe_to_seconds("15") == 15 * 60
    assert timeframe_to_seconds("60") == 3600
    assert timeframe_to_seconds("240") == 4 * 3600
    assert timeframe_to_seconds("1D") == 86_400
    assert timeframe_to_seconds("D") == 86_400
    assert timeframe_to_seconds("1W") == 7 * 86_400
    assert timeframe_to_seconds("bogus") is None
    assert timeframe_to_seconds("") is None


def _times(n: int, step: int, start: int = 1_700_000_000):
    return [start + i * step for i in range(n)]


def test_verify_matches_requested_timeframe():
    times = _times(50, 3600)  # hourly bars
    res = verify_bar_timeframe(times, "60")
    assert res["checked"] is True
    assert res["ok"] is True


def test_verify_detects_wrong_timeframe():
    # We asked for 4h (240) but TradingView returned hourly bars (lagged switch).
    times = _times(50, 3600)
    res = verify_bar_timeframe(times, "240")
    assert res["checked"] is True
    assert res["ok"] is False
    assert res["median_delta_sec"] == 3600
    assert res["expected_sec"] == 4 * 3600


def test_verify_tolerates_intraday_gaps():
    # Mostly hourly with a few large overnight gaps — median still hourly.
    times = _times(40, 3600)
    times += [times[-1] + 16 * 3600, times[-1] + 16 * 3600 + 3600]
    res = verify_bar_timeframe(times, "60")
    assert res["ok"] is True


def test_verify_skips_when_unknown_or_short():
    assert verify_bar_timeframe(_times(50, 3600), "bogus")["checked"] is False
    assert verify_bar_timeframe(_times(2, 3600), "60")["checked"] is False

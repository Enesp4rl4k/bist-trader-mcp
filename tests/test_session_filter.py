"""BIST session bar filter."""

from bist_trader_mcp.session_filter import filter_session_bars, is_intraday_timeframe


def test_intraday_tf_detection():
    assert is_intraday_timeframe("60") is True
    assert is_intraday_timeframe("D") is False


def test_filter_keeps_session_bars():
    from bist_trader_mcp.data_quality import _bar_hour_istanbul

    base = 1_700_000_000
    session_times: list[int] = []
    off_times: list[int] = []
    for t in range(base, base + 86400 * 4, 3600):
        h = _bar_hour_istanbul(t)
        if 10 <= h < 18:
            session_times.append(t)
        elif h < 10 or h >= 18:
            off_times.append(t)
    assert len(session_times) >= 30
    times = off_times[:8] + session_times
    n = len(times)
    closes = [100.0 + i * 0.1 for i in range(n)]
    highs = [c + 1 for c in closes]
    lows = [c - 1 for c in closes]
    out = filter_session_bars(closes, highs, lows, times, asset_class="bist_equity")
    assert out["filtered"] is True
    assert out["bars_kept"] == len(session_times)
    assert out["bars_dropped"] == 8

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


def test_filter_session_bars_half_day():
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from bist_trader_mcp.bist_calendar import is_bist_half_day

    # 2026-10-28 is a known BIST half-day (Republic Day Eve)
    dt = datetime(2026, 10, 28, 11, 0, 0, tzinfo=ZoneInfo("Europe/Istanbul"))
    ts_in = int(dt.timestamp())
    assert is_bist_half_day(ts_in) is True

    dt_off = datetime(2026, 10, 28, 14, 0, 0, tzinfo=ZoneInfo("Europe/Istanbul"))
    ts_off = int(dt_off.timestamp())

    # Build a series where we have 36 bars inside the morning session (10:00-13:00)
    # and 12 bars in the afternoon (13:00-18:00) which should be dropped on half-day
    times = []
    # Morning: 10:00 to 12:59
    for m in range(0, 180, 5):  # 36 bars
        times.append(int(datetime(2026, 10, 28, 10, 0, 0, tzinfo=ZoneInfo("Europe/Istanbul")).timestamp()) + m * 60)
    # Afternoon: 13:00 to 14:00
    for m in range(0, 60, 5):   # 12 bars
        times.append(int(datetime(2026, 10, 28, 13, 0, 0, tzinfo=ZoneInfo("Europe/Istanbul")).timestamp()) + m * 60)

    n = len(times)
    closes = [100.0] * n
    highs = [101.0] * n
    lows = [99.0] * n

    out = filter_session_bars(closes, highs, lows, times, asset_class="bist_equity")
    assert out["filtered"] is True
    # Afternoon bars (starting at 13:00) should be dropped
    assert out["bars_kept"] == 36
    assert out["bars_dropped"] == 12


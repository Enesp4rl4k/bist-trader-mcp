"""BIST holiday filter tests."""

from datetime import datetime
from zoneinfo import ZoneInfo

from bist_trader_mcp.bist_calendar import filter_holiday_bars, is_bist_holiday


def test_is_bist_holiday_new_year():
    tz = ZoneInfo("Europe/Istanbul")
    ts = int(datetime(2025, 1, 1, 12, 0, tzinfo=tz).timestamp())
    assert is_bist_holiday(ts) is True


def test_filter_holiday_bars_drops_holiday():
    tz = ZoneInfo("Europe/Istanbul")
    n = 25
    times = []
    closes, highs, lows = [], [], []
    for i in range(n):
        day = 2 + i if i != 10 else 1  # one bar on 2025-01-01 holiday
        times.append(int(datetime(2025, 1, day, 12, 0, tzinfo=tz).timestamp()))
        closes.append(100.0 + i * 0.1)
        highs.append(closes[-1] + 1)
        lows.append(closes[-1] - 1)
    out = filter_holiday_bars(closes, highs, lows, times)
    assert len(out["closes"]) == n - 1

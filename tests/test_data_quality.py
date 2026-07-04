"""Data quality gate tests."""

from bist_trader_mcp.data_quality import (
    assess_ohlcv_quality,
    assess_staleness,
    merge_mtf_data_quality,
)


def _bars(n: int, flat: bool = False):
    c = [100.0] * n if flat else [100.0 + i * 0.5 for i in range(n)]
    h = [x + 1 for x in c]
    l = [x - 1 for x in c]
    return c, h, l


def test_insufficient_bars_blocks():
    c, h, l = _bars(20)
    q = assess_ohlcv_quality(c, h, l, min_swings_bars=30)
    assert q["ok"] is False
    assert q["flag"] == "insufficient"


def test_clean_series_ok():
    c, h, l = _bars(80)
    q = assess_ohlcv_quality(c, h, l, asset_class="crypto")
    assert q["ok"] is True
    assert q["flag"] == "ok"


def test_merge_mtf_worst_flag():
    htf = assess_ohlcv_quality(*_bars(80))
    ltf = assess_ohlcv_quality(*_bars(20), min_swings_bars=30)
    merged = merge_mtf_data_quality(htf, ltf)
    assert merged["ok"] is False
    assert merged["flag"] == "insufficient"


def _hourly_times(n: int, *, end: int):
    step = 3600
    return [end - (n - 1 - i) * step for i in range(n)]


def test_crypto_fresh_feed_ok():
    c, h, l = _bars(80)
    now = 1_700_000_000
    times = _hourly_times(80, end=now)  # last bar == now
    q = assess_ohlcv_quality(c, h, l, times=times, asset_class="crypto", now_ts=now)
    assert q["flag"] == "ok"
    assert q["staleness"]["checked"] is True
    assert q["staleness"]["stale"] is False


def test_crypto_stale_feed_flagged():
    c, h, l = _bars(80)
    now = 1_700_000_000
    # Last bar 10h old on an hourly crypto feed → clearly stale (> 3 intervals).
    times = _hourly_times(80, end=now - 10 * 3600)
    q = assess_ohlcv_quality(c, h, l, times=times, asset_class="crypto", now_ts=now)
    assert q["flag"] == "stale"
    assert q["ok"] is False
    assert q["staleness"]["stale"] is True


def test_bist_overnight_gap_not_stale():
    c, h, l = _bars(80)
    now = 1_700_000_000
    # Hourly BIST bars, last bar ~20h old (overnight): must NOT be flagged stale.
    times = _hourly_times(80, end=now - 20 * 3600)
    q = assess_ohlcv_quality(c, h, l, times=times, asset_class="bist_equity", now_ts=now)
    assert q["staleness"]["stale"] is False


def test_assess_staleness_daily_grace():
    now = 1_700_000_000
    daily = [now - (5 - i) * 86_400 for i in range(5)]  # last bar 0d old
    res = assess_staleness(daily, asset_class="bist_index", now_ts=now)
    assert res["checked"] is True
    assert res["stale"] is False

"""Data quality gate tests."""

from bist_trader_mcp.data_quality import assess_ohlcv_quality, merge_mtf_data_quality


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

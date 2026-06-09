"""BIST EOD fetcher regressions."""

from datetime import date

import pytest

from bist_trader_mcp.bist_eod import _parse_yahoo_chart, _period_start
from bist_trader_mcp.http_utils import SourceError


def test_yahoo_parser_skips_incomplete_latest_bar():
    payload = {
        "chart": {
            "result": [
                {
                    "timestamp": [1_700_000_000, 1_700_086_400],
                    "indicators": {
                        "quote": [
                            {
                                "open": [10.0, None],
                                "high": [11.0, None],
                                "low": [9.0, None],
                                "close": [10.5, None],
                                "volume": [1000, 2000],
                            }
                        ]
                    },
                }
            ],
            "error": None,
        }
    }

    bars = _parse_yahoo_chart(payload, ticker="THYAO.IS")

    assert len(bars) == 1
    assert bars[0].close == 10.5


def test_period_start_supports_common_yahoo_ranges():
    end = date(2026, 6, 4)

    assert _period_start(end, "1mo") == date(2026, 5, 4)
    assert _period_start(end, "3mo") == date(2026, 3, 3)
    assert _period_start(end, "1y") == date(2025, 6, 4)
    assert _period_start(end, "10d") == date(2026, 5, 25)


def test_period_start_rejects_unknown_period():
    with pytest.raises(SourceError):
        _period_start(date(2026, 6, 4), "3w")

"""BIST / VIOP session bar filtering for intraday OHLCV from TradingView."""

from __future__ import annotations

from typing import Any

from .bist_calendar import filter_holiday_bars, is_bist_holiday
from .data_quality import _bar_hour_istanbul

# BIST cash ~10:00–18:00 Istanbul; holidays via bist_calendar
BIST_CASH_HOUR_START = 10
BIST_CASH_HOUR_END = 18

VIOP_DAY_HOUR_START = 9
VIOP_DAY_HOUR_END = 19


def is_intraday_timeframe(timeframe: str) -> bool:
    tf = str(timeframe).strip().upper()
    if tf in ("D", "W", "M", "1D", "1W", "1M", "DAILY", "WEEKLY", "MONTHLY"):
        return False
    if tf.endswith("D") or tf.endswith("W") or tf.endswith("M"):
        if len(tf) <= 2:
            return False
    return True


def _session_hours(asset_class: str) -> tuple[int, int]:
    if asset_class in ("viop_future", "viop_option"):
        return VIOP_DAY_HOUR_START, VIOP_DAY_HOUR_END
    return BIST_CASH_HOUR_START, BIST_CASH_HOUR_END


def filter_session_bars(
    closes: list[float],
    highs: list[float],
    lows: list[float],
    times: list[int],
    *,
    volumes: list[float] | None = None,
    asset_class: str = "bist_equity",
) -> dict[str, Any]:
    """Keep only bars inside Istanbul session window (intraday TV cleanup)."""
    n = min(len(closes), len(highs), len(lows), len(times))
    if n < 2:
        return {
            "closes": closes,
            "highs": highs,
            "lows": lows,
            "times": times,
            "volumes": volumes,
            "filtered": False,
            "bars_kept": n,
            "bars_dropped": 0,
        }

    start_h, end_h = _session_hours(asset_class)
    keep_idx: list[int] = []
    for i in range(n):
        h = _bar_hour_istanbul(int(times[i]))
        if start_h <= h < end_h:
            keep_idx.append(i)

    if len(keep_idx) < max(30, int(n * 0.25)):
        return {
            "closes": closes,
            "highs": highs,
            "lows": lows,
            "times": times,
            "volumes": volumes,
            "filtered": False,
            "bars_kept": n,
            "bars_dropped": 0,
            "note": "session_filter_skipped_too_few_bars",
        }

    def pick(seq: list) -> list:
        return [seq[i] for i in keep_idx]

    out_vol = pick(volumes) if volumes and len(volumes) >= n else volumes
    out = {
        "closes": pick(closes[:n]),
        "highs": pick(highs[:n]),
        "lows": pick(lows[:n]),
        "times": pick(times[:n]),
        "volumes": out_vol,
        "filtered": True,
        "bars_kept": len(keep_idx),
        "bars_dropped": n - len(keep_idx),
        "session": f"{start_h}:00-{end_h}:00 Europe/Istanbul",
    }
    if asset_class in ("bist_equity", "bist_index"):
        hol = filter_holiday_bars(
            out["closes"],
            out["highs"],
            out["lows"],
            out["times"],
            volumes=out.get("volumes"),
        )
        if len(hol["closes"]) >= max(30, int(len(out["closes"]) * 0.25)):
            dropped_h = len(out["closes"]) - len(hol["closes"])
            out.update(hol)
            out["holiday_bars_dropped"] = dropped_h
    return out


__all__ = [
    "is_intraday_timeframe",
    "filter_session_bars",
    "is_bist_holiday",
    "BIST_CASH_HOUR_START",
    "BIST_CASH_HOUR_END",
]

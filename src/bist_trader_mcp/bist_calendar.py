"""BIST cash session holidays (static list — extend yearly)."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

# ISO dates — BIST full-day closures (approximate; extend each year)
BIST_HOLIDAYS: frozenset[str] = frozenset(
    {
        "2025-01-01",
        "2025-03-30",
        "2025-03-31",
        "2025-04-01",
        "2025-04-23",
        "2025-05-01",
        "2025-05-19",
        "2025-06-05",
        "2025-06-06",
        "2025-07-15",
        "2025-08-30",
        "2025-10-28",
        "2025-10-29",
        "2026-01-01",
        "2026-04-23",
        "2026-05-01",
        "2026-05-19",
        "2026-07-15",
        "2026-08-30",
        "2026-10-28",
        "2026-10-29",
    }
)


def is_bist_holiday(unix_ts: int) -> bool:
    try:
        d = datetime.fromtimestamp(int(unix_ts), tz=ZoneInfo("Europe/Istanbul")).date()
    except Exception:
        d = datetime.fromtimestamp(int(unix_ts), timezone.utc).date()
    return d.isoformat() in BIST_HOLIDAYS


def filter_holiday_bars(
    closes: list[float],
    highs: list[float],
    lows: list[float],
    times: list[int],
    *,
    volumes: list[float] | None = None,
) -> dict[str, list]:
    """Drop bars that fall on known BIST holidays."""
    n = min(len(closes), len(highs), len(lows), len(times))
    keep = [i for i in range(n) if not is_bist_holiday(int(times[i]))]
    if len(keep) < max(20, int(n * 0.2)):
        return {
            "closes": closes,
            "highs": highs,
            "lows": lows,
            "times": times,
            "volumes": volumes,
        }

    def pick(seq: list) -> list:
        return [seq[i] for i in keep]

    vol = pick(volumes) if volumes and len(volumes) >= n else volumes
    return {
        "closes": pick(closes[:n]),
        "highs": pick(highs[:n]),
        "lows": pick(lows[:n]),
        "times": pick(times[:n]),
        "volumes": vol,
    }


__all__ = ["BIST_HOLIDAYS", "is_bist_holiday", "filter_holiday_bars"]

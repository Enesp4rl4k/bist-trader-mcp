"""OHLCV data quality gates before PA / Elliott analysis."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal
from zoneinfo import ZoneInfo

QualityFlag = Literal["ok", "thin", "stale", "insufficient"]


def _bar_hour_istanbul(unix_ts: int) -> int:
    try:
        dt = datetime.fromtimestamp(int(unix_ts), tz=ZoneInfo("Europe/Istanbul"))
        return dt.hour
    except Exception:
        dt = datetime.fromtimestamp(int(unix_ts), tz=timezone.utc)
        return dt.hour


def assess_ohlcv_quality(
    closes: list[float],
    highs: list[float],
    lows: list[float],
    *,
    times: list[int] | None = None,
    volumes: list[float] | None = None,
    asset_class: str = "unknown",
    min_bars: int = 60,
    min_swings_bars: int = 30,
) -> dict[str, Any]:
    """Return quality flag + issues list — block analysis when insufficient."""
    n = len(closes)
    issues: list[str] = []
    if n < min_swings_bars:
        return {
            "flag": "insufficient",
            "ok": False,
            "bars": n,
            "issues": [f"need>={min_swings_bars} bars, got {n}"],
        }
    # Preferred bar count is advisory only — do not block analysis on this alone.

    flat = 0
    for i in range(1, n):
        if closes[i] == closes[i - 1] and highs[i] == highs[i - 1] and lows[i] == lows[i - 1]:
            flat += 1
    if n > 0 and flat / max(n - 1, 1) > 0.35:
        issues.append(f"too many flat bars ({flat})")

    if volumes and len(volumes) == n:
        zero_vol = sum(1 for v in volumes if float(v) <= 0)
        if zero_vol / n > 0.25:
            issues.append(f"low volume on {zero_vol}/{n} bars")

    off_session = 0
    if times and len(times) == n and asset_class in ("bist_equity", "bist_index", "viop_future", "viop_option"):
        for t in times[-min(80, n):]:
            h = _bar_hour_istanbul(int(t))
            if h < 10 or h >= 18:
                off_session += 1
        if off_session > min(40, n) * 0.5:
            issues.append("many bars outside BIST cash session (10-18 Istanbul)")

    if times and len(times) >= 2:
        gaps = 0
        deltas = [int(times[i]) - int(times[i - 1]) for i in range(1, n)]
        if deltas:
            med = sorted(deltas)[len(deltas) // 2]
            for d in deltas[-20:]:
                if med > 0 and d > med * 3:
                    gaps += 1
            if gaps >= 3:
                issues.append(f"time gaps detected ({gaps} recent)")

    flag: QualityFlag = "ok"
    if n < min_swings_bars:
        flag = "insufficient"
    elif len(issues) >= 3:
        flag = "thin"
    elif len(issues) >= 1:
        flag = "thin"

    return {
        "flag": flag,
        "ok": flag == "ok",
        "bars": n,
        "issues": issues,
        "asset_class": asset_class,
    }


def merge_mtf_data_quality(htf: dict[str, Any], ltf: dict[str, Any]) -> dict[str, Any]:
    """Combine HTF/LTF quality — worst flag wins."""
    order = {"insufficient": 0, "thin": 1, "stale": 2, "ok": 3}
    h_flag = str(htf.get("flag") or "ok")
    l_flag = str(ltf.get("flag") or "ok")
    worst = h_flag if order.get(h_flag, 0) <= order.get(l_flag, 0) else l_flag
    return {
        "flag": worst,
        "ok": worst == "ok",
        "htf": htf,
        "ltf": ltf,
        "issues": list(htf.get("issues") or []) + list(ltf.get("issues") or []),
    }


__all__ = ["assess_ohlcv_quality", "merge_mtf_data_quality"]

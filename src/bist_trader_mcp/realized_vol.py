"""Realized volatility estimators — pure math.

Three estimators, all annualised, in % units (45.0 = 45%):

- close_to_close: classic stdev of log returns. Underestimates intraday vol.
- parkinson: uses high-low range. ~5x more efficient than CC.
- garman_klass: uses O/H/L/C. ~7-8x more efficient than CC.

All assume 252 trading days/year unless overridden (crypto uses 365).

Why this matters: implied vol vs realized vol spread (IV-RV) is the
canonical option mean-reversion signal. When IV is far above RV,
short-vol strategies (iron condor, short straddle) historically win;
the reverse for long-vol.
"""

from __future__ import annotations

import math


def close_to_close_vol(
    closes: list[float],
    period: int = 30,
    annualise_days: int = 252,
) -> float | None:
    """Annualised stdev of log returns over the last `period` bars."""
    if period < 2 or len(closes) < period + 1:
        return None
    rets: list[float] = []
    for i in range(len(closes) - period, len(closes)):
        prev = closes[i - 1]
        cur = closes[i]
        if prev <= 0 or cur <= 0:
            continue
        rets.append(math.log(cur / prev))
    if len(rets) < 2:
        return None
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
    return math.sqrt(var * annualise_days) * 100.0


def parkinson_vol(
    highs: list[float],
    lows: list[float],
    period: int = 30,
    annualise_days: int = 252,
) -> float | None:
    """Parkinson estimator using high/low range."""
    if len(highs) != len(lows):
        raise ValueError("highs and lows must be equal length")
    if period < 2 or len(highs) < period:
        return None
    factor = 1.0 / (4.0 * math.log(2.0))
    window_hi = highs[-period:]
    window_lo = lows[-period:]
    s = 0.0
    cnt = 0
    for h, low_v in zip(window_hi, window_lo, strict=False):
        if h <= 0 or low_v <= 0 or h < low_v:
            continue
        s += math.log(h / low_v) ** 2
        cnt += 1
    if cnt < 2:
        return None
    var = factor * s / cnt
    return math.sqrt(var * annualise_days) * 100.0


def garman_klass_vol(
    opens: list[float],
    highs: list[float],
    lows: list[float],
    closes: list[float],
    period: int = 30,
    annualise_days: int = 252,
) -> float | None:
    """Garman-Klass estimator using O/H/L/C."""
    n = len(closes)
    if not (len(opens) == len(highs) == len(lows) == n):
        raise ValueError("O/H/L/C must all be equal length")
    if period < 2 or n < period:
        return None
    s = 0.0
    cnt = 0
    for i in range(n - period, n):
        o = opens[i]; h = highs[i]; lw = lows[i]; c = closes[i]
        if min(o, h, lw, c) <= 0 or h < lw:
            continue
        hl = math.log(h / lw) ** 2
        co = math.log(c / o) ** 2
        s += 0.5 * hl - (2 * math.log(2) - 1) * co
        cnt += 1
    if cnt < 2:
        return None
    var = s / cnt
    return math.sqrt(var * annualise_days) * 100.0


def realized_vol_panel(
    opens: list[float] | None,
    highs: list[float] | None,
    lows: list[float] | None,
    closes: list[float],
    period: int = 30,
    annualise_days: int = 252,
    iv_atm_pct: float | None = None,
) -> dict[str, float | None]:
    """One-shot panel returning all available realized vol estimators.

    If `iv_atm_pct` is supplied, includes IV/RV ratio and the spread
    (IV - RV in vol points) for each estimator. A ratio > 1.0 means
    options are pricing in more volatility than recent history.
    """
    cc = close_to_close_vol(closes, period, annualise_days)
    pk = None
    gk = None
    if highs and lows:
        pk = parkinson_vol(highs, lows, period, annualise_days)
        if opens:
            gk = garman_klass_vol(opens, highs, lows, closes, period,
                                    annualise_days)

    out: dict[str, float | None] = {
        "close_to_close_vol_pct": cc,
        "parkinson_vol_pct": pk,
        "garman_klass_vol_pct": gk,
        "period_bars": period,
        "annualise_days": annualise_days,
    }
    if iv_atm_pct is not None:
        out["iv_atm_pct"] = iv_atm_pct
        for label, rv in (("cc", cc), ("parkinson", pk), ("garman_klass", gk)):
            if rv is not None and rv > 0:
                out[f"iv_rv_ratio_{label}"] = round(iv_atm_pct / rv, 3)
                out[f"iv_rv_spread_{label}_vol_pts"] = round(iv_atm_pct - rv, 3)
            else:
                out[f"iv_rv_ratio_{label}"] = None
                out[f"iv_rv_spread_{label}_vol_pts"] = None
    return out


__all__ = [
    "close_to_close_vol",
    "parkinson_vol",
    "garman_klass_vol",
    "realized_vol_panel",
]

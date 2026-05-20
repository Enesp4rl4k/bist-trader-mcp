"""Pure-math technical indicators on OHLCV series.

No network — operates on lists of floats. Used by `calculate_technicals`
tool to overlay RSI / MACD / Bollinger / ATR / EMA / SMA on any series
the user can fetch (BIST EOD, crypto klines, FX bars, etc).

Conventions:
- Inputs are simple list[float]; None values are skipped where it makes
  sense (gaps in EOD data).
- Outputs are list[float | None] aligned 1:1 with the input — the first
  N positions where the window can't yet be filled are None.
- Periods follow market convention (RSI 14, MACD 12/26/9, BB 20/2).
"""

from __future__ import annotations

import math
from dataclasses import dataclass


def sma(values: list[float], period: int) -> list[float | None]:
    """Simple moving average."""
    if period <= 0:
        raise ValueError("period must be > 0")
    out: list[float | None] = [None] * len(values)
    if len(values) < period:
        return out
    running = sum(values[:period])
    out[period - 1] = running / period
    for i in range(period, len(values)):
        running += values[i] - values[i - period]
        out[i] = running / period
    return out


def ema(values: list[float], period: int) -> list[float | None]:
    """Exponential moving average. Seeds with SMA over the first `period`."""
    if period <= 0:
        raise ValueError("period must be > 0")
    out: list[float | None] = [None] * len(values)
    if len(values) < period:
        return out
    k = 2.0 / (period + 1)
    seed = sum(values[:period]) / period
    out[period - 1] = seed
    prev = seed
    for i in range(period, len(values)):
        cur = values[i] * k + prev * (1 - k)
        out[i] = cur
        prev = cur
    return out


def rsi(values: list[float], period: int = 14) -> list[float | None]:
    """Wilder's RSI. Range 0-100; >70 overbought, <30 oversold (convention)."""
    if period <= 0:
        raise ValueError("period must be > 0")
    n = len(values)
    out: list[float | None] = [None] * n
    if n <= period:
        return out
    gains = 0.0
    losses = 0.0
    for i in range(1, period + 1):
        delta = values[i] - values[i - 1]
        if delta >= 0:
            gains += delta
        else:
            losses += -delta
    avg_gain = gains / period
    avg_loss = losses / period
    out[period] = _rsi_from(avg_gain, avg_loss)
    for i in range(period + 1, n):
        delta = values[i] - values[i - 1]
        gain = max(delta, 0.0)
        loss = max(-delta, 0.0)
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period
        out[i] = _rsi_from(avg_gain, avg_loss)
    return out


def _rsi_from(avg_gain: float, avg_loss: float) -> float:
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


@dataclass
class MACDResult:
    macd_line: list[float | None]
    signal_line: list[float | None]
    histogram: list[float | None]


def macd(
    values: list[float],
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> MACDResult:
    """Standard MACD: EMA(12) - EMA(26), signal = EMA(9) of MACD."""
    if fast <= 0 or slow <= 0 or signal <= 0:
        raise ValueError("periods must be > 0")
    if fast >= slow:
        raise ValueError("fast period must be < slow period")
    ema_fast = ema(values, fast)
    ema_slow = ema(values, slow)
    macd_line: list[float | None] = []
    for f, s in zip(ema_fast, ema_slow, strict=False):
        if f is None or s is None:
            macd_line.append(None)
        else:
            macd_line.append(f - s)
    # Signal EMA on the non-None portion
    valid_start = next((i for i, v in enumerate(macd_line) if v is not None), None)
    signal_line: list[float | None] = [None] * len(values)
    if valid_start is not None:
        non_none = [v for v in macd_line[valid_start:] if v is not None]
        sig_partial = ema(non_none, signal)
        for i, v in enumerate(sig_partial):
            signal_line[valid_start + i] = v
    hist: list[float | None] = []
    for m, s in zip(macd_line, signal_line, strict=False):
        if m is None or s is None:
            hist.append(None)
        else:
            hist.append(m - s)
    return MACDResult(macd_line=macd_line, signal_line=signal_line, histogram=hist)


@dataclass
class BollingerResult:
    middle: list[float | None]
    upper: list[float | None]
    lower: list[float | None]
    bandwidth: list[float | None]
    pct_b: list[float | None]


def bollinger_bands(
    values: list[float],
    period: int = 20,
    std_dev: float = 2.0,
) -> BollingerResult:
    """Bollinger Bands: SMA(N) ± k * stdev(N)."""
    if period <= 0:
        raise ValueError("period must be > 0")
    middle = sma(values, period)
    n = len(values)
    upper: list[float | None] = [None] * n
    lower: list[float | None] = [None] * n
    bandwidth: list[float | None] = [None] * n
    pct_b: list[float | None] = [None] * n
    for i in range(period - 1, n):
        window = values[i - period + 1 : i + 1]
        mean = sum(window) / period
        var = sum((x - mean) ** 2 for x in window) / period
        sd = math.sqrt(var)
        u = mean + std_dev * sd
        low = mean - std_dev * sd
        upper[i] = u
        lower[i] = low
        bandwidth[i] = (u - low) / mean if mean else None
        pct_b[i] = (values[i] - low) / (u - low) if (u - low) else None
    return BollingerResult(middle=middle, upper=upper, lower=lower,
                            bandwidth=bandwidth, pct_b=pct_b)


def atr(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    period: int = 14,
) -> list[float | None]:
    """Wilder's Average True Range. Returns absolute ATR in price units."""
    if not (len(highs) == len(lows) == len(closes)):
        raise ValueError("highs, lows, closes must be equal length")
    n = len(closes)
    out: list[float | None] = [None] * n
    if n <= period:
        return out
    trs: list[float] = []
    for i in range(1, n):
        h, low_v, prev_c = highs[i], lows[i], closes[i - 1]
        tr = max(h - low_v, abs(h - prev_c), abs(low_v - prev_c))
        trs.append(tr)
    # Seed with simple mean of first `period` TRs
    seed = sum(trs[:period]) / period
    out[period] = seed
    prev = seed
    for i in range(period + 1, n):
        cur = (prev * (period - 1) + trs[i - 1]) / period
        out[i] = cur
        prev = cur
    return out


@dataclass
class TechnicalSnapshot:
    """Compact 'where are we on every indicator' summary at the last bar."""
    close: float | None
    sma_20: float | None
    sma_50: float | None
    sma_200: float | None
    ema_12: float | None
    ema_26: float | None
    rsi_14: float | None
    macd: float | None
    macd_signal: float | None
    macd_hist: float | None
    bb_upper: float | None
    bb_lower: float | None
    bb_pct_b: float | None
    atr_14: float | None
    trend_label: str  # "bullish" | "bearish" | "neutral"
    rsi_label: str    # "overbought" | "oversold" | "neutral"
    bb_label: str     # "upper_band" | "lower_band" | "mid_band"


def compute_snapshot(
    closes: list[float],
    highs: list[float] | None = None,
    lows: list[float] | None = None,
) -> TechnicalSnapshot:
    """Compute all standard indicators and reduce to a one-row snapshot."""
    if not closes:
        return TechnicalSnapshot(
            close=None, sma_20=None, sma_50=None, sma_200=None,
            ema_12=None, ema_26=None, rsi_14=None,
            macd=None, macd_signal=None, macd_hist=None,
            bb_upper=None, bb_lower=None, bb_pct_b=None,
            atr_14=None,
            trend_label="neutral", rsi_label="neutral", bb_label="mid_band",
        )

    def last(arr: list[float | None]) -> float | None:
        for v in reversed(arr):
            if v is not None:
                return v
        return None

    s20 = last(sma(closes, 20))
    s50 = last(sma(closes, 50))
    s200 = last(sma(closes, 200))
    e12 = last(ema(closes, 12))
    e26 = last(ema(closes, 26))
    r14 = last(rsi(closes, 14))
    macd_res = macd(closes)
    m = last(macd_res.macd_line)
    ms = last(macd_res.signal_line)
    mh = last(macd_res.histogram)
    bb = bollinger_bands(closes, 20, 2.0)
    bu = last(bb.upper)
    bl = last(bb.lower)
    bp = last(bb.pct_b)
    a14 = None
    if highs and lows and len(highs) == len(lows) == len(closes):
        a14 = last(atr(highs, lows, closes, 14))

    cur = closes[-1]
    trend = "neutral"
    if s50 is not None and s200 is not None:
        if cur > s50 > s200:
            trend = "bullish"
        elif cur < s50 < s200:
            trend = "bearish"

    rsi_lbl = "neutral"
    if r14 is not None:
        if r14 >= 70:
            rsi_lbl = "overbought"
        elif r14 <= 30:
            rsi_lbl = "oversold"

    bb_lbl = "mid_band"
    if bp is not None:
        if bp >= 0.95:
            bb_lbl = "upper_band"
        elif bp <= 0.05:
            bb_lbl = "lower_band"

    return TechnicalSnapshot(
        close=cur, sma_20=s20, sma_50=s50, sma_200=s200,
        ema_12=e12, ema_26=e26, rsi_14=r14,
        macd=m, macd_signal=ms, macd_hist=mh,
        bb_upper=bu, bb_lower=bl, bb_pct_b=bp,
        atr_14=a14,
        trend_label=trend, rsi_label=rsi_lbl, bb_label=bb_lbl,
    )


__all__ = [
    "sma", "ema", "rsi", "macd", "bollinger_bands", "atr",
    "MACDResult", "BollingerResult", "TechnicalSnapshot", "compute_snapshot",
]

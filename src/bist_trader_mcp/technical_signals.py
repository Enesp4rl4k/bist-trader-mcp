"""Indicator + divergence signals that feed the price-action confluence layer.

`technicals.py` computes correct RSI / MACD / Bollinger / SMA series but, until
now, only ATR was consumed by the trading logic. This module turns those series
into structured directional signals (momentum, trend, mean-reversion) plus
regular/hidden RSI & MACD divergences, and exposes a bounded confluence
adjustment so the decision path reflects momentum — not just structure.

Pure functions over float lists; no network, fully testable.
"""

from __future__ import annotations

from typing import Any, Literal

from .technicals import bollinger_bands, ema, macd, rsi, sma

Direction = Literal["long", "short"]

# Confluence adjustment is capped so indicators tilt, never override, structure.
MAX_CONFLUENCE_ADJUST = 24.0


def _last(arr: list[float | None]) -> float | None:
    for v in reversed(arr):
        if v is not None:
            return v
    return None


def _last_two_pivot_indices(pivots: list[dict[str, Any]]) -> tuple[int, int] | None:
    idxs = [int(p["index"]) for p in pivots if p.get("index") is not None]
    if len(idxs) < 2:
        return None
    idxs = sorted(idxs)
    return idxs[-2], idxs[-1]


def detect_divergence(
    closes: list[float],
    swing_highs: list[dict[str, Any]],
    swing_lows: list[dict[str, Any]],
    *,
    oscillator: str = "rsi",
    rsi_period: int = 14,
) -> dict[str, Any]:
    """Detect regular/hidden divergence between price and an oscillator.

    Regular bullish: price lower-low, oscillator higher-low (reversal up).
    Regular bearish: price higher-high, oscillator lower-high (reversal down).
    Hidden bullish:  price higher-low, oscillator lower-low (trend continuation up).
    Hidden bearish:  price lower-high, oscillator higher-high (continuation down).
    """
    none = {"type": "none", "oscillator": oscillator, "bias": "neutral", "class": None}
    n = len(closes)
    if n < rsi_period + 5:
        return none

    if oscillator == "macd":
        osc = macd(closes).histogram
    else:
        osc = rsi(closes, rsi_period)

    def osc_at(i: int) -> float | None:
        if 0 <= i < len(osc):
            return osc[i]
        return None

    # Bearish divergences off swing highs
    hi = _last_two_pivot_indices(swing_highs)
    if hi:
        i1, i2 = hi
        p1, p2 = closes[i1], closes[i2]
        o1, o2 = osc_at(i1), osc_at(i2)
        if o1 is not None and o2 is not None:
            if p2 > p1 and o2 < o1:
                return {"type": "regular_bearish", "oscillator": oscillator,
                        "bias": "short", "class": "reversal",
                        "detail": f"price HH / {oscillator} LH"}
            if p2 < p1 and o2 > o1:
                return {"type": "hidden_bearish", "oscillator": oscillator,
                        "bias": "short", "class": "continuation",
                        "detail": f"price LH / {oscillator} HH"}

    # Bullish divergences off swing lows
    lo = _last_two_pivot_indices(swing_lows)
    if lo:
        i1, i2 = lo
        p1, p2 = closes[i1], closes[i2]
        o1, o2 = osc_at(i1), osc_at(i2)
        if o1 is not None and o2 is not None:
            if p2 < p1 and o2 > o1:
                return {"type": "regular_bullish", "oscillator": oscillator,
                        "bias": "long", "class": "reversal",
                        "detail": f"price LL / {oscillator} HL"}
            if p2 > p1 and o2 < o1:
                return {"type": "hidden_bullish", "oscillator": oscillator,
                        "bias": "long", "class": "continuation",
                        "detail": f"price HL / {oscillator} LL"}

    return none


def compute_indicator_signals(
    closes: list[float],
    highs: list[float] | None = None,
    lows: list[float] | None = None,
    *,
    swing_highs: list[dict[str, Any]] | None = None,
    swing_lows: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Structured momentum / trend / mean-reversion signals at the last bar."""
    if len(closes) < 15:
        return {
            "available": False,
            "momentum_bias": "neutral",
            "signal_score": 0.0,
            "factors": [],
        }

    r = _last(rsi(closes, 14))
    macd_res = macd(closes)
    m = _last(macd_res.macd_line)
    msig = _last(macd_res.signal_line)
    mhist = _last(macd_res.histogram)
    bb = bollinger_bands(closes, 20, 2.0)
    pct_b = _last(bb.pct_b)
    s20 = _last(sma(closes, 20))
    s50 = _last(sma(closes, 50))
    e12 = _last(ema(closes, 12))
    e26 = _last(ema(closes, 26))
    close = closes[-1]

    factors: list[str] = []
    score = 0.0

    rsi_state = "neutral"
    if r is not None:
        # Overbought/oversold are mean-reversion *cautions*, intentionally
        # smaller than the trend weight so they temper — not flip — a trend.
        if r >= 70:
            rsi_state, score = "overbought", score - 4
            factors.append("rsi_overbought")
        elif r <= 30:
            rsi_state, score = "oversold", score + 4
            factors.append("rsi_oversold")
        elif r >= 55:
            rsi_state, score = "bullish", score + 5
        elif r <= 45:
            rsi_state, score = "bearish", score - 5

    macd_cross = "none"
    if m is not None and msig is not None:
        if m > msig:
            macd_cross = "bullish"
            score += 6
            factors.append("macd_above_signal")
        else:
            macd_cross = "bearish"
            score -= 6
            factors.append("macd_below_signal")
    if mhist is not None:
        score += 3 if mhist > 0 else -3

    trend = "neutral"
    if s20 is not None and s50 is not None:
        if close > s20 > s50:
            trend, score = "bullish", score + 8
            factors.append("price_above_sma_stack")
        elif close < s20 < s50:
            trend, score = "bearish", score - 8
            factors.append("price_below_sma_stack")
        elif close > s50:
            trend, score = "weak_bullish", score + 3
        elif close < s50:
            trend, score = "weak_bearish", score - 3
    if e12 is not None and e26 is not None:
        score += 2 if e12 > e26 else -2

    bb_state = "mid_band"
    if pct_b is not None:
        if pct_b <= 0.05:
            bb_state, score = "lower_band", score + 3
            factors.append("bb_lower_band")
        elif pct_b >= 0.95:
            bb_state, score = "upper_band", score - 3
            factors.append("bb_upper_band")

    div_rsi = detect_divergence(closes, swing_highs or [], swing_lows or [], oscillator="rsi")
    div_macd = detect_divergence(closes, swing_highs or [], swing_lows or [], oscillator="macd")
    divergence = div_rsi if div_rsi["type"] != "none" else div_macd
    if divergence["type"] != "none":
        factors.append(divergence["type"])
        bump = 12 if divergence.get("class") == "reversal" else 8
        score += bump if divergence["bias"] == "long" else -bump

    score = max(-100.0, min(100.0, score))
    if score >= 12:
        momentum_bias = "long"
    elif score <= -12:
        momentum_bias = "short"
    else:
        momentum_bias = "neutral"

    return {
        "available": True,
        "rsi": {"value": round(r, 1) if r is not None else None, "state": rsi_state},
        "macd": {
            "line": round(m, 6) if m is not None else None,
            "hist": round(mhist, 6) if mhist is not None else None,
            "cross": macd_cross,
        },
        "bollinger": {"pct_b": round(pct_b, 3) if pct_b is not None else None, "state": bb_state},
        "trend": {"label": trend, "sma_20": s20, "sma_50": s50},
        "divergence": divergence,
        "momentum_bias": momentum_bias,
        "signal_score": round(score, 1),
        "factors": factors,
    }


def confluence_adjustment(
    signals: dict[str, Any] | None,
    direction: Direction,
) -> tuple[float, list[str]]:
    """Bounded confluence delta + factor labels for a trade direction.

    Aligns the indicator signal_score with the trade direction: momentum that
    agrees adds confluence, momentum that fights the setup subtracts it.
    """
    if not signals or not signals.get("available"):
        return 0.0, []

    raw = float(signals.get("signal_score") or 0.0)
    delta = raw if direction == "long" else -raw
    delta = max(-MAX_CONFLUENCE_ADJUST, min(MAX_CONFLUENCE_ADJUST, delta * 0.6))

    factors: list[str] = []
    div = signals.get("divergence") or {}
    if div.get("type") not in (None, "none") and div.get("bias") == direction:
        factors.append(f"momentum_{div['type']}")
    if signals.get("momentum_bias") == direction and direction in ("long", "short"):
        factors.append("momentum_aligned")
    elif signals.get("momentum_bias") not in ("neutral", direction):
        factors.append("momentum_against")

    return round(delta, 1), factors


def indicator_summary_tr(signals: dict[str, Any] | None) -> str:
    """One-line Turkish momentum summary for chat_report."""
    if not signals or not signals.get("available"):
        return "Momentum: veri yetersiz"
    rsi_v = (signals.get("rsi") or {}).get("value")
    macd_c = (signals.get("macd") or {}).get("cross")
    trend = (signals.get("trend") or {}).get("label")
    div = (signals.get("divergence") or {}).get("type")
    parts = [
        f"RSI {rsi_v if rsi_v is not None else '—'}",
        f"MACD {macd_c}",
        f"trend {trend}",
    ]
    if div and div != "none":
        parts.append(f"divergence {div}")
    parts.append(f"momentum {signals.get('momentum_bias')}")
    return "Momentum: " + " · ".join(parts)


__all__ = [
    "detect_divergence",
    "compute_indicator_signals",
    "confluence_adjustment",
    "indicator_summary_tr",
    "MAX_CONFLUENCE_ADJUST",
]

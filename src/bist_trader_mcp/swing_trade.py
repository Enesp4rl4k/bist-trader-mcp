"""Swing-trade layer — daily-first setups with a multi-day holding horizon.

The MCP already detects intraday/structural setups (``pa_setups``) and designs
trade plans. Swing trading adds a distinct frame: trade off the **daily** chart,
hold days-to-weeks, and manage with a **time stop** as well as a price stop. This
module supplies that layer:

  * trend-regime classification from the EMA stack (20/50/200)
  * two canonical swing entries — trend pullback and breakout-retest (long+short)
  * price stop (structure/ATR) + R-multiple and structural targets
  * **expected holding period** and a **time stop** (bars), the swing-specific bits
  * optional fundamental gate — swing on quality names (uses the selection score)

Pure math on daily OHLCV (no network), so it is testable and composes with the
fundamental engine. Not advice; no execution.
"""

from __future__ import annotations

from typing import Any

from .price_action import adaptive_swing_params, find_swings
from .technicals import atr, ema, rsi


def _last_valid(arr: list[float | None]) -> float | None:
    for v in reversed(arr):
        if v is not None:
            return v
    return None


def _trend_regime(price: float, e20: float, e50: float, e200: float | None) -> str:
    """Classify the daily trend from the moving-average stack."""
    if e200 is not None:
        if e20 > e50 > e200 and price > e50:
            return "uptrend"
        if e20 < e50 < e200 and price < e50:
            return "downtrend"
    if e20 > e50 and price > e50:
        return "uptrend_weak"
    if e20 < e50 and price < e50:
        return "downtrend_weak"
    return "range"


def _holding_horizon(distance: float, atr_val: float) -> dict[str, int]:
    """Estimate expected holding days from how many ATRs the target is away, and a
    time stop (exit if the thesis hasn't played out)."""
    if atr_val <= 0:
        return {"expected_days": 5, "time_stop_bars": 15}
    days = max(2, min(30, round(distance / atr_val)))
    time_stop = max(10, min(40, days * 3))
    return {"expected_days": days, "time_stop_bars": time_stop}


def analyze_swing_trade(
    closes: list[float],
    highs: list[float],
    lows: list[float],
    *,
    volumes: list[float] | None = None,
    symbol: str | None = None,
    account_equity: float | None = None,
    risk_pct: float = 1.0,
    min_rr: float = 1.5,
    fundamental_score: float | None = None,
    breakout_lookback: int = 20,
) -> dict[str, Any]:
    """Detect a daily swing setup with entry/stop/targets + holding horizon.

    ``fundamental_score`` (-100..+100 from ``fundamental_statements.selection``)
    gates/colours longs: a strongly negative score downgrades a long ("swing on
    quality"). Returns a structured plan + Turkish summary; ``setup="no_setup"``
    when no clean swing entry is present.
    """
    n = len(closes)
    if n < 60:
        return {"source": "bist-trader-mcp — swing_trade", "setup": "no_setup",
                "reason": "need>=60 daily bars", "bars": n}

    price = closes[-1]
    e20 = _last_valid(ema(closes, 20))
    e50 = _last_valid(ema(closes, 50))
    e200 = _last_valid(ema(closes, 200)) if n >= 200 else None
    atr_val = _last_valid(atr(highs, lows, closes, 14)) or 0.0
    rsi_val = _last_valid(rsi(closes, 14)) or 50.0
    if e20 is None or e50 is None or atr_val <= 0:
        return {"source": "bist-trader-mcp — swing_trade", "setup": "no_setup",
                "reason": "insufficient_indicators", "bars": n}

    lookback, prom = adaptive_swing_params(atr_val, price, n_bars=n)
    sh, sl = find_swings(highs, lows, lookback=lookback, min_prominence=prom)
    last_sh = sh[-1].price if sh else max(highs[-breakout_lookback:])
    last_sl = sl[-1].price if sl else min(lows[-breakout_lookback:])

    regime = _trend_regime(price, e20, e50, e200)
    # Prior resistance/support for breakout detection (exclude the live bar).
    prior_high = max(highs[-breakout_lookback - 1:-1]) if n > breakout_lookback else max(highs[:-1])
    prior_low = min(lows[-breakout_lookback - 1:-1]) if n > breakout_lookback else min(lows[:-1])

    setup, direction, entry, stop, note = _detect_setup(
        price=price, e20=e20, e50=e50, atr_val=atr_val, rsi_val=rsi_val,
        regime=regime, last_sh=last_sh, last_sl=last_sl,
        prior_high=prior_high, prior_low=prior_low,
    )
    if setup == "no_setup":
        return {"source": "bist-trader-mcp — swing_trade", "setup": "no_setup",
                "regime": regime, "rsi": round(rsi_val, 1),
                "ema": {"e20": _r(e20), "e50": _r(e50), "e200": _r(e200)},
                "reason": note, "bars": n, "symbol": symbol}

    risk = abs(entry - stop)
    if risk <= 0:
        return {"source": "bist-trader-mcp — swing_trade", "setup": "no_setup",
                "reason": "non_positive_risk", "bars": n}

    sign = 1.0 if direction == "long" else -1.0
    r_targets = [round(entry + sign * m * risk, 4) for m in (1.5, 2.5, 4.0)]
    structural = last_sh if direction == "long" else last_sl
    first_target = r_targets[0]
    rr_structural = abs(structural - entry) / risk if risk else None

    horizon = _holding_horizon(abs(first_target - entry), atr_val)
    grade, score = _swing_grade(
        regime=regime, direction=direction, rsi_val=rsi_val,
        rr=abs(first_target - entry) / risk, fundamental_score=fundamental_score,
    )

    sizing = None
    if account_equity and account_equity > 0:
        risk_amount = account_equity * (risk_pct / 100.0)
        units = risk_amount / risk
        sizing = {
            "units": round(units, 4),
            "risk_amount": round(risk_amount, 2),
            "notional": round(units * entry, 2),
            "risk_pct_of_equity": risk_pct,
        }

    flags: list[str] = []
    if direction == "long" and fundamental_score is not None and fundamental_score < -30:
        flags.append("weak_fundamentals_for_long")

    return {
        "source": "bist-trader-mcp — swing_trade.analyze_swing_trade",
        "symbol": symbol,
        "setup": setup,
        "direction": direction,
        "regime": regime,
        "entry": _r(entry),
        "stop": _r(stop),
        "risk_per_unit": _r(risk),
        "targets_r_multiple": r_targets,
        "structural_target": _r(structural),
        "rr_first_target": round(abs(first_target - entry) / risk, 2),
        "rr_structural": None if rr_structural is None else round(rr_structural, 2),
        "expected_holding_days": horizon["expected_days"],
        "time_stop_bars": horizon["time_stop_bars"],
        "rsi": round(rsi_val, 1),
        "atr": _r(atr_val),
        "ema": {"e20": _r(e20), "e50": _r(e50), "e200": _r(e200)},
        "grade": grade,
        "swing_score": score,
        "sizing": sizing,
        "flags": flags,
        "note": note,
        "summary_tr": _summary_tr(symbol, setup, direction, regime, entry, stop,
                                  first_target, horizon, grade, flags),
    }


def _detect_setup(
    *, price: float, e20: float, e50: float, atr_val: float, rsi_val: float,
    regime: str, last_sh: float, last_sl: float, prior_high: float, prior_low: float,
) -> tuple[str, str, float, float, str]:
    """Return (setup, direction, entry, stop, note). 'no_setup' when none clean."""
    up = regime in ("uptrend", "uptrend_weak")
    down = regime in ("downtrend", "downtrend_weak")

    # 1) Breakout-retest: close clears prior resistance (long) / support (short).
    if up and price > prior_high:
        stop = min(prior_high - 0.5 * atr_val, e20 - 0.5 * atr_val)
        return ("breakout_long", "long", price, stop, "daily breakout over prior high")
    if down and price < prior_low:
        stop = max(prior_low + 0.5 * atr_val, e20 + 0.5 * atr_val)
        return ("breakout_short", "short", price, stop, "daily breakdown under prior low")

    # 2) Trend pullback: price has cooled back toward the 20/50 EMA in a trend.
    near_ema = min(abs(price - e20), abs(price - e50)) <= 1.0 * atr_val
    if up and near_ema and 38 <= rsi_val <= 60 and price > last_sl:
        stop = min(last_sl, e50 - 0.5 * atr_val)
        return ("trend_pullback_long", "long", price, stop, "pullback to EMA in uptrend")
    if down and near_ema and 40 <= rsi_val <= 62 and price < last_sh:
        stop = max(last_sh, e50 + 0.5 * atr_val)
        return ("trend_pullback_short", "short", price, stop, "pullback to EMA in downtrend")

    return ("no_setup", "neutral", 0.0, 0.0, f"no clean swing setup in {regime}")


def _swing_grade(
    *, regime: str, direction: str, rsi_val: float, rr: float,
    fundamental_score: float | None,
) -> tuple[str, float]:
    """0..100 swing quality from trend alignment, R:R, RSI and fundamentals."""
    score = 40.0
    if regime in ("uptrend", "downtrend"):
        score += 20  # full MA stack alignment
    elif regime in ("uptrend_weak", "downtrend_weak"):
        score += 8
    score += min(20.0, rr * 6.0)
    if direction == "long" and rsi_val < 35:
        score += 6  # deeper pullback, better entry
    if direction == "short" and rsi_val > 65:
        score += 6
    if fundamental_score is not None:
        if direction == "long":
            score += max(-15.0, min(12.0, fundamental_score * 0.2))
        else:
            score += max(-12.0, min(10.0, -fundamental_score * 0.15))
    score = round(max(0.0, min(100.0, score)), 1)
    grade = "A" if score >= 78 else ("B" if score >= 62 else ("C" if score >= 48 else "D"))
    return grade, score


def _summary_tr(
    symbol: str | None, setup: str, direction: str, regime: str,
    entry: float, stop: float, target: float, horizon: dict[str, int],
    grade: str, flags: list[str],
) -> str:
    yon = "AL" if direction == "long" else "SAT"
    line = (
        f"{symbol or 'Swing'}: {yon} ({setup}, {regime}) | giriş {_r(entry)} "
        f"stop {_r(stop)} hedef {_r(target)} | tahmini tutuş {horizon['expected_days']} gün "
        f"(zaman-stop {horizon['time_stop_bars']} bar) | not {grade}"
    )
    if flags:
        line += " | ⚠ " + ", ".join(flags)
    return line


def _r(x: float | None, n: int = 4) -> float | None:
    return None if x is None else round(x, n)


__all__ = ["analyze_swing_trade"]

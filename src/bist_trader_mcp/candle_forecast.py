"""Next-candle forecast — "N possible futures" in plain language.

Inspired by Kronos-style candle forecasting charts, but model-free and
dependency-free: we resample the *shape* of the last ``context`` real candles
(close-to-close return, gap, upper/lower wick) in short blocks and draw the
next ``horizon`` candles one at a time, ``n_paths`` times. Each run is one
possible future. The output is deliberately simple:

- how many runs ended above / below the last close (Up % / Down %)
- the mean path (average of the runs) and the spread band (lowest → highest run)
- volatility amplification: how many runs swing harder than the last real
  ``horizon`` candles did
- a short Turkish + English summary

Pure math on OHLCV lists. Deterministic when ``seed`` is given.
Not investment advice — this is a spread of plausible paths, not a signal.
"""

from __future__ import annotations

import math
import random
from typing import Any


def _stdev(xs: list[float]) -> float:
    if len(xs) < 2:
        return 0.0
    m = sum(xs) / len(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))


def _bar_shapes(
    opens: list[float],
    highs: list[float],
    lows: list[float],
    closes: list[float],
) -> list[tuple[float, float, float, float]]:
    """Per-bar log shape relative to the previous close.

    (ret, gap, upper_wick, lower_wick):
      ret        = ln(close / prev_close)
      gap        = ln(open / prev_close)
      upper_wick = ln(high / max(open, close))   >= 0
      lower_wick = ln(min(open, close) / low)    >= 0
    """
    out: list[tuple[float, float, float, float]] = []
    for i in range(1, len(closes)):
        pc, o, h, lo, c = closes[i - 1], opens[i], highs[i], lows[i], closes[i]
        if min(pc, o, h, lo, c) <= 0:
            continue
        body_hi, body_lo = max(o, c), min(o, c)
        out.append(
            (
                math.log(c / pc),
                math.log(o / pc),
                max(0.0, math.log(max(h, body_hi) / body_hi)),
                max(0.0, math.log(body_lo / min(lo, body_lo))),
            )
        )
    return out


def _simulate_path(
    shapes: list[tuple[float, float, float, float]],
    last_close: float,
    horizon: int,
    block: int,
    scale: float,
    drift_adj: float,
    rng: random.Random,
) -> list[dict[str, float]]:
    candles: list[dict[str, float]] = []
    prev = last_close
    n = len(shapes)
    i = rng.randrange(n)
    left_in_block = 0
    for _ in range(horizon):
        if left_in_block <= 0:
            i = rng.randrange(n)
            left_in_block = block
        ret, gap, up, dn = shapes[i]
        ret = ret * scale - drift_adj
        gap = gap * scale
        o = prev * math.exp(gap)
        c = prev * math.exp(ret)
        h = max(o, c) * math.exp(up * scale)
        lo = min(o, c) / math.exp(dn * scale)
        candles.append({"open": o, "high": h, "low": lo, "close": c})
        prev = c
        i = (i + 1) % n
        left_in_block -= 1
    return candles


def forecast_candles(
    closes: list[float],
    highs: list[float],
    lows: list[float],
    opens: list[float] | None = None,
    *,
    horizon: int = 24,
    n_paths: int = 30,
    context: int = 360,
    block: int = 5,
    drift: str = "historical",
    vol_regime: bool = True,
    seed: int | None = None,
    include_paths: bool = False,
) -> dict[str, Any]:
    """Simulate ``n_paths`` possible futures of the next ``horizon`` candles.

    Args:
        closes/highs/lows/opens: OHLC history, oldest first.
        horizon: number of future candles to draw.
        n_paths: number of runs ("possible futures").
        context: how many of the latest real candles the sampler reads.
        block: consecutive candles copied together (keeps short-term rhythm).
        drift: "historical" keeps the context's average move; "zero" removes it.
        vol_regime: rescale moves so recent volatility (last ~20 bars) sets the tone.
        seed: fix for reproducible output.
        include_paths: also return every simulated candle (bigger payload).
    """
    n = len(closes)
    if not (n == len(highs) == len(lows)):
        raise ValueError("closes, highs, lows must be equal length")
    if opens is None:
        opens = [closes[0]] + closes[:-1]
    if len(opens) != n:
        raise ValueError("opens must match closes length")
    if horizon < 1 or n_paths < 1:
        raise ValueError("horizon and n_paths must be >= 1")
    if drift not in ("historical", "zero"):
        raise ValueError("drift must be 'historical' or 'zero'")

    ctx = max(2, min(int(context), n))
    shapes = _bar_shapes(opens[-ctx:], highs[-ctx:], lows[-ctx:], closes[-ctx:])
    if len(shapes) < 20:
        raise ValueError("need at least ~21 valid bars of history to forecast")

    block = max(1, min(int(block), len(shapes)))
    rets = [s[0] for s in shapes]
    ctx_vol = _stdev(rets)
    scale = 1.0
    if vol_regime and ctx_vol > 0:
        recent_vol = _stdev(rets[-20:])
        scale = max(0.5, min(2.0, recent_vol / ctx_vol)) if recent_vol > 0 else 1.0
    drift_adj = (sum(rets) / len(rets)) * scale if drift == "zero" else 0.0

    last_close = closes[-1]
    rng = random.Random(seed)
    paths = [
        _simulate_path(shapes, last_close, horizon, block, scale, drift_adj, rng)
        for _ in range(n_paths)
    ]

    finals = [p[-1]["close"] for p in paths]
    up = sum(1 for f in finals if f > last_close)
    down = n_paths - up

    mean_path, band_low, band_high, p10, p90 = [], [], [], [], []
    for step in range(horizon):
        col = sorted(p[step]["close"] for p in paths)
        mean_path.append(sum(col) / len(col))
        band_low.append(col[0])
        band_high.append(col[-1])
        p10.append(col[max(0, int(0.1 * (len(col) - 1)))])
        p90.append(col[min(len(col) - 1, math.ceil(0.9 * (len(col) - 1)))])

    # Volatility amplification: runs whose candle-to-candle swings are larger
    # than the last `horizon` real candles.
    real_window = min(horizon, len(rets))
    real_vol = _stdev(rets[-real_window:]) if real_window >= 2 else ctx_vol
    amplified = 0
    for p in paths:
        prices = [last_close] + [c["close"] for c in p]
        path_rets = [math.log(b / a) for a, b in zip(prices, prices[1:], strict=False)]
        if _stdev(path_rets) > real_vol:
            amplified += 1

    mean_final = mean_path[-1]
    change_pct = (mean_final / last_close - 1.0) * 100.0
    lo_run, hi_run = min(finals), max(finals)
    up_pct = round(100.0 * up / n_paths)
    down_pct = 100 - up_pct
    amp_pct = round(100.0 * amplified / n_paths)

    if up_pct >= 65:
        lean_tr, lean_en = "yukarı eğilimli", "leans up"
    elif down_pct >= 65:
        lean_tr, lean_en = "aşağı eğilimli", "leans down"
    else:
        lean_tr, lean_en = "kararsız (iki yön de mümkün)", "undecided"

    def _f(x: float) -> str:
        return f"{x:,.2f}"

    summary_tr = (
        f"{n_paths} olası gelecek: {up} tanesi {_f(last_close)} üzerinde, "
        f"{down} tanesi altında bitti (Yukarı %{up_pct} / Aşağı %{down_pct}). "
        f"{horizon} mum sonra ortalama tahmin {_f(mean_final)} "
        f"({change_pct:+.2f}%), tüm aralık {_f(lo_run)} – {_f(hi_run)}. "
        f"Tablo {lean_tr}. Koşuların %{amp_pct}'i son {real_window} gerçek mumdan "
        f"daha sert dalgalanıyor."
    )
    summary_en = (
        f"{n_paths} possible futures: {up} end higher and {down} end lower than "
        f"{_f(last_close)}; mean forecast {_f(mean_final)} ({change_pct:+.2f}%) "
        f"after {horizon} candles, full range {_f(lo_run)} – {_f(hi_run)}. "
        f"Picture {lean_en}; {amplified} of {n_paths} runs swing harder than the "
        f"last {real_window} real candles."
    )

    def _r(xs: list[float]) -> list[float]:
        return [round(x, 6) for x in xs]

    result: dict[str, Any] = {
        "method": "block-bootstrap candle simulation (model-free, Kronos-style view)",
        "last_close": last_close,
        "horizon": horizon,
        "n_paths": n_paths,
        "context_bars": ctx,
        "candles": {
            "up_count": up,
            "down_count": down,
            "up_pct": up_pct,
            "down_pct": down_pct,
        },
        "mean_forecast": {
            "price": round(mean_final, 6),
            "change_pct": round(change_pct, 2),
        },
        "full_range": {"lowest_run": round(lo_run, 6), "highest_run": round(hi_run, 6)},
        "volatility_amplification": {
            "count": amplified,
            "pct": amp_pct,
            "vol_regime_scale": round(scale, 3),
        },
        "lean": lean_en,
        "series": {
            "mean": _r(mean_path),
            "band_low": _r(band_low),
            "band_high": _r(band_high),
            "p10": _r(p10),
            "p90": _r(p90),
        },
        "summary_tr": summary_tr,
        "summary_en": summary_en,
        "how_it_works": (
            f"Son {ctx} mumu okudu, sonraki {horizon} mumu tek tek çizdi, bunu "
            f"{n_paths} kez tekrarladı → {n_paths} olası gelecek. Turuncu çizgi "
            "ortalama, gölgeli bant en düşük ile en yüksek koşu arasıdır."
        ),
        "disclaimer": "Olasılık dağılımı, sinyal değil. Yatırım tavsiyesi değildir.",
    }
    if include_paths:
        result["paths"] = [
            [{k: round(v, 6) for k, v in c.items()} for c in p] for p in paths
        ]
    return result


__all__ = ["forecast_candles"]

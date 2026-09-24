"""Is the candle forecast band honest? Walk-forward calibration check.

At past points ``t`` we run :func:`candle_forecast.forecast_candles` on the
prefix ``[:t+1]`` and compare with the close actually printed ``horizon`` bars
later:

- p10–p90 coverage: should be ~80% for a calibrated band
- full band (lowest→highest run) coverage
- direction hit rate: runs' majority (Up% > 50) vs the realised direction
- mean band width in % of price
"""

from __future__ import annotations

from typing import Any

from .candle_forecast import forecast_candles


def evaluate_forecast_calibration(
    opens: list[float],
    highs: list[float],
    lows: list[float],
    closes: list[float],
    *,
    horizon: int = 24,
    n_paths: int = 30,
    context: int = 360,
    step: int = 10,
    warmup: int = 120,
    seed: int = 0,
    drift: str = "historical",
) -> dict[str, Any]:
    """Walk-forward coverage / direction check of ``forecast_candles``."""
    n = len(closes)
    if not (n == len(opens) == len(highs) == len(lows)):
        raise ValueError("opens, highs, lows, closes must be equal length")
    step = max(1, int(step))
    points = list(range(warmup, n - horizon, step))
    if len(points) < 5:
        raise ValueError(
            f"need more history: {n} bars gives {len(points)} test points "
            f"(warmup={warmup}, horizon={horizon}, step={step}); need >= 5"
        )

    in_p, in_full, dir_hits, dir_total = 0, 0, 0, 0
    widths: list[float] = []
    rows = []
    for k, t in enumerate(points):
        fc = forecast_candles(
            closes[: t + 1], highs[: t + 1], lows[: t + 1], opens[: t + 1],
            horizon=horizon, n_paths=n_paths, context=context, seed=seed + k, drift=drift,
        )
        s = fc["series"]
        actual = closes[t + horizon]
        last = closes[t]
        p10, p90 = s["p10"][-1], s["p90"][-1]
        lo, hi = s["band_low"][-1], s["band_high"][-1]
        in_p += p10 <= actual <= p90
        in_full += lo <= actual <= hi
        widths.append((p90 - p10) / last * 100.0)
        up_pct = fc["candles"]["up_pct"]
        if up_pct != 50 and actual != last:
            dir_total += 1
            dir_hits += (up_pct > 50) == (actual > last)
        rows.append({"t": t, "last": last, "actual": actual, "p10": p10, "p90": p90,
                     "up_pct": up_pct})

    m = len(points)
    cov = 100.0 * in_p / m
    full = 100.0 * in_full / m
    hit = 100.0 * dir_hits / dir_total if dir_total else None
    if cov < 65:
        band_tr = "Bant fazla dar — gerçek fiyat sık sık dışına çıkıyor; oynaklık hafife alınıyor."
        band = "too_narrow"
    elif cov > 92:
        band_tr = "Bant gereksiz geniş — tahmin fazla temkinli."
        band = "too_wide"
    else:
        band_tr = "Bant makul kalibre (hedef ~%80)."
        band = "calibrated"
    if hit is None:
        dir_tr = "Yön isabeti ölçülemedi."
    elif hit >= 55:
        dir_tr = f"Yön tahmini yazı-turadan iyi (%{hit:.0f})."
    elif hit <= 45:
        dir_tr = f"Yön tahmini ters çalışıyor (%{hit:.0f}) — Yukarı/Aşağı %'sine güvenme."
    else:
        dir_tr = f"Yön tahmini yazı-tura seviyesinde (%{hit:.0f}); bant kullanışlı, yön değil."

    return {
        "method": "walk-forward, prefix-only forecasts vs realised close after horizon",
        "test_points": m,
        "horizon": horizon,
        "p10_p90_coverage_pct": round(cov, 1),
        "full_band_coverage_pct": round(full, 1),
        "direction_hit_rate_pct": None if hit is None else round(hit, 1),
        "direction_samples": dir_total,
        "mean_p10_p90_width_pct": round(sum(widths) / m, 2),
        "band_verdict": band,
        "summary_tr": f"{m} geçmiş noktada test edildi. {band_tr} {dir_tr}",
        "points": rows[-20:],
    }


__all__ = ["evaluate_forecast_calibration"]

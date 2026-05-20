"""Cross-asset correlation analytics — pure math, no network.

Used by `calculate_correlation_matrix` and `calculate_rolling_correlation`
tools to surface portfolio diversification + regime change signals.

Inputs: dict of {asset_name: list[float] of closes}. Length alignment is
handled by trimming to the common minimum.
"""

from __future__ import annotations

import math
from typing import Any


def returns_from_closes(closes: list[float], method: str = "log") -> list[float]:
    """Convert a closes series into log or simple percentage returns."""
    if method not in ("log", "simple"):
        raise ValueError("method must be 'log' or 'simple'")
    if len(closes) < 2:
        return []
    out: list[float] = []
    for i in range(1, len(closes)):
        prev = closes[i - 1]
        cur = closes[i]
        if prev is None or cur is None or prev <= 0:
            out.append(0.0)
            continue
        if method == "log":
            out.append(math.log(cur / prev))
        else:
            out.append((cur - prev) / prev)
    return out


def pearson(x: list[float], y: list[float]) -> float | None:
    """Pearson correlation of two equal-length series. Returns None on
    degenerate input (constant series, mismatched length)."""
    n = min(len(x), len(y))
    if n < 2:
        return None
    mx = sum(x[:n]) / n
    my = sum(y[:n]) / n
    var_x = sum((x[i] - mx) ** 2 for i in range(n))
    var_y = sum((y[i] - my) ** 2 for i in range(n))
    if var_x == 0 or var_y == 0:
        return None
    cov = sum((x[i] - mx) * (y[i] - my) for i in range(n))
    return cov / math.sqrt(var_x * var_y)


def correlation_matrix(
    series: dict[str, list[float]],
    method: str = "log",
) -> dict[str, Any]:
    """Compute the full pairwise correlation matrix of returns.

    Args:
        series: {asset: closes} dict. All inputs are trimmed to the
            common minimum length.
        method: 'log' or 'simple' return method.

    Returns dict with:
        - assets: ordered list of names
        - matrix: NxN list-of-lists of correlations (diag = 1.0)
        - sample_size: number of return observations used
        - top_correlations: top 10 |ρ| pairs (excluding self)
        - lowest_correlations: bottom 10 (most diversifying)
    """
    if not series:
        return {"assets": [], "matrix": [], "sample_size": 0,
                "top_correlations": [], "lowest_correlations": []}

    assets = list(series.keys())
    # Trim to common min length and compute returns
    rets: dict[str, list[float]] = {}
    min_len = min(len(v) for v in series.values())
    for a in assets:
        closes = series[a][-min_len:]
        rets[a] = returns_from_closes(closes, method=method)

    sample = min(len(v) for v in rets.values()) if rets else 0
    n = len(assets)
    matrix: list[list[float | None]] = [[None] * n for _ in range(n)]
    pairs: list[dict[str, Any]] = []

    for i in range(n):
        for j in range(n):
            if i == j:
                matrix[i][j] = 1.0
                continue
            if j < i:
                matrix[i][j] = matrix[j][i]
                continue
            rho = pearson(rets[assets[i]], rets[assets[j]])
            matrix[i][j] = rho
            if rho is not None:
                pairs.append({
                    "asset_a": assets[i],
                    "asset_b": assets[j],
                    "correlation": round(rho, 4),
                })

    pairs_sorted_abs = sorted(pairs, key=lambda r: abs(r["correlation"]),
                               reverse=True)
    pairs_sorted_low = sorted(pairs, key=lambda r: r["correlation"])

    return {
        "assets": assets,
        "matrix": matrix,
        "sample_size": sample,
        "method": method,
        "top_correlations": pairs_sorted_abs[:10],
        "lowest_correlations": pairs_sorted_low[:10],
    }


def rolling_correlation(
    series_a: list[float],
    series_b: list[float],
    window: int = 30,
    method: str = "log",
) -> list[float | None]:
    """Rolling correlation over `window` return observations."""
    ra = returns_from_closes(series_a, method=method)
    rb = returns_from_closes(series_b, method=method)
    n = min(len(ra), len(rb))
    out: list[float | None] = [None] * n
    if n < window:
        return out
    for i in range(window - 1, n):
        out[i] = pearson(ra[i - window + 1 : i + 1], rb[i - window + 1 : i + 1])
    return out


__all__ = [
    "returns_from_closes",
    "pearson",
    "correlation_matrix",
    "rolling_correlation",
]

"""Markowitz portfolio optimization — efficient frontier + min-variance.

Pure math, no external solvers. Uses Lagrangian closed-form for the
unconstrained problem (allows shorting; weights sum to 1):

    min  wᵀΣw      s.t.  wᵀμ = target_ret,  wᵀ1 = 1

Closed-form solution via the (A, B, C, D) coefficients of Markowitz
analytical frontier.

For long-only constraints we use a grid search over the unconstrained
frontier — adequate for portfolios up to ~20 assets.

All returns annualised; covariance matrix from sample returns × T.
"""

from __future__ import annotations

import math
from typing import Any

from .correlation import returns_from_closes


def _mean(v: list[float]) -> float:
    return sum(v) / len(v) if v else 0.0


def _sample_covariance(
    series: dict[str, list[float]],
) -> tuple[list[str], list[list[float]], list[float]]:
    """Compute (asset_names, covariance matrix, mean returns) from closes."""
    assets = list(series.keys())
    rets = {a: returns_from_closes(series[a], method="log") for a in assets}
    min_len = min(len(r) for r in rets.values()) if rets else 0
    if min_len < 2:
        return assets, [], []
    aligned = {a: rets[a][-min_len:] for a in assets}
    means = [_mean(aligned[a]) for a in assets]
    n = len(assets)
    cov = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(i, n):
            ai = aligned[assets[i]]; aj = aligned[assets[j]]
            mi = means[i]; mj = means[j]
            c = sum((ai[t] - mi) * (aj[t] - mj) for t in range(min_len))
            c /= (min_len - 1) if min_len > 1 else 1
            cov[i][j] = c
            cov[j][i] = c
    return assets, cov, means


def _matrix_inverse(M: list[list[float]]) -> list[list[float]] | None:
    """Gauss-Jordan inversion for small dense matrices."""
    n = len(M)
    A = [row[:] + [1.0 if i == j else 0.0 for j in range(n)] for i, row in enumerate(M)]
    for i in range(n):
        # Pivot
        piv = max(range(i, n), key=lambda r: abs(A[r][i]))
        if abs(A[piv][i]) < 1e-14:
            return None
        A[i], A[piv] = A[piv], A[i]
        # Normalize row
        norm = A[i][i]
        A[i] = [v / norm for v in A[i]]
        for r in range(n):
            if r == i:
                continue
            factor = A[r][i]
            A[r] = [A[r][c] - factor * A[i][c] for c in range(2 * n)]
    return [row[n:] for row in A]


def _vec_matmul(M: list[list[float]], v: list[float]) -> list[float]:
    return [sum(M[i][j] * v[j] for j in range(len(v))) for i in range(len(M))]


def _quad_form(w: list[float], M: list[list[float]]) -> float:
    return sum(w[i] * sum(M[i][j] * w[j] for j in range(len(w))) for i in range(len(w)))


def _dot(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=False))


def optimize_portfolio(
    series: dict[str, list[float]],
    target_return_pct: float | None = None,
    risk_free_pct: float = 0.0,
    periods_per_year: int = 252,
) -> dict[str, Any]:
    """Markowitz portfolio optimization.

    Returns:
        - min_variance_portfolio: minimum-variance long/short portfolio
        - max_sharpe_portfolio: tangency portfolio
        - target_portfolio: if target_return_pct supplied, the min-variance
          portfolio achieving that annualised return
        - efficient_frontier: 25 points spanning the frontier
    """
    if not series or len(series) < 2:
        return {"error": "bad_input",
                "detail": "need at least 2 asset series"}

    assets, cov, mean_per_period = _sample_covariance(series)
    n = len(assets)
    if n < 2 or not cov:
        return {"error": "bad_input", "detail": "insufficient observations"}

    inv = _matrix_inverse(cov)
    if inv is None:
        return {"error": "singular_covariance",
                "detail": "covariance matrix not invertible (collinear assets?)"}

    ones = [1.0] * n
    Iv = _vec_matmul(inv, ones)
    Im = _vec_matmul(inv, mean_per_period)
    A = _dot(ones, Iv)        # 1ᵀ Σ⁻¹ 1
    B = _dot(mean_per_period, Iv)   # μᵀ Σ⁻¹ 1
    C = _dot(mean_per_period, Im)   # μᵀ Σ⁻¹ μ
    D = A * C - B * B

    # Annualisation scaling
    ann = periods_per_year

    def _portfolio_stats(w: list[float]) -> dict[str, Any]:
        mu_per_period = _dot(w, mean_per_period)
        var_per_period = _quad_form(w, cov)
        ann_ret = mu_per_period * ann * 100.0
        ann_vol = math.sqrt(var_per_period * ann) * 100.0
        sharpe = (ann_ret - risk_free_pct) / ann_vol if ann_vol > 0 else None
        return {
            "weights": {assets[i]: round(w[i], 6) for i in range(n)},
            "annualised_return_pct": ann_ret,
            "annualised_volatility_pct": ann_vol,
            "sharpe_ratio": sharpe,
        }

    # Min-variance portfolio: w = Σ⁻¹ 1 / A
    if abs(A) < 1e-14:
        return {"error": "degenerate", "detail": "A coefficient near zero"}
    w_min = [v / A for v in Iv]
    min_var = _portfolio_stats(w_min)

    # Tangency (max-Sharpe): w ∝ Σ⁻¹ (μ - rf/T·1)
    rf_per_period = (risk_free_pct / 100.0) / ann
    excess = [m - rf_per_period for m in mean_per_period]
    Iv_ex = _vec_matmul(inv, excess)
    s = sum(Iv_ex)
    if abs(s) < 1e-14:
        max_sharpe = None
    else:
        w_tan = [v / s for v in Iv_ex]
        max_sharpe = _portfolio_stats(w_tan)

    # Target return portfolio
    target_port: dict[str, Any] | None = None
    if target_return_pct is not None:
        target_per_period = (target_return_pct / 100.0) / ann
        if abs(D) > 1e-14:
            # Closed-form: w = (C·Σ⁻¹1 - B·Σ⁻¹μ)/D + r_p·(A·Σ⁻¹μ - B·Σ⁻¹1)/D
            g = [(C * Iv[i] - B * Im[i]) / D for i in range(n)]
            h = [(A * Im[i] - B * Iv[i]) / D for i in range(n)]
            w_t = [g[i] + target_per_period * h[i] for i in range(n)]
            target_port = _portfolio_stats(w_t)

    # Efficient frontier (25 points spanning min-var to ~2× max-Sharpe ret)
    frontier = []
    ret_min = (B / A) * ann * 100.0    # min-variance portfolio return
    if max_sharpe is not None:
        ret_max = max(ret_min + 5.0, max_sharpe["annualised_return_pct"] * 1.5)
    else:
        ret_max = ret_min + 50.0
    for i in range(25):
        target_ret = ret_min + (ret_max - ret_min) * i / 24
        target_per_period = (target_ret / 100.0) / ann
        if abs(D) < 1e-14:
            continue
        g = [(C * Iv[k] - B * Im[k]) / D for k in range(n)]
        h = [(A * Im[k] - B * Iv[k]) / D for k in range(n)]
        w_f = [g[k] + target_per_period * h[k] for k in range(n)]
        stats = _portfolio_stats(w_f)
        frontier.append({
            "target_return_pct": target_ret,
            "annualised_return_pct": stats["annualised_return_pct"],
            "annualised_volatility_pct": stats["annualised_volatility_pct"],
            "sharpe_ratio": stats["sharpe_ratio"],
        })

    return {
        "assets": assets,
        "sample_size": len(returns_from_closes(series[assets[0]])),
        "annualisation_factor": ann,
        "min_variance_portfolio": min_var,
        "max_sharpe_portfolio": max_sharpe,
        "target_portfolio": target_port,
        "efficient_frontier": frontier,
    }


__all__ = ["optimize_portfolio"]

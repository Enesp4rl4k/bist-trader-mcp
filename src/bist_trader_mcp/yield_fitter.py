"""Nelson-Siegel-Svensson yield curve fitter.

Fits the 4-parameter Nelson-Siegel or 6-parameter Nelson-Siegel-Svensson
model to a set of observed (maturity_years, yield_pct) pairs, then lets
you evaluate the smooth yield at any maturity.

NS form:
    y(τ) = β₀ + β₁·((1-e^(-τ/λ))/(τ/λ))
                + β₂·((1-e^(-τ/λ))/(τ/λ) - e^(-τ/λ))

NSS adds a second hump:
    + β₃·((1-e^(-τ/λ₂))/(τ/λ₂) - e^(-τ/λ₂))

Why bother: TR DİBS quotes come in spotty maturities; NSS gives a clean
smooth curve for ANY tenor (e.g. derive 3.5Y yield from observed 2Y/5Y).
Also a popular shape descriptor — β₀ = long-rate, β₁ = -slope, β₂ =
medium-curvature, β₃ = far-curvature.

Implementation: closed-form OLS for the linear betas at each (λ₁, λ₂),
then grid-search the λs. Faster than full nonlinear MLE; accurate enough
for trading-desk overlays.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass
class NSSParams:
    beta0: float
    beta1: float
    beta2: float
    beta3: float
    lambda1: float
    lambda2: float
    rmse: float


def _ns_factors(tau: float, lam: float) -> tuple[float, float]:
    """Loadings on β₁ and β₂ for a single (τ, λ)."""
    if tau <= 0:
        return 1.0, 0.0
    x = tau / lam
    if x < 1e-9:
        return 1.0, 0.0
    decay = math.exp(-x)
    slope = (1 - decay) / x
    curve = slope - decay
    return slope, curve


def _solve_ols(
    maturities: list[float],
    yields: list[float],
    lam1: float,
    lam2: float | None,
) -> tuple[list[float], float]:
    """Solve OLS for (β₀,β₁,β₂[,β₃]) at given λs. Returns (betas, rmse)."""
    n = len(maturities)
    p = 4 if lam2 is not None else 3
    # Build X (n × p) row by row
    X = [[0.0] * p for _ in range(n)]
    for i, tau in enumerate(maturities):
        X[i][0] = 1.0
        s1, c1 = _ns_factors(tau, lam1)
        X[i][1] = s1
        X[i][2] = c1
        if lam2 is not None:
            _, c2 = _ns_factors(tau, lam2)
            X[i][3] = c2

    # Normal equations: (XᵀX) β = Xᵀ y
    XtX = [[0.0] * p for _ in range(p)]
    Xty = [0.0] * p
    for i in range(n):
        for j in range(p):
            for k in range(p):
                XtX[j][k] += X[i][j] * X[i][k]
            Xty[j] += X[i][j] * yields[i]

    betas = _solve_linear(XtX, Xty)
    if betas is None:
        return [], float("inf")

    # RMSE
    sse = 0.0
    for i in range(n):
        pred = sum(X[i][j] * betas[j] for j in range(p))
        sse += (pred - yields[i]) ** 2
    rmse = math.sqrt(sse / n) if n else float("inf")
    return betas, rmse


def _solve_linear(A: list[list[float]], b: list[float]) -> list[float] | None:
    """Gaussian elimination for small dense systems."""
    n = len(A)
    # Augment
    M = [row[:] + [b[i]] for i, row in enumerate(A)]
    for i in range(n):
        # Partial pivot
        piv = max(range(i, n), key=lambda r: abs(M[r][i]))
        if abs(M[piv][i]) < 1e-14:
            return None
        M[i], M[piv] = M[piv], M[i]
        # Eliminate
        for r in range(i + 1, n):
            factor = M[r][i] / M[i][i]
            for c in range(i, n + 1):
                M[r][c] -= factor * M[i][c]
    # Back-substitute
    x = [0.0] * n
    for i in range(n - 1, -1, -1):
        s = M[i][n] - sum(M[i][j] * x[j] for j in range(i + 1, n))
        x[i] = s / M[i][i]
    return x


def fit_nelson_siegel(
    maturities_years: list[float],
    yields_pct: list[float],
    use_svensson: bool = True,
    lambda_grid_steps: int = 20,
) -> NSSParams:
    """Fit NS (3-factor) or NSS (4-factor) to the term structure.

    Args:
        maturities_years: list of τ (years) for each observed yield.
        yields_pct: matching yields in percent.
        use_svensson: True for NSS (4 betas + 2 lambdas), False for NS.
        lambda_grid_steps: search resolution for λs (default 20).

    Returns NSSParams with the best fit and RMSE in percent.
    """
    if len(maturities_years) != len(yields_pct):
        raise ValueError("maturities and yields must have same length")
    if len(maturities_years) < 3:
        raise ValueError("need at least 3 observed yields")

    # Search λ over [0.5, 8] (years) — standard NSS range
    lambda_lo, lambda_hi = 0.5, 8.0
    step = (lambda_hi - lambda_lo) / (lambda_grid_steps - 1)
    lambdas = [lambda_lo + i * step for i in range(lambda_grid_steps)]

    best = NSSParams(beta0=0, beta1=0, beta2=0, beta3=0,
                     lambda1=2.0, lambda2=5.0, rmse=float("inf"))

    if not use_svensson:
        for lam in lambdas:
            betas, rmse = _solve_ols(maturities_years, yields_pct, lam, None)
            if rmse < best.rmse and len(betas) == 3:
                best = NSSParams(beta0=betas[0], beta1=betas[1], beta2=betas[2],
                                  beta3=0.0, lambda1=lam, lambda2=0.0, rmse=rmse)
        return best

    for lam1 in lambdas:
        for lam2 in lambdas:
            if lam2 <= lam1:   # require λ₂ > λ₁ to identify the second hump
                continue
            betas, rmse = _solve_ols(maturities_years, yields_pct, lam1, lam2)
            if rmse < best.rmse and len(betas) == 4:
                best = NSSParams(beta0=betas[0], beta1=betas[1], beta2=betas[2],
                                  beta3=betas[3], lambda1=lam1, lambda2=lam2,
                                  rmse=rmse)
    return best


def evaluate_curve(params: NSSParams, tau: float) -> float:
    """Evaluate fitted NSS yield (in %) at maturity τ years."""
    s1, c1 = _ns_factors(tau, params.lambda1)
    y = params.beta0 + params.beta1 * s1 + params.beta2 * c1
    if params.beta3 != 0 and params.lambda2 > 0:
        _, c2 = _ns_factors(tau, params.lambda2)
        y += params.beta3 * c2
    return y


def evaluate_curve_grid(
    params: NSSParams,
    tenors_years: list[float],
) -> list[dict[str, float]]:
    """Evaluate at a list of tenors for charting/serving."""
    return [
        {"tenor_years": t, "yield_pct": evaluate_curve(params, t)}
        for t in tenors_years
    ]


__all__ = [
    "NSSParams",
    "fit_nelson_siegel",
    "evaluate_curve",
    "evaluate_curve_grid",
]

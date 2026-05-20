"""Volatility forecasting — EWMA + GARCH(1,1) lite.

Pure math on a returns series. Two estimators:

- EWMA (RiskMetrics convention): σ²_t = λ·σ²_{t-1} + (1-λ)·r²_{t-1}
  with λ=0.94 for daily data. Captures vol clustering with minimal
  state — used widely as a baseline.

- GARCH(1,1): σ²_t = ω + α·r²_{t-1} + β·σ²_{t-1}
  fit by simple grid search over (ω,α,β) maximising Gaussian log-
  likelihood under the constraint α+β < 1. Not as accurate as a
  full MLE but close enough for risk overlays and IV/RV comparison.

Both return annualised forecast vol in % (252 trading days unless
overridden — pass 365 for crypto).
"""

from __future__ import annotations

import math
from dataclasses import dataclass


def ewma_volatility(
    returns: list[float],
    decay: float = 0.94,
    annualise_days: int = 252,
) -> dict[str, float | list[float] | None]:
    """RiskMetrics EWMA volatility forecast.

    Args:
        returns: log returns (decimal). Use returns_from_closes(closes, 'log').
        decay: λ — RiskMetrics default 0.94 for daily.
        annualise_days: 252 equities, 365 crypto.

    Returns dict with `current_vol_pct` (annualised), `vol_path_pct` (full
    series for charting), and `next_period_forecast_pct`.
    """
    if not returns:
        return {"current_vol_pct": None, "vol_path_pct": [],
                "next_period_forecast_pct": None}
    if not 0 < decay < 1:
        raise ValueError("decay must be in (0,1)")
    n = len(returns)
    if n < 2:
        return {"current_vol_pct": None, "vol_path_pct": [],
                "next_period_forecast_pct": None}

    # Seed σ² with sample variance of first 10% of data (min 10 points)
    seed_n = max(10, n // 10)
    seed_mean = sum(returns[:seed_n]) / seed_n
    seed_var = sum((r - seed_mean) ** 2 for r in returns[:seed_n]) / seed_n
    if seed_var <= 0:
        seed_var = 1e-8

    var_path: list[float] = [seed_var]
    sig = seed_var
    for t in range(1, n):
        sig = decay * sig + (1 - decay) * returns[t - 1] ** 2
        var_path.append(sig)

    # Next-period forecast uses returns[n-1]
    next_var = decay * sig + (1 - decay) * returns[n - 1] ** 2

    factor = math.sqrt(annualise_days) * 100.0
    return {
        "current_vol_pct": math.sqrt(sig) * factor,
        "vol_path_pct": [math.sqrt(v) * factor for v in var_path],
        "next_period_forecast_pct": math.sqrt(next_var) * factor,
        "decay": decay,
        "n": n,
    }


@dataclass
class GarchParams:
    omega: float
    alpha: float
    beta: float
    log_likelihood: float


def _garch_log_lik(
    returns: list[float],
    omega: float,
    alpha: float,
    beta: float,
) -> float:
    """Gaussian log-likelihood of GARCH(1,1) on `returns`."""
    if omega <= 0 or alpha < 0 or beta < 0 or (alpha + beta) >= 0.999:
        return -1e18
    n = len(returns)
    if n < 5:
        return -1e18
    # Initial variance: sample
    mean = sum(returns) / n
    sig2 = max(sum((r - mean) ** 2 for r in returns) / n, 1e-12)
    ll = 0.0
    for t in range(n):
        if sig2 <= 0:
            return -1e18
        ll += -0.5 * (math.log(2 * math.pi) + math.log(sig2) +
                       returns[t] ** 2 / sig2)
        sig2 = omega + alpha * returns[t] ** 2 + beta * sig2
    return ll


def fit_garch_11(
    returns: list[float],
    grid_steps: int = 8,
) -> GarchParams:
    """Coarse grid search fit of GARCH(1,1) — not MLE-grade but fast.

    Args:
        returns: log returns.
        grid_steps: number of points per axis (default 8). Total trials
            ≈ grid_steps³ — keep small.
    """
    if len(returns) < 30:
        raise ValueError("need at least 30 return observations")

    # Sensible search ranges for daily financial returns
    omega_grid = [10 ** (e / grid_steps * 4 - 8) for e in range(grid_steps)]
    alpha_grid = [0.02 + (i / (grid_steps - 1)) * 0.20 for i in range(grid_steps)]
    beta_grid = [0.70 + (i / (grid_steps - 1)) * 0.25 for i in range(grid_steps)]

    best = GarchParams(omega=1e-6, alpha=0.1, beta=0.85,
                        log_likelihood=-1e18)
    for w in omega_grid:
        for a in alpha_grid:
            for b in beta_grid:
                if a + b >= 0.999:
                    continue
                ll = _garch_log_lik(returns, w, a, b)
                if ll > best.log_likelihood:
                    best = GarchParams(omega=w, alpha=a, beta=b, log_likelihood=ll)
    return best


def garch_forecast(
    returns: list[float],
    params: GarchParams | None = None,
    horizon_days: int = 20,
    annualise_days: int = 252,
) -> dict[str, list[float] | float | None]:
    """Run GARCH(1,1) forward `horizon_days` and report annualised vol path.

    Args:
        returns: log returns.
        params: fitted params (else fit_garch_11 is called).
        horizon_days: forecast horizon in trading days.
        annualise_days: 252 equities, 365 crypto.
    """
    if not returns:
        return {"forecast_path_pct": [], "stationary_vol_pct": None,
                "h1_forecast_pct": None}

    p = params or fit_garch_11(returns)
    n = len(returns)
    # Current conditional variance via running update
    mean = sum(returns) / n
    sig2 = max(sum((r - mean) ** 2 for r in returns) / n, 1e-12)
    for t in range(n):
        sig2 = p.omega + p.alpha * returns[t] ** 2 + p.beta * sig2

    # Forward path under E[r²] = σ²
    out: list[float] = []
    factor = math.sqrt(annualise_days) * 100.0
    cur = sig2
    for _ in range(horizon_days):
        out.append(math.sqrt(cur) * factor)
        # h+1: σ²_{t+1} = ω + (α+β)·σ²_t
        cur = p.omega + (p.alpha + p.beta) * cur

    stationary = (p.omega / (1 - p.alpha - p.beta)
                   if (p.alpha + p.beta) < 0.999 else None)
    stationary_pct = (math.sqrt(stationary) * factor
                       if stationary is not None else None)

    return {
        "forecast_path_pct": out,
        "h1_forecast_pct": out[0] if out else None,
        "stationary_vol_pct": stationary_pct,
        "params": p.__dict__,
        "horizon_days": horizon_days,
    }


__all__ = [
    "ewma_volatility",
    "fit_garch_11",
    "garch_forecast",
    "GarchParams",
]

"""Cross-sectional factor ranking — the quant leg of the hedge-fund engine.

**Faz C** of ``docs/HEDGE_FUND_GRADE_PLAN.md``: take per-ticker metrics across the
whole universe and rank them the way a systematic equity fund does — z-score each
factor cross-sectionally (optionally sector-neutral), winsorize outliers, combine
into a weighted composite, and sort. This is what turns single-name dossiers into
a ranked buy/sell list and a screen.

Pure math (no network): feed records assembled from ``fundamental_statements`` +
``valuation`` + simple price stats (or the point-in-time ``PanelStore``). Each
record is ``{"ticker": str, "sector": str|None, **factor_values}``.

Factor directions are explicit: ``"high"`` means a larger raw value is better
(ROE, FCF yield, momentum); ``"low"`` means smaller is better (P/E, net-debt/EBITDA,
volatility) and is sign-flipped before combining.
"""

from __future__ import annotations

import math
from typing import Any

# Sensible default factor set + directions + weights for a BIST equity screen.
DEFAULT_FACTORS: dict[str, dict[str, Any]] = {
    "fcf_yield": {"direction": "high", "weight": 1.0, "group": "value"},
    "earnings_yield": {"direction": "high", "weight": 1.0, "group": "value"},
    "roe": {"direction": "high", "weight": 1.0, "group": "quality"},
    "roic": {"direction": "high", "weight": 1.0, "group": "quality"},
    "piotroski": {"direction": "high", "weight": 0.5, "group": "quality"},
    "momentum_6m": {"direction": "high", "weight": 1.0, "group": "momentum"},
    "net_debt_to_ebitda": {"direction": "low", "weight": 0.5, "group": "safety"},
    "volatility": {"direction": "low", "weight": 0.5, "group": "low_vol"},
}


def _winsorize(values: list[float], limit: float = 3.0) -> list[float]:
    return [max(-limit, min(limit, v)) for v in values]


def _zscore_group(records: list[dict[str, Any]], factor: str) -> dict[int, float | None]:
    """Cross-sectional z-scores for one factor over the given records (by id)."""
    present = [(id(r), r.get(factor)) for r in records]
    vals = [v for _, v in present if isinstance(v, (int, float))]
    out: dict[int, float | None] = {rid: None for rid, _ in present}
    if len(vals) < 2:
        return out
    mean = sum(vals) / len(vals)
    var = sum((v - mean) ** 2 for v in vals) / len(vals)
    std = math.sqrt(var)
    if std == 0:
        for rid, v in present:
            out[rid] = 0.0 if isinstance(v, (int, float)) else None
        return out
    for rid, v in present:
        out[rid] = (v - mean) / std if isinstance(v, (int, float)) else None
    return out


def rank_universe(
    records: list[dict[str, Any]],
    *,
    factors: dict[str, dict[str, Any]] | None = None,
    sector_neutral: bool = False,
    top: int | None = None,
) -> dict[str, Any]:
    """Rank a universe by a weighted, winsorized, cross-sectional factor composite.

    Returns each ticker's composite z-score, percentile and per-factor z-scores,
    sorted best-first. With ``sector_neutral=True`` factor z-scores are computed
    within each sector (removes sector tilts so you rank stock-vs-peers).
    """
    factors = factors or DEFAULT_FACTORS
    if not records:
        return {"source": "bist-trader-mcp — universe_ranking.rank_universe",
                "count": 0, "ranking": []}

    # Group membership for sector-neutral mode.
    if sector_neutral:
        groups: dict[str, list[dict[str, Any]]] = {}
        for r in records:
            groups.setdefault(r.get("sector") or "_none", []).append(r)
    else:
        groups = {"_all": records}

    # factor -> {id(record): z}
    z_by_factor: dict[str, dict[int, float | None]] = {}
    for f in factors:
        merged: dict[int, float | None] = {}
        for grp in groups.values():
            merged.update(_zscore_group(grp, f))
        z_by_factor[f] = merged

    ranking: list[dict[str, Any]] = []
    for r in records:
        rid = id(r)
        composite = 0.0
        weight_used = 0.0
        per_factor: dict[str, float] = {}
        for f, cfg in factors.items():
            z = z_by_factor[f].get(rid)
            if z is None:
                continue
            signed = z if cfg.get("direction", "high") == "high" else -z
            signed = max(-3.0, min(3.0, signed))  # winsorize
            w = float(cfg.get("weight", 1.0))
            composite += signed * w
            weight_used += w
            per_factor[f] = round(signed, 3)
        score = composite / weight_used if weight_used > 0 else None
        ranking.append({
            "ticker": r.get("ticker"),
            "sector": r.get("sector"),
            "composite_z": None if score is None else round(score, 4),
            "factors_used": len(per_factor),
            "factor_z": per_factor,
        })

    rated = [x for x in ranking if x["composite_z"] is not None]
    unrated = [x for x in ranking if x["composite_z"] is None]
    rated.sort(key=lambda x: x["composite_z"], reverse=True)
    n = len(rated)
    for i, x in enumerate(rated):
        x["rank"] = i + 1
        x["percentile"] = round(100.0 * (n - i) / n, 1) if n else None

    ordered = rated + unrated
    if top is not None:
        ordered = ordered[:top]
    return {
        "source": "bist-trader-mcp — universe_ranking.rank_universe",
        "count": len(records),
        "rated": n,
        "sector_neutral": sector_neutral,
        "factors": list(factors.keys()),
        "ranking": ordered,
    }


def screen_universe(
    records: list[dict[str, Any]],
    criteria: list[dict[str, Any]],
) -> dict[str, Any]:
    """Rule-based screen. Each criterion: ``{"field", "op", "value"}`` with op in
    >, >=, <, <=, ==, !=. A record passes only if it satisfies all criteria (and
    has the field). Returns passing tickers with the matched fields.
    """
    ops = {
        ">": lambda a, b: a > b, ">=": lambda a, b: a >= b,
        "<": lambda a, b: a < b, "<=": lambda a, b: a <= b,
        "==": lambda a, b: a == b, "!=": lambda a, b: a != b,
    }
    passed: list[dict[str, Any]] = []
    for r in records:
        ok = True
        for c in criteria:
            fn = ops.get(c.get("op", ">"))
            val = r.get(c["field"])
            if fn is None or val is None or not fn(val, c["value"]):
                ok = False
                break
        if ok:
            passed.append({
                "ticker": r.get("ticker"),
                "sector": r.get("sector"),
                "matched": {c["field"]: r.get(c["field"]) for c in criteria},
            })
    return {
        "source": "bist-trader-mcp — universe_ranking.screen_universe",
        "screened": len(records),
        "passed": len(passed),
        "results": passed,
    }


def build_factor_record(
    *,
    ticker: str,
    sector: str | None = None,
    analysis: dict[str, Any] | None = None,
    valuation: dict[str, Any] | None = None,
    momentum_6m: float | None = None,
    volatility: float | None = None,
    earnings_yield: float | None = None,
) -> dict[str, Any]:
    """Assemble a ranking record from an ``analyze_financials`` result (+ extras).

    Pulls quality/safety factors out of the statement analysis and value factors
    from the (optional) DCF/valuation pass, so the same engine output that scores a
    single name feeds straight into the cross-sectional ranker.
    """
    rec: dict[str, Any] = {"ticker": ticker, "sector": sector}
    if analysis:
        ratios = analysis.get("ratios") or {}
        rec["roe"] = ratios.get("roe")
        rec["roic"] = ratios.get("roic")
        rec["fcf_yield"] = ratios.get("fcf_yield")
        rec["net_debt_to_ebitda"] = ratios.get("net_debt_to_ebitda")
        rec["piotroski"] = (analysis.get("piotroski") or {}).get("score")
        rec["selection_score"] = (analysis.get("selection") or {}).get("score")
    if valuation:
        rec["margin_of_safety"] = valuation.get("margin_of_safety")
    if momentum_6m is not None:
        rec["momentum_6m"] = momentum_6m
    if volatility is not None:
        rec["volatility"] = volatility
    if earnings_yield is not None:
        rec["earnings_yield"] = earnings_yield
    return rec


__all__ = [
    "rank_universe",
    "screen_universe",
    "build_factor_record",
    "DEFAULT_FACTORS",
]

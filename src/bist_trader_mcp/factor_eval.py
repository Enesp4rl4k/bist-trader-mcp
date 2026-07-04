"""Signal evaluation — does a higher score actually predict better returns?

**Faz B/D measurement** (``docs/HEDGE_FUND_GRADE_PLAN.md``): the harness that turns
"how accurate is this?" into numbers. Given scores (selection score, fusion score,
confidence…) paired with realised forward returns, it computes the rank
information coefficient (IC), quantile-bucket return spread and monotonicity, and —
for a panel of dates — the IC mean / IR / hit-rate a quant uses to judge a factor.

Pure math, no numpy/scipy, so it runs in CI. Pairs are evaluated **point-in-time
safe** by construction: the caller supplies the forward return that was realised
*after* the score was known (use ``PanelStore`` as-of reads to build them).
"""

from __future__ import annotations

import math
from typing import Any


def _ranks(values: list[float]) -> list[float]:
    """Average (fractional) ranks, ties shared — for Spearman."""
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1.0  # 1-based average rank
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    n = len(xs)
    if n < 2:
        return None
    mx = sum(xs) / n
    my = sum(ys) / n
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True))
    vx = sum((x - mx) ** 2 for x in xs)
    vy = sum((y - my) ** 2 for y in ys)
    if vx == 0 or vy == 0:
        return None
    return cov / math.sqrt(vx * vy)


def rank_ic(scores: list[float], forward_returns: list[float]) -> float | None:
    """Spearman rank correlation between scores and forward returns (the IC)."""
    pairs = [
        (s, r) for s, r in zip(scores, forward_returns, strict=True)
        if isinstance(s, (int, float)) and isinstance(r, (int, float))
    ]
    if len(pairs) < 3:
        return None
    s = [p[0] for p in pairs]
    r = [p[1] for p in pairs]
    ic = _pearson(_ranks(s), _ranks(r))
    return None if ic is None else round(ic, 4)


def quantile_spread(
    scores: list[float], forward_returns: list[float], *, n_quantiles: int = 5
) -> dict[str, Any]:
    """Bucket by score into quantiles; report mean forward return per bucket plus
    top-minus-bottom spread and whether bucket means rise monotonically."""
    pairs = sorted(
        ((s, r) for s, r in zip(scores, forward_returns, strict=True)
         if isinstance(s, (int, float)) and isinstance(r, (int, float))),
        key=lambda p: p[0],
    )
    n = len(pairs)
    if n < n_quantiles:
        return {"available": False, "reason": "not_enough_observations", "n": n}

    buckets: list[list[float]] = [[] for _ in range(n_quantiles)]
    for idx, (_s, r) in enumerate(pairs):
        q = min(idx * n_quantiles // n, n_quantiles - 1)
        buckets[q].append(r)
    means = [round(sum(b) / len(b), 6) if b else None for b in buckets]

    valid = [m for m in means if m is not None]
    monotonic = all(
        valid[i] <= valid[i + 1] for i in range(len(valid) - 1)
    ) if len(valid) >= 2 else False
    spread = None
    if means[0] is not None and means[-1] is not None:
        spread = round(means[-1] - means[0], 6)
    return {
        "available": True,
        "n": n,
        "n_quantiles": n_quantiles,
        "bucket_mean_returns": means,
        "bucket_sizes": [len(b) for b in buckets],
        "top_minus_bottom": spread,
        "monotonic_increasing": monotonic,
    }


def evaluate_signal(
    observations: list[dict[str, Any]],
    *,
    score_field: str = "score",
    return_field: str = "forward_return",
    n_quantiles: int = 5,
) -> dict[str, Any]:
    """Pooled evaluation of one signal: IC + quantile spread + hit rate.

    ``observations`` = list of {score_field, return_field}. Hit rate = share of
    observations where the score's sign matches the forward return's sign.
    """
    scores = [o.get(score_field) for o in observations]
    rets = [o.get(return_field) for o in observations]
    ic = rank_ic(scores, rets)
    spread = quantile_spread(scores, rets, n_quantiles=n_quantiles)

    hits = total = 0
    for s, r in zip(scores, rets, strict=True):
        if isinstance(s, (int, float)) and isinstance(r, (int, float)) and s != 0:
            total += 1
            if (s > 0) == (r > 0):
                hits += 1
    hit_rate = round(hits / total, 4) if total else None

    return {
        "source": "bist-trader-mcp — factor_eval.evaluate_signal",
        "n": len(observations),
        "rank_ic": ic,
        "hit_rate": hit_rate,
        "quantile": spread,
        "verdict": _verdict(ic, spread),
    }


def evaluate_cross_sectional(
    by_date: list[dict[str, Any]],
    *,
    score_field: str = "score",
    return_field: str = "forward_return",
) -> dict[str, Any]:
    """Per-date cross-sectional IC, averaged over dates — the quant standard.

    ``by_date`` = list of {date, records:[{score, forward_return}, ...]}. Returns
    IC mean, IC std, IR (mean/std), and the share of dates with positive IC.
    """
    ics: list[float] = []
    for day in by_date:
        recs = day.get("records") or []
        ic = rank_ic(
            [r.get(score_field) for r in recs],
            [r.get(return_field) for r in recs],
        )
        if ic is not None:
            ics.append(ic)
    if not ics:
        return {"available": False, "reason": "no_datable_ic", "dates": len(by_date)}
    mean = sum(ics) / len(ics)
    std = math.sqrt(sum((x - mean) ** 2 for x in ics) / len(ics)) if len(ics) > 1 else 0.0
    ir = round(mean / std, 4) if std > 0 else None
    pos = sum(1 for x in ics if x > 0) / len(ics)
    return {
        "source": "bist-trader-mcp — factor_eval.evaluate_cross_sectional",
        "dates_evaluated": len(ics),
        "ic_mean": round(mean, 4),
        "ic_std": round(std, 4),
        "ic_ir": ir,
        "positive_ic_share": round(pos, 4),
        "verdict": _ic_verdict(mean),
    }


def _ic_verdict(ic: float) -> str:
    a = abs(ic)
    if a >= 0.05:
        return "strong"
    if a >= 0.03:
        return "usable"
    if a >= 0.01:
        return "weak"
    return "noise"


def _verdict(ic: float | None, spread: dict[str, Any]) -> str:
    if ic is None:
        return "insufficient_data"
    base = _ic_verdict(ic)
    monotonic = spread.get("available") and spread.get("monotonic_increasing")
    if monotonic and base in ("usable", "strong"):
        return base + "_monotonic"
    return base


__all__ = [
    "rank_ic",
    "quantile_spread",
    "evaluate_signal",
    "evaluate_cross_sectional",
]

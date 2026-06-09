"""Elliott Wave — zigzag pivots, impulse/ABC hypotheses, fib levels.

Rule-based (not subjective LLM counts). Returns primary + alternate hypotheses
with scores and invalidation prices.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from .elliott_projections import attach_projection_to_hypothesis
from .price_action import SwingPoint, find_swings

WaveKind = Literal["impulse_bull", "impulse_bear", "abc_bull", "abc_bear", "unclear"]
Direction = Literal["long", "short", "neutral"]


@dataclass(frozen=True)
class Pivot:
    index: int
    price: float
    kind: Literal["high", "low"]


def _merge_alternating_pivots(
    swing_highs: list[SwingPoint],
    swing_lows: list[SwingPoint],
) -> list[Pivot]:
    """Time-ordered pivots; drop consecutive same-kind if less extreme."""
    merged: list[Pivot] = [
        *[Pivot(s.index, s.price, "high") for s in swing_highs],
        *[Pivot(s.index, s.price, "low") for s in swing_lows],
    ]
    merged.sort(key=lambda p: p.index)
    if not merged:
        return []

    out: list[Pivot] = [merged[0]]
    for p in merged[1:]:
        last = out[-1]
        if p.kind == last.kind:
            if p.kind == "high" and p.price >= last.price:
                out[-1] = p
            elif p.kind == "low" and p.price <= last.price:
                out[-1] = p
        else:
            out.append(p)
    return out


def build_zigzag_pivots(
    highs: list[float],
    lows: list[float],
    *,
    swing_lookback: int = 5,
) -> list[Pivot]:
    swing_highs, swing_lows = find_swings(highs, lows, lookback=swing_lookback)
    return _merge_alternating_pivots(swing_highs, swing_lows)


def _fib_ratio(a: float, b: float, c: float) -> float | None:
    """Retracement of move a→b at price c."""
    span = b - a
    if abs(span) < 1e-12:
        return None
    return abs(c - b) / abs(span)


def _score_impulse_bull(p: list[Pivot]) -> tuple[float, dict[str, Any]]:
    """Six pivots L0 H1 L2 H3 L4 H5 — bullish impulse labeling."""
    if len(p) < 6:
        return 0.0, {"error": "need_6_pivots"}
    seg = p[-6:]
    if not (
        seg[0].kind == "low"
        and seg[1].kind == "high"
        and seg[2].kind == "low"
        and seg[3].kind == "high"
        and seg[4].kind == "low"
        and seg[5].kind == "high"
    ):
        return 0.0, {"error": "pattern_not_LHLHLH"}

    l0, h1, l2, h3, l4, h5 = [x.price for x in seg]
    w1 = h1 - l0
    w2 = h1 - l2
    w3 = h3 - l2
    w4 = h3 - l4
    w5 = h5 - l4
    score = 50.0
    violations: list[str] = []

    if l2 <= l0:
        score -= 25
        violations.append("wave2_below_wave0")
    if w3 <= 0 or (w1 > 0 and w3 <= min(w1, w5) * 0.85):
        score -= 20
        violations.append("wave3_shortest_or_flat")
    if l4 <= h1:
        score -= 15
        violations.append("wave4_overlaps_wave1")
    if w5 <= 0:
        score -= 20
        violations.append("wave5_incomplete")

    retr2 = _fib_ratio(l0, h1, l2)
    retr4 = _fib_ratio(l2, h3, l4)
    fib_notes: dict[str, Any] = {}
    if retr2 is not None:
        fib_notes["wave2_retrace_of_w1"] = round(retr2, 3)
        if 0.382 <= retr2 <= 0.618:
            score += 8
    if retr4 is not None:
        fib_notes["wave4_retrace_of_w3"] = round(retr4, 3)
        if 0.236 <= retr4 <= 0.5:
            score += 5

    labels = ["(0)", "(1)", "(2)", "(3)", "(4)", "(5)"]
    points = [
        {"index": seg[i].index, "price": seg[i].price, "label": labels[i], "kind": seg[i].kind}
        for i in range(6)
    ]
    invalidation = l0
    target_ext = h5 + (h5 - l4) * 0.618 if w5 > 0 else h5

    detail: dict[str, Any] = {
        "kind": "impulse_bull",
        "direction": "long",
        "degree": "impulse",
        "labels": labels,
        "points": points,
        "violations": violations,
        "fib": fib_notes,
        "invalidation_price": round(invalidation, 8),
        "extension_target": round(target_ext, 8),
        "current_wave": "5_complete_or_extended" if w5 > 0 else "forming_5",
    }
    return min(100.0, max(0.0, score)), detail


def _score_impulse_bull_forming(p: list[Pivot]) -> tuple[float, dict[str, Any]]:
    """Five pivots (0)–(4) — wave 5 not yet confirmed; projection required."""
    if len(p) < 5:
        return 0.0, {"error": "need_5_pivots"}
    seg = p[-5:]
    if not (
        seg[0].kind == "low"
        and seg[1].kind == "high"
        and seg[2].kind == "low"
        and seg[3].kind == "high"
        and seg[4].kind == "low"
    ):
        return 0.0, {"error": "pattern_not_LHLHL"}

    l0, h1, l2, h3, l4 = [x.price for x in seg]
    w1 = h1 - l0
    w3 = h3 - l2
    score = 46.0
    if l2 <= l0:
        score -= 16
    if l4 <= h1:
        score -= 12
    if w3 <= 0 or (w1 > 0 and w3 < w1 * 0.9):
        score -= 10  # wave 3 should not be the weakest impulse leg
    retr2 = _fib_ratio(l0, h1, l2)
    if retr2 is not None and 0.382 <= retr2 <= 0.618:
        score += 6
    retr4 = _fib_ratio(l2, h3, l4)
    if retr4 is not None and 0.236 <= retr4 <= 0.5:
        score += 4
    points = [
        {"index": seg[i].index, "price": seg[i].price, "label": f"({i})", "kind": seg[i].kind}
        for i in range(5)
    ]
    detail = {
        "kind": "impulse_bull",
        "direction": "long",
        "degree": "impulse",
        "labels": ["(0)", "(1)", "(2)", "(3)", "(4)"],
        "points": points,
        "invalidation_price": round(l0, 8),
        "current_wave": "forming_5",
    }
    return min(100.0, max(0.0, score)), detail


def _score_impulse_bear_forming(p: list[Pivot]) -> tuple[float, dict[str, Any]]:
    if len(p) < 5:
        return 0.0, {"error": "need_5_pivots"}
    seg = p[-5:]
    if not (
        seg[0].kind == "high"
        and seg[1].kind == "low"
        and seg[2].kind == "high"
        and seg[3].kind == "low"
        and seg[4].kind == "high"
    ):
        return 0.0, {"error": "pattern_not_HLHLH"}

    h0, l1, h2, l3, h4 = [x.price for x in seg]
    w1 = h0 - l1
    w3 = h2 - l3
    score = 46.0
    if h2 >= h0:
        score -= 16
    if h4 >= l1:
        score -= 12
    if w3 <= 0 or (w1 > 0 and w3 < w1 * 0.9):
        score -= 10
    retr2 = _fib_ratio(h0, l1, h2)
    if retr2 is not None and 0.382 <= retr2 <= 0.618:
        score += 6
    retr4 = _fib_ratio(h2, l3, h4)
    if retr4 is not None and 0.236 <= retr4 <= 0.5:
        score += 4
    points = [
        {"index": seg[i].index, "price": seg[i].price, "label": f"({i})", "kind": seg[i].kind}
        for i in range(5)
    ]
    detail = {
        "kind": "impulse_bear",
        "direction": "short",
        "degree": "impulse",
        "labels": ["(0)", "(1)", "(2)", "(3)", "(4)"],
        "points": points,
        "invalidation_price": round(h0, 8),
        "current_wave": "forming_5",
    }
    return min(100.0, max(0.0, score)), detail


def _score_impulse_bear(p: list[Pivot]) -> tuple[float, dict[str, Any]]:
    if len(p) < 6:
        return 0.0, {"error": "need_6_pivots"}
    seg = p[-6:]
    if not (
        seg[0].kind == "high"
        and seg[1].kind == "low"
        and seg[2].kind == "high"
        and seg[3].kind == "low"
        and seg[4].kind == "high"
        and seg[5].kind == "low"
    ):
        return 0.0, {"error": "pattern_not_HLHLHL"}

    h0, l1, h2, l3, h4, l5_end = [x.price for x in seg]
    w1 = h0 - l1
    w2 = h2 - l1
    w3 = h2 - l3
    w4 = h4 - l3
    w5 = h4 - l5_end
    score = 50.0
    violations: list[str] = []

    if h2 >= h0:
        score -= 25
        violations.append("wave2_above_wave0")
    if w3 <= 0 or (w1 > 0 and w3 <= min(w1, w5) * 0.85):
        score -= 20
        violations.append("wave3_shortest_or_flat")
    if h4 >= l1:
        score -= 15
        violations.append("wave4_overlaps_wave1")
    if w5 <= 0:
        score -= 20
        violations.append("wave5_incomplete")

    retr2 = _fib_ratio(h0, l1, h2)
    retr4 = _fib_ratio(h2, l3, h4)
    fib_notes: dict[str, Any] = {}
    if retr2 is not None:
        fib_notes["wave2_retrace_of_w1"] = round(retr2, 3)
        if 0.382 <= retr2 <= 0.618:
            score += 8
    if retr4 is not None:
        fib_notes["wave4_retrace_of_w3"] = round(retr4, 3)
        if 0.236 <= retr4 <= 0.5:
            score += 5

    labels = ["(0)", "(1)", "(2)", "(3)", "(4)", "(5)"]
    points = [
        {"index": seg[i].index, "price": seg[i].price, "label": labels[i], "kind": seg[i].kind}
        for i in range(6)
    ]
    invalidation = h0
    target_ext = l5_end - (h4 - l5_end) * 0.618 if w5 > 0 else l5_end

    detail = {
        "kind": "impulse_bear",
        "direction": "short",
        "degree": "impulse",
        "labels": labels,
        "points": points,
        "violations": violations,
        "fib": fib_notes,
        "invalidation_price": round(invalidation, 8),
        "extension_target": round(target_ext, 8),
        "current_wave": "5_complete_or_extended" if w5 > 0 else "forming_5",
    }
    return min(100.0, max(0.0, score)), detail


def _score_abc_bull(p: list[Pivot]) -> tuple[float, dict[str, Any]]:
    """Corrective ABC after bull — last 4 pivots H A L B H C (simplified H-L-H-L)."""
    if len(p) < 4:
        return 0.0, {"error": "need_4_pivots"}
    seg = p[-4:]
    # Bearish correction in bull trend: high, low, high, low (A down, B up, C down)
    if not (seg[0].kind == "high" and seg[1].kind == "low" and seg[2].kind == "high" and seg[3].kind == "low"):
        return 0.0, {"error": "pattern_not_correction_HLHL"}

    a0, b1, a2, c3 = [x.price for x in seg]
    leg_a = abs(b1 - a0)
    if leg_a < 1e-9:
        return 0.0, {"error": "flat_wave_a"}
    retrace_b = abs(a2 - b1) / leg_a
    score = 28.0
    if c3 < b1:
        score += 12
    if a2 < a0:
        score += 8
    if 0.382 <= retrace_b <= 0.786:
        score += 15
    else:
        score -= 18
    if abs(c3 - b1) / leg_a < 0.5:
        score -= 12
    labels = ["start", "A", "B", "C"]
    points = [
        {"index": seg[i].index, "price": seg[i].price, "label": labels[i], "kind": seg[i].kind}
        for i in range(4)
    ]
    detail = {
        "kind": "abc_bull",
        "direction": "long",
        "degree": "correction",
        "labels": ["A", "B", "C"],
        "points": points,
        "invalidation_price": round(a0, 8),
        "current_wave": "abc_complete_candidate",
        "note": "Corrective ABC — long if C holds above A start invalidation",
    }
    return min(100.0, max(0.0, score)), detail


def _score_abc_bear(p: list[Pivot]) -> tuple[float, dict[str, Any]]:
    if len(p) < 4:
        return 0.0, {"error": "need_4_pivots"}
    seg = p[-4:]
    if not (seg[0].kind == "low" and seg[1].kind == "high" and seg[2].kind == "low" and seg[3].kind == "high"):
        return 0.0, {"error": "pattern_not_correction_LHLH"}

    a0, b1, a2, c3 = [x.price for x in seg]
    leg_a = abs(b1 - a0)
    if leg_a < 1e-9:
        return 0.0, {"error": "flat_wave_a"}
    retrace_b = abs(a2 - b1) / leg_a
    score = 28.0
    if c3 > b1:
        score += 12
    if a2 > a0:
        score += 8
    if 0.382 <= retrace_b <= 0.786:
        score += 15
    else:
        score -= 18
    if abs(c3 - b1) / leg_a < 0.5:
        score -= 12
    labels = ["start", "A", "B", "C"]
    points = [
        {"index": seg[i].index, "price": seg[i].price, "label": labels[i], "kind": seg[i].kind}
        for i in range(4)
    ]
    detail = {
        "kind": "abc_bear",
        "direction": "short",
        "degree": "correction",
        "labels": ["A", "B", "C"],
        "points": points,
        "invalidation_price": round(a0, 8),
        "current_wave": "abc_complete_candidate",
    }
    return min(100.0, max(0.0, score)), detail


def _select_primary_alternate_hypotheses(
    candidates: list[dict[str, Any]],
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Prefer HTF impulse counts over loose ABC fits when scores are close."""
    if not candidates:
        return None, None
    impulses = [c for c in candidates if c.get("degree") == "impulse"]
    corrections = [c for c in candidates if c.get("degree") == "correction"]
    if impulses:
        best_imp = max(impulses, key=lambda x: float(x.get("score") or 0))
        if float(best_imp.get("score") or 0) >= 42:
            alternate = (
                max(corrections, key=lambda x: float(x.get("score") or 0))
                if corrections
                else None
            )
            return best_imp, alternate
    return candidates[0], candidates[1] if len(candidates) > 1 else None


def analyze_elliott_wave(
    closes: list[float],
    highs: list[float],
    lows: list[float],
    *,
    times: list[int] | None = None,
    swing_lookback: int = 5,
) -> dict[str, Any]:
    """Score EW hypotheses on one timeframe (typically HTF)."""
    if len(closes) < swing_lookback * 2 + 1:
        return {
            "error": "insufficient_bars",
            "detail": f"need at least {swing_lookback * 2 + 1} bars",
        }

    pivots = build_zigzag_pivots(highs, lows, swing_lookback=swing_lookback)
    last_bar_index = len(closes) - 1
    candidates: list[dict[str, Any]] = []

    for scorer, name in (
        (_score_impulse_bull, "impulse_bull"),
        (_score_impulse_bear, "impulse_bear"),
        (_score_impulse_bull_forming, "impulse_bull_forming"),
        (_score_impulse_bear_forming, "impulse_bear_forming"),
        (_score_abc_bull, "abc_bull"),
        (_score_abc_bear, "abc_bear"),
    ):
        score, detail = scorer(pivots)
        if score > 0 and "error" not in detail:
            kind = name.replace("_forming", "")
            if kind.startswith("impulse"):
                seg = pivots[-6:] if len(pivots) >= 6 else pivots[-5:]
            else:
                seg = pivots[-4:]
            detail = attach_projection_to_hypothesis(
                detail,
                seg,
                kind=kind,
                bars_ahead=15,
                last_bar_index=last_bar_index,
                times=times,
            )
            row = {"name": name, "score": round(score, 2), **detail}
            for pt_list in (row.get("points"), row.get("projected_points")):
                if not pt_list or not times:
                    continue
                for pt in pt_list:
                    idx = pt.get("index")
                    if idx is not None and 0 <= int(idx) < len(times):
                        pt["time"] = int(times[int(idx)])
            candidates.append(row)

    candidates.sort(key=lambda x: -x["score"])
    primary, alternate = _select_primary_alternate_hypotheses(candidates)

    from .elliott_detail import build_elliott_detail_panel

    detail_panel = build_elliott_detail_panel(
        primary=primary,
        alternate=alternate,
        hypotheses=candidates,
        current_price=closes[-1],
    )
    if primary:
        primary = detail_panel.get("primary") or primary
    if alternate:
        alternate = detail_panel.get("alternate") or alternate

    bias: Direction = "neutral"
    if primary:
        d = primary.get("direction")
        if d in ("long", "short"):
            bias = d

    return {
        "source": "bist-trader-mcp — elliott_wave.analyze_elliott_wave",
        "bars_analyzed": len(closes),
        "current_price": closes[-1],
        "pivot_count": len(pivots),
        "pivots": [
            {"index": p.index, "price": p.price, "kind": p.kind}
            for p in pivots[-12:]
        ],
        "hypotheses": candidates,
        "primary": primary,
        "alternate": alternate,
        "bias": bias,
        "invalidation_price": primary.get("invalidation_price") if primary else None,
        "forecast": primary.get("forecast") if primary else None,
        "forecast_summary": primary.get("forecast_summary") if primary else None,
        "target_scenarios": primary.get("target_scenarios") if primary else None,
        "detail": detail_panel,
        "report_tr": detail_panel.get("report_tr"),
        "rule_checklist": (primary or {}).get("rule_checklist"),
        "wave_traits": (primary or {}).get("wave_traits"),
        "fib_grades": (primary or {}).get("fib_grades"),
        "channel": (primary or {}).get("channel"),
        "notes": (
            "Scores are rule-based; alternate count may be equally valid. "
            "Use with PA/MTF — never trade on EW alone. See detail.report_tr."
        ),
    }


__all__ = [
    "Pivot",
    "build_zigzag_pivots",
    "analyze_elliott_wave",
]

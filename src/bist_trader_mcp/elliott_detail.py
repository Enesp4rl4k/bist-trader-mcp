"""Elliott Wave detail panel — rules, fib grades, wave traits, TR narrative."""

from __future__ import annotations

from typing import Any


def _impulse_metrics_bull(seg_prices: list[float]) -> dict[str, float] | None:
    if len(seg_prices) < 5:
        return None
    l0, h1, l2, h3, l4 = seg_prices[:5]
    w1, w3, w5 = h1 - l0, h3 - l2, 0.0
    if len(seg_prices) >= 6:
        w5 = seg_prices[5] - l4
    return {"w1": w1, "w2": h1 - l2, "w3": w3, "w4": h3 - l4, "w5": w5, "l0": l0, "h1": h1, "l2": l2, "h3": h3, "l4": l4}


def _impulse_metrics_bear(seg_prices: list[float]) -> dict[str, float] | None:
    if len(seg_prices) < 5:
        return None
    h0, l1, h2, l3, h4 = seg_prices[:5]
    w1, w3, w5 = h0 - l1, h2 - l3, 0.0
    if len(seg_prices) >= 6:
        w5 = h4 - seg_prices[5]
    return {"w1": w1, "w2": h2 - l1, "w3": w3, "w4": h4 - l3, "w5": w5, "h0": h0, "l1": l1, "h2": h2, "l3": l3, "h4": h4}


def build_impulse_rule_checklist(
    hypothesis: dict[str, Any],
) -> list[dict[str, Any]]:
    """Classic impulse rules with pass/fail for the active count."""
    kind = str(hypothesis.get("kind") or "")
    if hypothesis.get("degree") != "impulse" and not kind.startswith("impulse_"):
        return []
    points = hypothesis.get("points") or []
    prices = [float(p["price"]) for p in points]
    bull = kind.startswith("impulse_bull")
    m = _impulse_metrics_bull(prices) if bull else _impulse_metrics_bear(prices)
    if not m:
        return []

    w1, w2, w3, w4, w5 = m["w1"], m["w2"], m["w3"], m["w4"], m["w5"]
    checks: list[dict[str, Any]] = []

    if bull:
        checks.append({
            "rule": "wave2_not_below_start",
            "pass": m["l2"] > m["l0"],
            "detail": f"(2) {m['l2']:.4f} vs (0) {m['l0']:.4f}",
        })
        checks.append({
            "rule": "wave3_not_shortest",
            "pass": w3 > 0 and (w1 <= 0 or w3 > min(w1, w5 or w1) * 0.85),
            "detail": f"W3={w3:.4f} vs W1={w1:.4f} W5={w5:.4f}",
        })
        checks.append({
            "rule": "wave4_not_into_wave1",
            "pass": m["l4"] > m["h1"],
            "detail": f"(4) low above (1) high {m['h1']:.4f}",
        })
    else:
        checks.append({
            "rule": "wave2_not_above_start",
            "pass": m["h2"] < m["h0"],
            "detail": f"(2) {m['h2']:.4f} vs (0) {m['h0']:.4f}",
        })
        checks.append({
            "rule": "wave3_not_shortest",
            "pass": w3 > 0 and (w1 <= 0 or w3 > min(w1, w5 or w1) * 0.85),
            "detail": f"W3={w3:.4f}",
        })
        checks.append({
            "rule": "wave4_not_into_wave1",
            "pass": m["h4"] < m["l1"],
            "detail": "(4) high below (1) low",
        })

    if w5 > 0:
        checks.append({
            "rule": "wave5_positive",
            "pass": True,
            "detail": f"W5 length {w5:.4f}",
        })
    return checks


def classify_correction_subtype(hypothesis: dict[str, Any]) -> str:
    fib = hypothesis.get("fib") or {}
    for key, val in fib.items():
        if "retrace" in key and isinstance(val, (int, float)):
            r = float(val)
            if r >= 0.9:
                return "flat"
            if r >= 0.786:
                return "deep_zigzag"
            if r >= 0.382:
                return "zigzag"
            return "shallow"
    points = hypothesis.get("points") or []
    if len(points) >= 3:
        a0, b1, a2 = [float(points[i]["price"]) for i in range(3)]
        leg = abs(b1 - a0)
        if leg > 0:
            r = abs(a2 - b1) / leg
            if r >= 0.9:
                return "flat"
            if r >= 0.382:
                return "zigzag"
            return "shallow"
    return "unclear"


def detect_wave_traits(hypothesis: dict[str, Any]) -> dict[str, Any]:
    """Truncation, extension, forming state."""
    kind = str(hypothesis.get("kind") or "")
    name = str(hypothesis.get("name", kind))
    points = hypothesis.get("points") or []
    prices = [float(p["price"]) for p in points]
    traits: dict[str, Any] = {
        "current_wave": hypothesis.get("current_wave"),
        "forming": "forming" in name,
    }
    if kind.startswith("impulse_"):
        bull = kind.startswith("impulse_bull")
        m = _impulse_metrics_bull(prices) if bull else _impulse_metrics_bear(prices)
    else:
        m = None
    if m:
        w1, w3, w5 = m["w1"], m["w3"], m["w5"]
        if w1 > 0 and w5 > 0:
            traits["wave5_vs_wave1"] = round(w5 / w1, 3)
            traits["truncated_wave5"] = w5 < w1 * 0.618
            traits["extended_wave5"] = w5 > w1 * 1.618
        if w1 > 0 and w3 > 0:
            traits["wave3_vs_wave1"] = round(w3 / w1, 3)
            traits["extended_wave3"] = w3 > w1 * 1.618
        traits["wave3_longest_candidate"] = w3 > max(w1, w5 or 0) * 1.05 if w3 > 0 else False
    if kind.startswith("abc_") or hypothesis.get("degree") == "correction":
        traits["correction_subtype"] = classify_correction_subtype(hypothesis)
    return traits


def build_fib_grade_card(hypothesis: dict[str, Any]) -> dict[str, Any]:
    """Grade fib fit for impulse 2/4 or ABC B-wave."""
    fib = dict(hypothesis.get("fib") or {})
    grades: list[dict[str, Any]] = []
    r2 = fib.get("wave2_retrace_of_w1")
    if r2 is not None:
        ideal = 0.382 <= float(r2) <= 0.618
        grades.append({
            "wave": "2",
            "ratio": r2,
            "ideal_zone": "0.382–0.618 of W1",
            "grade": "A" if ideal else ("B" if 0.236 <= float(r2) <= 0.786 else "C"),
        })
    r4 = fib.get("wave4_retrace_of_w3")
    if r4 is not None:
        ideal = 0.236 <= float(r4) <= 0.5
        grades.append({
            "wave": "4",
            "ratio": r4,
            "ideal_zone": "0.236–0.50 of W3",
            "grade": "A" if ideal else ("B" if float(r4) <= 0.618 else "C"),
        })
    return {"ratios": fib, "grades": grades}


def build_wave_channel(
    hypothesis: dict[str, Any],
) -> dict[str, Any] | None:
    """Simple parallel channel from waves 2–4 (impulse bull/bear)."""
    points = hypothesis.get("points") or []
    if len(points) < 5:
        return None
    kind = str(hypothesis.get("kind") or "")
    if "impulse_bull" in kind:
        # baseline: line through (2) and (4) lows; parallel through (3) high
        p2, p3, p4 = points[2], points[3], points[4]
        if p2["kind"] != "low" or p4["kind"] != "low" or p3["kind"] != "high":
            return None
        slope = (p4["price"] - p2["price"]) / max(p4["index"] - p2["index"], 1)
        upper_at_end = p3["price"] + slope * (p4["index"] - p3["index"])
        return {
            "type": "bull_impulse_channel",
            "support_line": {"from": p2, "to": {"index": p4["index"], "price": p4["price"]}},
            "resistance_parallel": {"anchor": p3, "end_price": round(upper_at_end, 8)},
            "slope_per_bar": round(slope, 8),
        }
    if "impulse_bear" in kind:
        p2, p3, p4 = points[2], points[3], points[4]
        if p2["kind"] != "high" or p4["kind"] != "high" or p3["kind"] != "low":
            return None
        slope = (p4["price"] - p2["price"]) / max(p4["index"] - p2["index"], 1)
        lower_at_end = p3["price"] + slope * (p4["index"] - p3["index"])
        return {
            "type": "bear_impulse_channel",
            "resistance_line": {"from": p2, "to": {"index": p4["index"], "price": p4["price"]}},
            "support_parallel": {"anchor": p3, "end_price": round(lower_at_end, 8)},
            "slope_per_bar": round(slope, 8),
        }
    return None


def build_elliott_report_tr(
    *,
    primary: dict[str, Any] | None,
    alternate: dict[str, Any] | None,
    current_price: float,
) -> str:
    """Multi-line Turkish Elliott brief for MCP / user."""
    if not primary:
        return "Elliott: uygun sayım bulunamadı — pivot yetersiz veya skor düşük."
    lines = [
        f"Elliott birincil: {primary.get('kind')} skor {primary.get('score')} "
        f"| dalga {primary.get('current_wave', '—')} | yön {primary.get('direction')}.",
    ]
    fc = primary.get("forecast_summary") or (primary.get("forecast") or {}).get("summary")
    if fc:
        lines.append(f"Hedef özeti: {str(fc)[:200]}")
    inv = primary.get("invalidation_price")
    if inv is not None:
        lines.append(f"Geçersizlik: {inv} (fiyat {current_price:.4f}).")
    traits = primary.get("wave_traits") or {}
    if traits.get("truncated_wave5"):
        lines.append("Not: olası kısaltılmış 5. dalga (momentum zayıf).")
    if traits.get("extended_wave3"):
        lines.append("Not: güçlü 3. dalga uzantısı — 5. dalga hedeflerini fib ile doğrula.")
    if traits.get("correction_subtype"):
        lines.append(f"Düzeltme tipi: {traits['correction_subtype']}.")
    rules = primary.get("rule_checklist") or []
    failed = [r["rule"] for r in rules if not r.get("pass")]
    if failed:
        lines.append(f"Kural ihlali: {', '.join(failed)} — alternatif sayım düşün.")
    if alternate:
        lines.append(
            f"Alternatif: {alternate.get('kind')} skor {alternate.get('score')} "
            f"(birincil geçersiz olursa)."
        )
    return "\n".join(lines)


def enrich_hypothesis_detail(hypothesis: dict[str, Any]) -> dict[str, Any]:
    """Attach detail fields to one hypothesis row."""
    if not hypothesis or hypothesis.get("error"):
        return hypothesis
    kind = str(hypothesis.get("kind") or "")
    out = {**hypothesis}
    if kind.startswith("impulse_") or out.get("degree") == "impulse":
        out["rule_checklist"] = build_impulse_rule_checklist(hypothesis)
        out["rules_passed"] = sum(1 for r in out["rule_checklist"] if r.get("pass"))
        out["rules_total"] = len(out["rule_checklist"])
    if kind.startswith("abc_") or out.get("degree") == "correction":
        out["correction_subtype"] = classify_correction_subtype(hypothesis)
    out["wave_traits"] = detect_wave_traits(hypothesis)
    out["fib_grades"] = build_fib_grade_card(hypothesis)
    ch = build_wave_channel(hypothesis)
    if ch:
        out["channel"] = ch
    return out


def build_elliott_detail_panel(
    *,
    primary: dict[str, Any] | None,
    alternate: dict[str, Any] | None,
    hypotheses: list[dict[str, Any]],
    current_price: float,
) -> dict[str, Any]:
    """Top-level detail block for analyze_elliott_wave."""
    p = enrich_hypothesis_detail(primary) if primary else None
    a = enrich_hypothesis_detail(alternate) if alternate else None
    return {
        "primary": p,
        "alternate": a,
        "report_tr": build_elliott_report_tr(
            primary=p, alternate=a, current_price=current_price
        ),
        "hypothesis_count": len(hypotheses),
        "top_scores": [
            {"name": h.get("name"), "score": h.get("score"), "kind": h.get("kind")}
            for h in hypotheses[:5]
        ],
    }


__all__ = [
    "build_impulse_rule_checklist",
    "classify_correction_subtype",
    "detect_wave_traits",
    "build_fib_grade_card",
    "build_wave_channel",
    "build_elliott_report_tr",
    "enrich_hypothesis_detail",
    "build_elliott_detail_panel",
]

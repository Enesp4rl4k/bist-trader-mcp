"""Elliott Wave forward projections — next-wave price/time targets (rule-based)."""

from __future__ import annotations

from typing import Any, Literal, Protocol

Direction = Literal["long", "short"]


class _PivotLike(Protocol):
    index: int
    price: float
    kind: str


def _future_index(last_index: int, bars_ahead: int, max_index: int) -> int:
    return min(last_index + bars_ahead, max_index)


def _future_time(
    last_index: int,
    bars_ahead: int,
    times: list[int] | None,
    bar_seconds: int = 3600,
) -> int | None:
    if times and 0 <= last_index < len(times):
        base = int(times[last_index])
        step = bar_seconds
        if len(times) >= 2:
            step = max(int(times[-1] - times[-2]), 60)
        return base + step * bars_ahead
    return None


def _pt(
    *,
    index: int,
    price: float,
    label: str,
    kind: str,
    projected: bool = True,
    time: int | None = None,
    role: str = "target",
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "index": index,
        "price": round(float(price), 8),
        "label": label,
        "kind": kind,
        "projected": projected,
        "role": role,
    }
    if time is not None:
        row["time"] = int(time)
    return row


def project_impulse_bull(
    seg: list[_PivotLike],
    *,
    bars_ahead: int = 12,
    last_bar_index: int | None = None,
    times: list[int] | None = None,
    complete_through_5: bool = False,
) -> dict[str, Any]:
    """Wave 5 targets from wave 4, or post-5 ABC retrace if impulse finished."""
    if len(seg) < 5:
        return {"error": "need_5_pivots"}
    l0, h1, l2, h3, l4 = [x.price for x in seg[:5]]
    pivots = seg[:6] if len(seg) >= 6 else seg[:5]
    w1 = h1 - l0
    w3 = h3 - l2
    last_idx = int(pivots[-1].index)
    cap = last_bar_index if last_bar_index is not None else last_idx + bars_ahead * 2
    t5_idx = _future_index(last_idx, bars_ahead, cap)
    t5_time = _future_time(last_idx, bars_ahead, times)

    wave5_targets = [
        ("5=1.0×W1", l4 + w1, "equality_with_wave1"),
        ("5=0.618×W1", l4 + w1 * 0.618, "fib_618_of_wave1"),
        ("5=1.618×W1", l4 + w1 * 1.618, "fib_1618_of_wave1"),
    ]
    if w3 > 0:
        wave5_targets.append(("5=1.0×W3", l4 + w3, "equality_with_wave3"))

    scenarios = [
        {
            "wave": "5",
            "label": lbl,
            "price": round(px, 8),
            "method": method,
            "direction": "long",
        }
        for lbl, px, method in wave5_targets
    ]

    primary_target = l4 + w1
    path: list[dict[str, Any]] = [
        _pt(
            index=int(pivots[4].index),
            price=l4,
            label="(4)",
            kind="low",
            projected=False,
            time=int(times[pivots[4].index]) if times and pivots[4].index < len(times) else None,
            role="anchor",
        ),
        _pt(
            index=t5_idx,
            price=primary_target,
            label="5?",
            kind="high",
            projected=True,
            time=t5_time,
            role="primary_target",
        ),
    ]

    out: dict[str, Any] = {
        "phase": "forming_wave_5" if not complete_through_5 else "wave_5_complete",
        "active_wave": "5",
        "direction": "long",
        "invalidation": round(l4, 8),
        "primary_target": round(primary_target, 8),
        "scenarios": scenarios,
        "path_points": path,
        "summary": (
            f"Bull impulse: from (4) {l4:.2f} project wave 5 "
            f"≈ {primary_target:.2f} (1.0× wave1). Invalidation below (4)."
        ),
    }

    if complete_through_5 and len(seg) >= 6:
        h5 = seg[5].price
        impulse_span = h5 - l0
        out["phase"] = "post_wave_5_correction"
        out["active_wave"] = "A"
        out["direction"] = "short"
        abc_targets = [
            ("A 38.2%", h5 - impulse_span * 0.382),
            ("A 50%", h5 - impulse_span * 0.5),
            ("A 61.8%", h5 - impulse_span * 0.618),
        ]
        out["correction_scenarios"] = [
            {"wave": "A", "label": lbl, "price": round(px, 8), "direction": "short"}
            for lbl, px in abc_targets
        ]
        t_a = _future_index(int(seg[5].index), bars_ahead, cap)
        out["path_points"] = [
            _pt(
                index=int(seg[5].index),
                price=h5,
                label="(5)",
                kind="high",
                projected=False,
                time=int(times[seg[5].index]) if times and seg[5].index < len(times) else None,
                role="anchor",
            ),
            _pt(
                index=t_a,
                price=abc_targets[1][1],
                label="A?",
                kind="low",
                projected=True,
                time=_future_time(int(seg[5].index), bars_ahead, times),
                role="primary_target",
            ),
        ]
        out["summary"] = (
            f"Wave 5 complete at {h5:.2f}. Project ABC correction toward "
            f"~{abc_targets[1][1]:.2f} (50% retrace of impulse)."
        )
    return out


def project_impulse_bear(
    seg: list[_PivotLike],
    *,
    bars_ahead: int = 12,
    last_bar_index: int | None = None,
    times: list[int] | None = None,
    complete_through_5: bool = False,
) -> dict[str, Any]:
    if len(seg) < 5:
        return {"error": "need_5_pivots"}
    h0, l1, h2, l3, h4 = [x.price for x in seg[:5]]
    pivots = seg[:6] if len(seg) >= 6 else seg[:5]
    w1 = h0 - l1
    w3 = h2 - l3
    last_idx = int(pivots[-1].index)
    cap = last_bar_index if last_bar_index is not None else last_idx + bars_ahead * 2
    t5_idx = _future_index(last_idx, bars_ahead, cap)
    t5_time = _future_time(last_idx, bars_ahead, times)

    wave5_targets = [
        ("5=1.0×W1", h4 - w1, "equality_with_wave1"),
        ("5=0.618×W1", h4 - w1 * 0.618, "fib_618_of_wave1"),
        ("5=1.618×W1", h4 - w1 * 1.618, "fib_1618_of_wave1"),
    ]
    if w3 > 0:
        wave5_targets.append(("5=1.0×W3", h4 - w3, "equality_with_wave3"))

    primary_target = h4 - w1
    scenarios = [
        {
            "wave": "5",
            "label": lbl,
            "price": round(px, 8),
            "method": method,
            "direction": "short",
        }
        for lbl, px, method in wave5_targets
    ]

    path = [
        _pt(
            index=int(pivots[4].index),
            price=h4,
            label="(4)",
            kind="high",
            projected=False,
            time=int(times[pivots[4].index]) if times and pivots[4].index < len(times) else None,
            role="anchor",
        ),
        _pt(
            index=t5_idx,
            price=primary_target,
            label="5?",
            kind="low",
            projected=True,
            time=t5_time,
            role="primary_target",
        ),
    ]

    out: dict[str, Any] = {
        "phase": "forming_wave_5" if not complete_through_5 else "wave_5_complete",
        "active_wave": "5",
        "direction": "short",
        "invalidation": round(h4, 8),
        "primary_target": round(primary_target, 8),
        "scenarios": scenarios,
        "path_points": path,
        "summary": (
            f"Bear impulse: from (4) {h4:.2f} project wave 5 "
            f"≈ {primary_target:.2f}. Invalidation above (4)."
        ),
    }

    if complete_through_5 and len(seg) >= 6:
        l5 = seg[5].price
        impulse_span = h0 - l5
        out["phase"] = "post_wave_5_correction"
        out["active_wave"] = "A"
        abc_targets = [
            ("A 38.2%", l5 + impulse_span * 0.382),
            ("A 50%", l5 + impulse_span * 0.5),
            ("A 61.8%", l5 + impulse_span * 0.618),
        ]
        out["correction_scenarios"] = [
            {"wave": "A", "label": lbl, "price": round(px, 8), "direction": "long"}
            for lbl, px in abc_targets
        ]
        t_a = _future_index(int(seg[5].index), bars_ahead, cap)
        out["path_points"] = [
            _pt(
                index=int(seg[5].index),
                price=l5,
                label="(5)",
                kind="low",
                projected=False,
                time=int(times[seg[5].index]) if times and seg[5].index < len(times) else None,
                role="anchor",
            ),
            _pt(
                index=t_a,
                price=abc_targets[1][1],
                label="A?",
                kind="high",
                projected=True,
                time=_future_time(int(seg[5].index), bars_ahead, times),
                role="primary_target",
            ),
        ]
        out["summary"] = (
            f"Wave 5 complete at {l5:.2f}. Project ABC bounce toward "
            f"~{abc_targets[1][1]:.2f} (50% retrace)."
        )
    return out


def project_abc_bull(
    seg: list[_PivotLike],
    *,
    bars_ahead: int = 10,
    last_bar_index: int | None = None,
    times: list[int] | None = None,
) -> dict[str, Any]:
    """After bull-trend ABC down — project new impulse leg up (wave 1 of next cycle)."""
    if len(seg) < 3:
        return {"error": "need_abc_pivots"}
    a0, b1, c2 = seg[0].price, seg[1].price, seg[2].price
    leg_a = abs(b1 - a0)
    last_idx = int(seg[-1].index)
    cap = last_bar_index if last_bar_index is not None else last_idx + bars_ahead * 2
    t1_idx = _future_index(last_idx, bars_ahead, cap)
    targets = [
        ("1=0.618×A", c2 + leg_a * 0.618),
        ("1=1.0×A", c2 + leg_a),
        ("1=1.618×A", c2 + leg_a * 1.618),
    ]
    primary = c2 + leg_a
    return {
        "phase": "post_abc_new_impulse",
        "active_wave": "1",
        "direction": "long",
        "invalidation": round(c2, 8),
        "primary_target": round(primary, 8),
        "scenarios": [
            {"wave": "1", "label": lbl, "price": round(px, 8), "direction": "long"}
            for lbl, px in targets
        ],
        "path_points": [
            _pt(
                index=int(seg[2].index),
                price=c2,
                label="C",
                kind="low",
                projected=False,
                time=int(times[seg[2].index]) if times and seg[2].index < len(times) else None,
                role="anchor",
            ),
            _pt(
                index=t1_idx,
                price=primary,
                label="1?",
                kind="high",
                projected=True,
                time=_future_time(last_idx, bars_ahead, times),
                role="primary_target",
            ),
        ],
        "summary": (
            f"ABC correction complete near {c2:.2f}. Project new bull leg "
            f"≈ {primary:.2f} (1.0× wave-A)."
        ),
    }


def project_abc_bear(
    seg: list[_PivotLike],
    *,
    bars_ahead: int = 10,
    last_bar_index: int | None = None,
    times: list[int] | None = None,
) -> dict[str, Any]:
    if len(seg) < 3:
        return {"error": "need_abc_pivots"}
    a0, b1, c2 = seg[0].price, seg[1].price, seg[2].price
    leg_a = abs(b1 - a0)
    last_idx = int(seg[-1].index)
    cap = last_bar_index if last_bar_index is not None else last_idx + bars_ahead * 2
    t1_idx = _future_index(last_idx, bars_ahead, cap)
    targets = [
        ("1=0.618×A", c2 - leg_a * 0.618),
        ("1=1.0×A", c2 - leg_a),
        ("1=1.618×A", c2 - leg_a * 1.618),
    ]
    primary = c2 - leg_a
    return {
        "phase": "post_abc_new_impulse",
        "active_wave": "1",
        "direction": "short",
        "invalidation": round(c2, 8),
        "primary_target": round(primary, 8),
        "scenarios": [
            {"wave": "1", "label": lbl, "price": round(px, 8), "direction": "short"}
            for lbl, px in targets
        ],
        "path_points": [
            _pt(
                index=int(seg[2].index),
                price=c2,
                label="C",
                kind="high",
                projected=False,
                time=int(times[seg[2].index]) if times and seg[2].index < len(times) else None,
                role="anchor",
            ),
            _pt(
                index=t1_idx,
                price=primary,
                label="1?",
                kind="low",
                projected=True,
                time=_future_time(last_idx, bars_ahead, times),
                role="primary_target",
            ),
        ],
        "summary": (
            f"ABC correction complete near {c2:.2f}. Project new bear leg "
            f"≈ {primary:.2f} (1.0× wave-A)."
        ),
    }


def attach_projection_to_hypothesis(
    detail: dict[str, Any],
    seg: list[_PivotLike],
    *,
    kind: str,
    bars_ahead: int,
    last_bar_index: int | None,
    times: list[int] | None,
) -> dict[str, Any]:
    """Add forecast block + merged draw_points (history + projected)."""
    complete_5 = len(seg) >= 6 and detail.get("current_wave", "").startswith("5_complete")
    proj: dict[str, Any]
    if kind == "impulse_bull":
        proj = project_impulse_bull(
            seg,
            bars_ahead=bars_ahead,
            last_bar_index=last_bar_index,
            times=times,
            complete_through_5=complete_5,
        )
    elif kind == "impulse_bear":
        proj = project_impulse_bear(
            seg,
            bars_ahead=bars_ahead,
            last_bar_index=last_bar_index,
            times=times,
            complete_through_5=complete_5,
        )
    elif kind == "abc_bull":
        proj = project_abc_bull(seg, bars_ahead=bars_ahead, last_bar_index=last_bar_index, times=times)
    elif kind == "abc_bear":
        proj = project_abc_bear(seg, bars_ahead=bars_ahead, last_bar_index=last_bar_index, times=times)
    else:
        return detail

    if proj.get("error"):
        return detail

    detail = {**detail, "forecast": proj}
    detail["next_wave"] = proj.get("active_wave")
    detail["forecast_summary"] = proj.get("summary")
    detail["target_scenarios"] = proj.get("scenarios") or proj.get("correction_scenarios")
    detail["primary_forecast_target"] = proj.get("primary_target")

    hist = list(detail.get("points") or [])
    proj_pts = proj.get("path_points") or []
    detail["draw_points"] = hist
    detail["projected_points"] = proj_pts
    return detail


__all__ = [
    "project_impulse_bull",
    "project_impulse_bear",
    "project_abc_bull",
    "project_abc_bear",
    "attach_projection_to_hypothesis",
]

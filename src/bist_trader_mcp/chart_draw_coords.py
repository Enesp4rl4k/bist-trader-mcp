"""Map analysis bar indices → TradingView unix times on the active chart timeframe."""

from __future__ import annotations

from typing import Any


def map_points_to_chart_times(
    points: list[dict[str, Any]] | None,
    source_times: list[int] | None,
    chart_times: list[int] | None,
) -> list[dict[str, Any]]:
    """Project EW/PA pivots (indexed on HTF series) onto LTF bar times for drawing.

    Points whose source timestamp falls outside the chart time range
    (with a small tolerance) are **dropped** so that they don't snap to
    the chart edge and produce wrong diagonal lines.
    """
    if not points or not chart_times:
        return []
    src = source_times if source_times else chart_times
    if not src:
        return []

    ct_min = min(int(t) for t in chart_times)
    ct_max = max(int(t) for t in chart_times)
    # Allow a tolerance of ~1 bar spacing on each side so points very
    # close to the edge still draw.  Use median bar gap as estimate.
    sorted_ct = sorted(int(t) for t in chart_times)
    if len(sorted_ct) >= 2:
        gaps = [sorted_ct[i + 1] - sorted_ct[i] for i in range(len(sorted_ct) - 1)]
        gaps.sort()
        bar_gap = gaps[len(gaps) // 2]  # median
    else:
        bar_gap = 3600
    tolerance = bar_gap * 2
    range_lo = ct_min - tolerance
    range_hi = ct_max + tolerance

    mapped: list[dict[str, Any]] = []
    for pt in points:
        price = pt.get("price")
        if price is None:
            continue
        t_src: int | None = None
        if pt.get("time") is not None:
            t_src = int(pt["time"])
        else:
            idx = pt.get("index")
            if idx is None:
                continue
            i = int(idx)
            if i < 0 or i >= len(src):
                continue
            t_src = int(src[i])
        if t_src is None:
            continue

        # --- KEY FIX: skip points outside the visible chart range ---
        if t_src < range_lo or t_src > range_hi:
            continue

        best_t = int(chart_times[0])
        best_d = abs(best_t - t_src)
        for t in chart_times:
            tt = int(t)
            d = abs(tt - t_src)
            if d < best_d:
                best_d = d
                best_t = tt
        mapped.append(
            {
                **pt,
                "time": best_t,
                "index": None,
                "price": float(price),
            }
        )
    return mapped


def points_drawable_on_chart(
    points: list[dict[str, Any]] | None,
    chart_times: list[int] | None,
) -> bool:
    if not points or not chart_times or len(points) < 2:
        return False
    t_min, t_max = min(chart_times), max(chart_times)
    ok = 0
    for p in points:
        t = p.get("time")
        if t is None:
            continue
        if t_min <= int(t) <= t_max:
            ok += 1
    return ok >= 2

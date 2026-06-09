"""Fair Value Gap (FVG) and Inverse FVG (IFVG) detection on OHLCV."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

FvgDirection = Literal["bullish", "bearish"]
FvgStatus = Literal["open", "partial", "filled", "inverted"]
IfvgSide = Literal["support", "resistance"]


@dataclass
class FairValueGap:
    """Three-candle imbalance zone (ICT-style)."""

    index: int
    direction: FvgDirection
    top: float
    bottom: float
    mid: float
    size: float
    size_pct: float
    status: FvgStatus = "open"
    ifvg_side: IfvgSide | None = None
    formation_bar: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "direction": self.direction,
            "top": round(self.top, 8),
            "bottom": round(self.bottom, 8),
            "mid": round(self.mid, 8),
            "size": round(self.size, 8),
            "size_pct": round(self.size_pct, 6),
            "status": self.status,
            "ifvg_side": self.ifvg_side,
            "formation_bar": self.formation_bar,
        }


def _middle_bar_displacement(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    mid_idx: int,
    atr_val: float | None,
) -> bool:
    """Middle candle of 3-bar FVG should be impulsive (displacement)."""
    if mid_idx < 1 or mid_idx >= len(closes):
        return True
    bar_range = highs[mid_idx] - lows[mid_idx]
    if bar_range <= 0:
        return False
    body = abs(closes[mid_idx] - closes[mid_idx - 1])
    impulse_ratio = body / bar_range
    if atr_val and bar_range < atr_val * 0.25:
        return False
    return impulse_ratio >= 0.42 or bar_range >= (atr_val or 0) * 0.35


def _min_gap_size(close: float, atr_val: float | None, min_gap_pct: float) -> float:
    by_pct = close * min_gap_pct if close > 0 else 0.0
    by_atr = (atr_val or 0.0) * 0.08
    return max(by_pct, by_atr, 1e-12)


def detect_fvgs(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    *,
    atr_val: float | None = None,
    min_gap_pct: float = 0.0012,
    min_size_atr_ratio: float = 0.12,
    max_age_bars: int = 120,
    require_displacement: bool = True,
) -> list[FairValueGap]:
    """Scan 3-bar FVGs: bull if low[i] > high[i-2]; bear if high[i] < low[i-2]."""
    n = min(len(highs), len(lows), len(closes))
    if n < 3:
        return []

    start = max(2, n - max_age_bars)
    out: list[FairValueGap] = []
    for i in range(start, n):
        close_i = closes[i]
        mg = _min_gap_size(close_i, atr_val, min_gap_pct)

        if lows[i] > highs[i - 2] + mg:
            if require_displacement and not _middle_bar_displacement(
                highs, lows, closes, i - 1, atr_val
            ):
                continue
            bottom = highs[i - 2]
            top = lows[i]
            size = top - bottom
            size_pct = size / close_i if close_i else 0.0
            if size_pct < min_gap_pct:
                continue
            if atr_val and size < atr_val * min_size_atr_ratio:
                continue
            out.append(
                FairValueGap(
                    index=i,
                    direction="bullish",
                    top=top,
                    bottom=bottom,
                    mid=(top + bottom) / 2,
                    size=size,
                    size_pct=size_pct,
                    formation_bar=i,
                )
            )
        elif highs[i] < lows[i - 2] - mg:
            if require_displacement and not _middle_bar_displacement(
                highs, lows, closes, i - 1, atr_val
            ):
                continue
            top = lows[i - 2]
            bottom = highs[i]
            size = top - bottom
            size_pct = size / close_i if close_i else 0.0
            if size_pct < min_gap_pct:
                continue
            if atr_val and size < atr_val * min_size_atr_ratio:
                continue
            out.append(
                FairValueGap(
                    index=i,
                    direction="bearish",
                    top=top,
                    bottom=bottom,
                    mid=(top + bottom) / 2,
                    size=size,
                    size_pct=size_pct,
                    formation_bar=i,
                )
            )
    return _dedupe_overlapping_fvgs(out)


def _dedupe_overlapping_fvgs(fvgs: list[FairValueGap]) -> list[FairValueGap]:
    """Keep newest gap when zones overlap same direction."""
    if not fvgs:
        return []
    fvgs = sorted(fvgs, key=lambda g: g.index)
    kept: list[FairValueGap] = []
    for g in fvgs:
        if not kept:
            kept.append(g)
            continue
        prev = kept[-1]
        if g.direction == prev.direction and abs(g.mid - prev.mid) / max(prev.mid, 1e-9) < 0.003:
            kept[-1] = g
        else:
            kept.append(g)
    return kept


def update_fvg_lifecycle(
    fvgs: list[FairValueGap],
    highs: list[float],
    lows: list[float],
    closes: list[float],
) -> list[FairValueGap]:
    """Mark open → partial → filled → inverted from subsequent price action."""
    n = min(len(highs), len(lows), len(closes))
    for gap in fvgs:
        if gap.index >= n - 1:
            continue
        for j in range(gap.index + 1, n):
            if gap.direction == "bullish":
                if lows[j] <= gap.bottom:
                    gap.status = "filled"
                    if closes[j] < gap.bottom:
                        gap.status = "inverted"
                        gap.ifvg_side = "resistance"
                elif lows[j] < gap.top and lows[j] > gap.bottom:
                    if gap.status == "open":
                        gap.status = "partial"
            else:
                if highs[j] >= gap.top:
                    gap.status = "filled"
                    if closes[j] > gap.top:
                        gap.status = "inverted"
                        gap.ifvg_side = "support"
                elif highs[j] > gap.bottom and highs[j] < gap.top:
                    if gap.status == "open":
                        gap.status = "partial"
    return fvgs


def summarize_fvgs(fvgs: list[FairValueGap]) -> dict[str, Any]:
    open_bull = [g for g in fvgs if g.direction == "bullish" and g.status in ("open", "partial")]
    open_bear = [g for g in fvgs if g.direction == "bearish" and g.status in ("open", "partial")]
    ifvg = [g for g in fvgs if g.status == "inverted"]
    return {
        "total": len(fvgs),
        "open_bullish": len(open_bull),
        "open_bearish": len(open_bear),
        "inverted": len(ifvg),
        "open_bullish_zones": [g.to_dict() for g in open_bull[-3:]],
        "open_bearish_zones": [g.to_dict() for g in open_bear[-3:]],
        "ifvg_zones": [g.to_dict() for g in ifvg[-3:]],
    }


def price_in_zone(close: float, gap: FairValueGap, buffer_pct: float = 0.002) -> bool:
    buf = gap.mid * buffer_pct
    return (gap.bottom - buf) <= close <= (gap.top + buf)


def nearest_fvg_for_direction(
    fvgs: list[FairValueGap],
    close: float,
    direction: Literal["long", "short"],
) -> FairValueGap | None:
    """Best active zone for entry confluence."""
    candidates: list[FairValueGap] = []
    for g in fvgs:
        if g.status not in ("open", "partial", "inverted"):
            continue
        if not price_in_zone(close, g) and abs(close - g.mid) / max(g.mid, 1e-9) > 0.025:
            continue
        if direction == "long":
            if g.direction == "bullish" and g.status in ("open", "partial"):
                candidates.append(g)
            if g.status == "inverted" and g.ifvg_side == "support":
                candidates.append(g)
        else:
            if g.direction == "bearish" and g.status in ("open", "partial"):
                candidates.append(g)
            if g.status == "inverted" and g.ifvg_side == "resistance":
                candidates.append(g)
    if not candidates:
        return None
    return min(candidates, key=lambda g: abs(close - g.mid))


def find_stacked_imbalances(
    fvgs: list[FairValueGap],
    *,
    max_mid_distance_pct: float = 0.006,
) -> list[dict[str, Any]]:
    """Overlapping same-direction FVGs → stronger imbalance stack."""
    stacks: list[dict[str, Any]] = []
    by_dir: dict[str, list[FairValueGap]] = {"bullish": [], "bearish": []}
    for g in fvgs:
        if g.status in ("open", "partial"):
            by_dir[g.direction].append(g)
    for direction, group in by_dir.items():
        group = sorted(group, key=lambda x: x.index)
        i = 0
        while i < len(group):
            chunk = [group[i]]
            j = i + 1
            while j < len(group):
                if abs(group[j].mid - chunk[-1].mid) / max(chunk[-1].mid, 1e-9) <= max_mid_distance_pct:
                    chunk.append(group[j])
                    j += 1
                else:
                    break
            if len(chunk) >= 2:
                top = max(g.top for g in chunk)
                bottom = min(g.bottom for g in chunk)
                stacks.append({
                    "direction": direction,
                    "count": len(chunk),
                    "top": round(top, 8),
                    "bottom": round(bottom, 8),
                    "mid": round((top + bottom) / 2, 8),
                    "indices": [g.index for g in chunk],
                })
            i = j if j > i + 1 else i + 1
    return stacks


def imbalances_for_range_zone(
    fvgs: list[FairValueGap],
    range_box: dict[str, Any],
    *,
    close: float,
) -> dict[str, Any]:
    """Match open/IFVG zones to range discount/premium (range-trade confluence)."""
    if not range_box.get("active"):
        return {"aligned_long": [], "aligned_short": []}
    zone = range_box.get("zone")
    rl = float(range_box["range_low"])
    rh = float(range_box["range_high"])
    long_z: list[dict[str, Any]] = []
    short_z: list[dict[str, Any]] = []
    for g in fvgs:
        if g.status not in ("open", "partial", "inverted"):
            continue
        d = g.to_dict()
        if zone == "discount" and g.direction == "bullish" and g.status in ("open", "partial"):
            if g.bottom >= rl * 0.995 and g.top <= rh:
                long_z.append(d)
        if zone == "discount" and g.status == "inverted" and g.ifvg_side == "support":
            long_z.append(d)
        if zone == "premium" and g.direction == "bearish" and g.status in ("open", "partial"):
            if g.top <= rh * 1.005 and g.bottom >= rl:
                short_z.append(d)
        if zone == "premium" and g.status == "inverted" and g.ifvg_side == "resistance":
            short_z.append(d)
    if not long_z and zone == "discount":
        for g in fvgs:
            if g.direction == "bullish" and g.status in ("open", "partial") and price_in_zone(close, g, 0.01):
                long_z.append(g.to_dict())
    if not short_z and zone == "premium":
        for g in fvgs:
            if g.direction == "bearish" and g.status in ("open", "partial") and price_in_zone(close, g, 0.01):
                short_z.append(g.to_dict())
    return {"aligned_long": long_z[:3], "aligned_short": short_z[:3]}


def build_imbalance_panel(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    *,
    atr_val: float | None = None,
    min_gap_pct: float = 0.0012,
    range_box: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """FVG + stacks + range-aligned imbalances (single MCP payload)."""
    raw = detect_fvgs(highs, lows, closes, atr_val=atr_val, min_gap_pct=min_gap_pct)
    updated = update_fvg_lifecycle(raw, highs, lows, closes)
    summary = summarize_fvgs(updated)
    stacks = find_stacked_imbalances(updated)
    range_align = (
        imbalances_for_range_zone(updated, range_box, close=closes[-1])
        if range_box
        else None
    )
    return {
        "fvgs": [g.to_dict() for g in updated[-20:]],
        "summary": summary,
        "stacks": stacks,
        "range_aligned": range_align,
    }


def build_fvg_panel(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    *,
    atr_val: float | None = None,
    min_gap_pct: float = 0.0012,
    range_box: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return build_imbalance_panel(
        highs, lows, closes, atr_val=atr_val, min_gap_pct=min_gap_pct, range_box=range_box
    )


__all__ = [
    "FairValueGap",
    "detect_fvgs",
    "update_fvg_lifecycle",
    "summarize_fvgs",
    "nearest_fvg_for_direction",
    "find_stacked_imbalances",
    "imbalances_for_range_zone",
    "build_imbalance_panel",
    "build_fvg_panel",
    "price_in_zone",
]

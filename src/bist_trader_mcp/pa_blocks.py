"""Order Block (OB) and Breaker Block (BB) detection on OHLCV."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

BlockDirection = Literal["bullish", "bearish"]
BlockStatus = Literal["open", "mitigated", "broken"]


@dataclass
class OrderBlock:
    """A zone representing the last opposite candle before a strong displacement move."""

    index: int
    direction: BlockDirection
    top: float
    bottom: float
    mid: float
    status: BlockStatus = "open"
    mitigation_bar: int | None = None
    mitigation_count: int = 0
    formation_bar: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "direction": self.direction,
            "top": round(self.top, 8),
            "bottom": round(self.bottom, 8),
            "mid": round(self.mid, 8),
            "status": self.status,
            "mitigation_bar": self.mitigation_bar,
            "mitigation_count": self.mitigation_count,
            "formation_bar": self.formation_bar,
        }


@dataclass
class BreakerBlock:
    """A broken/invalidated Order Block that flips its role (support/resistance)."""

    index: int
    direction: BlockDirection  # "bullish" breaker acts as support, "bearish" acts as resistance
    top: float
    bottom: float
    mid: float
    status: BlockStatus = "open"
    original_ob_index: int = 0
    formation_bar: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "direction": self.direction,
            "top": round(self.top, 8),
            "bottom": round(self.bottom, 8),
            "mid": round(self.mid, 8),
            "status": self.status,
            "original_ob_index": self.original_ob_index,
            "formation_bar": self.formation_bar,
        }


def detect_order_blocks(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    opens: list[float],
    *,
    atr_val: float | None = None,
    min_displacement_atr: float = 1.2,
    max_age_bars: int = 120,
) -> tuple[list[OrderBlock], list[BreakerBlock]]:
    """Scan history for Order Blocks and their Breaker Block transitions.

    - Bullish OB: Bearish candle preceding a strong upward displacement.
    - Bearish OB: Bullish candle preceding a strong downward displacement.
    - If an OB is broken by a candle closing past it, it deactivates and spawns a Breaker Block.
    """
    n = min(len(highs), len(lows), len(closes), len(opens))
    if n < 5:
        return [], []

    if atr_val and atr_val > 0:
        atr_threshold = atr_val
    else:
        recent = list(zip(highs[-20:], lows[-20:]))
        atr_threshold = (sum(h - l for h, l in recent) / len(recent)) if recent else 0.0
    if atr_threshold <= 0:
        atr_threshold = closes[-1] * 0.01

    start_idx = max(1, n - max_age_bars)
    obs: list[OrderBlock] = []
    breakers: list[BreakerBlock] = []

    # Step 1: Detect OB candidates based on displacement
    for i in range(start_idx, n - 2):
        # Bullish displacement check: next 1 or 2 candles show strong expansion
        move_1 = closes[i + 1] - opens[i + 1]
        move_2 = closes[i + 2] - opens[i + 1]
        
        is_bullish_displacement = (
            (move_1 >= atr_threshold * min_displacement_atr and closes[i + 1] > opens[i + 1]) or
            (move_2 >= atr_threshold * min_displacement_atr and closes[i + 2] > opens[i + 1] and closes[i + 1] >= opens[i + 1])
        )
        
        if is_bullish_displacement:
            # Look for last bearish candle at i, or up to 3 bars back
            ob_idx = i
            for back in range(3):
                idx = i - back
                if idx >= 0 and closes[idx] < opens[idx]:
                    ob_idx = idx
                    break
            
            # Create Bullish OB candidate
            top = highs[ob_idx]
            bottom = lows[ob_idx]
            # Avoid duplicate OB at same bar
            if not any(o.index == ob_idx and o.direction == "bullish" for o in obs):
                obs.append(
                    OrderBlock(
                        index=ob_idx,
                        direction="bullish",
                        top=top,
                        bottom=bottom,
                        mid=(top + bottom) / 2.0,
                        formation_bar=i + 1,
                    )
                )

        # Bearish displacement check
        move_bear_1 = opens[i + 1] - closes[i + 1]
        move_bear_2 = opens[i + 1] - closes[i + 2]
        
        is_bearish_displacement = (
            (move_bear_1 >= atr_threshold * min_displacement_atr and closes[i + 1] < opens[i + 1]) or
            (move_bear_2 >= atr_threshold * min_displacement_atr and closes[i + 2] < opens[i + 1] and closes[i + 1] <= opens[i + 1])
        )
        
        if is_bearish_displacement:
            # Look for last bullish candle at i, or up to 3 bars back
            ob_idx = i
            for back in range(3):
                idx = i - back
                if idx >= 0 and closes[idx] > opens[idx]:
                    ob_idx = idx
                    break
            
            # Create Bearish OB candidate
            top = highs[ob_idx]
            bottom = lows[ob_idx]
            if not any(o.index == ob_idx and o.direction == "bearish" for o in obs):
                obs.append(
                    OrderBlock(
                        index=ob_idx,
                        direction="bearish",
                        top=top,
                        bottom=bottom,
                        mid=(top + bottom) / 2.0,
                        formation_bar=i + 1,
                    )
                )

    # Step 2: Track lifecycle and handle breaker transitions
    for ob in obs:
        # Track mitigation only after the displacement leg has cleared the zone,
        # so the displacement candle itself never counts as a mitigation touch.
        eval_start = max(ob.formation_bar, ob.index + 1)
        left_zone = False
        for j in range(eval_start, n):
            close_j = closes[j]
            low_j = lows[j]
            high_j = highs[j]

            if ob.direction == "bullish":
                # Check broken condition (close below OB bottom)
                if close_j < ob.bottom:
                    ob.status = "broken"
                    ob.mitigation_bar = j
                    # Spawn Bearish Breaker Block (resistance role)
                    breakers.append(
                        BreakerBlock(
                            index=ob.index,
                            direction="bearish",
                            top=ob.top,
                            bottom=ob.bottom,
                            mid=ob.mid,
                            original_ob_index=ob.index,
                            formation_bar=j,
                        )
                    )
                    break
                # Price must first clear above the zone before a return counts as mitigation
                if not left_zone:
                    if low_j > ob.top:
                        left_zone = True
                    continue
                # Check mitigation (wick re-enters/touches OB after leaving)
                if low_j <= ob.top:
                    if ob.status == "open":
                        ob.status = "mitigated"
                        ob.mitigation_bar = j
                    ob.mitigation_count += 1
            else:
                # Check broken condition (close above OB top)
                if close_j > ob.top:
                    ob.status = "broken"
                    ob.mitigation_bar = j
                    # Spawn Bullish Breaker Block (support role)
                    breakers.append(
                        BreakerBlock(
                            index=ob.index,
                            direction="bullish",
                            top=ob.top,
                            bottom=ob.bottom,
                            mid=ob.mid,
                            original_ob_index=ob.index,
                            formation_bar=j,
                        )
                    )
                    break
                # Price must first clear below the zone before a return counts as mitigation
                if not left_zone:
                    if high_j < ob.bottom:
                        left_zone = True
                    continue
                # Check mitigation (wick re-enters/touches OB after leaving)
                if high_j >= ob.bottom:
                    if ob.status == "open":
                        ob.status = "mitigated"
                        ob.mitigation_bar = j
                    ob.mitigation_count += 1

    # Step 3: Track lifecycle of spawned Breaker Blocks
    for bb in breakers:
        eval_start = bb.formation_bar + 1
        for k in range(eval_start, n):
            close_k = closes[k]
            low_k = lows[k]
            high_k = highs[k]

            if bb.direction == "bullish":
                # Invalidated if price closes back below breaker bottom
                if close_k < bb.bottom:
                    bb.status = "broken"
                    break
                elif low_k <= bb.top:
                    if bb.status == "open":
                        bb.status = "mitigated"
            else:
                # Invalidated if price closes back above breaker top
                if close_k > bb.top:
                    bb.status = "broken"
                    break
                elif high_k >= bb.bottom:
                    if bb.status == "open":
                        bb.status = "mitigated"

    return obs, breakers


def build_block_panel(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    opens: list[float],
    *,
    atr_val: float | None = None,
    min_displacement_atr: float = 1.2,
) -> dict[str, Any]:
    """MCP dashboard structure for Order Blocks and Breaker Blocks."""
    obs, breakers = detect_order_blocks(
        highs, lows, closes, opens, atr_val=atr_val, min_displacement_atr=min_displacement_atr
    )

    open_bull_ob = [o.to_dict() for o in obs if o.direction == "bullish" and o.status in ("open", "mitigated")]
    open_bear_ob = [o.to_dict() for o in obs if o.direction == "bearish" and o.status in ("open", "mitigated")]
    active_bull_bb = [b.to_dict() for b in breakers if b.direction == "bullish" and b.status in ("open", "mitigated")]
    active_bear_bb = [b.to_dict() for b in breakers if b.direction == "bearish" and b.status in ("open", "mitigated")]

    return {
        "order_blocks": {
            "bullish": open_bull_ob[-3:],
            "bearish": open_bear_ob[-3:],
            "total_detected": len(obs),
        },
        "breaker_blocks": {
            "bullish": active_bull_bb[-3:],
            "bearish": active_bear_bb[-3:],
            "total_detected": len(breakers),
        },
        "raw_obs": [o.to_dict() for o in obs],
        "raw_breakers": [b.to_dict() for b in breakers],
    }

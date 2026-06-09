"""Multi-timeframe price action — HTF bias + LTF entry alignment."""

from __future__ import annotations

from typing import Any, Literal

from .price_action import analyze_price_action

Direction = Literal["long", "short", "neutral"]


def analyze_mtf_price_action(
    htf_closes: list[float],
    htf_highs: list[float],
    htf_lows: list[float],
    ltf_closes: list[float],
    ltf_highs: list[float],
    ltf_lows: list[float],
    *,
    htf_volumes: list[float] | None = None,
    ltf_volumes: list[float] | None = None,
    htf_label: str = "HTF",
    ltf_label: str = "LTF",
    pa_kwargs: dict[str, Any] | None = None,
    htf_pa_kwargs: dict[str, Any] | None = None,
    ltf_pa_kwargs: dict[str, Any] | None = None,
    min_ltf_confluence: float = 52.0,
) -> dict[str, Any]:
    """Combine higher-TF structure bias with lower-TF setup timing."""
    shared = pa_kwargs or {}
    htf_kw = {**shared, **(htf_pa_kwargs or {})}
    ltf_kw = {**shared, **(ltf_pa_kwargs or {})}
    htf = analyze_price_action(
        htf_closes, htf_highs, htf_lows, volumes=htf_volumes, **htf_kw
    )
    ltf = analyze_price_action(
        ltf_closes, ltf_highs, ltf_lows, volumes=ltf_volumes, **ltf_kw
    )

    htf_structure = htf["market_structure"]
    ltf_structure = ltf["market_structure"]
    htf_bias: Direction = htf["bias"]
    ltf_bias: Direction = ltf["bias"]

    aligned_direction: Direction = "neutral"
    if htf_bias == "long" and ltf_bias in ("long", "neutral"):
        aligned_direction = "long"
    elif htf_bias == "short" and ltf_bias in ("short", "neutral"):
        aligned_direction = "short"
    elif htf_bias == "neutral" and ltf_bias != "neutral":
        aligned_direction = ltf_bias

    conflict = (
        (htf_bias == "long" and ltf_bias == "short")
        or (htf_bias == "short" and ltf_bias == "long")
    )
    structure_conflict = (
        (htf_structure == "bearish" and ltf_structure == "bullish")
        or (htf_structure == "bullish" and ltf_structure == "bearish")
    )
    if structure_conflict:
        conflict = True

    setup = None
    if aligned_direction == "long":
        setup = ltf.get("suggested_long_setup")
    elif aligned_direction == "short":
        setup = ltf.get("suggested_short_setup")

    if setup:
        conf = (setup.get("confluence") or {}).get("score", 0)
        if float(conf) < min_ltf_confluence:
            setup = None

    if htf_structure == "transition" and ltf_structure == "transition":
        aligned_direction = "neutral"
        setup = None

    trade_quality = "no_trade"
    if conflict:
        trade_quality = "conflict"
    elif aligned_direction != "neutral" and setup:
        if htf_bias == aligned_direction and ltf_bias == aligned_direction:
            trade_quality = "a_plus"
        elif htf_bias == aligned_direction:
            trade_quality = "a"
        else:
            trade_quality = "b"
    elif aligned_direction != "neutral":
        trade_quality = "c"

    return {
        "htf_label": htf_label,
        "ltf_label": ltf_label,
        "htf_structure": htf_structure,
        "ltf_structure": ltf_structure,
        "htf_bias": htf_bias,
        "ltf_bias": ltf_bias,
        "aligned_direction": aligned_direction,
        "conflict": conflict,
        "structure_conflict": structure_conflict,
        "trade_quality": trade_quality,
        "recommended_setup": setup,
        "htf_analysis": htf,
        "ltf_analysis": ltf,
        "notes": (
            "A+ = HTF and LTF same bias with setup. A = HTF bias, LTF neutral/setup. "
            "B = LTF-only bias. conflict = do not trade until aligned."
        ),
    }


__all__ = ["analyze_mtf_price_action"]

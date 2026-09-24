"""Simple price action — the full PA engine boiled down to a handful of answers.

``analyze_price_action`` returns swings, FVGs, order blocks, breakers, sweeps,
confluence scores… This module keeps only what a trader reads first:

1. Trend        — yükseliş / düşüş / yatay (+ strength)
2. Levels       — nearest support and resistance with distance %
3. Last event   — did price just break a swing high/low?
4. Zone         — cheap (discount) or expensive (premium) inside the last swing
5. Verdict      — AL / SAT / BEKLE with one sentence of reasoning
6. Plan         — at most one setup: entry / stop / target / R:R
"""

from __future__ import annotations

from typing import Any

from .price_action import analyze_price_action

_TREND_TR = {"bullish": "yükseliş", "bearish": "düşüş", "ranging": "yatay", "transition": "yatay"}

_EVENT_TR = {
    "bos_bull": "son tepe yukarı kırıldı (yükseliş devam ediyor)",
    "mss_bull": "son tepe güçlü mumla yukarı kırıldı",
    "choch_bull": "düşüş yapısı yukarı kırıldı (dönüş sinyali)",
    "bos_bear": "son dip aşağı kırıldı (düşüş devam ediyor)",
    "mss_bear": "son dip güçlü mumla aşağı kırıldı",
    "choch_bear": "yükseliş yapısı aşağı kırıldı (dönüş sinyali)",
}


def _level(item: dict[str, Any] | None, price: float) -> dict[str, Any] | None:
    if not item:
        return None
    p = float(item["price"])
    return {"price": round(p, 4), "distance_pct": round((p / price - 1.0) * 100.0, 2)}


def _plan(setup: dict[str, Any] | None) -> dict[str, Any] | None:
    if not setup:
        return None
    entry, stop = float(setup["entry"]), float(setup["stop"])
    targets = setup.get("targets") or []
    if not targets:
        return None
    target = float(targets[0])
    risk = abs(entry - stop)
    rr = round(abs(target - entry) / risk, 2) if risk > 0 else None
    return {
        "direction": "long" if setup.get("direction") == "long" else "short",
        "entry": round(entry, 4),
        "stop": round(stop, 4),
        "target": round(target, 4),
        "risk_reward": rr,
    }


def simple_price_action(
    closes: list[float],
    highs: list[float],
    lows: list[float],
    opens: list[float] | None = None,
    *,
    volumes: list[float] | None = None,
    min_rr: float = 1.5,
    debug: bool = False,
) -> dict[str, Any]:
    """Plain-language price action summary (trend, levels, verdict, one plan).

    ``debug=True`` adds a ``debug`` block (confluence score, factors, setup type)
    used by the walk-forward backtest for factor attribution.
    """
    pa = analyze_price_action(closes, highs, lows, opens=opens, volumes=volumes)
    price = float(pa["current_price"])
    structure = pa["market_structure"]
    trend = _TREND_TR.get(structure, "yatay")
    strength = pa.get("bias_strength") or 0.35
    strength_tr = "güçlü" if strength >= 0.8 else "orta" if strength >= 0.6 else "zayıf"

    # supports/resistances are ranked by touches; pick the *nearest* instead
    sups = sorted(pa.get("support_levels") or [], key=lambda s: price - s["price"])
    ress = sorted(pa.get("resistance_levels") or [], key=lambda r: r["price"] - price)
    support = _level(sups[0] if sups else None, price)
    resistance = _level(ress[0] if ress else None, price)

    events = pa.get("structure_events") or []
    last_event = _EVENT_TR.get(events[-1]["kind"]) if events else None

    leg = pa.get("swing_leg") or {}
    zone = None
    if leg.get("active"):
        pos = float(leg.get("position_pct") or 0.5)
        zone = "ucuz bölge (dip tarafı)" if pos < 0.5 else "pahalı bölge (tepe tarafı)"

    cl = float((pa.get("confluence_long") or {}).get("score") or 0)
    cs = float((pa.get("confluence_short") or {}).get("score") or 0)
    long_plan = _plan(pa.get("suggested_long_setup"))
    short_plan = _plan(pa.get("suggested_short_setup"))

    plan = None
    if structure == "bullish" and long_plan:
        plan = long_plan
    elif structure == "bearish" and short_plan:
        plan = short_plan
    elif long_plan or short_plan:
        plan = long_plan if (long_plan and (not short_plan or cl >= cs)) else short_plan
    if plan and (plan["risk_reward"] or 0) < min_rr:
        plan = None

    if plan and plan["direction"] == "long":
        verdict = "AL"
        why = f"Trend {trend}, destek yakın; {plan['entry']} civarı alış, stop {plan['stop']}."
    elif plan:
        verdict = "SAT"
        why = f"Trend {trend}, direnç yakın; {plan['entry']} civarı satış, stop {plan['stop']}."
    else:
        verdict = "BEKLE"
        if structure in ("ranging", "transition"):
            why = "Net yön yok; destek veya direnç kırılımını bekle."
        else:
            why = f"Trend {trend} ama giriş için risk/ödül uygun değil; geri çekilme bekle."

    lines = [f"Trend: {trend} ({strength_tr})."]
    if support:
        lines.append(f"Destek: {support['price']} ({support['distance_pct']:+.2f}%).")
    if resistance:
        lines.append(f"Direnç: {resistance['price']} ({resistance['distance_pct']:+.2f}%).")
    if last_event:
        lines.append(f"Son olay: {last_event}.")
    if zone:
        lines.append(f"Fiyat son salınımın {zone} kısmında.")
    lines.append(f"Karar: {verdict} — {why}")

    out: dict[str, Any] = {
        "price": price,
        "trend": trend,
        "trend_strength": strength_tr,
        "support": support,
        "resistance": resistance,
        "last_event": last_event,
        "zone": zone,
        "verdict": verdict,
        "reason": why,
        "plan": plan,
        "summary_tr": " ".join(lines),
    }
    if debug:
        raw = None
        if plan:
            key = "suggested_long_setup" if plan["direction"] == "long" else "suggested_short_setup"
            raw = pa.get(key) or {}
        conf = (raw or {}).get("confluence") or {}
        out["debug"] = {
            "structure": structure,
            "setup_type": (raw or {}).get("setup_type"),
            "entry_style": (raw or {}).get("entry_style"),
            "confluence_score": conf.get("score"),
            "factors": list(conf.get("factors") or []),
            "atr_14": pa.get("atr_14"),
        }
    return out


__all__ = ["simple_price_action"]

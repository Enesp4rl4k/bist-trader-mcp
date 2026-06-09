"""Watchlist PA scanner — rank symbols by setup quality."""

from __future__ import annotations

from typing import Any, Literal

from .fundamental_context import build_fundamental_context
from .market_profiles import get_market_profile
from .mtf_analysis import analyze_mtf_price_action
from .position_design import design_trade_setup
from .price_action import analyze_price_action

Direction = Literal["long", "short"]


def _score_setup(plan: dict[str, Any], pa: dict[str, Any]) -> float:
    if not plan.get("approved"):
        return -1.0
    rr = float(plan.get("best_risk_reward") or 0)
    structure = pa.get("market_structure") or "ranging"
    structure_bonus = {"bullish": 2.0, "bearish": 2.0, "transition": 0.5, "ranging": 0.0}
    bias = pa.get("bias") or "neutral"
    bias_bonus = 1.0 if bias in ("long", "short") else 0.0
    return rr + structure_bonus.get(structure, 0) + bias_bonus


def scan_price_action_watchlist(
    series: dict[str, dict[str, list[float]]],
    *,
    directions: list[Direction] | None = None,
    equity: float = 100_000.0,
    min_risk_reward: float = 2.0,
    min_score: float = 0.0,
) -> dict[str, Any]:
    """Scan multiple symbols with pre-fetched OHLCV.

    `series` shape:
      { "BINANCE:BTCUSDT": {"closes": [...], "highs": [...], "lows": [...]}, ... }
    """
    dirs = directions or ["long", "short"]
    results: list[dict[str, Any]] = []

    for symbol, ohlcv in series.items():
        closes = ohlcv.get("closes") or []
        highs = ohlcv.get("highs") or []
        lows = ohlcv.get("lows") or []
        if len(closes) < 30:
            results.append({"symbol": symbol, "error": "insufficient_bars"})
            continue
        try:
            prof = get_market_profile(symbol)
            pa = analyze_price_action(closes, highs, lows, **prof["pa_kwargs"])
        except ValueError as e:
            results.append({"symbol": symbol, "error": str(e)})
            continue

        best: dict[str, Any] | None = None
        best_score = -999.0
        for d in dirs:
            setup_key = "suggested_long_setup" if d == "long" else "suggested_short_setup"
            setup = pa.get(setup_key)
            if not setup:
                continue
            sz = prof["sizing_overlay"]
            plan = design_trade_setup(
                symbol=symbol,
                direction=d,
                entry_price=setup["entry"],
                stop_price=setup["stop"],
                target_prices=setup["targets"],
                equity=equity,
                min_risk_reward=float(
                    min_risk_reward
                    if min_risk_reward != 2.0
                    else prof["defaults"]["min_risk_reward"]
                ),
                risk_per_trade_pct=float(sz["risk_per_trade_pct"]),
                max_notional_pct=float(sz["max_single_asset_notional_pct"]),
            )
            sc = _score_setup(plan, pa)
            if sc > best_score:
                best_score = sc
                best = {
                    "symbol": symbol,
                    "direction": d,
                    "score": round(sc, 2),
                    "structure": pa.get("market_structure"),
                    "bias": pa.get("bias"),
                    "entry": plan.get("entry"),
                    "stop": plan.get("stop"),
                    "best_rr": plan.get("best_risk_reward"),
                    "approved": plan.get("approved"),
                    "plan": plan,
                }
        if best and best_score >= min_score:
            results.append(best)
        else:
            results.append({
                "symbol": symbol,
                "structure": pa.get("market_structure"),
                "bias": pa.get("bias"),
                "setup_found": False,
            })

    ranked = sorted(
        [r for r in results if r.get("approved")],
        key=lambda x: float(x.get("score") or 0),
        reverse=True,
    )
    return {
        "source": "bist-trader-mcp — pa_scanner.scan_price_action_watchlist",
        "symbols_scanned": len(series),
        "setups_found": len(ranked),
        "top_setups": ranked[:10],
        "all_results": results,
    }


def scan_mtf_watchlist(
    series: dict[str, dict[str, dict[str, list[float]]]],
    *,
    equity: float = 100_000.0,
    min_risk_reward: float = 2.0,
    min_quality: str = "a",
) -> dict[str, Any]:
    """MTF scan: each symbol has htf + ltf OHLCV blocks.

    series shape:
      { "SYM": { "htf": {closes, highs, lows}, "ltf": {closes, highs, lows} } }
    """
    quality_rank = {"a_plus": 4, "a": 3, "b": 2, "c": 1, "no_trade": 0, "conflict": -1}
    min_rank = quality_rank.get(min_quality, 3)
    results: list[dict[str, Any]] = []

    for symbol, blocks in series.items():
        htf = blocks.get("htf") or {}
        ltf = blocks.get("ltf") or {}
        try:
            prof = get_market_profile(symbol)
            mtf = analyze_mtf_price_action(
                htf.get("closes") or [],
                htf.get("highs") or [],
                htf.get("lows") or [],
                ltf.get("closes") or [],
                ltf.get("highs") or [],
                ltf.get("lows") or [],
                pa_kwargs=prof["pa_kwargs"],
            )
        except ValueError as e:
            results.append({"symbol": symbol, "error": str(e)})
            continue

        setup = mtf.get("recommended_setup")
        direction = mtf.get("aligned_direction")
        if direction not in ("long", "short") or not setup:
            results.append({
                "symbol": symbol,
                "trade_quality": mtf.get("trade_quality"),
                "setup_found": False,
            })
            continue

        sz = prof["sizing_overlay"]
        plan = design_trade_setup(
            symbol=symbol,
            direction=direction,
            entry_price=setup["entry"],
            stop_price=setup["stop"],
            target_prices=setup["targets"],
            equity=equity,
            min_risk_reward=float(
                min_risk_reward
                if min_risk_reward != 2.0
                else prof["defaults"]["min_risk_reward"]
            ),
            risk_per_trade_pct=float(sz["risk_per_trade_pct"]),
            max_notional_pct=float(sz["max_single_asset_notional_pct"]),
        )
        q = mtf.get("trade_quality") or "no_trade"
        if quality_rank.get(q, 0) < min_rank or not plan.get("approved"):
            continue
        results.append({
            "symbol": symbol,
            "trade_quality": q,
            "direction": direction,
            "htf_bias": mtf.get("htf_bias"),
            "ltf_bias": mtf.get("ltf_bias"),
            "entry": plan.get("entry"),
            "stop": plan.get("stop"),
            "best_rr": plan.get("best_risk_reward"),
            "plan": plan,
        })

    ranked = sorted(
        results,
        key=lambda x: quality_rank.get(str(x.get("trade_quality")), 0),
        reverse=True,
    )
    return {
        "source": "bist-trader-mcp — pa_scanner.scan_mtf_watchlist",
        "symbols_scanned": len(series),
        "setups_found": len(ranked),
        "top_setups": ranked[:10],
        "all_results": results,
    }


def scan_ta_fundamental_watchlist(
    series: dict[str, dict[str, dict[str, list[float]]]],
    *,
    equity: float = 100_000.0,
    min_risk_reward: float = 2.0,
    min_quality: str = "a",
    market: str | None = None,
) -> dict[str, Any]:
    """MTF technical scan + per-symbol fundamental research checklist."""
    scan = scan_mtf_watchlist(
        series,
        equity=equity,
        min_risk_reward=min_risk_reward,
        min_quality=min_quality,
    )
    enriched: list[dict[str, Any]] = []
    for row in scan.get("all_results") or []:
        sym = row.get("symbol")
        if not sym:
            enriched.append(row)
            continue
        fund = build_fundamental_context(str(sym), market=market)
        enriched.append({**row, "fundamental": fund, "research_tools": fund.get("recommended_mcp_tools")})
    scan["all_results"] = enriched
    scan["top_setups"] = [
        {**r, "fundamental": build_fundamental_context(str(r["symbol"]), market=market)}
        for r in (scan.get("top_setups") or [])
        if r.get("symbol")
    ]
    scan["source"] = "bist-trader-mcp — pa_scanner.scan_ta_fundamental_watchlist"
    return scan


__all__ = [
    "scan_price_action_watchlist",
    "scan_mtf_watchlist",
    "scan_ta_fundamental_watchlist",
]

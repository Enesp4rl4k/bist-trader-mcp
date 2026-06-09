"""Trade setup design + portfolio risk gates — pure math."""

from __future__ import annotations

from typing import Any, Literal

from .price_action import analyze_price_action

Direction = Literal["long", "short"]


DEFAULT_RISK_RULES: dict[str, float | int] = {
    "default_equity": 100_000.0,
    "risk_per_trade_pct": 1.0,
    "min_risk_reward": 2.0,
    "max_open_positions": 5,
    "max_single_asset_notional_pct": 20.0,
    "max_total_open_risk_pct": 5.0,
    "max_daily_loss_pct": 3.0,
}


def position_size_from_stop(
    equity: float,
    entry_price: float,
    stop_price: float,
    direction: Direction,
    risk_per_trade_pct: float = 1.0,
    max_notional_pct_of_equity: float | None = None,
) -> dict[str, Any]:
    """Size so a stop-out loses risk_per_trade_pct% of equity.

    If max_notional_pct_of_equity is set, units are capped so notional
    does not exceed that fraction of equity (e.g. 20% single-asset limit).
    Actual risk at stop may then be below the target risk_pct.
    """
    if equity <= 0:
        raise ValueError("equity must be > 0")
    if entry_price <= 0:
        raise ValueError("entry_price must be > 0")
    if risk_per_trade_pct <= 0:
        raise ValueError("risk_per_trade_pct must be > 0")

    stop_distance = abs(entry_price - stop_price)
    if stop_distance <= 0:
        raise ValueError("stop must differ from entry")

    if direction == "long" and stop_price >= entry_price:
        raise ValueError("long stop must be below entry")
    if direction == "short" and stop_price <= entry_price:
        raise ValueError("short stop must be above entry")

    target_risk = equity * (risk_per_trade_pct / 100.0)
    units = target_risk / stop_distance
    notional = units * entry_price
    capped = False

    if max_notional_pct_of_equity is not None and max_notional_pct_of_equity > 0:
        max_notional = equity * (max_notional_pct_of_equity / 100.0)
        if notional > max_notional:
            units = max_notional / entry_price
            notional = units * entry_price
            capped = True

    risk_amount = units * stop_distance

    return {
        "equity": equity,
        "entry_price": entry_price,
        "stop_price": stop_price,
        "stop_distance": stop_distance,
        "direction": direction,
        "risk_amount": risk_amount,
        "risk_per_trade_pct": risk_per_trade_pct,
        "target_risk_amount": target_risk,
        "notional_capped": capped,
        "units": units,
        "notional": notional,
        "notional_pct_of_equity": (notional / equity) * 100.0,
        "actual_risk_pct_of_equity": (risk_amount / equity) * 100.0,
        "leverage": notional / equity,
    }


def _risk_reward(
    entry: float,
    stop: float,
    target: float,
    direction: Direction,
) -> float:
    risk = abs(entry - stop)
    if risk <= 0:
        return 0.0
    if direction == "long":
        reward = target - entry
    else:
        reward = entry - target
    return reward / risk if reward > 0 else 0.0


def design_trade_setup(
    *,
    symbol: str,
    direction: Direction,
    entry_price: float,
    stop_price: float,
    target_prices: list[float],
    equity: float = DEFAULT_RISK_RULES["default_equity"],  # type: ignore[assignment]
    risk_per_trade_pct: float = DEFAULT_RISK_RULES["risk_per_trade_pct"],  # type: ignore[assignment]
    min_risk_reward: float = DEFAULT_RISK_RULES["min_risk_reward"],  # type: ignore[assignment]
    max_notional_pct: float = DEFAULT_RISK_RULES["max_single_asset_notional_pct"],  # type: ignore[assignment]
    closes: list[float] | None = None,
    highs: list[float] | None = None,
    lows: list[float] | None = None,
) -> dict[str, Any]:
    """Build a complete trade plan with sizing and approval gate."""
    equity_f = float(equity)
    targets = [float(t) for t in target_prices if t is not None]
    reject_reasons: list[str] = []

    try:
        sizing = position_size_from_stop(
            equity=equity_f,
            entry_price=float(entry_price),
            stop_price=float(stop_price),
            direction=direction,
            risk_per_trade_pct=float(risk_per_trade_pct),
            max_notional_pct_of_equity=float(max_notional_pct),
        )
    except ValueError as e:
        return {"error": "bad_input", "detail": str(e)}

    target_rows: list[dict[str, Any]] = []
    for i, tp in enumerate(targets, start=1):
        rr = _risk_reward(float(entry_price), float(stop_price), tp, direction)
        target_rows.append(
            {
                "label": f"TP{i}",
                "price": tp,
                "risk_reward": round(rr, 2),
            }
        )

    best_rr = max((r["risk_reward"] for r in target_rows), default=0.0)
    if best_rr < float(min_risk_reward):
        reject_reasons.append(
            f"best R:R {best_rr:.2f} below minimum {min_risk_reward}"
        )

    pa_context: dict[str, Any] | None = None
    if closes and highs and lows:
        try:
            pa_context = analyze_price_action(closes, highs, lows)
        except ValueError:
            pa_context = None

    approved = len(reject_reasons) == 0

    return {
        "source": "bist-trader-mcp — position_design.design_trade_setup",
        "symbol": symbol,
        "direction": direction,
        "entry": float(entry_price),
        "stop": float(stop_price),
        "targets": target_rows,
        "best_risk_reward": round(best_rr, 2),
        "min_risk_reward_required": float(min_risk_reward),
        "approved": approved,
        "reject_reasons": reject_reasons,
        "sizing": sizing,
        "price_action_context": pa_context,
        "disclaimer": (
            "Research / planning output only — not investment advice. "
            "Verify levels on your chart before trading."
        ),
    }


def _position_risk_at_stop(pos: dict[str, Any], equity: float) -> float:
    entry = float(pos.get("entry") or pos.get("entry_price") or 0)
    stop = float(pos.get("stop") or pos.get("stop_price") or 0)
    size = float(pos.get("units") or pos.get("size") or 0)
    if entry <= 0 or size <= 0:
        return 0.0
    return abs(entry - stop) * size


def _normalise_symbol(symbol: str) -> str:
    return symbol.upper().replace(" ", "")


def portfolio_risk_check(
    *,
    equity: float,
    open_positions: list[dict[str, Any]] | None = None,
    proposed_trade: dict[str, Any] | None = None,
    rules: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Check open book + optional new trade against portfolio risk rules."""
    equity_f = float(equity)
    if equity_f <= 0:
        return {"error": "bad_input", "detail": "equity must be > 0"}

    merged_rules = {**DEFAULT_RISK_RULES, **(rules or {})}
    positions = list(open_positions or [])
    violations: list[str] = []
    warnings: list[str] = []

    open_count = len(positions)
    max_pos = int(merged_rules["max_open_positions"])
    if proposed_trade and open_count >= max_pos:
        violations.append(
            f"max open positions ({max_pos}) reached — cannot add new trade"
        )

    total_risk = sum(_position_risk_at_stop(p, equity_f) for p in positions)
    if proposed_trade and "sizing" in proposed_trade:
        total_risk += float(proposed_trade["sizing"].get("risk_amount") or 0)
    elif proposed_trade:
        total_risk += _position_risk_at_stop(proposed_trade, equity_f)

    max_total_risk_pct = float(merged_rules["max_total_open_risk_pct"])
    total_risk_pct = (total_risk / equity_f) * 100.0
    if total_risk_pct > max_total_risk_pct:
        violations.append(
            f"total open risk {total_risk_pct:.2f}% exceeds "
            f"limit {max_total_risk_pct}%"
        )

    max_single_pct = float(merged_rules["max_single_asset_notional_pct"])
    exposure_by_symbol: dict[str, float] = {}
    for p in positions:
        sym = _normalise_symbol(str(p.get("symbol") or ""))
        notional = float(p.get("notional") or 0)
        if notional <= 0:
            entry = float(p.get("entry") or p.get("entry_price") or 0)
            units = float(p.get("units") or p.get("size") or 0)
            notional = entry * units
        exposure_by_symbol[sym] = exposure_by_symbol.get(sym, 0.0) + notional

    if proposed_trade:
        psym = _normalise_symbol(str(proposed_trade.get("symbol") or ""))
        pnotional = 0.0
        if "sizing" in proposed_trade:
            pnotional = float(proposed_trade["sizing"].get("notional") or 0)
        exposure_by_symbol[psym] = exposure_by_symbol.get(psym, 0.0) + pnotional

    for sym, notional in exposure_by_symbol.items():
        if not sym:
            continue
        pct = (notional / equity_f) * 100.0
        if pct > max_single_pct:
            violations.append(
                f"{sym} notional {pct:.1f}% exceeds single-asset limit "
                f"{max_single_pct}%"
            )

    daily_pnl = sum(float(p.get("unrealised_pnl") or 0) for p in positions)
    daily_loss_limit = float(merged_rules["max_daily_loss_pct"])
    daily_loss_pct = (-daily_pnl / equity_f * 100.0) if daily_pnl < 0 else 0.0
    if daily_loss_pct >= daily_loss_limit:
        violations.append(
            f"daily loss {daily_loss_pct:.2f}% hit limit {daily_loss_limit}%"
        )

    same_dir_count = 0
    if proposed_trade:
        pdirection = proposed_trade.get("direction")
        for p in positions:
            if p.get("direction") == pdirection:
                same_dir_count += 1
        if same_dir_count >= 3:
            warnings.append(
                f"{same_dir_count} open {pdirection} positions — "
                "directional concentration elevated"
            )

    approved = len(violations) == 0
    return {
        "source": "bist-trader-mcp — position_design.portfolio_risk_check",
        "equity": equity_f,
        "open_position_count": open_count,
        "total_risk_amount": round(total_risk, 2),
        "total_risk_pct_of_equity": round(total_risk_pct, 2),
        "exposure_by_symbol": {
            k: round(v, 2) for k, v in exposure_by_symbol.items()
        },
        "rules_applied": merged_rules,
        "approved": approved,
        "violations": violations,
        "warnings": warnings,
        "disclaimer": (
            "Portfolio gate for planning — does not connect to a broker. "
            "Pass realised/unrealised PnL on positions for daily loss checks."
        ),
    }


def design_from_price_action(
    *,
    symbol: str,
    closes: list[float],
    highs: list[float],
    lows: list[float],
    direction: Direction | None = None,
    equity: float = DEFAULT_RISK_RULES["default_equity"],  # type: ignore[assignment]
    risk_per_trade_pct: float = DEFAULT_RISK_RULES["risk_per_trade_pct"],  # type: ignore[assignment]
    min_risk_reward: float = DEFAULT_RISK_RULES["min_risk_reward"],  # type: ignore[assignment]
    max_notional_pct: float = DEFAULT_RISK_RULES["max_single_asset_notional_pct"],  # type: ignore[assignment]
) -> dict[str, Any]:
    """Analyze PA then design a trade from the suggested setup."""
    try:
        pa = analyze_price_action(closes, highs, lows)
    except ValueError as e:
        return {"error": "bad_input", "detail": str(e)}

    pick = direction
    if pick is None:
        bias = pa.get("bias")
        if bias == "long":
            pick = "long"
        elif bias == "short":
            pick = "short"
        else:
            return {
                "error": "no_clear_bias",
                "detail": "market is ranging — specify direction explicitly",
                "price_action": pa,
            }

    setup_key = "suggested_long_setup" if pick == "long" else "suggested_short_setup"
    setup = pa.get(setup_key)
    if not setup:
        return {
            "error": "no_setup",
            "detail": f"no viable {pick} setup for current structure",
            "price_action": pa,
        }

    plan = design_trade_setup(
        symbol=symbol,
        direction=pick,
        entry_price=setup["entry"],
        stop_price=setup["stop"],
        target_prices=setup["targets"],
        equity=equity,
        risk_per_trade_pct=risk_per_trade_pct,
        min_risk_reward=min_risk_reward,
        max_notional_pct=max_notional_pct,
        closes=closes,
        highs=highs,
        lows=lows,
    )
    plan["auto_setup_rationale"] = setup.get("rationale")
    plan["price_action"] = pa
    return plan


__all__ = [
    "DEFAULT_RISK_RULES",
    "position_size_from_stop",
    "design_trade_setup",
    "design_from_price_action",
    "portfolio_risk_check",
]

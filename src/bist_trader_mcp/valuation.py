"""Intrinsic valuation — two-stage DCF, reverse DCF, WACC, margin of safety.

Part of **Faz B/C** (``docs/HEDGE_FUND_GRADE_PLAN.md``): turns the cash-flow line
items from ``fundamental_statements`` into a fair value and a margin of safety vs
the market price — the valuation leg a buy-side analyst applies on top of quality.

Pure math (no network), so it is fully testable and works on figures supplied
manually, by an LLM, or from the KAP-fed ``PanelStore``. All rates are decimals
(0.45 = 45%). Reverse DCF answers the key question for an expensive market: *what
growth is the current price already pricing in?*
"""

from __future__ import annotations

from typing import Any


def wacc(
    *,
    risk_free: float,
    equity_risk_premium: float,
    beta: float = 1.0,
    cost_of_debt: float | None = None,
    tax_rate: float = 0.25,
    equity_weight: float = 1.0,
    debt_weight: float = 0.0,
) -> dict[str, Any]:
    """Weighted average cost of capital via CAPM cost of equity.

    For TL-denominated BIST DCFs use a TL risk-free (e.g. the 10Y DİBS yield) so
    the discount rate and the (nominal) cash flows are in the same currency/regime.
    """
    cost_of_equity = risk_free + beta * equity_risk_premium
    after_tax_kd = None if cost_of_debt is None else cost_of_debt * (1 - tax_rate)
    total_w = equity_weight + debt_weight
    if total_w <= 0:
        raise ValueError("equity_weight + debt_weight must be > 0")
    ew, dw = equity_weight / total_w, debt_weight / total_w
    rate = cost_of_equity * ew + (after_tax_kd or 0.0) * dw
    return {
        "wacc": round(rate, 4),
        "cost_of_equity": round(cost_of_equity, 4),
        "after_tax_cost_of_debt": None if after_tax_kd is None else round(after_tax_kd, 4),
        "equity_weight": round(ew, 4),
        "debt_weight": round(dw, 4),
    }


def _explicit_growth_path(
    high_growth: float, years: int, fade_to: float | None
) -> list[float]:
    """Per-year growth rates; optionally fade linearly from high_growth to fade_to."""
    if fade_to is None:
        return [high_growth] * years
    if years <= 1:
        return [high_growth]
    step = (fade_to - high_growth) / (years - 1)
    return [high_growth + step * i for i in range(years)]


def two_stage_dcf(
    fcf0: float,
    *,
    discount_rate: float,
    high_growth: float,
    years: int = 5,
    terminal_growth: float = 0.05,
    fade_to: float | None = None,
    net_debt: float = 0.0,
    shares_outstanding: float | None = None,
    growth_path: list[float] | None = None,
) -> dict[str, Any]:
    """Two-stage free-cash-flow DCF → enterprise/equity value (+ per share).

    Stage 1: ``years`` of explicit growth (constant, or fading to ``fade_to``, or a
    caller-supplied ``growth_path``). Stage 2: Gordon terminal value at
    ``terminal_growth``. Requires ``discount_rate > terminal_growth``.
    """
    if discount_rate <= terminal_growth:
        return {"available": False, "reason": "discount_rate_must_exceed_terminal_growth"}
    if years < 1:
        return {"available": False, "reason": "years_must_be_positive"}

    path = growth_path or _explicit_growth_path(high_growth, years, fade_to)
    flows: list[float] = []
    fcf = fcf0
    pv_explicit = 0.0
    for t, g in enumerate(path, start=1):
        fcf = fcf * (1 + g)
        pv = fcf / (1 + discount_rate) ** t
        flows.append(round(fcf, 2))
        pv_explicit += pv

    fcf_terminal = fcf * (1 + terminal_growth)
    tv = fcf_terminal / (discount_rate - terminal_growth)
    pv_terminal = tv / (1 + discount_rate) ** len(path)

    enterprise_value = pv_explicit + pv_terminal
    equity_value = enterprise_value - net_debt
    per_share = None
    if shares_outstanding and shares_outstanding > 0:
        per_share = equity_value / shares_outstanding

    return {
        "available": True,
        "enterprise_value": round(enterprise_value, 2),
        "equity_value": round(equity_value, 2),
        "fair_value_per_share": None if per_share is None else round(per_share, 4),
        "pv_explicit": round(pv_explicit, 2),
        "pv_terminal": round(pv_terminal, 2),
        "terminal_value_pct": (
            round(pv_terminal / enterprise_value, 4) if enterprise_value else None
        ),
        "projected_fcf": flows,
        "assumptions": {
            "discount_rate": discount_rate,
            "high_growth": high_growth,
            "terminal_growth": terminal_growth,
            "years": years,
            "fade_to": fade_to,
            "net_debt": net_debt,
        },
    }


def reverse_dcf(
    market_cap: float,
    fcf0: float,
    *,
    discount_rate: float,
    years: int = 5,
    terminal_growth: float = 0.05,
    net_debt: float = 0.0,
) -> dict[str, Any]:
    """Solve for the stage-1 growth the current market cap already implies.

    Bisection on the explicit-stage growth rate so that the DCF equity value equals
    ``market_cap``. A high implied growth on a mature firm = the market is demanding
    a lot; a low/negative one = pessimism is priced in.
    """
    if discount_rate <= terminal_growth:
        return {"available": False, "reason": "discount_rate_must_exceed_terminal_growth"}
    if fcf0 == 0:
        return {"available": False, "reason": "fcf0_is_zero"}

    def equity_for(g: float) -> float:
        d = two_stage_dcf(
            fcf0, discount_rate=discount_rate, high_growth=g, years=years,
            terminal_growth=terminal_growth, net_debt=net_debt,
        )
        return d["equity_value"]

    lo, hi = -0.60, 1.50
    # Monotonic increasing in g; ensure the target is bracketed.
    if equity_for(lo) > market_cap:
        return {"available": True, "implied_growth": None,
                "note": "market_cap below value even at -60% growth (deep pessimism)"}
    if equity_for(hi) < market_cap:
        return {"available": True, "implied_growth": None,
                "note": "market_cap above value even at +150% growth (extreme optimism)"}

    for _ in range(100):
        mid = (lo + hi) / 2
        if equity_for(mid) < market_cap:
            lo = mid
        else:
            hi = mid
    implied = (lo + hi) / 2
    return {
        "available": True,
        "implied_growth": round(implied, 4),
        "discount_rate": discount_rate,
        "terminal_growth": terminal_growth,
        "years": years,
    }


def value_equity(
    *,
    fcf0: float,
    discount_rate: float,
    high_growth: float,
    shares_outstanding: float,
    current_price: float | None = None,
    market_cap: float | None = None,
    years: int = 5,
    terminal_growth: float = 0.05,
    fade_to: float | None = None,
    net_debt: float = 0.0,
) -> dict[str, Any]:
    """Full valuation: DCF fair value + reverse DCF + margin of safety + TR note."""
    dcf = two_stage_dcf(
        fcf0, discount_rate=discount_rate, high_growth=high_growth, years=years,
        terminal_growth=terminal_growth, fade_to=fade_to, net_debt=net_debt,
        shares_outstanding=shares_outstanding,
    )
    if market_cap is None and current_price is not None and shares_outstanding:
        market_cap = current_price * shares_outstanding

    rev = None
    if market_cap:
        rev = reverse_dcf(
            market_cap, fcf0, discount_rate=discount_rate, years=years,
            terminal_growth=terminal_growth, net_debt=net_debt,
        )

    fv = dcf.get("fair_value_per_share")
    mos = None
    verdict = "na"
    if fv is not None and current_price and current_price > 0:
        mos = fv / current_price - 1.0
        verdict = "undervalued" if mos > 0.15 else ("overvalued" if mos < -0.15 else "fair")

    return {
        "source": "bist-trader-mcp — valuation.value_equity",
        "dcf": dcf,
        "reverse_dcf": rev,
        "current_price": current_price,
        "margin_of_safety": None if mos is None else round(mos, 4),
        "verdict": verdict,
        "summary_tr": _valuation_summary_tr(dcf, rev, current_price, mos, verdict, high_growth),
    }


def _valuation_summary_tr(
    dcf: dict[str, Any], rev: dict[str, Any] | None,
    price: float | None, mos: float | None, verdict: str, assumed_growth: float,
) -> str:
    if not dcf.get("available"):
        return f"DCF hesaplanamadı: {dcf.get('reason')}"
    fv = dcf.get("fair_value_per_share")
    tr = {"undervalued": "ucuz", "overvalued": "pahalı", "fair": "makul", "na": "—"}[verdict]
    parts = [f"DCF gerçeğe uygun değer {fv}"]
    if price:
        parts.append(f"fiyat {price}")
    if mos is not None:
        parts.append(f"güvenlik marjı %{mos * 100:.0f} ({tr})")
    if rev and rev.get("implied_growth") is not None:
        parts.append(
            f"piyasanın fiyatladığı büyüme %{rev['implied_growth'] * 100:.0f} "
            f"(varsayım %{assumed_growth * 100:.0f})"
        )
    return " | ".join(parts)


__all__ = ["wacc", "two_stage_dcf", "reverse_dcf", "value_equity"]

"""CFO-grade financial statement analysis — from KAP line items to stock picks.

This is the core of **Faz B** (``docs/HEDGE_FUND_GRADE_PLAN.md``): given the raw
line items a company files with KAP (income statement, balance sheet, cash flow),
compute the same battery of checks a financial analyst / CFO runs:

  * ratio analysis      — profitability, liquidity, leverage, efficiency
  * DuPont              — what drives ROE (margin × turnover × leverage)
  * Piotroski F-Score   — 9-point fundamental momentum / quality
  * Altman Z-Score      — bankruptcy distance (emerging-market Z'' by default)
  * Beneish M-Score     — earnings-manipulation probability
  * accruals quality    — cash backing of reported earnings (Sloan)
  * growth              — YoY revenue / EBIT / net income / FCF
  * selection score     — composite -100..+100 + grade + red flags, for screening

Everything here is a **pure function** of the supplied statements (no network), so
it is fully testable and works whether the line items come from the KAP ingest +
``PanelStore`` or are supplied manually. Two consecutive periods (current + prior)
unlock the trend-based checks (Piotroski, Beneish, growth); a single period still
yields ratios, Altman and a partial score.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# ---------------------------------------------------------------------------
# Input model — one reporting period's line items (all optional / best-effort)
# ---------------------------------------------------------------------------


@dataclass
class FinancialPeriod:
    """Line items for a single reporting period (annual or TTM).

    Use the canonical names below; missing items are tolerated and the dependent
    metrics simply report as unavailable. Magnitudes in the issuer's currency;
    ``capex`` may be passed as a positive magnitude or the (negative) cash-flow
    figure — both are handled.
    """

    period_end: str = ""
    is_inflation_adjusted: bool = False

    # Income statement
    revenue: float | None = None
    cogs: float | None = None
    gross_profit: float | None = None
    sga: float | None = None
    operating_income: float | None = None      # EBIT
    ebitda: float | None = None
    depreciation: float | None = None
    interest_expense: float | None = None
    pretax_income: float | None = None
    tax_expense: float | None = None
    net_income: float | None = None

    # Balance sheet
    total_assets: float | None = None
    current_assets: float | None = None
    cash: float | None = None
    inventory: float | None = None
    receivables: float | None = None
    ppe: float | None = None                    # net property, plant & equipment
    current_liabilities: float | None = None
    short_term_debt: float | None = None
    long_term_debt: float | None = None
    total_debt: float | None = None
    total_liabilities: float | None = None
    total_equity: float | None = None
    retained_earnings: float | None = None
    shares_outstanding: float | None = None

    # Cash flow
    operating_cash_flow: float | None = None    # CFO
    capex: float | None = None
    free_cash_flow: float | None = None
    dividends_paid: float | None = None

    # Market (optional — enables valuation overlays)
    market_cap: float | None = None

    # --- derived getters with sensible fallbacks ----------------------------
    def gp(self) -> float | None:
        if self.gross_profit is not None:
            return self.gross_profit
        return _sub(self.revenue, self.cogs)

    def ebit(self) -> float | None:
        if self.operating_income is not None:
            return self.operating_income
        if self.ebitda is not None and self.depreciation is not None:
            return self.ebitda - self.depreciation
        return self.pretax_income  # last resort (pre-interest unknown)

    def ebitda_(self) -> float | None:
        if self.ebitda is not None:
            return self.ebitda
        return _add(self.ebit(), self.depreciation)

    def debt(self) -> float | None:
        if self.total_debt is not None:
            return self.total_debt
        return _add(self.short_term_debt, self.long_term_debt)

    def fcf(self) -> float | None:
        if self.free_cash_flow is not None:
            return self.free_cash_flow
        if self.operating_cash_flow is None or self.capex is None:
            return None
        return self.operating_cash_flow - abs(self.capex)

    def working_capital(self) -> float | None:
        return _sub(self.current_assets, self.current_liabilities)

    def tax_rate(self) -> float:
        r = _div(self.tax_expense, self.pretax_income)
        if r is None or r < 0:
            return 0.22  # TR statutory fallback
        return min(r, 0.45)


# ---------------------------------------------------------------------------
# None-safe arithmetic
# ---------------------------------------------------------------------------


def _div(a: float | None, b: float | None) -> float | None:
    if a is None or b is None or b == 0:
        return None
    return a / b


def _sub(a: float | None, b: float | None) -> float | None:
    return None if a is None or b is None else a - b


def _add(a: float | None, b: float | None) -> float | None:
    return None if a is None or b is None else a + b


def _avg(a: float | None, b: float | None) -> float | None:
    if a is None:
        return b
    if b is None:
        return a
    return (a + b) / 2.0


def _r(x: float | None, n: int = 4) -> float | None:
    return None if x is None else round(x, n)


def _gt(a: float | None, b: float | None) -> int:
    """1 when both values are known and a > b, else 0 (for binary score tests)."""
    return 1 if (a is not None and b is not None and a > b) else 0


def _lt(a: float | None, b: float | None) -> int:
    return 1 if (a is not None and b is not None and a < b) else 0


# ---------------------------------------------------------------------------
# 1. Ratio analysis
# ---------------------------------------------------------------------------


def compute_ratios(cur: FinancialPeriod, prior: FinancialPeriod | None = None) -> dict[str, Any]:
    """Profitability, liquidity, leverage and efficiency ratios.

    Balance-sheet denominators use period averages when a prior period is given
    (the correct treatment for flow/stock ratios like ROE, ROA, turnover).
    """
    avg_assets = _avg(cur.total_assets, prior.total_assets if prior else None)
    avg_equity = _avg(cur.total_equity, prior.total_equity if prior else None)
    avg_inv = _avg(cur.inventory, prior.inventory if prior else None)

    ebit = cur.ebit()
    nopat = None if ebit is None else ebit * (1 - cur.tax_rate())
    invested = None
    if cur.debt() is not None and cur.total_equity is not None:
        invested = cur.debt() + cur.total_equity - (cur.cash or 0.0)

    net_debt = _sub(cur.debt(), cur.cash)
    rec_ratio = _div(cur.receivables, cur.revenue)
    receivable_days = None if rec_ratio is None else rec_ratio * 365

    out = {
        # profitability
        "gross_margin": _r(_div(cur.gp(), cur.revenue)),
        "operating_margin": _r(_div(ebit, cur.revenue)),
        "net_margin": _r(_div(cur.net_income, cur.revenue)),
        "ebitda_margin": _r(_div(cur.ebitda_(), cur.revenue)),
        "roe": _r(_div(cur.net_income, avg_equity)),
        "roa": _r(_div(cur.net_income, avg_assets)),
        "roic": _r(_div(nopat, invested)),
        # liquidity
        "current_ratio": _r(_div(cur.current_assets, cur.current_liabilities)),
        "quick_ratio": _r(_div(_sub(cur.current_assets, cur.inventory), cur.current_liabilities)),
        "cash_ratio": _r(_div(cur.cash, cur.current_liabilities)),
        # leverage / solvency
        "debt_to_equity": _r(_div(cur.debt(), cur.total_equity)),
        "net_debt_to_ebitda": _r(_div(net_debt, cur.ebitda_())),
        "interest_coverage": _r(_div(ebit, cur.interest_expense)),
        "liabilities_to_assets": _r(_div(cur.total_liabilities, cur.total_assets)),
        # efficiency
        "asset_turnover": _r(_div(cur.revenue, avg_assets)),
        "inventory_turnover": _r(_div(cur.cogs, avg_inv)),
        "receivable_days": _r(receivable_days),
        # cash
        "fcf": _r(cur.fcf(), 2),
        "fcf_margin": _r(_div(cur.fcf(), cur.revenue)),
        "fcf_yield": _r(_div(cur.fcf(), cur.market_cap)),
        "cfo_to_net_income": _r(_div(cur.operating_cash_flow, cur.net_income)),
    }
    return out


# ---------------------------------------------------------------------------
# 2. DuPont decomposition of ROE
# ---------------------------------------------------------------------------


def dupont_roe(cur: FinancialPeriod, prior: FinancialPeriod | None = None) -> dict[str, Any]:
    """ROE = net margin × asset turnover × equity multiplier."""
    avg_assets = _avg(cur.total_assets, prior.total_assets if prior else None)
    avg_equity = _avg(cur.total_equity, prior.total_equity if prior else None)
    net_margin = _div(cur.net_income, cur.revenue)
    asset_turn = _div(cur.revenue, avg_assets)
    equity_mult = _div(avg_assets, avg_equity)
    roe = None
    if None not in (net_margin, asset_turn, equity_mult):
        roe = net_margin * asset_turn * equity_mult
    return {
        "net_margin": _r(net_margin),
        "asset_turnover": _r(asset_turn),
        "equity_multiplier": _r(equity_mult),
        "roe": _r(roe),
        "driver": _dupont_driver(net_margin, asset_turn, equity_mult),
    }


def _dupont_driver(nm: float | None, at: float | None, em: float | None) -> str:
    """Which lever dominates ROE — useful colour for stock selection."""
    if em is not None and em > 3.0:
        return "leverage_driven"
    if nm is not None and at is not None:
        if nm > 0.15 and at < 0.7:
            return "margin_driven"
        if at > 1.2 and nm < 0.10:
            return "turnover_driven"
    return "balanced"


# ---------------------------------------------------------------------------
# 3. Piotroski F-Score (0..9)
# ---------------------------------------------------------------------------


def piotroski_f_score(cur: FinancialPeriod, prior: FinancialPeriod | None) -> dict[str, Any]:
    """9 binary fundamental-strength tests. Needs a prior period for 5 of them."""
    pts: dict[str, int] = {}
    roa = _div(cur.net_income, cur.total_assets)
    cfo = cur.operating_cash_flow

    pts["roa_positive"] = _gt(roa, 0.0)
    pts["cfo_positive"] = _gt(cfo, 0.0)
    # Accruals: CFO exceeds net income (earnings backed by cash).
    pts["accruals"] = _gt(cfo, cur.net_income)

    if prior:
        pts["roa_rising"] = _gt(roa, _div(prior.net_income, prior.total_assets))
        pts["leverage_down"] = _lt(
            _div(cur.long_term_debt, cur.total_assets),
            _div(prior.long_term_debt, prior.total_assets),
        )
        pts["current_ratio_up"] = _gt(
            _div(cur.current_assets, cur.current_liabilities),
            _div(prior.current_assets, prior.current_liabilities),
        )
        so_cur, so_prior = cur.shares_outstanding, prior.shares_outstanding
        if so_cur is not None and so_prior is not None:
            pts["no_dilution"] = 1 if so_cur <= so_prior * 1.001 else 0
        else:
            pts["no_dilution"] = 0
        pts["gross_margin_up"] = _gt(
            _div(cur.gp(), cur.revenue), _div(prior.gp(), prior.revenue)
        )
        pts["asset_turnover_up"] = _gt(
            _div(cur.revenue, cur.total_assets), _div(prior.revenue, prior.total_assets)
        )

    score = sum(pts.values())
    max_score = 9 if prior else 3
    grade = "strong" if score >= 7 else ("weak" if score <= 3 else "neutral")
    if not prior:
        grade = "partial"
    return {"score": score, "max": max_score, "components": pts, "grade": grade}


# ---------------------------------------------------------------------------
# 4. Altman Z-Score (emerging-market Z'' by default)
# ---------------------------------------------------------------------------


def altman_z_score(cur: FinancialPeriod, *, model: str = "em") -> dict[str, Any]:
    """Bankruptcy distance.

    ``model="em"`` (default) → Altman Z''-Score for emerging markets / non-
    manufacturers: uses book equity (no sales term, no market cap needed), plus a
    +3.25 constant. ``model="original"`` → the classic 5-factor manufacturing Z
    (needs market_cap). Zones for EM Z'': >5.85 safe, 3.75–5.85 grey, <3.75 distress.
    """
    ta = cur.total_assets
    if ta is None or ta == 0:
        return {"available": False, "model": model}
    x1 = _div(cur.working_capital(), ta)
    x2 = _div(cur.retained_earnings, ta)
    x3 = _div(cur.ebit(), ta)

    if model == "original":
        x4 = _div(cur.market_cap, cur.total_liabilities)
        x5 = _div(cur.revenue, ta)
        if None in (x1, x2, x3, x4, x5):
            return {"available": False, "model": model,
                    "missing": _which_none({"x1": x1, "x2": x2, "x3": x3, "x4": x4, "x5": x5})}
        z = 1.2 * x1 + 1.4 * x2 + 3.3 * x3 + 0.6 * x4 + 1.0 * x5
        zone = "safe" if z > 2.99 else ("grey" if z >= 1.81 else "distress")
        return {
            "available": True, "model": "original", "z_score": _r(z, 3), "zone": zone,
            "components": {"x1": _r(x1), "x2": _r(x2), "x3": _r(x3),
                           "x4": _r(x4), "x5": _r(x5)},
        }

    # Emerging-market Z'' (double prime)
    x4 = _div(cur.total_equity, cur.total_liabilities)
    if None in (x1, x2, x3, x4):
        return {"available": False, "model": "em",
                "missing": _which_none({"x1": x1, "x2": x2, "x3": x3, "x4": x4})}
    z = 6.56 * x1 + 3.26 * x2 + 6.72 * x3 + 1.05 * x4 + 3.25
    zone = "safe" if z > 5.85 else ("grey" if z >= 3.75 else "distress")
    return {"available": True, "model": "em", "z_score": _r(z, 3), "zone": zone,
            "components": {"x1": _r(x1), "x2": _r(x2), "x3": _r(x3), "x4": _r(x4)}}


def _which_none(d: dict[str, Any]) -> list[str]:
    return [k for k, v in d.items() if v is None]


# ---------------------------------------------------------------------------
# 5. Beneish M-Score (earnings manipulation)
# ---------------------------------------------------------------------------


def beneish_m_score(cur: FinancialPeriod, prior: FinancialPeriod | None) -> dict[str, Any]:
    """8-variable manipulation probability. M > -1.78 ⇒ likely manipulator.

    Requires a prior period and several balance-sheet items (PPE, SGA,
    depreciation). Returns ``available=False`` with the missing inputs when it
    cannot be computed rather than guessing.
    """
    if prior is None:
        return {"available": False, "reason": "needs_prior_period"}

    need = {
        "rev_t": cur.revenue, "rev_p": prior.revenue,
        "rec_t": cur.receivables, "rec_p": prior.receivables,
        "gp_t": cur.gp(), "gp_p": prior.gp(),
        "ca_t": cur.current_assets, "ca_p": prior.current_assets,
        "ppe_t": cur.ppe, "ppe_p": prior.ppe,
        "ta_t": cur.total_assets, "ta_p": prior.total_assets,
        "dep_t": cur.depreciation, "dep_p": prior.depreciation,
        "sga_t": cur.sga, "sga_p": prior.sga,
        "ni_t": cur.net_income, "cfo_t": cur.operating_cash_flow,
        "td_t": cur.total_liabilities, "td_p": prior.total_liabilities,
    }
    missing = _which_none(need)
    if missing:
        return {"available": False, "missing": missing}

    dsri = _div(_div(need["rec_t"], need["rev_t"]), _div(need["rec_p"], need["rev_p"]))
    gm_t = _div(need["gp_t"], need["rev_t"])
    gm_p = _div(need["gp_p"], need["rev_p"])
    gmi = _div(gm_p, gm_t)
    aqi = _div(
        1 - _div(need["ca_t"] + need["ppe_t"], need["ta_t"]),
        1 - _div(need["ca_p"] + need["ppe_p"], need["ta_p"]),
    )
    sgi = _div(need["rev_t"], need["rev_p"])
    deprate_t = _div(need["dep_t"], need["dep_t"] + need["ppe_t"])
    deprate_p = _div(need["dep_p"], need["dep_p"] + need["ppe_p"])
    depi = _div(deprate_p, deprate_t)
    sgai = _div(_div(need["sga_t"], need["rev_t"]), _div(need["sga_p"], need["rev_p"]))
    lvgi = _div(_div(need["td_t"], need["ta_t"]), _div(need["td_p"], need["ta_p"]))
    tata = _div(need["ni_t"] - need["cfo_t"], need["ta_t"])

    if None in (dsri, gmi, aqi, sgi, depi, sgai, lvgi, tata):
        return {"available": False, "reason": "ratio_undefined"}

    m = (-4.84 + 0.92 * dsri + 0.528 * gmi + 0.404 * aqi + 0.892 * sgi
         + 0.115 * depi - 0.172 * sgai + 4.679 * tata - 0.327 * lvgi)
    return {
        "available": True,
        "m_score": _r(m, 3),
        "flag": "likely_manipulator" if m > -1.78 else "clean",
        "components": {k: _r(v) for k, v in {
            "DSRI": dsri, "GMI": gmi, "AQI": aqi, "SGI": sgi,
            "DEPI": depi, "SGAI": sgai, "LVGI": lvgi, "TATA": tata}.items()},
    }


# ---------------------------------------------------------------------------
# 6. Accruals quality (Sloan)
# ---------------------------------------------------------------------------


def accruals_quality(cur: FinancialPeriod, prior: FinancialPeriod | None = None) -> dict[str, Any]:
    """Cash backing of earnings. High positive accruals ⇒ lower quality."""
    avg_assets = _avg(cur.total_assets, prior.total_assets if prior else None)
    accruals = None
    if cur.net_income is not None and cur.operating_cash_flow is not None:
        accruals = _div(cur.net_income - cur.operating_cash_flow, avg_assets)
    quality = "na"
    if accruals is not None:
        quality = "high" if accruals < 0.05 else ("low" if accruals > 0.15 else "moderate")
    return {
        "accruals_ratio": _r(accruals),
        "cfo_to_net_income": _r(_div(cur.operating_cash_flow, cur.net_income)),
        "quality": quality,
    }


# ---------------------------------------------------------------------------
# 7. Growth (YoY)
# ---------------------------------------------------------------------------


def growth_metrics(cur: FinancialPeriod, prior: FinancialPeriod | None) -> dict[str, Any]:
    """Year-over-year growth. Note: nominal unless statements are TMS 29 adjusted."""
    if prior is None:
        return {"available": False}

    def g(a: float | None, b: float | None) -> float | None:
        if a is None or b is None or b == 0:
            return None
        return (a - b) / abs(b)

    return {
        "available": True,
        "nominal_warning": not (cur.is_inflation_adjusted and prior.is_inflation_adjusted),
        "revenue_growth": _r(g(cur.revenue, prior.revenue)),
        "ebit_growth": _r(g(cur.ebit(), prior.ebit())),
        "net_income_growth": _r(g(cur.net_income, prior.net_income)),
        "fcf_growth": _r(g(cur.fcf(), prior.fcf())),
    }


# ---------------------------------------------------------------------------
# 8. Composite selection score
# ---------------------------------------------------------------------------


def selection_score(
    *, ratios: dict[str, Any], piotroski: dict[str, Any], altman: dict[str, Any],
    beneish: dict[str, Any], accruals: dict[str, Any], growth: dict[str, Any],
) -> dict[str, Any]:
    """Blend the analyses into a -100..+100 stock-selection score + red flags.

    Quality and safety are weighted ahead of raw growth, and any hard red flag
    (manipulation, distress) caps the score so a screen never surfaces a value
    trap as a buy.
    """
    score = 0.0
    factors: list[str] = []
    red_flags: list[str] = []

    def add(pts: float, label: str | None = None) -> None:
        nonlocal score
        score += pts
        if label and abs(pts) >= 3:
            factors.append(label)

    roe = ratios.get("roe")
    if roe is not None:
        add(_band(roe, [(0.0, -12), (0.10, 0), (0.20, 8)], 14),
            "strong_roe" if roe > 0.15 else ("weak_roe" if roe < 0.05 else None))
    roic = ratios.get("roic")
    if roic is not None:
        add(_band(roic, [(0.0, -8), (0.10, 0), (0.20, 6)], 10),
            "high_roic" if roic > 0.15 else None)
    nm = ratios.get("net_margin")
    if nm is not None:
        add(_band(nm, [(0.0, -8), (0.08, 0), (0.18, 4)], 6), "loss_making" if nm < 0 else None)

    f = piotroski.get("score")
    if f is not None and piotroski.get("grade") != "partial":
        add((f - 5) * 3.0, "piotroski_strong" if f >= 7 else ("piotroski_weak" if f <= 3 else None))

    zone = altman.get("zone")
    if zone == "safe":
        add(8, "altman_safe")
    elif zone == "distress":
        add(-18, "altman_distress")
        red_flags.append("bankruptcy_distress")
    elif zone == "grey":
        add(-4)

    if beneish.get("flag") == "likely_manipulator":
        add(-20, "earnings_manipulation_flag")
        red_flags.append("earnings_manipulation")

    aq = accruals.get("quality")
    if aq == "high":
        add(6, "high_earnings_quality")
    elif aq == "low":
        add(-8, "low_earnings_quality")
        red_flags.append("low_earnings_quality")

    cov = ratios.get("interest_coverage")
    if cov is not None and cov < 2.0:
        add(-8, "weak_interest_coverage")
        red_flags.append("weak_interest_coverage")
    nde = ratios.get("net_debt_to_ebitda")
    if nde is not None and nde > 4.0:
        add(-6, "high_leverage")
        red_flags.append("high_leverage")

    if growth.get("available"):
        rg = growth.get("revenue_growth")
        if rg is not None:
            add(_band(rg, [(0.0, -6), (0.15, 2)], 6),
                "revenue_growth" if rg > 0.10 else "revenue_decline")
        eg = growth.get("net_income_growth")
        if eg is not None:
            add(_band(eg, [(-0.10, -8), (0.0, -3), (0.15, 3)], 7),
                "earnings_growth" if eg > 0.10 else ("earnings_decline" if eg < 0 else None))

    fcf = ratios.get("fcf")
    if fcf is not None and fcf < 0:
        add(-6, "negative_fcf")

    score = round(max(-100.0, min(100.0, score)), 1)
    # Hard red flags cap the upside — never recommend a flagged name.
    if red_flags and score > 0:
        score = min(score, -5.0)

    bias = "bullish" if score >= 15 else ("bearish" if score <= -15 else "neutral")
    grade = _grade(score)
    return {
        "score": score, "grade": grade, "bias": bias,
        "factors": factors, "red_flags": red_flags,
    }


def _band(value: float, bands: list[tuple[float, float]], default: float) -> float:
    for bound, pts in bands:
        if value <= bound:
            return pts
    return default


def _grade(score: float) -> str:
    if score >= 35:
        return "A"
    if score >= 15:
        return "B"
    if score >= -10:
        return "C"
    if score >= -30:
        return "D"
    return "F"


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


def analyze_financials(
    cur: FinancialPeriod | dict[str, Any],
    prior: FinancialPeriod | dict[str, Any] | None = None,
    *,
    ticker: str | None = None,
    altman_model: str = "em",
) -> dict[str, Any]:
    """Run the full CFO-grade battery and return a structured report + TR summary.

    Accepts ``FinancialPeriod`` instances or plain dicts (so it works directly off
    KAP-ingested rows). The ``selection.score`` field is what a screen ranks on.
    """
    c = cur if isinstance(cur, FinancialPeriod) else FinancialPeriod(**cur)
    p = None
    if prior is not None:
        p = prior if isinstance(prior, FinancialPeriod) else FinancialPeriod(**prior)

    ratios = compute_ratios(c, p)
    dupont = dupont_roe(c, p)
    piotroski = piotroski_f_score(c, p)
    altman = altman_z_score(c, model=altman_model)
    beneish = beneish_m_score(c, p)
    accruals = accruals_quality(c, p)
    growth = growth_metrics(c, p)
    selection = selection_score(
        ratios=ratios, piotroski=piotroski, altman=altman,
        beneish=beneish, accruals=accruals, growth=growth,
    )

    return {
        "source": "bist-trader-mcp — fundamental_statements.analyze_financials",
        "ticker": ticker,
        "period_end": c.period_end,
        "is_inflation_adjusted": c.is_inflation_adjusted,
        "ratios": ratios,
        "dupont": dupont,
        "piotroski": piotroski,
        "altman": altman,
        "beneish": beneish,
        "accruals": accruals,
        "growth": growth,
        "selection": selection,
        "summary_tr": summarize_financials_tr(
            ticker, ratios, piotroski, altman, beneish, growth, selection,
            inflation_adjusted=c.is_inflation_adjusted,
        ),
    }


def summarize_financials_tr(
    ticker: str | None,
    ratios: dict[str, Any],
    piotroski: dict[str, Any],
    altman: dict[str, Any],
    beneish: dict[str, Any],
    growth: dict[str, Any],
    selection: dict[str, Any],
    *,
    inflation_adjusted: bool = False,
) -> str:
    """One-paragraph Turkish verdict for chat_report / screening output."""
    def pct(v: Any) -> str:
        return f"%{v * 100:.1f}" if isinstance(v, (int, float)) else "—"

    head = f"{ticker or 'Hisse'}: seçim skoru {selection['score']:+.0f} " \
           f"(not {selection['grade']}, {selection['bias']})"
    body = [
        f"ROE {pct(ratios.get('roe'))} · net marj {pct(ratios.get('net_margin'))}",
        f"Piotroski {piotroski.get('score')}/{piotroski.get('max')}",
        f"Altman {altman.get('zone', 'na')}",
    ]
    if beneish.get("available"):
        manip = beneish.get("flag") == "likely_manipulator"
        body.append("Beneish " + ("MANİPÜLASYON RİSKİ" if manip else "temiz"))
    if growth.get("available") and growth.get("revenue_growth") is not None:
        suffix = " (nominal!)" if growth.get("nominal_warning") else " (reel)"
        body.append(f"ciro büy. {pct(growth.get('revenue_growth'))}{suffix}")
    line = head + " | " + " · ".join(body)
    if selection.get("red_flags"):
        line += " | ⚠ " + ", ".join(selection["red_flags"])
    if not inflation_adjusted:
        line += " | not: tablolar TMS29-düzeltmesiz olabilir"
    return line


def to_fusion_entry(analysis: dict[str, Any]) -> dict[str, Any]:
    """Adapt an :func:`analyze_financials` result into a fusion-ready score entry.

    Callers place the returned dict at
    ``fund_enrich["fetched"]["financial_statements_score"]`` so the fusion layer
    (``fundamental_score.score_from_enrich``) uses this CFO-grade, statement-based
    signal as the dominant fundamental core (preferred over the Yahoo ratio pack),
    and so hard red flags (manipulation / distress) can gate the trade.
    """
    sel = analysis.get("selection") or {}
    return {
        "available": True,
        "source": "financial_statements",
        "score": sel.get("score"),
        "grade": sel.get("grade"),
        "bias": sel.get("bias"),
        "factors": sel.get("factors") or [],
        "red_flags": sel.get("red_flags") or [],
        "period_end": analysis.get("period_end"),
        "is_inflation_adjusted": analysis.get("is_inflation_adjusted"),
    }


__all__ = [
    "FinancialPeriod",
    "to_fusion_entry",
    "compute_ratios",
    "dupont_roe",
    "piotroski_f_score",
    "altman_z_score",
    "beneish_m_score",
    "accruals_quality",
    "growth_metrics",
    "selection_score",
    "analyze_financials",
    "summarize_financials_tr",
]

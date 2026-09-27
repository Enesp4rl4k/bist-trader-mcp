"""Advanced company valuation — driver-based DCF, cost of capital, uncertainty,
bank models, multiples and a football-field summary.

Everything here is pure math (no network) so it can be tested exactly and fed
by hand, by the model, by KAP statements or by the Yahoo auto-fill in tools.

Conventions
-----------
- Rates and margins are decimals (0.45 = 45 %).
- **Currency / inflation must be consistent.** For TL with high inflation use
  either nominal TL cash flows with a nominal TL WACC (10Y DİBS based), or real
  cash flows with a real WACC — :func:`fisher` converts between them. The
  sanity checks flag the usual mixes (e.g. a nominal WACC with a terminal
  growth below inflation = shrinking forever in real terms).
- Driver DCF values the **firm** (FCFF discounted at WACC), then bridges to
  equity: − debt + cash − minority interests − preferred + non-operating assets.
"""

from __future__ import annotations

import math
import random
import statistics
from typing import Any

# --------------------------------------------------------------------------- rates


def fisher(rate: float, inflation: float, *, to: str = "real") -> float:
    """(1 + nominal) = (1 + real)(1 + inflation). ``to`` = "real" or "nominal"."""
    if to == "real":
        return (1 + rate) / (1 + inflation) - 1
    if to == "nominal":
        return (1 + rate) * (1 + inflation) - 1
    raise ValueError("to must be 'real' or 'nominal'")


def estimate_beta(
    stock_closes: list[float],
    index_closes: list[float],
    *,
    blume: bool = True,
) -> dict[str, Any]:
    """OLS beta of stock returns on index returns (aligned, same frequency).

    Blume adjustment (0.67 β + 0.33) pulls raw betas toward 1, which predicts
    future betas better than the raw estimate.
    """
    k = min(len(stock_closes), len(index_closes))
    s, m = stock_closes[-k:], index_closes[-k:]
    rs = [b / a - 1 for a, b in zip(s, s[1:], strict=False) if a > 0]
    rm = [b / a - 1 for a, b in zip(m, m[1:], strict=False) if a > 0]
    n = min(len(rs), len(rm))
    if n < 20:
        raise ValueError(f"need ≥ 21 aligned prices for a beta, got {n + 1}")
    rs, rm = rs[-n:], rm[-n:]
    ms, mm = statistics.fmean(rs), statistics.fmean(rm)
    cov = sum((a - ms) * (b - mm) for a, b in zip(rs, rm, strict=True)) / (n - 1)
    var = sum((b - mm) ** 2 for b in rm) / (n - 1)
    if var <= 0:
        raise ValueError("index returns have zero variance")
    beta = cov / var
    sd_s = statistics.stdev(rs)
    corr = cov / (sd_s * math.sqrt(var)) if sd_s > 0 else 0.0
    se = math.sqrt(max(0.0, (1 - corr ** 2) * (sd_s ** 2) / var / (n - 2))) if n > 2 else None
    return {
        "raw_beta": round(beta, 4),
        "beta": round(0.67 * beta + 0.33, 4) if blume else round(beta, 4),
        "blume_adjusted": blume,
        "r_squared": round(corr ** 2, 4),
        "std_error": None if se is None else round(se, 4),
        "observations": n,
    }


def unlever_beta(levered: float, debt_to_equity: float, tax_rate: float) -> float:
    """Hamada: βu = βl / (1 + (1 − t)·D/E)."""
    return levered / (1 + (1 - tax_rate) * debt_to_equity)


def relever_beta(unlevered: float, debt_to_equity: float, tax_rate: float) -> float:
    return unlevered * (1 + (1 - tax_rate) * debt_to_equity)


def build_wacc(
    *,
    risk_free: float,
    beta: float,
    equity_risk_premium: float,
    country_risk_premium: float = 0.0,
    pre_tax_cost_of_debt: float | None = None,
    tax_rate: float = 0.25,
    market_cap: float | None = None,
    debt: float = 0.0,
    size_premium: float = 0.0,
) -> dict[str, Any]:
    """CAPM cost of equity (+ country and size premia) and market-value weights.

    ``risk_free`` in the valuation currency (TL: 10Y DİBS). If it is a local-
    currency government yield it already contains Turkey's default risk, so
    pass ``country_risk_premium`` only on top of a *mature-market* ERP, and do
    not double count it in ``risk_free`` for USD valuations.
    """
    ke = risk_free + beta * (equity_risk_premium + country_risk_premium) + size_premium
    kd_pre = pre_tax_cost_of_debt if pre_tax_cost_of_debt is not None else risk_free + 0.02
    kd = kd_pre * (1 - tax_rate)
    if market_cap and market_cap > 0:
        we = market_cap / (market_cap + max(debt, 0.0))
    else:
        we = 1.0 if not debt else 0.7
    wd = 1 - we
    return {
        "wacc": round(we * ke + wd * kd, 5),
        "cost_of_equity": round(ke, 5),
        "pre_tax_cost_of_debt": round(kd_pre, 5),
        "after_tax_cost_of_debt": round(kd, 5),
        "equity_weight": round(we, 4),
        "debt_weight": round(wd, 4),
        "inputs": {"risk_free": risk_free, "beta": beta, "erp": equity_risk_premium,
                   "crp": country_risk_premium, "size_premium": size_premium,
                   "tax_rate": tax_rate},
    }


# --------------------------------------------------------------------------- DCF


def _path(value: float | list[float], years: int, fade_to: float | None = None) -> list[float]:
    if isinstance(value, list):
        if len(value) < years:
            value = value + [value[-1]] * (years - len(value))
        return [float(v) for v in value[:years]]
    if fade_to is None or years == 1:
        return [float(value)] * years
    step = (fade_to - value) / (years - 1)
    return [value + step * i for i in range(years)]


def driver_dcf(
    *,
    revenue0: float,
    wacc: float,
    revenue_growth: float | list[float],
    ebit_margin: float | list[float],
    years: int = 10,
    growth_fade_to: float | None = None,
    margin_fade_to: float | None = None,
    tax_rate: float = 0.25,
    da_pct_revenue: float = 0.04,
    capex_pct_revenue: float = 0.05,
    nwc_pct_revenue: float = 0.10,
    terminal_growth: float = 0.03,
    terminal_roic: float | None = None,
    mid_year: bool = True,
    debt: float = 0.0,
    cash: float = 0.0,
    minority_interest: float = 0.0,
    preferred: float = 0.0,
    non_operating_assets: float = 0.0,
    shares_outstanding: float | None = None,
) -> dict[str, Any]:
    """FCFF DCF from operating drivers.

    Per year t: revenue grows; EBIT = margin × revenue; NOPAT = EBIT(1 − tax);
    FCFF = NOPAT + D&A − capex − ΔNWC, with D&A / capex / NWC as % of revenue.

    Terminal value (Gordon, end of year N): if ``terminal_roic`` is given the
    value-driver formula FCFF_N+1 = NOPAT_N+1 · (1 − g / RONIC) keeps growth and
    reinvestment consistent (RONIC = WACC ⇒ growth adds no value); otherwise the
    last FCFF grows at g. Mid-year convention discounts year-t flows at t − 0.5.
    """
    if wacc <= terminal_growth:
        return {"available": False, "reason": "wacc_must_exceed_terminal_growth"}
    if revenue0 <= 0 or years < 1:
        return {"available": False, "reason": "revenue0_and_years_must_be_positive"}
    g_path = _path(revenue_growth, years, growth_fade_to)
    m_path = _path(ebit_margin, years, margin_fade_to)

    rows = []
    rev_prev = revenue0
    pv_sum = 0.0
    for t in range(1, years + 1):
        rev = rev_prev * (1 + g_path[t - 1])
        ebit = rev * m_path[t - 1]
        nopat = ebit * (1 - tax_rate)
        da = rev * da_pct_revenue
        capex = rev * capex_pct_revenue
        d_nwc = nwc_pct_revenue * (rev - rev_prev)
        fcff = nopat + da - capex - d_nwc
        disc = (1 + wacc) ** (t - 0.5 if mid_year else t)
        pv = fcff / disc
        pv_sum += pv
        rows.append({"year": t, "revenue": round(rev, 2), "growth": round(g_path[t - 1], 4),
                     "ebit_margin": round(m_path[t - 1], 4), "nopat": round(nopat, 2),
                     "reinvestment": round(capex + d_nwc - da, 2), "fcff": round(fcff, 2),
                     "pv": round(pv, 2)})
        rev_prev = rev

    last = rows[-1]
    nopat_next = last["nopat"] * (1 + terminal_growth)
    if terminal_roic is not None:
        if terminal_roic <= 0:
            return {"available": False, "reason": "terminal_roic_must_be_positive"}
        fcff_next = nopat_next * (1 - terminal_growth / terminal_roic)
        tv_method = "value_driver"
    else:
        fcff_next = last["fcff"] * (1 + terminal_growth)
        tv_method = "gordon_on_last_fcff"
    tv = fcff_next / (wacc - terminal_growth)
    pv_tv = tv / (1 + wacc) ** years
    ev = pv_sum + pv_tv
    equity = ev - debt + cash - minority_interest - preferred + non_operating_assets
    per_share = equity / shares_outstanding if shares_outstanding else None
    ebit_next = last["revenue"] * m_path[-1] * (1 + terminal_growth)
    return {
        "available": True,
        "enterprise_value": round(ev, 2),
        "equity_value": round(equity, 2),
        "fair_value_per_share": None if per_share is None else round(per_share, 4),
        "pv_explicit": round(pv_sum, 2),
        "pv_terminal": round(pv_tv, 2),
        "terminal_value_pct": round(pv_tv / ev, 4) if ev else None,
        "terminal_method": tv_method,
        # forward EV/EBIT the terminal value implies — compare with sector multiples
        "implied_exit_ev_ebit": round(tv / ebit_next, 2) if ebit_next > 0 else None,
        "projection": rows,
        "bridge": {"enterprise_value": round(ev, 2), "debt": -debt, "cash": cash,
                   "minority_interest": -minority_interest, "preferred": -preferred,
                   "non_operating_assets": non_operating_assets},
        "assumptions": {"wacc": wacc, "terminal_growth": terminal_growth, "tax_rate": tax_rate,
                        "years": years, "mid_year": mid_year, "terminal_roic": terminal_roic},
    }


def sensitivity(
    base_kwargs: dict[str, Any],
    *,
    wacc_steps: tuple[float, ...] = (-0.02, -0.01, 0.0, 0.01, 0.02),
    growth_steps: tuple[float, ...] = (-0.01, -0.005, 0.0, 0.005, 0.01),
) -> dict[str, Any]:
    """Fair value per share (or equity value) over WACC × terminal growth."""
    w0, g0 = base_kwargs["wacc"], base_kwargs.get("terminal_growth", 0.03)
    key = "fair_value_per_share" if base_kwargs.get("shares_outstanding") else "equity_value"
    grid = []
    for dw in wacc_steps:
        row = []
        for dg in growth_steps:
            r = driver_dcf(**{**base_kwargs, "wacc": w0 + dw, "terminal_growth": g0 + dg})
            row.append(r.get(key) if r.get("available") else None)
        grid.append(row)
    return {"metric": key, "wacc": [round(w0 + d, 4) for d in wacc_steps],
            "terminal_growth": [round(g0 + d, 4) for d in growth_steps], "values": grid}


def scenario_valuation(
    base_kwargs: dict[str, Any],
    scenarios: dict[str, dict[str, Any]],
    probabilities: dict[str, float],
) -> dict[str, Any]:
    """Probability-weighted value over named scenarios (overrides of driver inputs)."""
    total_p = sum(probabilities.get(k, 0.0) for k in scenarios)
    if total_p <= 0:
        raise ValueError("scenario probabilities must sum to > 0")
    key = "fair_value_per_share" if base_kwargs.get("shares_outstanding") else "equity_value"
    rows, expected = {}, 0.0
    for name, overrides in scenarios.items():
        r = driver_dcf(**{**base_kwargs, **overrides})
        if not r.get("available"):
            raise ValueError(f"scenario {name}: {r.get('reason')}")
        p = probabilities.get(name, 0.0) / total_p
        rows[name] = {"value": r[key], "probability": round(p, 4),
                      "terminal_value_pct": r["terminal_value_pct"]}
        expected += p * r[key]
    return {"metric": key, "expected_value": round(expected, 4), "scenarios": rows}


def monte_carlo_dcf(
    base_kwargs: dict[str, Any],
    *,
    n: int = 2000,
    growth_sd: float = 0.03,
    margin_sd: float = 0.02,
    wacc_sd: float = 0.01,
    terminal_growth_sd: float = 0.005,
    price: float | None = None,
    seed: int | None = 7,
) -> dict[str, Any]:
    """Distribution of value when growth, margin, WACC and terminal growth are uncertain.

    Each draw shifts the whole growth / margin path by one normal shock (paths
    stay coherent), draws that break WACC > g are resampled out.
    """
    rng = random.Random(seed)
    years = base_kwargs.get("years", 10)
    g_base = _path(base_kwargs["revenue_growth"], years, base_kwargs.get("growth_fade_to"))
    m_base = _path(base_kwargs["ebit_margin"], years, base_kwargs.get("margin_fade_to"))
    key = "fair_value_per_share" if base_kwargs.get("shares_outstanding") else "equity_value"
    values: list[float] = []
    rejected = 0
    for _ in range(n):
        dg, dm = rng.gauss(0, growth_sd), rng.gauss(0, margin_sd)
        w = base_kwargs["wacc"] + rng.gauss(0, wacc_sd)
        tg = base_kwargs.get("terminal_growth", 0.03) + rng.gauss(0, terminal_growth_sd)
        if w - tg < 0.01:
            rejected += 1
            continue
        kw = {**base_kwargs, "wacc": w, "terminal_growth": tg,
              "revenue_growth": [g + dg for g in g_base],
              "ebit_margin": [max(-0.5, m + dm) for m in m_base],
              "growth_fade_to": None, "margin_fade_to": None}
        r = driver_dcf(**kw)
        if r.get("available"):
            values.append(r[key])
    if len(values) < 50:
        raise ValueError("too few valid Monte Carlo draws; loosen the input spreads")
    values.sort()

    def pct(p: float) -> float:
        return round(values[min(len(values) - 1, int(p * len(values)))], 4)

    out = {"metric": key, "draws": len(values), "rejected": rejected,
           "mean": round(statistics.fmean(values), 4), "p5": pct(0.05), "p25": pct(0.25),
           "p50": pct(0.50), "p75": pct(0.75), "p95": pct(0.95)}
    if price is not None:
        out["prob_above_price"] = round(sum(1 for v in values if v > price) / len(values), 4)
    return out


# --------------------------------------------------------------------------- other models


def dividend_discount(
    *,
    dividend0: float,
    cost_of_equity: float,
    high_growth: float,
    years: int = 5,
    terminal_growth: float = 0.03,
) -> dict[str, Any]:
    """Two-stage dividend discount model (per share)."""
    if cost_of_equity <= terminal_growth:
        return {"available": False, "reason": "cost_of_equity_must_exceed_terminal_growth"}
    d, pv = dividend0, 0.0
    for t in range(1, years + 1):
        d *= 1 + high_growth
        pv += d / (1 + cost_of_equity) ** t
    tv = d * (1 + terminal_growth) / (cost_of_equity - terminal_growth)
    pv_tv = tv / (1 + cost_of_equity) ** years
    return {"available": True, "value_per_share": round(pv + pv_tv, 4),
            "pv_dividends": round(pv, 4), "pv_terminal": round(pv_tv, 4)}


def justified_pb(roe: float, cost_of_equity: float, growth: float) -> float:
    """Steady-state P/B = (ROE − g) / (ke − g): the bank/insurer anchor."""
    if cost_of_equity <= growth:
        raise ValueError("cost_of_equity must exceed growth")
    return (roe - growth) / (cost_of_equity - growth)


def residual_income(
    *,
    book_value0: float,
    roe: float | list[float],
    cost_of_equity: float,
    payout: float = 0.3,
    years: int = 5,
    terminal_growth: float = 0.03,
    roe_fade_to: float | None = None,
    shares_outstanding: float | None = None,
) -> dict[str, Any]:
    """Residual income (excess return) model — the right DCF for banks.

    Value = BV0 + Σ (ROE_t − ke)·BV_t−1 / (1+ke)^t + terminal RI. Book grows by
    retained earnings (ROE × (1 − payout)). A bank earning exactly its cost of
    equity is worth book.
    """
    if cost_of_equity <= terminal_growth:
        return {"available": False, "reason": "cost_of_equity_must_exceed_terminal_growth"}
    path = _path(roe, years, roe_fade_to)
    bv, pv, rows = book_value0, 0.0, []
    for t, r in enumerate(path, start=1):
        ri = (r - cost_of_equity) * bv
        pv += ri / (1 + cost_of_equity) ** t
        rows.append({"year": t, "book_value": round(bv, 2), "roe": round(r, 4),
                     "residual_income": round(ri, 2)})
        bv *= 1 + r * (1 - payout)
    last_ri = rows[-1]["residual_income"]
    tv = last_ri * (1 + terminal_growth) / (cost_of_equity - terminal_growth)
    pv_tv = tv / (1 + cost_of_equity) ** years
    equity = book_value0 + pv + pv_tv
    return {
        "available": True,
        "equity_value": round(equity, 2),
        "value_per_share": round(equity / shares_outstanding, 4) if shares_outstanding else None,
        "implied_pb": round(equity / book_value0, 3) if book_value0 else None,
        "pv_excess_returns": round(pv, 2),
        "pv_terminal": round(pv_tv, 2),
        "projection": rows,
    }


# --------------------------------------------------------------------------- multiples

_MULTIPLE_BASE = {
    "pe": ("net_income", "equity"),
    "pb": ("book_value", "equity"),
    "ps": ("revenue", "equity"),
    "ev_ebitda": ("ebitda", "enterprise"),
    "ev_sales": ("revenue", "enterprise"),
}


def relative_valuation(
    peers: list[dict[str, Any]],
    target: dict[str, Any],
    *,
    shares_outstanding: float,
    net_debt: float = 0.0,
) -> dict[str, Any]:
    """Implied value per share from peer median multiples.

    ``peers``: [{ticker, pe, pb, ps, ev_ebitda, ev_sales}], non-positive or
    missing multiples are ignored. ``target``: {net_income, book_value, revenue,
    ebitda}. EV multiples are bridged to equity with ``net_debt``.
    """
    out: dict[str, Any] = {}
    for m, (metric, kind) in _MULTIPLE_BASE.items():
        vals = sorted(float(p[m]) for p in peers
                      if isinstance(p.get(m), (int, float)) and p[m] > 0 and math.isfinite(p[m]))
        base = target.get(metric)
        if len(vals) < 2 or not base or base <= 0:
            continue
        med = statistics.median(vals)
        q1 = vals[len(vals) // 4]
        q3 = vals[(3 * len(vals)) // 4] if len(vals) > 3 else vals[-1]
        bridge = net_debt if kind == "enterprise" else 0.0
        low, mid, high = ((mult * base - bridge) / shares_outstanding for mult in (q1, med, q3))
        out[m] = {"peer_median": round(med, 3), "peers_used": len(vals),
                  "low": round(low, 4), "base": round(mid, 4), "high": round(high, 4)}
    return {"multiples": out,
            "median_of_methods": round(statistics.median(v["base"] for v in out.values()), 4)
            if out else None}


# --------------------------------------------------------------------------- summary


def football_field(
    methods: dict[str, dict[str, float]],
    *,
    price: float | None = None,
    weights: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Combine method ranges {name: {low, base, high}} into a blended fair value."""
    usable = {k: v for k, v in methods.items() if v and v.get("base") is not None}
    if not usable:
        return {"available": False, "reason": "no_methods"}
    w = {k: (weights or {}).get(k, 1.0) for k in usable}
    tw = sum(w.values()) or 1.0
    blended = sum(usable[k]["base"] * w[k] for k in usable) / tw
    out = {"available": True, "methods": usable,
           "weights": {k: round(v / tw, 3) for k, v in w.items()},
           "blended_value": round(blended, 4)}
    if price:
        mos = blended / price - 1
        out["price"] = price
        out["margin_of_safety"] = round(mos, 4)
        out["verdict"] = "undervalued" if mos > 0.2 else "overvalued" if mos < -0.15 else "fair"
    return out


def sanity_checks(
    dcf: dict[str, Any],
    *,
    expected_inflation: float | None = None,
    long_run_real_gdp: float = 0.03,
) -> list[str]:
    """Turkish-language warnings about fragile or inconsistent assumptions."""
    notes: list[str] = []
    if not dcf.get("available"):
        return [f"DCF hesaplanamadı: {dcf.get('reason')}"]
    a = dcf["assumptions"]
    tvp = dcf.get("terminal_value_pct") or 0
    if tvp > 0.85:
        notes.append(f"Değerin %{tvp * 100:.0f}'i terminal değerden geliyor — sonuç "
                     "terminal büyüme ve WACC varsayımına çok duyarlı.")
    if a["wacc"] - a["terminal_growth"] < 0.02:
        notes.append("WACC ile terminal büyüme arası %2'den az — terminal değer patlıyor.")
    if expected_inflation is not None:
        real_tg = fisher(a["terminal_growth"], expected_inflation)
        if real_tg < -0.01:
            notes.append(f"Terminal büyüme (%{a['terminal_growth'] * 100:.0f}) beklenen "
                         f"enflasyonun (%{expected_inflation * 100:.0f}) altında: şirket reel "
                         "olarak sonsuza dek küçülüyor sayılıyor. Nominal WACC kullanıyorsan "
                         "terminal büyüme de nominal olmalı.")
        if real_tg > long_run_real_gdp + 0.01:
            notes.append("Terminal büyüme reel olarak uzun vadeli ekonomik büyümenin üstünde — "
                         "hiçbir şirket ekonomiden sonsuza dek hızlı büyüyemez.")
    elif a["terminal_growth"] > 0.06:
        notes.append("Terminal büyüme %6'nın üstünde: yüksek enflasyonlu TL modeli değilse "
                     "iyimser; expected_inflation vererek kontrol et.")
    proj = dcf.get("projection") or []
    if proj and proj[-1]["fcff"] < 0:
        notes.append("Son projeksiyon yılında FCFF negatif — terminal değer negatif akıştan "
                     "büyütülüyor; marj/yatırım varsayımlarını gözden geçir.")
    if a.get("terminal_roic") is None:
        notes.append("terminal_roic verilmedi: terminal büyüme için gereken yatırım "
                     "modellenmiyor (değer-sürücü formülü daha tutarlı).")
    return notes


__all__ = [
    "build_wacc", "dividend_discount", "driver_dcf", "estimate_beta", "fisher",
    "football_field", "justified_pb", "monte_carlo_dcf", "relative_valuation",
    "relever_beta", "residual_income", "sanity_checks", "scenario_valuation",
    "sensitivity", "unlever_beta",
]

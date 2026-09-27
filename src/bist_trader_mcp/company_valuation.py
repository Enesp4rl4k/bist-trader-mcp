"""One-call company valuation: auto-fill → cost of capital → model → summary.

Picks the right model for the business:

- **industrial / services**: driver-based FCFF DCF + sensitivity + scenarios +
  Monte Carlo (+ DDM when dividends are paid)
- **banks** (and when ``model="bank"``): residual income + justified P/B + DDM —
  FCFF is meaningless for a lender whose debt is raw material

plus relative valuation from peer multiples, a football-field blend and
sanity checks. Every input records where it came from (``user`` / ``yahoo`` /
``derived`` / ``default``) so the model and the user can see what is assumed.
"""

from __future__ import annotations

import asyncio
from typing import Any

from . import valuation_pro as vp

BANKS = {"AKBNK", "GARAN", "ISCTR", "YKBNK", "HALKB", "VAKBN", "TSKB", "ALBRK", "SKBNK",
         "QNBTR", "QNBFB", "ICBCT", "KLNMA"}

DEFAULT_ERP = 0.055  # mature-market equity risk premium (assumption, override it)


class _Inputs:
    """Merge explicit > auto-filled > default, remembering the source of each."""

    def __init__(self) -> None:
        self.values: dict[str, Any] = {}
        self.sources: dict[str, str] = {}

    def set(self, key: str, *candidates: tuple[Any, str]) -> Any:
        for value, src in candidates:
            if value is not None:
                self.values[key] = value
                self.sources[key] = src
                return value
        self.values[key] = None
        return None


async def _default_history(symbol: str) -> dict[str, Any]:
    from .fundamental_data import derive_drivers, fetch_financial_history

    h = await fetch_financial_history(symbol)
    return derive_drivers(h["history"])


async def _default_fundamentals(symbol: str) -> dict[str, Any]:
    from .fundamental_ratios import fetch_equity_fundamentals

    return (await fetch_equity_fundamentals(symbol)).to_dict()


async def _default_bars(symbol: str) -> dict[str, Any]:
    from .tools import _resolve_bars

    # public data: estimating a beta must not flip the TradingView chart
    return await _resolve_bars(None, None, None, None, symbol, "1D", 500, "public")


async def value_company(
    symbol: str | None = None,
    *,
    model: str = "auto",
    autofill: bool = True,
    price: float | None = None,
    # operating drivers
    revenue0: float | None = None,
    revenue_growth: float | list[float] | None = None,
    growth_fade_to: float | None = None,
    ebit_margin: float | list[float] | None = None,
    margin_fade_to: float | None = None,
    years: int = 10,
    tax_rate: float | None = None,
    da_pct_revenue: float | None = None,
    capex_pct_revenue: float | None = None,
    nwc_pct_revenue: float | None = None,
    terminal_growth: float | None = None,
    terminal_roic: float | None = None,
    expected_inflation: float | None = None,
    # balance sheet
    debt: float | None = None,
    cash: float | None = None,
    minority_interest: float | None = None,
    non_operating_assets: float = 0.0,
    shares_outstanding: float | None = None,
    # cost of capital
    wacc: float | None = None,
    risk_free: float | None = None,
    equity_risk_premium: float | None = None,
    country_risk_premium: float = 0.0,
    beta: float | None = None,
    pre_tax_cost_of_debt: float | None = None,
    # banks / dividends
    book_value: float | None = None,
    roe: float | list[float] | None = None,
    payout: float | None = None,
    dividend_per_share: float | None = None,
    # extras
    peers: list[Any] | None = None,
    run_monte_carlo: bool = True,
    load_history=None,
    load_fundamentals=None,
    load_bars=None,
) -> dict[str, Any]:
    load_history = load_history or _default_history
    load_fundamentals = load_fundamentals or _default_fundamentals
    load_bars = load_bars or _default_bars
    sym = symbol.strip().upper() if symbol else None
    notes: list[str] = []

    # ---- auto-fill ---------------------------------------------------------
    auto: dict[str, Any] = {}
    fund: dict[str, Any] = {}
    if autofill and sym:
        hist_res, fund_res = await asyncio.gather(
            load_history(sym), load_fundamentals(sym), return_exceptions=True)
        if isinstance(hist_res, BaseException):
            notes.append(f"Finansal geçmiş alınamadı ({type(hist_res).__name__}); "
                         "sürücüleri elle ver.")
        elif hist_res.get("available"):
            auto = hist_res
        if isinstance(fund_res, BaseException):
            notes.append("Güncel fiyat/piyasa değeri alınamadı.")
        else:
            fund = fund_res or {}

    inp = _Inputs()
    s = inp.set
    kind = model if model in ("industrial", "bank") else (
        "bank" if sym in BANKS else "industrial")
    px = s("price", (price, "user"), (fund.get("current_price"), "yahoo"))
    shares = s("shares_outstanding", (shares_outstanding, "user"),
               (auto.get("shares_outstanding"), "yahoo"),
               ((fund.get("market_cap") / px) if fund.get("market_cap") and px else None,
                "derived"))
    tax = s("tax_rate", (tax_rate, "user"), (auto.get("tax_rate"), "yahoo"), (0.25, "default"))
    dbt = s("debt", (debt, "user"), (auto.get("debt"), "yahoo"), (0.0, "default"))
    csh = s("cash", (cash, "user"), (auto.get("cash"), "yahoo"), (0.0, "default"))
    mi = s("minority_interest", (minority_interest, "user"),
           (auto.get("minority_interest"), "yahoo"), (0.0, "default"))

    # ---- cost of capital -----------------------------------------------------
    b = beta
    beta_info = None
    if b is None and sym:
        try:
            stock, index = await asyncio.gather(load_bars(sym), load_bars("XU100"))
            beta_info = vp.estimate_beta(stock["closes"], index["closes"])
            b = beta_info["beta"]
        except Exception as e:  # noqa: BLE001
            notes.append(f"Beta fiyattan hesaplanamadı ({type(e).__name__}); 1.0 varsayıldı.")
    s("beta", (beta, "user"), (beta_info and beta_info["beta"], "derived"), (1.0, "default"))
    b = inp.values["beta"]
    erp = s("equity_risk_premium", (equity_risk_premium, "user"), (DEFAULT_ERP, "default"))
    wacc_info = None
    if wacc is None:
        if risk_free is None:
            return {
                "error": "needs_input",
                "detail": "İskonto oranı için `wacc` ya da `risk_free` ver (TL için 10 yıllık "
                          "DİBS getirisi, ör. 0.30). Risksiz faiz otomatik çekilemiyor.",
                "autofilled": {k: inp.values[k] for k in inp.values},
                "sources": inp.sources,
            }
        mcap = px * shares if px and shares else fund.get("market_cap")
        wacc_info = vp.build_wacc(risk_free=risk_free, beta=b, equity_risk_premium=erp,
                                  country_risk_premium=country_risk_premium,
                                  pre_tax_cost_of_debt=pre_tax_cost_of_debt, tax_rate=tax,
                                  market_cap=mcap, debt=dbt)
    w = s("wacc", (wacc, "user"), (wacc_info and wacc_info["wacc"], "derived"))
    ke = wacc_info["cost_of_equity"] if wacc_info else w
    if wacc_info is None and kind == "bank":
        notes.append("Banka için verilen `wacc` özkaynak maliyeti olarak kullanıldı.")

    infl = expected_inflation
    tg = s("terminal_growth", (terminal_growth, "user"),
           (vp.fisher(0.02, infl, to="nominal") if infl is not None else None, "derived"),
           (0.03, "default"))
    if infl is None and risk_free and risk_free > 0.15 and terminal_growth is None:
        notes.append("Yüksek TL faizi ile %3 nominal terminal büyüme tutarsız olabilir; "
                     "`expected_inflation` ver (terminal büyüme = %2 reel + enflasyon).")

    methods: dict[str, dict[str, float]] = {}
    out: dict[str, Any] = {"symbol": sym, "model": kind, "price": px}

    # ---- bank model ----------------------------------------------------------
    if kind == "bank":
        bv = s("book_value", (book_value, "user"), (auto.get("book_value"), "yahoo"))
        r = s("roe", (roe, "user"), (auto.get("roe"), "yahoo"))
        po = s("payout", (payout, "user"), (auto.get("payout"), "yahoo"), (0.3, "default"))
        if not bv or r is None:
            return {"error": "needs_input",
                    "detail": "Banka modeli için book_value ve roe gerekli.",
                    "sources": inp.sources}
        ri = vp.residual_income(book_value0=bv, roe=r, cost_of_equity=ke, payout=po,
                                years=years, terminal_growth=tg,
                                roe_fade_to=ke + 0.02 if isinstance(r, (int, float)) else None,
                                shares_outstanding=shares)
        out["residual_income"] = ri
        r0 = r if isinstance(r, (int, float)) else r[0]
        try:
            jpb = vp.justified_pb(r0, ke, tg)
            out["justified_pb"] = round(jpb, 3)
            if shares:
                v = jpb * bv / shares
                methods["justified_pb"] = {"low": v * 0.85, "base": v, "high": v * 1.15}
        except ValueError as e:
            notes.append(str(e))
        if ri.get("available") and ri.get("value_per_share"):
            v = ri["value_per_share"]
            methods["residual_income"] = {"low": v * 0.85, "base": v, "high": v * 1.15}
    # ---- industrial model ----------------------------------------------------
    else:
        rev = s("revenue0", (revenue0, "user"), (auto.get("revenue0"), "yahoo"))
        cagr = auto.get("revenue_cagr")
        g = s("revenue_growth", (revenue_growth, "user"),
              (None if cagr is None else max(-0.2, min(cagr, 0.8)), "yahoo"), (0.05, "default"))
        m = s("ebit_margin", (ebit_margin, "user"), (auto.get("ebit_margin_avg"), "yahoo"),
              (auto.get("ebit_margin_last"), "yahoo"))
        if not rev or m is None:
            return {"error": "needs_input",
                    "detail": "DCF için revenue0 ve ebit_margin gerekli (otomatik doldurma "
                              "başarısız ya da eksik).", "sources": inp.sources,
                    "notes": notes}
        base = dict(
            revenue0=rev, wacc=w, revenue_growth=g,
            growth_fade_to=growth_fade_to if growth_fade_to is not None else tg,
            ebit_margin=m, margin_fade_to=margin_fade_to, years=years, tax_rate=tax,
            da_pct_revenue=s("da_pct_revenue", (da_pct_revenue, "user"),
                             (auto.get("da_pct_revenue"), "yahoo"), (0.04, "default")),
            capex_pct_revenue=s("capex_pct_revenue", (capex_pct_revenue, "user"),
                                (auto.get("capex_pct_revenue"), "yahoo"), (0.05, "default")),
            nwc_pct_revenue=s("nwc_pct_revenue", (nwc_pct_revenue, "user"),
                              (auto.get("nwc_pct_revenue"), "yahoo"), (0.10, "default")),
            terminal_growth=tg,
            # RONIC = WACC by default: growth in perpetuity creates no extra value
            terminal_roic=s("terminal_roic", (terminal_roic, "user"), (w, "default")),
            debt=dbt, cash=csh, minority_interest=mi,
            non_operating_assets=non_operating_assets, shares_outstanding=shares,
        )
        dcf = vp.driver_dcf(**base)
        if not dcf.get("available"):
            return {"error": "bad_input", "detail": dcf.get("reason"), "sources": inp.sources}
        out["dcf"] = dcf
        out["sensitivity"] = vp.sensitivity(base)
        g0 = g if isinstance(g, (int, float)) else g[0]
        m0 = m if isinstance(m, (int, float)) else m[0]
        out["scenarios"] = vp.scenario_valuation(
            base,
            {"ayı": {"revenue_growth": g0 * 0.6, "ebit_margin": m0 * 0.8},
             "baz": {},
             "boğa": {"revenue_growth": g0 * 1.3, "ebit_margin": m0 * 1.15}},
            {"ayı": 0.25, "baz": 0.5, "boğa": 0.25},
        )
        if run_monte_carlo:
            mc = await asyncio.to_thread(vp.monte_carlo_dcf, base, n=1500, price=px)
            out["monte_carlo"] = mc
        key = "fair_value_per_share" if shares else "equity_value"
        if out.get("monte_carlo"):
            mc = out["monte_carlo"]
            methods["dcf"] = {"low": mc["p25"], "base": dcf[key], "high": mc["p75"]}
        else:
            methods["dcf"] = {"low": dcf[key] * 0.85, "base": dcf[key], "high": dcf[key] * 1.15}
        notes += vp.sanity_checks(dcf, expected_inflation=infl)

    # ---- dividends -------------------------------------------------------------
    dps = s("dividend_per_share", (dividend_per_share, "user"),
            (auto.get("dividend_per_share"), "yahoo"))
    if dps:
        ddm = vp.dividend_discount(dividend0=dps, cost_of_equity=ke,
                                   high_growth=g if kind != "bank" and isinstance(g, float)
                                   else tg, years=5, terminal_growth=tg)
        out["ddm"] = ddm
        if ddm.get("available"):
            v = ddm["value_per_share"]
            methods["ddm"] = {"low": v * 0.85, "base": v, "high": v * 1.15}

    # ---- peers -----------------------------------------------------------------
    if peers and shares:
        peer_rows = []
        for p in peers:
            if isinstance(p, dict):
                peer_rows.append(p)
                continue
            try:
                f = await load_fundamentals(str(p))
                peer_rows.append({"ticker": p, "pe": f.get("trailing_pe"),
                                  "pb": f.get("price_to_book"), "ps": f.get("price_to_sales"),
                                  "ev_ebitda": f.get("ev_to_ebitda")})
            except Exception:  # noqa: BLE001
                notes.append(f"Emsal {p} verisi alınamadı.")
        target = {"net_income": auto.get("net_income"), "book_value": auto.get("book_value"),
                  "revenue": auto.get("revenue0") or revenue0, "ebitda": auto.get("ebitda")}
        rel = vp.relative_valuation(peer_rows, target, shares_outstanding=shares,
                                    net_debt=(dbt or 0) - (csh or 0))
        out["relative"] = rel
        if rel["multiples"]:
            bases = [v["base"] for v in rel["multiples"].values()]
            methods["multiples"] = {"low": min(v["low"] for v in rel["multiples"].values()),
                                    "base": rel["median_of_methods"],
                                    "high": max(v["high"] for v in rel["multiples"].values())}
            if len(bases) < 2:
                notes.append("Göreli değerleme tek çarpana dayanıyor.")

    ff = vp.football_field(methods, price=px, weights={"dcf": 2, "residual_income": 2})
    out.update({
        "cost_of_capital": wacc_info or {"wacc": w},
        "beta": beta_info,
        "football_field": ff,
        "inputs": inp.values,
        "sources": inp.sources,
        "notes": notes,
        "summary_tr": _summary(sym, kind, px, ff, out, notes),
    })
    return out


def _summary(sym, kind, px, ff, out, notes) -> str:
    name = sym or "Şirket"
    if not ff.get("available"):
        return f"{name}: değer hesaplanamadı."
    parts = [f"{name} ({'banka modeli' if kind == 'bank' else 'FCFF DCF'}): "
             f"harmanlanmış değer {ff['blended_value']:,.2f}"]
    if px:
        tr = {"undervalued": "ucuz", "overvalued": "pahalı", "fair": "makul"}[ff["verdict"]]
        parts.append(f"fiyat {px:,.2f}, güvenlik marjı %{ff['margin_of_safety'] * 100:.0f} "
                     f"({tr})")
    mc = out.get("monte_carlo")
    if mc and mc.get("prob_above_price") is not None:
        parts.append(f"Monte Carlo: değerin fiyatın üstünde olma olasılığı "
                     f"%{mc['prob_above_price'] * 100:.0f} (p25–p75: {mc['p25']:,.2f}–"
                     f"{mc['p75']:,.2f})")
    dcf = out.get("dcf")
    if dcf:
        parts.append(f"terminal değer payı %{dcf['terminal_value_pct'] * 100:.0f}")
    text = " | ".join(parts) + "."
    if notes:
        text += " Dikkat: " + " ".join(notes[:3])
    return text


__all__ = ["BANKS", "value_company"]

"""Real equity fundamentals — valuation, profitability, leverage, growth.

Until now the "fundamental" layer scored KAP headline tone + price momentum.
This module adds the missing core: P/E, P/B, ROE, margins, debt/equity, growth,
dividend yield and analyst targets, plus a rigorous ratio-based composite score
(-100..+100) with a per-factor breakdown.

Data source: Yahoo Finance `quoteSummary` (free, unofficial). It now requires a
cookie + crumb handshake, which we cache. The *scoring* is a pure function so it
is fully testable and also works on ratios supplied manually by the LLM/user.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import asdict, dataclass
from typing import Any

import httpx

from .http_utils import SourceError

_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
_QS_MODULES = "summaryDetail,defaultKeyStatistics,financialData,price"
_CRUMB_TTL = 1800  # 30 min


@dataclass
class EquityFundamentals:
    """Snapshot of valuation / quality / growth ratios for one equity."""

    ticker: str
    name: str | None = None
    currency: str | None = None
    market_cap: float | None = None
    trailing_pe: float | None = None
    forward_pe: float | None = None
    price_to_book: float | None = None
    price_to_sales: float | None = None
    ev_to_ebitda: float | None = None
    return_on_equity: float | None = None       # fraction (0.155 = 15.5%)
    return_on_assets: float | None = None
    profit_margin: float | None = None
    operating_margin: float | None = None
    debt_to_equity: float | None = None         # ratio (0.84 = 84%)
    current_ratio: float | None = None
    revenue_growth: float | None = None         # fraction YoY
    earnings_growth: float | None = None        # fraction YoY
    dividend_yield: float | None = None         # fraction
    analyst_recommendation: str | None = None
    target_mean_price: float | None = None
    current_price: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Fetch (best-effort, cached crumb session)
# ---------------------------------------------------------------------------
_session: httpx.AsyncClient | None = None
_session_loop: object | None = None
_crumb: str | None = None
_crumb_ts: float = 0.0


def _bist_to_yahoo(ticker: str) -> str:
    t = ticker.upper().strip()
    if t.endswith(".IS") or t.startswith("^"):
        return t
    return f"{t}.IS"


async def _ensure_crumb() -> tuple[httpx.AsyncClient, str]:
    global _session, _session_loop, _crumb, _crumb_ts
    try:
        loop: object | None = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    fresh = _crumb and (time.time() - _crumb_ts) < _CRUMB_TTL
    # Rebuild the client when the event loop changes (a client is loop-bound).
    if _session is None or _session.is_closed or _session_loop is not loop:
        _session = httpx.AsyncClient(
            headers={"User-Agent": _BROWSER_UA, "Accept": "*/*"},
            follow_redirects=True,
            timeout=20.0,
        )
        _session_loop = loop
        fresh = False
    if not fresh:
        try:
            await _session.get("https://fc.yahoo.com")
            r = await _session.get("https://query2.finance.yahoo.com/v1/test/getcrumb")
            crumb = r.text.strip()
            if not crumb or "<html" in crumb.lower():
                raise SourceError("yahoo", "could not obtain crumb")
            _crumb = crumb
            _crumb_ts = time.time()
        except httpx.HTTPError as e:
            raise SourceError("yahoo", f"crumb handshake failed: {e}") from e
    return _session, _crumb  # type: ignore[return-value]


def _raw(node: Any) -> float | None:
    if isinstance(node, dict):
        node = node.get("raw")
    if node is None:
        return None
    try:
        f = float(node)
    except (TypeError, ValueError):
        return None
    return None if f != f else f


def _norm_debt_to_equity(v: float | None) -> float | None:
    """Yahoo returns D/E as a percent (83.9 == 0.839x). Normalise to a ratio."""
    if v is None:
        return None
    return v / 100.0 if v > 5 else v


async def fetch_equity_fundamentals(ticker: str) -> EquityFundamentals:
    """Fetch live fundamentals for a BIST equity via Yahoo quoteSummary."""
    symbol = _bist_to_yahoo(ticker)
    session, crumb = await _ensure_crumb()
    url = f"https://query2.finance.yahoo.com/v10/finance/quoteSummary/{symbol}"
    params = {"modules": _QS_MODULES, "crumb": crumb}
    try:
        resp = await session.get(url, params=params)
        if resp.status_code == 401:
            # Crumb expired mid-flight; force one refresh and retry.
            global _crumb_ts
            _crumb_ts = 0.0
            session, crumb = await _ensure_crumb()
            params["crumb"] = crumb
            resp = await session.get(url, params=params)
        resp.raise_for_status()
        payload = resp.json()
    except httpx.HTTPError as e:
        raise SourceError("yahoo", f"quoteSummary failed for {symbol}: {e}") from e

    results = ((payload or {}).get("quoteSummary") or {}).get("result") or []
    if not results:
        raise SourceError("yahoo", f"no fundamentals for {symbol}")
    res = results[0]
    sd = res.get("summaryDetail") or {}
    ks = res.get("defaultKeyStatistics") or {}
    fd = res.get("financialData") or {}
    pr = res.get("price") or {}

    rec = fd.get("recommendationKey")
    return EquityFundamentals(
        ticker=symbol.replace(".IS", ""),
        name=pr.get("longName") or pr.get("shortName"),
        currency=pr.get("currency"),
        market_cap=_raw(pr.get("marketCap")) or _raw(sd.get("marketCap")),
        trailing_pe=_raw(sd.get("trailingPE")),
        forward_pe=_raw(sd.get("forwardPE")) or _raw(ks.get("forwardPE")),
        price_to_book=_raw(ks.get("priceToBook")),
        price_to_sales=_raw(sd.get("priceToSalesTrailing12Months")),
        ev_to_ebitda=_raw(ks.get("enterpriseToEbitda")),
        return_on_equity=_raw(fd.get("returnOnEquity")),
        return_on_assets=_raw(fd.get("returnOnAssets")),
        profit_margin=_raw(fd.get("profitMargins")) or _raw(ks.get("profitMargins")),
        operating_margin=_raw(fd.get("operatingMargins")),
        debt_to_equity=_norm_debt_to_equity(_raw(fd.get("debtToEquity"))),
        current_ratio=_raw(fd.get("currentRatio")),
        revenue_growth=_raw(fd.get("revenueGrowth")),
        earnings_growth=_raw(fd.get("earningsGrowth")),
        dividend_yield=_raw(sd.get("dividendYield")),
        analyst_recommendation=str(rec) if rec else None,
        target_mean_price=_raw(fd.get("targetMeanPrice")),
        current_price=_raw(fd.get("currentPrice")) or _raw(pr.get("regularMarketPrice")),
    )


# ---------------------------------------------------------------------------
# Scoring (pure) — emerging-market (BIST) calibrated thresholds
# ---------------------------------------------------------------------------
def _band(value: float, bands: list[tuple[float, float]], default: float) -> float:
    """Return score for the first band whose upper threshold value <= bound."""
    for bound, pts in bands:
        if value <= bound:
            return pts
    return default


def score_fundamental_ratios(f: EquityFundamentals | dict[str, Any] | None) -> dict[str, Any]:
    """Composite -100..+100 fundamental quality/value score with breakdown."""
    if f is None:
        return {"score": 0.0, "grade": "NA", "bias": "neutral", "factors": [],
                "components": {}, "available": False}
    data = f.to_dict() if isinstance(f, EquityFundamentals) else dict(f)

    score = 0.0
    factors: list[str] = []
    components: dict[str, float] = {}

    def add(name: str, pts: float, label: str | None = None) -> None:
        nonlocal score
        score += pts
        components[name] = round(pts, 1)
        if label and abs(pts) >= 3:
            factors.append(label)

    pe = data.get("trailing_pe")
    if pe is not None and pe > 0:
        pts = _band(pe, [(8, 12), (15, 6), (25, 0), (40, -6)], -12)
        add("pe", pts, "cheap_pe" if pts > 0 else ("expensive_pe" if pts < 0 else None))
    elif pe is not None and pe <= 0:
        add("pe", -10, "negative_earnings")

    pb = data.get("price_to_book")
    if pb is not None and pb > 0:
        pts = _band(pb, [(1, 10), (2, 5), (4, 0)], -6)
        add("pb", pts, "low_pb" if pts > 0 else ("high_pb" if pts < 0 else None))

    roe = data.get("return_on_equity")
    if roe is not None:
        pts = _band(roe, [(0, -12), (0.08, -2), (0.15, 3), (0.25, 8)], 12)
        add("roe", pts, "strong_roe" if pts > 0 else ("weak_roe" if pts < 0 else None))

    margin = data.get("profit_margin")
    if margin is not None:
        pts = _band(margin, [(0, -10), (0.10, 0), (0.20, 4)], 8)
        add("profit_margin", pts, "healthy_margin" if pts > 0 else ("loss_making" if pts < 0 else None))

    de = data.get("debt_to_equity")
    if de is not None:
        pts = _band(de, [(0.5, 6), (1.0, 2), (2.0, -3)], -8)
        add("debt_to_equity", pts, "low_leverage" if pts > 0 else ("high_leverage" if pts < 0 else None))

    eg = data.get("earnings_growth")
    if eg is not None:
        pts = _band(eg, [(-0.10, -10), (0.0, -4), (0.10, 2), (0.25, 7)], 12)
        add("earnings_growth", pts, "earnings_growth" if pts > 0 else ("earnings_decline" if pts < 0 else None))

    rg = data.get("revenue_growth")
    if rg is not None:
        pts = _band(rg, [(0.0, -5), (0.20, 2)], 6)
        add("revenue_growth", pts, "revenue_growth" if pts > 0 else ("revenue_decline" if pts < 0 else None))

    cr = data.get("current_ratio")
    if cr is not None:
        pts = _band(cr, [(1.0, -5), (2.0, 0)], 3)
        add("current_ratio", pts, "liquidity_tight" if pts < 0 else None)

    dy = data.get("dividend_yield")
    if dy is not None and dy > 0:
        pts = _band(dy, [(0.02, 0), (0.05, 2)], 4)
        add("dividend_yield", pts, "dividend_payer" if pts > 0 else None)

    rec = (data.get("analyst_recommendation") or "").lower()
    if rec in ("buy", "strong_buy"):
        add("analyst", 5, "analyst_buy")
    elif rec in ("sell", "strong_sell", "underperform"):
        add("analyst", -5, "analyst_sell")

    tp, cp = data.get("target_mean_price"), data.get("current_price")
    if tp and cp and cp > 0:
        upside = (tp / cp - 1.0)
        if upside >= 0.15:
            add("analyst_upside", 5, "analyst_upside")
        elif upside <= -0.10:
            add("analyst_upside", -5, "analyst_downside")

    available = bool(components)
    score = round(max(-100.0, min(100.0, score)), 1)
    bias = "neutral"
    if score >= 15:
        bias = "bullish"
    elif score <= -15:
        bias = "bearish"

    grade = "NA"
    if available:
        if score >= 35:
            grade = "A"
        elif score >= 15:
            grade = "B"
        elif score >= -10:
            grade = "C"
        elif score >= -30:
            grade = "D"
        else:
            grade = "F"

    return {
        "score": score,
        "grade": grade,
        "bias": bias,
        "factors": factors,
        "components": components,
        "available": available,
    }


def summarize_fundamentals_tr(
    f: EquityFundamentals | dict[str, Any] | None,
    score_pack: dict[str, Any] | None = None,
) -> str:
    """One-line Turkish valuation summary for chat_report / highlights."""
    if f is None:
        return "Temel: veri yok"
    data = f.to_dict() if isinstance(f, EquityFundamentals) else dict(f)
    sp = score_pack or score_fundamental_ratios(f)
    if not sp.get("available"):
        return "Temel: oran verisi yok"

    def pct(v: Any) -> str:
        return f"{v * 100:.1f}%" if isinstance(v, (int, float)) else "—"

    def num(v: Any) -> str:
        return f"{v:.1f}" if isinstance(v, (int, float)) else "—"

    parts = [
        f"F/K {num(data.get('trailing_pe'))}",
        f"PD/DD {num(data.get('price_to_book'))}",
        f"ROE {pct(data.get('return_on_equity'))}",
        f"marj {pct(data.get('profit_margin'))}",
    ]
    eg = data.get("earnings_growth")
    if eg is not None:
        parts.append(f"kâr büy. {pct(eg)}")
    return (
        f"Temel skor {sp['score']:+.0f} (not {sp['grade']}, {sp['bias']}): "
        + " · ".join(parts)
    )


__all__ = [
    "EquityFundamentals",
    "fetch_equity_fundamentals",
    "score_fundamental_ratios",
    "summarize_fundamentals_tr",
]

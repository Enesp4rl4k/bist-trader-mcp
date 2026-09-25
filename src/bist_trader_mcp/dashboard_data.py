"""Dashboard data — one snapshot of everything the live panel shows.

``build_snapshot(state)`` fetches the selected sections concurrently, each with
its own timeout, so one slow or failing source never blanks the whole panel
(the section carries ``error`` instead). Sources:

- ticker     macro indices, TL, commodities, crypto (Yahoo quotes, ~15 min delayed)
- watchlist  quotes + a simple-PA verdict from *public* daily bars — it never
             touches the TradingView chart, which has a single symbol
- chart      the selected symbol from TradingView (``chart_source="auto"``) with
             plan lines, support/resistance and the candle-forecast band
- news       KAP disclosures (needs the ``browser`` extra) + RSS, watchlist
             matches flagged
- calendar   TCMB MPC / CPI / PPI dates
- risk       portfolio heat, P&L, breaker, clusters (risk_engine)

Loaders are injectable for tests.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any

from ._cache import LRUDict

TICKER = [
    ("XU100", "^XU100"), ("XU030", "^XU030"), ("USDTRY", "USDTRY=X"), ("EURTRY", "EURTRY=X"),
    ("ALTIN", "GC=F"), ("GÜMÜŞ", "SI=F"), ("BRENT", "BZ=F"), ("BAKIR", "HG=F"),
    ("S&P500", "^GSPC"), ("NASDAQ", "^NDX"), ("DAX", "^GDAXI"), ("VIX", "^VIX"),
    ("DXY", "DX-Y.NYB"), ("ABD10Y", "^TNX"), ("BTC", "BTC-USD"),
]
DEFAULT_WATCHLIST = ["THYAO", "ASELS", "GARAN", "AKBNK", "BIMAS", "TUPRS", "KCHOL", "EREGL"]
PANELS = ("ticker", "watchlist", "chart", "news", "calendar", "risk")
TIMEFRAMES = ("15", "60", "240", "1D", "1W")
TR_KEYWORDS = ("turkey", "türkiye", "turkish", "lira", "tcmb", "istanbul", "borsa")

SECTION_TIMEOUT = {"ticker": 12, "watchlist": 25, "chart": 30, "news": 20,
                   "calendar": 5, "risk": 20}
QUOTE_TTL = 60.0


@dataclass
class DashboardState:
    symbol: str = "THYAO"
    timeframe: str = "1D"
    watchlist: list[str] = field(default_factory=lambda: list(DEFAULT_WATCHLIST))
    panels: dict[str, bool] = field(default_factory=lambda: {p: True for p in PANELS})
    chart_source: str = "auto"

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> DashboardState:
        d = d or {}
        wl = [str(s).strip().upper() for s in (d.get("watchlist") or DEFAULT_WATCHLIST)
              if str(s).strip()][:20]
        panels = {p: True for p in PANELS}
        for k, v in (d.get("panels") or {}).items():
            if k in panels:
                panels[k] = bool(v)
        tf = str(d.get("timeframe") or "1D").upper()
        src = d.get("chart_source") or "auto"
        return cls(
            symbol=str(d.get("symbol") or (wl[0] if wl else "THYAO")).strip().upper(),
            timeframe=tf if tf in TIMEFRAMES else "1D",
            watchlist=wl,
            panels=panels,
            chart_source=src if src in ("auto", "tradingview", "public") else "auto",
        )


# --------------------------------------------------------------------------- loaders

_quote_cache: dict[str, tuple[float, dict[str, Any]]] = LRUDict(256)


async def _quotes(pairs: list[tuple[str, str]]) -> list[dict[str, Any]]:
    """Yahoo quotes with a 60 s cache (the panel polls; Yahoo must not)."""
    from .bist_snapshot import _fetch_one_snapshot

    now = time.monotonic()
    out: dict[str, dict[str, Any]] = {}
    todo = []
    for alias, ysym in pairs:
        hit = _quote_cache.get(ysym)
        if hit and now - hit[0] < QUOTE_TTL:
            out[alias] = hit[1]
        else:
            todo.append((alias, ysym))
    snaps = await asyncio.gather(
        *[_fetch_one_snapshot(a, y) for a, y in todo], return_exceptions=True
    )
    for (alias, ysym), snap in zip(todo, snaps, strict=True):
        if isinstance(snap, BaseException):
            continue
        row = {
            "symbol": alias,
            "last": snap.last_price,
            "change_pct": snap.change_pct,
            "market_state": snap.market_state,
            "as_of": snap.as_of,
        }
        _quote_cache[ysym] = (now, row)
        out[alias] = row
    return [out[a] for a, _ in pairs if a in out and out[a].get("last") is not None]


async def default_quotes(pairs: list[tuple[str, str]]) -> list[dict[str, Any]]:
    return await _quotes(pairs)


async def default_bars(symbol: str, timeframe: str, source: str) -> dict[str, Any]:
    from .tools import _resolve_bars

    return await _resolve_bars(None, None, None, None, symbol, timeframe, 300, source)


async def default_news(watchlist: list[str]) -> list[dict[str, Any]]:
    from .kap import fetch_disclosures
    from .news import fetch_news

    items: list[dict[str, Any]] = []
    try:
        for d in await fetch_disclosures(since=date.today() - timedelta(days=2), limit=60):
            items.append({
                "source": "KAP", "title": f"{d.company_ticker or ''} {d.subject}".strip(),
                "summary": d.summary, "link": d.url, "time": d.publish_date,
                "tickers": [d.company_ticker] if d.company_ticker else [],
                "material": d.is_material,
            })
    except Exception:  # noqa: BLE001 — KAP needs the browser extra; RSS still works
        pass
    try:
        rss = await fetch_news(["investing_top", "investing_economy", "reuters_business"],
                               limit_per_feed=15)
        for n in rss:
            items.append({"source": n.source, "title": n.title, "summary": n.summary,
                          "link": n.link, "time": n.published_iso, "tickers": [],
                          "material": False})
    except Exception:  # noqa: BLE001
        pass
    return items


async def default_risk() -> dict[str, Any]:
    from .tools import get_portfolio_risk

    return await get_portfolio_risk()


# --------------------------------------------------------------------------- sections


async def section_watchlist(state: DashboardState, quotes, bars) -> list[dict[str, Any]]:
    from .bist_snapshot import _to_yahoo
    from .pa_simple import simple_price_action

    q = {r["symbol"]: r for r in await quotes([(s, _to_yahoo(s)) for s in state.watchlist])}

    async def one(sym: str) -> dict[str, Any]:
        row: dict[str, Any] = {"symbol": sym, **{k: v for k, v in q.get(sym, {}).items()
                                                 if k != "symbol"}}
        try:
            b = await bars(sym, "1D", "public")
            pa = await asyncio.to_thread(
                simple_price_action, b["closes"], b["highs"], b["lows"], b.get("opens")
            )
            row.update(trend=pa["trend"], verdict=pa["verdict"])
            if row.get("last") is None:
                row["last"] = b["closes"][-1]
                row["change_pct"] = (b["closes"][-1] / b["closes"][-2] - 1) * 100
        except Exception as e:  # noqa: BLE001
            row["error"] = str(e)[:120]
        return row

    return list(await asyncio.gather(*[one(s) for s in state.watchlist]))


async def section_chart(state: DashboardState, bars) -> dict[str, Any]:
    from .candle_forecast import forecast_candles
    from .pa_simple import simple_price_action

    b = await bars(state.symbol, state.timeframe, state.chart_source)

    def compute() -> tuple[dict[str, Any], dict[str, Any]]:
        pa = simple_price_action(b["closes"], b["highs"], b["lows"], b.get("opens"),
                                 debug=True)
        fc = forecast_candles(b["closes"], b["highs"], b["lows"], b.get("opens"),
                              horizon=10, n_paths=30, seed=0)
        return pa, fc

    # CPU work off the event loop: MCP calls and the web panel stay responsive.
    pa, fc = await asyncio.to_thread(compute)
    k = 150
    opens = b.get("opens") or ([b["closes"][0]] + b["closes"][:-1])
    return {
        "symbol": state.symbol,
        "timeframe": state.timeframe,
        "data_source": b.get("data_source"),
        "candles": {
            "t": (b.get("times") or [])[-k:],
            "o": opens[-k:], "h": b["highs"][-k:], "l": b["lows"][-k:], "c": b["closes"][-k:],
        },
        "analysis": {k2: pa[k2] for k2 in ("trend", "trend_strength", "support",
                                           "resistance", "last_event", "zone", "verdict",
                                           "reason", "plan", "summary_tr")},
        "forecast": {
            "up_pct": fc["candles"]["up_pct"],
            "mean": fc["series"]["mean"], "p10": fc["series"]["p10"],
            "p90": fc["series"]["p90"], "summary_tr": fc["summary_tr"],
        },
        **({"tradingview_error": b["tradingview_error"]} if b.get("tradingview_error") else {}),
    }


async def section_news(state: DashboardState, news) -> list[dict[str, Any]]:
    items = await news(state.watchlist)
    wl = set(state.watchlist)
    for it in items:
        title = (it.get("title") or "").lower()
        hits = [t for t in (it.get("tickers") or []) if t in wl]
        hits += [s for s in wl if s.lower() in title.split() and s not in hits]
        it["watchlist_hit"] = hits
        it["tr_relevant"] = bool(hits) or any(k in title for k in TR_KEYWORDS) or \
            it.get("source") == "KAP"
    items.sort(key=lambda i: (bool(i["watchlist_hit"]), i.get("time") or ""), reverse=True)
    return items[:40]


def section_calendar() -> list[dict[str, Any]]:
    from .calendar_data import build_calendar

    today = date.today()
    return [asdict(e) for e in build_calendar(today, today + timedelta(days=21))]


# --------------------------------------------------------------------------- snapshot


async def build_snapshot(
    state_dict: dict[str, Any] | None = None,
    *,
    quotes=None,
    bars=None,
    news=None,
    risk=None,
) -> dict[str, Any]:
    quotes = quotes or default_quotes
    bars = bars or default_bars
    news = news or default_news
    risk = risk or default_risk
    state = DashboardState.from_dict(state_dict)
    jobs: dict[str, Any] = {}
    if state.panels["ticker"]:
        jobs["ticker"] = quotes(TICKER)
    if state.panels["watchlist"]:
        jobs["watchlist"] = section_watchlist(state, quotes, bars)
    if state.panels["chart"]:
        jobs["chart"] = section_chart(state, bars)
    if state.panels["news"]:
        jobs["news"] = section_news(state, news)
    if state.panels["risk"]:
        jobs["risk"] = risk()

    async def guarded(name: str, coro: Any) -> tuple[str, dict[str, Any]]:
        t0 = time.monotonic()
        try:
            data = await asyncio.wait_for(coro, SECTION_TIMEOUT[name])
            return name, {"ok": True, "data": data,
                          "ms": round((time.monotonic() - t0) * 1000)}
        except asyncio.TimeoutError:
            return name, {"ok": False, "error": f"zaman aşımı ({SECTION_TIMEOUT[name]} sn)"}
        except Exception as e:  # noqa: BLE001 — a section failure must not kill the panel
            return name, {"ok": False, "error": f"{type(e).__name__}: {e}"[:200]}

    results = dict(await asyncio.gather(*[guarded(n, c) for n, c in jobs.items()]))
    if state.panels["calendar"]:
        try:
            results["calendar"] = {"ok": True, "data": section_calendar()}
        except Exception as e:  # noqa: BLE001
            results["calendar"] = {"ok": False, "error": str(e)}
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "state": asdict(state),
        "sections": results,
        "delayed_note": "Şerit ve izleme listesi Yahoo kaynaklı (~15 dk gecikmeli); "
                        "grafik TradingView'dan.",
    }


def snapshot_text(snap: dict[str, Any]) -> str:
    """Short text version for the model / text-only hosts."""
    s = snap["sections"]
    parts = []
    t = s.get("ticker", {})
    if t.get("ok"):
        parts.append(" · ".join(
            f"{r['symbol']} {r['last']:,.2f} ({(r.get('change_pct') or 0):+.2f}%)"
            for r in t["data"][:8]))
    c = s.get("chart", {})
    if c.get("ok"):
        a = c["data"]["analysis"]
        parts.append(f"{c['data']['symbol']} {c['data']['timeframe']}: {a['summary_tr']}")
    w = s.get("watchlist", {})
    if w.get("ok"):
        parts.append("İzleme: " + ", ".join(
            f"{r['symbol']} {r.get('verdict', '-')}" for r in w["data"]))
    r = s.get("risk", {})
    if r.get("ok"):
        parts.append("Risk: " + r["data"].get("summary_tr", ""))
    n = s.get("news", {})
    if n.get("ok"):
        hot = [i for i in n["data"] if i.get("watchlist_hit")][:3]
        if hot:
            parts.append("Haber: " + " | ".join(i["title"] for i in hot))
    return "\n".join(parts) or "Panel verisi alınamadı."


__all__ = ["DashboardState", "build_snapshot", "snapshot_text", "PANELS", "TIMEFRAMES"]

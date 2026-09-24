"""Live dashboard: data snapshot, MCP Apps wiring, local web server safety."""

import asyncio
import http.client
import json

import pytest

from bist_trader_mcp import dashboard_data as dd
from bist_trader_mcp import dashboard_web

from .test_candle_forecast import _series


def _bars(seed=1, n=300):
    o, h, l, c = _series(n=n, drift=0.002, seed=seed)
    return {"opens": o, "highs": h, "lows": l, "closes": c, "volumes": [1e6] * n,
            "times": [1_700_000_000 + i * 86400 for i in range(n)], "data_source": "tradingview"}


class Fakes:
    def __init__(self):
        self.bar_calls = []

    async def quotes(self, pairs):
        return [{"symbol": a, "last": 100.0, "change_pct": 1.5, "as_of": "x"} for a, _ in pairs]

    async def bars(self, symbol, timeframe, source):
        self.bar_calls.append((symbol, timeframe, source))
        return _bars(seed=len(symbol))

    async def news(self, watchlist):
        return [
            {"source": "KAP", "title": "ASELS yeni sözleşme", "tickers": ["ASELS"],
             "time": "2026-09-24T10:00", "link": "https://kap.org.tr/x"},
            {"source": "investing_top", "title": "Fed holds rates", "tickers": [],
             "time": "2026-09-24T09:00", "link": "https://x"},
            {"source": "reuters", "title": "Turkey lira steady", "tickers": [],
             "time": "2026-09-24T08:00", "link": "https://y"},
        ]

    async def risk(self):
        return {"heat_pct": 1.0, "max_open_risk_pct": 6.0, "summary_tr": "ok",
                "positions": [], "circuit_breaker": False}


def _snap(state=None, **over):
    f = Fakes()
    kw = {"quotes": f.quotes, "bars": f.bars, "news": f.news, "risk": f.risk, **over}
    return f, asyncio.run(dd.build_snapshot(state, **kw))


def test_snapshot_has_all_sections():
    f, s = _snap({"symbol": "ASELS", "watchlist": ["THYAO", "ASELS"]})
    sec = s["sections"]
    assert set(sec) == {"ticker", "watchlist", "chart", "news", "calendar", "risk"}
    assert all(v["ok"] for v in sec.values()), {k: v.get("error") for k, v in sec.items()}
    chart = sec["chart"]["data"]
    assert chart["symbol"] == "ASELS" and len(chart["candles"]["c"]) == 150
    assert len(chart["forecast"]["p10"]) == 10
    assert [r["symbol"] for r in sec["watchlist"]["data"]] == ["THYAO", "ASELS"]
    assert sec["watchlist"]["data"][0]["verdict"] in ("AL", "SAT", "BEKLE")


def test_watchlist_never_touches_tradingview():
    f, _ = _snap({"symbol": "ASELS", "watchlist": ["THYAO", "GARAN"]})
    wl_calls = [c for c in f.bar_calls if c[0] in ("THYAO", "GARAN")]
    assert wl_calls and all(src == "public" for *_, src in wl_calls)
    assert ("ASELS", "1D", "auto") in f.bar_calls  # only the chart may use TV


def test_one_failing_source_does_not_blank_the_panel():
    async def broken(*a, **k):
        raise RuntimeError("yahoo down")

    _, s = _snap(quotes=broken)
    assert s["sections"]["ticker"]["ok"] is False
    assert "yahoo down" in s["sections"]["ticker"]["error"]
    assert s["sections"]["chart"]["ok"] and s["sections"]["news"]["ok"]


def test_panel_toggles_skip_work():
    f, s = _snap({"panels": {"chart": False, "news": False, "watchlist": False}})
    assert "chart" not in s["sections"] and "news" not in s["sections"]
    assert f.bar_calls == []


def test_news_flags_watchlist_and_turkey():
    _, s = _snap({"watchlist": ["ASELS"]})
    items = s["sections"]["news"]["data"]
    assert items[0]["title"].startswith("ASELS") and items[0]["watchlist_hit"] == ["ASELS"]
    lira = next(i for i in items if "lira" in i["title"])
    fed = next(i for i in items if "Fed" in i["title"])
    assert lira["tr_relevant"] and not fed["tr_relevant"]


def test_state_is_sanitised():
    st = dd.DashboardState.from_dict({"timeframe": "7D", "chart_source": "evil",
                                      "watchlist": [" thyao ", "", *["X"] * 50],
                                      "panels": {"bogus": False}})
    assert st.timeframe == "1D" and st.chart_source == "auto"
    assert st.watchlist[0] == "THYAO" and len(st.watchlist) == 20
    assert "bogus" not in st.panels


# ---------------------------------------------------------------- MCP wiring


def test_mcp_apps_wiring(monkeypatch):
    from mcp.shared.memory import create_connected_server_and_client_session

    from bist_trader_mcp import server as srv

    f = Fakes()
    monkeypatch.setattr(dd, "default_quotes", f.quotes)
    monkeypatch.setattr(dd, "default_bars", f.bars)
    monkeypatch.setattr(dd, "default_news", f.news)
    monkeypatch.setattr(dd, "default_risk", f.risk)

    async def main():
        async with create_connected_server_and_client_session(srv.server) as client:
            tools = {t.name: t for t in (await client.list_tools()).tools}
            meta = tools["open_dashboard"].meta
            assert meta["ui"]["resourceUri"] == srv.DASHBOARD_URI
            assert meta["ui/resourceUri"] == srv.DASHBOARD_URI
            assert tools["dashboard_snapshot"].meta["ui"]["visibility"] == ["app"]

            res = await client.read_resource(srv.DASHBOARD_URI)
            c = res.contents[0]
            assert c.mimeType == "text/html;profile=mcp-app"
            assert "ui/initialize" in c.text and "<script" in c.text

            out = await client.call_tool("open_dashboard", {"symbol": "ASELS"})
            assert not out.isError
            assert out.structuredContent["sections"]["chart"]["data"]["symbol"] == "ASELS"
            assert out.structuredContent["local_url"].startswith("http://127.0.0.1:")
            assert "ASELS" in out.content[0].text

            snap = await client.call_tool("dashboard_snapshot",
                                          {"state": {"symbol": "THYAO"}})
            assert snap.structuredContent["state"]["symbol"] == "THYAO"
            bad = await client.call_tool("dashboard_action",
                                         {"action": "risk_check", "symbol": "X"})
            assert bad.isError

    try:
        asyncio.run(main())
    finally:
        dashboard_web.stop()


# ---------------------------------------------------------------- local web


@pytest.fixture
def web():
    loop = asyncio.new_event_loop()
    import threading

    threading.Thread(target=loop.run_forever, daemon=True).start()

    async def dispatch(name, args):
        return {"echo": name, "args": args}

    url = dashboard_web.start(loop, dispatch, port=0)
    port = int(url.split(":")[2].split("/")[0])
    token = url.split("t=")[1]
    yield port, token
    dashboard_web.stop()
    loop.call_soon_threadsafe(loop.stop)


def _req(port, method, path, body=None, headers=None, host=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    h = {"Host": host or f"127.0.0.1:{port}", **(headers or {})}
    conn.request(method, path, body=json.dumps(body) if body is not None else None, headers=h)
    r = conn.getresponse()
    return r.status, r.read()


def test_web_requires_token_and_host(web):
    port, token = web
    assert _req(port, "GET", "/")[0] == 403
    status, body = _req(port, "GET", f"/?t={token}")
    assert status == 200 and b"BIST Trader" in body
    assert _req(port, "GET", f"/?t={token}", host="evil.example:80")[0] == 403


def test_web_api_allowlist(web):
    port, token = web
    hdr = {"X-Dashboard-Token": token, "Content-Type": "application/json"}
    ok, body = _req(port, "POST", "/api/call",
                    {"name": "dashboard_snapshot", "arguments": {"state": {}}}, hdr)
    assert ok == 200 and json.loads(body)["structuredContent"]["echo"] == "dashboard_snapshot"
    assert _req(port, "POST", "/api/call", {"name": "set_risk_config", "arguments": {}},
                hdr)[0] == 403
    assert _req(port, "POST", "/api/call", {"name": "dashboard_snapshot"},
                {"X-Dashboard-Token": "wrong"})[0] == 403

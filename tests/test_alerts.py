"""Alerts: builders, dedup, outbox, Telegram delivery and token secrecy."""

import asyncio
import json

import httpx

from bist_trader_mcp import alerts
from bist_trader_mcp import http_utils as hu

TOKEN = "123456:SECRET-token-value"


def _install(handler):
    async def setup():
        hu._shared_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        hu._shared_client_loop = asyncio.get_running_loop()
    return setup


def _run_with_transport(handler, coro_factory):
    async def main():
        await _install(handler)()
        return await coro_factory()
    return asyncio.run(main())


def test_lifecycle_and_pick_messages():
    changes = [
        {"trade_id": "a1", "symbol": "THYAO", "status": "closed", "reason": "target",
         "r": 2.1, "exit": 310.0},
        {"trade_id": "b2", "symbol": "ASELS", "status": "closed", "reason": "stop_gap",
         "r": -1.3, "exit": 90.0},
        {"trade_id": "c3", "symbol": "GARAN", "status": "open", "fill": 100.0},
        {"trade_id": "d4", "symbol": "AKBNK", "status": "cancelled"},
    ]
    out = alerts.from_tracked_changes(changes)
    assert [a["severity"] for a in out] == ["good", "bad", "info", "info"]
    assert "HEDEF" in out[0]["text"] and "+2.10R" in out[0]["text"]
    assert "STOP (boşlukla)" in out[1]["text"]
    picks = alerts.from_new_picks([{"symbol": "THYAO", "verdict": "AL",
                                    "plan": {"entry": 300, "stop": 290, "target": 330,
                                             "risk_reward": 3.0},
                                    "risk": {"sizing": {"quantity": 100}}}], "2026-09-25")
    assert "100 adet" in picks[0]["text"] and picks[0]["key"] == "pick:2026-09-25:THYAO"


def test_near_stop_long_and_short():
    rows = [
        {"id": "L", "symbol": "THYAO", "direction": "long", "entry": 100, "stop": 90},
        {"id": "S", "symbol": "ASELS", "direction": "short", "entry": 100, "stop": 110},
        {"id": "F", "symbol": "GARAN", "direction": "long", "entry": 100, "stop": 90},
    ]
    out = alerts.near_stop_alerts(rows, {"THYAO": 92.0, "ASELS": 108.5, "GARAN": 99.0})
    assert sorted(a["symbol"] for a in out) == ["ASELS", "THYAO"]


def test_dedup_and_outbox_without_telegram():
    a = [alerts.alert("k1", "x", "THYAO", "bir"), alerts.alert("k2", "x", "ASELS", "iki")]
    first = asyncio.run(alerts.deliver(a))
    again = asyncio.run(alerts.deliver(a + [alerts.alert("k3", "x", None, "üç")]))
    assert (first["new"], first["sent"], first["telegram"]) == (2, 0, False)
    assert again["new"] == 1
    assert [r["key"] for r in alerts.recent_alerts()] == ["k3", "k2", "k1"]


def test_telegram_delivery(monkeypatch):
    monkeypatch.setenv("BIST_TELEGRAM_BOT_TOKEN", TOKEN)
    monkeypatch.setenv("BIST_TELEGRAM_CHAT_ID", "42")
    seen = []

    def handler(req):
        seen.append(req)
        return httpx.Response(200, json={"ok": True})

    res = _run_with_transport(handler, lambda: alerts.deliver(
        [alerts.alert("t1", "x", "THYAO", "merhaba", "good")]))
    assert res["sent"] == 1 and not res["errors"]
    body = json.loads(seen[0].content)
    assert body["chat_id"] == "42" and "✅ merhaba" in body["text"]


def test_bot_token_never_leaks_in_errors(monkeypatch):
    monkeypatch.setenv("BIST_TELEGRAM_BOT_TOKEN", TOKEN)
    monkeypatch.setenv("BIST_TELEGRAM_CHAT_ID", "42")
    res = _run_with_transport(lambda req: httpx.Response(401),
                              lambda: alerts.deliver([alerts.alert("t2", "x", None, "x")]))
    assert res["sent"] == 0 and res["errors"]
    dumped = json.dumps(res, ensure_ascii=False)
    assert TOKEN not in dumped and "***" in dumped


def test_check_alerts_tool(monkeypatch):
    from bist_trader_mcp import dashboard_data, tools, trade_journal

    trade_journal.log_trade_plan({"symbol": "THYAO", "direction": "long", "entry": 100,
                                  "stop": 90, "targets": [120]}, status="open")

    async def quotes(pairs):
        return [{"symbol": a, "last": 91.0} for a, _ in pairs]

    async def no_kap(**kw):
        raise RuntimeError("playwright missing")

    monkeypatch.setattr(dashboard_data, "_quotes", quotes)
    monkeypatch.setattr(tools, "fetch_disclosures", no_kap)
    res = asyncio.run(tools.check_alerts())
    assert res["watched_symbols"] == ["THYAO"] and res["new"] == 1
    assert res["notes"] and "KAP" in res["notes"][0]
    assert asyncio.run(tools.check_alerts())["new"] == 0  # same day → not repeated

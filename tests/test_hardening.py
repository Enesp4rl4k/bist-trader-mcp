"""Hardening: safe journal writes, input validation, jobs, timeouts, tool stats."""

import json
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from bist_trader_mcp import trade_journal as tj
from bist_trader_mcp._fileio import atomic_write_text, locked

WRITER = """
import sys
from bist_trader_mcp.trade_journal import log_trade_plan
for i in range(50):
    log_trade_plan({"symbol": sys.argv[2] + str(i), "direction": "long",
                    "entry": 10, "stop": 9}, journal_path=sys.argv[1])
"""


def test_two_processes_writing_the_journal_lose_nothing(tmp_path):
    path = tmp_path / "journal.json"
    procs = [
        subprocess.Popen([sys.executable, "-c", WRITER, str(path), tag])
        for tag in ("A", "B")
    ]
    assert all(p.wait(timeout=120) == 0 for p in procs)
    rows = json.loads(path.read_text())
    assert len(rows) == 100
    assert len({r["id"] for r in rows}) == 100


def test_threads_updating_the_journal_lose_nothing(tmp_path):
    path = tmp_path / "journal.json"
    ids = [tj.log_trade_plan({"symbol": f"S{i}", "entry": 1, "stop": 0.9},
                             journal_path=path)["trade_id"] for i in range(20)]
    threads = [threading.Thread(target=tj.update_trade_status,
                                args=(i, "open"), kwargs={"journal_path": path})
               for i in ids]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert all(r["status"] == "open" for r in json.loads(path.read_text()))


def test_corrupt_journal_is_backed_up_not_overwritten(tmp_path):
    path = tmp_path / "journal.json"
    path.write_text('[{"id": "old", "symbol": "THYAO"')  # truncated write
    tj.log_trade_plan({"symbol": "NEW", "entry": 1, "stop": 0.9}, journal_path=path)
    backups = list(tmp_path.glob("journal.json.corrupt-*"))
    assert len(backups) == 1 and "THYAO" in backups[0].read_text()
    assert [r["symbol"] for r in json.loads(path.read_text())] == ["NEW"]


def test_atomic_write_leaves_no_temp_files(tmp_path):
    p = tmp_path / "x.json"
    atomic_write_text(p, "1")
    atomic_write_text(p, "2")
    assert p.read_text() == "2"
    assert sorted(f.name for f in tmp_path.iterdir()) == ["x.json"]


def test_lock_times_out_instead_of_hanging(tmp_path):
    p = tmp_path / "y.json"
    got = threading.Event()
    release = threading.Event()

    def holder():
        with locked(p):
            got.set()
            release.wait(5)

    t = threading.Thread(target=holder)
    t.start()
    got.wait(5)
    with pytest.raises(TimeoutError):
        with locked(p, timeout=0.2):
            pass
    release.set()
    t.join()
    with locked(p, timeout=1):  # free again
        pass


def test_risk_config_writes_are_atomic(tmp_path, monkeypatch):
    from bist_trader_mcp import risk_engine

    monkeypatch.setenv("BIST_RISK_CONFIG", str(tmp_path / "r.json"))
    risk_engine.save_config({"equity": 50_000})
    risk_engine.save_config({"risk_per_trade_pct": 0.5})
    cfg = json.loads(Path(tmp_path / "r.json").read_text())
    assert cfg["equity"] == 50_000 and cfg["risk_per_trade_pct"] == 0.5


# ---------------------------------------------------------------- validation


@pytest.mark.parametrize("sym", ["THYAO", " thyao ", "BIST:THYAO", "XU030", "F_XU0300625",
                                 "BINANCE:BTCUSDT", "^XU100", "USDTRY=X", "XU0301!"])
def test_valid_symbols(sym):
    from bist_trader_mcp.validation import validate_symbol

    assert validate_symbol(sym) == sym.strip().upper()


@pytest.mark.parametrize("sym", ["", "THY AO", "THYAO;rm -rf /", "--help", "$(id)", "A" * 40,
                                 "../etc/passwd", None, 123])
def test_invalid_symbols_rejected(sym):
    from bist_trader_mcp.validation import validate_symbol

    with pytest.raises(ValueError):
        validate_symbol(sym)


def test_timeframes_and_prices():
    from bist_trader_mcp.validation import validate_price, validate_timeframe

    assert [validate_timeframe(t) for t in ("15", "240", "1d", "D", "1W")] == \
        ["15", "240", "1D", "D", "1W"]
    for bad in ("0", "1Y", "15m;x", ""):
        with pytest.raises(ValueError):
            validate_timeframe(bad)
    assert validate_price("12.5") == 12.5
    for bad in (0, -1, float("nan"), float("inf"), "abc", None):
        with pytest.raises(ValueError):
            validate_price(bad)


def test_bad_symbol_never_reaches_tradingview(monkeypatch):
    import bist_trader_mcp.tv_tools as tvt

    calls = []
    monkeypatch.setattr(tvt, "tv_call", lambda *a, **k: calls.append(a) or {"success": True})
    assert tvt.tv_chart_set_symbol("--evil")["error"] == "bad_input"
    assert tvt.tv_chart_set_timeframe("1D; x")["error"] == "bad_input"
    assert calls == []


def test_tools_return_bad_input_for_garbage():
    import asyncio

    from bist_trader_mcp import tools

    r = asyncio.run(tools.check_trade_risk("THYAO", "sideways", 10, 9))
    assert r["error"] == "bad_input"
    r = asyncio.run(tools.check_trade_risk("THYAO", "long", float("nan"), 9))
    assert r["error"] == "bad_input"
    r = asyncio.run(tools.dashboard_action("tv_open", "$(id)"))
    assert r["error"] == "bad_input"
    r = asyncio.run(tools.get_simple_price_action(symbol="bad symbol"))
    assert r["error"] == "bad_input"


# ---------------------------------------------------------------- server dispatch


def _call(name, args=None):
    import asyncio

    from bist_trader_mcp import server as srv

    out = asyncio.run(srv._call_tool(name, args or {}))
    text = out.content[0].text if hasattr(out, "content") else out[0].text
    return json.loads(text)


def test_async_detection_matches_reality():
    from bist_trader_mcp import server as srv

    reg = srv.TOOL_REGISTRY
    for name in ("get_bist_eod_ohlcv", "open_dashboard", "start_job", "get_simple_price_action"):
        assert srv._is_async_handler(reg[name]), name
    for name in ("calculate_bond_metrics", "analyze_price_action", "get_job", "tv_chart_set_symbol"):
        assert not srv._is_async_handler(reg[name]), name


def test_slow_sync_tool_does_not_freeze_the_server(monkeypatch):
    import asyncio
    import time as _t

    from bist_trader_mcp import server as srv

    monkeypatch.setitem(srv.TOOL_REGISTRY, "slow_sync", {
        "description": "", "inputSchema": {}, "handler": lambda a: _t.sleep(0.4) or {"ok": 1},
        "meta": None, "structured": False, "timeout": None, "_is_async": False,
    })

    async def main():
        ticks = 0

        async def ticker():
            nonlocal ticks
            for _ in range(30):
                await asyncio.sleep(0.01)
                ticks += 1

        await asyncio.gather(srv._call_tool("slow_sync", {}), ticker())
        return ticks

    assert asyncio.run(main()) == 30  # the loop kept ticking while the tool slept


def test_timeout_and_error_envelope(monkeypatch):
    import asyncio

    from bist_trader_mcp import server as srv

    async def hang(_):
        await asyncio.sleep(5)

    monkeypatch.setitem(srv.TOOL_REGISTRY, "hangs", {
        "description": "", "inputSchema": {}, "handler": hang, "meta": None,
        "structured": False, "timeout": 0.2, "_is_async": True,
    })
    out = _call("hangs")
    assert out["error"] == "timeout" and out["tool"] == "hangs"
    boom = _call("calculate_bond_metrics", {})  # missing required args
    assert boom["error"] == "missing_argument" and boom["tool"] == "calculate_bond_metrics"


def test_tool_stats_are_recorded():
    from bist_trader_mcp.telemetry import tool_stats

    _call("list_catalog")
    _call("calculate_bond_metrics", {})
    stats = tool_stats()
    assert stats["list_catalog"]["calls"] >= 1
    assert stats["calculate_bond_metrics"]["errors"] >= 1
    assert "tools" in _call("get_network_stats")


def test_background_job_lifecycle(monkeypatch):
    import asyncio

    from bist_trader_mcp import jobs

    async def fake_universe(**kw):
        await asyncio.sleep(0.05)
        return {"summary_tr": "ok", "symbols": kw.get("symbols")}

    async def broken(**kw):
        raise RuntimeError("tv down")

    monkeypatch.setattr(jobs, "_kinds", lambda: {"backtest_universe": fake_universe,
                                                 "daily_pipeline": broken})
    jobs._jobs.clear()

    async def main():
        a = await jobs.start_job("backtest_universe", {"symbols": ["THYAO"]})
        b = await jobs.start_job("daily_pipeline", {})
        assert jobs.get_job(a["job_id"])["status"] in ("queued", "running")
        await asyncio.sleep(0.2)
        return a["job_id"], b["job_id"]

    ja, jb = asyncio.run(main())
    done = jobs.get_job(ja)
    assert done["status"] == "done" and done["result"]["symbols"] == ["THYAO"]
    failed = jobs.get_job(jb)
    assert failed["status"] == "failed" and "tv down" in failed["error"]
    assert jobs.get_job("nope")["error"] == "not_found"
    assert len(jobs.get_job()["jobs"]) == 2
    assert asyncio.run(jobs.start_job("rm_rf", {}))["error"] == "bad_input"


def test_tradingview_sequences_do_not_interleave(monkeypatch):
    import time as _t

    import bist_trader_mcp.tv_tools as tvt

    log = []
    real_sleep = _t.sleep
    results = {}

    def fake_call(*args, **kw):
        log.append((threading.current_thread().name, args[0]))
        real_sleep(0.01)  # give other threads a chance to cut in
        if args[0] == "ohlcv":
            return {"bars": [{"open": 1, "high": 2, "low": 0.5, "close": 1.5,
                              "time": 1_700_000_000 + i * 86400} for i in range(30)]}
        return {"success": True}

    monkeypatch.setattr(tvt, "tv_call", fake_call)
    monkeypatch.setattr(tvt.time, "sleep", lambda s: real_sleep(0.01))

    def run(sym):
        results[sym] = tvt.tv_fetch_ohlcv(sym, "1D", 30)

    threads = [threading.Thread(target=run, args=(s,), name=s)
               for s in ("THYAO", "ASELS", "GARAN")]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert all(r.get("success") for r in results.values()) and len(results) == 3
    # each thread's symbol → timeframe → ohlcv commands must be contiguous
    owners = [who for who, _ in log]
    runs = [owners[0]] + [b for a, b in zip(owners, owners[1:]) if a != b]
    assert len(runs) == 3, log

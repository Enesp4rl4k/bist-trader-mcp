"""Daily loop: scan → journal → replay outcomes → dashboard."""

import asyncio
import json

import pytest

from bist_trader_mcp import daily_pipeline as dp
from bist_trader_mcp.pa_weights import use_weights

from .test_candle_forecast import _series


@pytest.fixture(autouse=True)
def _isolated_risk_config(tmp_path, monkeypatch):
    monkeypatch.setenv("BIST_RISK_CONFIG", str(tmp_path / "risk.json"))

DAY = 86_400


def _bars(seed, n, drift=0.003):
    o, h, l, c = _series(n=700, drift=drift, vol=0.012, seed=seed)
    times = [1_600_000_000 + i * DAY for i in range(700)]
    full = {"opens": o, "highs": h, "lows": l, "closes": c,
            "volumes": [5e6] * 700, "times": times}
    return {k: v[:n] for k, v in full.items()}


def test_replay_plan_long_hits_target_and_stop_rules():
    bars = {"opens": [100, 100, 101, 104], "highs": [101, 101, 102, 111],
            "lows": [99, 99, 100, 103], "closes": [100, 100.5, 101.5, 110],
            "times": [0, DAY, 2 * DAY, 3 * DAY]}
    plan = {"direction": "long", "entry": 100.0, "stop": 95.0, "targets": [110.0],
            "market": True, "signal_time": 0, "max_hold": 20}
    res = dp.replay_plan(plan, bars, cost_pct=0.0)
    assert res["status"] == "closed" and res["reason"] == "target"
    assert res["r"] == pytest.approx((110 - 100) / 5)

    early = {k: v[:1] for k, v in bars.items()}
    assert dp.replay_plan(plan, early, 0.0)["status"] == "planned"


def test_replay_limit_plan_cancelled_when_never_filled():
    bars = {"opens": [100] * 6, "highs": [101] * 6, "lows": [99] * 6, "closes": [100] * 6,
            "times": [i * DAY for i in range(6)]}
    plan = {"direction": "long", "entry": 90.0, "stop": 85.0, "targets": [110.0],
            "market": False, "signal_time": 0}
    assert dp.replay_plan(plan, bars, 0.0)["status"] == "cancelled"


def test_pipeline_logs_then_tracks_outcomes(tmp_path, monkeypatch):
    monkeypatch.setenv("BIST_PANEL_DB", str(tmp_path / "panel.db"))
    journal = tmp_path / "journal.json"
    seeds = {"AAA": 3, "BBB": 5, "CCC": 7, "DDD": 11}
    state = {"n": 450}

    async def load(sym):
        return _bars(seeds[sym], state["n"])

    async def run():
        with use_weights(None):
            return await dp.run_pipeline(
                list(seeds), load, top_n=4, journal_path=journal, html_dir=tmp_path,
            )

    day1 = asyncio.run(run())
    assert day1["symbols_scanned"] == 4
    assert len(day1["logged_trade_ids"]) == len(day1["picks"])
    assert (tmp_path / f"daily_{day1['date']}.html").exists()
    assert day1["prices_stored"] > 0
    assert day1["logged_trade_ids"], f"no plans on day 1: {day1['risk_rejected']}"
    for p in day1["picks"]:
        assert p["risk"]["approved"] and p["risk"]["sizing"]["quantity"] > 0
    rows = json.loads(journal.read_text())
    assert all(r["plan_snapshot"]["source"] == dp.PIPELINE_TAG for r in rows)

    # no duplicate plans for symbols that already have one open/planned
    again = asyncio.run(run())
    assert not set(again["logged_trade_ids"]) & set(day1["logged_trade_ids"])
    assert not {p["symbol"] for p in again["picks"]} & {r["symbol"] for r in rows}

    state["n"] = 700  # 300 new bars later every plan must be resolved
    later = asyncio.run(run())
    resolved = {c["trade_id"]: c["status"] for c in later["tracked_changes"]}
    for tid in day1["logged_trade_ids"]:
        assert resolved.get(tid) in ("closed", "cancelled")
    perf = later["performance"]
    assert perf["closed"] + perf["cancelled"] >= len(day1["logged_trade_ids"])


def test_rank_prefers_forecast_agreement_then_track_record():
    base = {"data_issues": [], "confluence": 50}
    a = {**base, "symbol": "A", "forecast_agrees": False,
         "plan": {"risk_reward": 3.0, "track_record": {"avg_r": 0.5}}}
    b = {**base, "symbol": "B", "forecast_agrees": True, "plan": {"risk_reward": 1.5}}
    c = {**base, "symbol": "C", "forecast_agrees": True,
         "plan": {"risk_reward": 1.5, "track_record": {"avg_r": 0.3}}}
    d = {**base, "symbol": "D", "forecast_agrees": True, "plan": {"risk_reward": 9},
         "data_issues": ["suspect_split: 1 bar(s)"]}
    assert [s["symbol"] for s in dp.rank_candidates([a, b, c, d])] == ["C", "B", "A"]


def test_run_daily_pipeline_tool(monkeypatch, tmp_path):
    import bist_trader_mcp.tv_tools as tvt
    from bist_trader_mcp import tools

    monkeypatch.setenv("BIST_TRADE_JOURNAL", str(tmp_path / "j.json"))
    monkeypatch.setenv("BIST_PANEL_DB", str(tmp_path / "p.db"))
    monkeypatch.setenv("BIST_FORECAST_DIR", str(tmp_path))
    monkeypatch.setenv("BIST_PA_WEIGHTS", str(tmp_path / "w.json"))
    tools._BARS_CACHE.clear()
    seeds = {"AAA": 3, "BBB": 5}
    monkeypatch.setattr(tvt, "tv_fetch_ohlcv", lambda sym, *a, **k: {
        "success": True, "symbol_tv": sym, "bars": _bars(seeds[sym], 450)})
    res = asyncio.run(tools.run_daily_pipeline(list(seeds)))
    tools._BARS_CACHE.clear()
    assert res["symbols_scanned"] == 2
    assert res["html_path"].startswith(str(tmp_path))
    assert "summary_tr" in res


def test_pipeline_stops_logging_when_risk_budget_is_full(tmp_path, monkeypatch):
    from bist_trader_mcp import risk_engine

    monkeypatch.setenv("BIST_PANEL_DB", str(tmp_path / "panel.db"))
    risk_engine.save_config({"max_open_risk_pct": 1.0, "risk_per_trade_pct": 1.0})
    journal = tmp_path / "journal.json"
    seeds = {"AAA": 3, "BBB": 5, "CCC": 7}

    async def load(sym):
        return _bars(seeds[sym], 450)

    async def run():
        with use_weights(None):
            return await dp.run_pipeline(list(seeds), load, top_n=5, journal_path=journal,
                                         store_prices=False)

    res = asyncio.run(run())
    assert len(res["logged_trade_ids"]) == 1  # budget for exactly one 1% trade
    assert any("open_risk" in r["blocking"] for r in res["risk_rejected"])

"""Paper account: TL maths, drawdown, marking, live-vs-backtest, dashboard tracking."""

import asyncio
import json
import os

import pytest

from bist_trader_mcp import pa_weights, paper, risk_engine

from .test_daily_pipeline import _bars


def _row(i, pnl=None, status="closed", qty=100, entry=100.0, stop=95.0, sym="THYAO",
         src="daily_pipeline"):
    return {"id": f"t{i}", "symbol": sym, "status": status, "direction": "long",
            "entry": entry, "stop": stop, "pnl": pnl, "sizing": {"quantity": qty},
            "logged_at": f"2026-09-{i + 1:02d}T10:00:00+00:00",
            "updated_at": f"2026-09-{i + 1:02d}T17:00:00+00:00",
            "plan_snapshot": {"source": src, "signal_time": 1_700_000_000 + i}}


def _journal(rows):
    path = os.environ["BIST_TRADE_JOURNAL"]
    with open(path, "w") as f:
        json.dump(rows, f)
    return path


def test_tl_equity_and_drawdown():
    risk_engine.save_config({"equity": 100_000})
    # risk per trade = 100 shares × 5 TL = 500 TL
    _journal([_row(0, 2.0), _row(1, -1.0), _row(2, -1.0), _row(3, 3.0),
              _row(4, None, status="planned"),
              {**_row(5, 1.0), "plan_snapshot": {"source": "manual"}}])  # not tracked
    acc = paper.paper_account()
    assert acc["closed_trades"] == 4
    assert acc["equity"] == pytest.approx(100_000 + 500 * (2 - 1 - 1 + 3))
    # peak 101 000 after +2R, trough 100 000 → -0.99 %
    assert acc["max_drawdown_pct"] == pytest.approx(-100 * 1000 / 101_000, abs=0.01)
    assert acc["pending_plans"] == 1
    assert acc["stats"]["trades"] == 4


def test_open_position_is_marked_to_market():
    _journal([_row(0, status="open", qty=50, entry=100, stop=95)])
    acc = paper.paper_account(bars_by_symbol={"THYAO": {"closes": [100, 104.0]}})
    assert acc["open_positions"][0]["unrealised"] == pytest.approx(50 * 4.0)
    assert acc["equity_with_open"] == pytest.approx(acc["equity"] + 200.0)


@pytest.mark.parametrize("live,bt,verdict", [
    (0.30, 0.40, "consistent"), (0.10, 0.40, "weaker"),
    (-0.10, 0.40, "diverging"), (0.20, -0.05, "backtest_negative"),
])
def test_live_vs_backtest_verdicts(live, bt, verdict):
    out = paper.compare_live_to_backtest(live, 25, {"expectancy_r": bt})
    assert out["verdict"] == verdict


def test_live_vs_backtest_needs_samples_and_a_backtest():
    assert paper.compare_live_to_backtest(0.5, 5, {"expectancy_r": 0.3})["verdict"] == \
        "insufficient"
    assert paper.compare_live_to_backtest(0.5, 50, None)["verdict"] == "no_backtest"


def test_backtest_expectancy_read_from_saved_weights():
    pa_weights.save_weights({"active": True, "created_at": "x",
                             "validation": {"oos_baseline": {"expectancy_r": 0.21,
                                                             "trades": 60}}})
    assert paper.backtest_expectancy()["expectancy_r"] == 0.21


def test_dashboard_trade_is_tracked_even_outside_the_universe(monkeypatch):
    from bist_trader_mcp import daily_pipeline as dp
    from bist_trader_mcp import tools
    from bist_trader_mcp.pa_weights import use_weights

    async def fake_risk(*a, **k):
        return {"approved": True, "sizing": {"quantity": 10}, "summary_tr": "ONAY",
                "checks": [], "blocking": [], "warnings": []}

    monkeypatch.setattr(tools, "check_trade_risk", fake_risk)
    bars = _bars(3, 460)
    last = bars["closes"][-1]
    # buy limit far below the market: never touched → cancelled after the fill window
    plan = {"direction": "long", "entry": last * 0.5, "stop": last * 0.4,
            "target": last * 3}
    res = asyncio.run(tools.dashboard_action("journal_add", "XYZ", "1D", plan))
    assert res.get("trade_id")
    rows = json.loads(open(os.environ["BIST_TRADE_JOURNAL"]).read())
    rows[0]["plan_snapshot"]["signal_time"] = bars["times"][400]
    _journal(rows)

    async def load(sym):
        return bars

    async def run():
        with use_weights(None):
            return await dp.run_pipeline(["AAA"], load, top_n=0, notify=False,
                                         store_prices=False)

    out = asyncio.run(run())
    change = next(c for c in out["tracked_changes"] if c["symbol"] == "XYZ")
    assert change["status"] == "cancelled"

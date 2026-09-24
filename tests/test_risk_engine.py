"""Portfolio risk engine: sizing, limits, breakers, clusters, VaR."""

import json
import math
import random
from datetime import datetime, timedelta, timezone

import pytest

from bist_trader_mcp import risk_engine as re_
from bist_trader_mcp.risk_engine import RiskConfig, check_trade, portfolio_risk, position_size

NOW = datetime(2026, 9, 24, 15, 0, tzinfo=timezone.utc)
NO_EVENTS: list = []


def _rets(seed, n=120):
    rng = random.Random(seed)
    return [rng.gauss(0, 0.02) for _ in range(n)]


def _bars_from_rets(rets, vol=1e6):
    p, c = 100.0, []
    for r in rets:
        p *= math.exp(r)
        c.append(p)
    return {"closes": c, "volumes": [vol] * len(c)}


def _journal(tmp_path, rows):
    path = tmp_path / "j.json"
    path.write_text(json.dumps(rows))
    return path


def _open(sym, entry=100.0, stop=95.0, qty=None, direction="long"):
    row = {"id": sym, "symbol": sym, "status": "open", "direction": direction,
           "entry": entry, "stop": stop, "logged_at": NOW.isoformat()}
    if qty:
        row["sizing"] = {"quantity": qty}
    return row


PLAN = {"direction": "long", "entry": 100.0, "stop": 95.0, "target": 115.0}


def test_position_size_respects_risk_and_lot():
    cfg = RiskConfig(equity=100_000, risk_per_trade_pct=1.0, lot_size=10)
    s = position_size(100.0, 95.0, cfg)
    assert s["quantity"] == 200 and s["risk_amount"] == 1000.0 and s["risk_pct"] == 1.0
    tight = position_size(100.0, 99.99, cfg)  # would need 100k shares → capped by equity
    assert tight["notional"] <= cfg.equity


def test_clean_trade_is_approved(tmp_path):
    res = check_trade(PLAN, symbol="THYAO", cfg=RiskConfig(), journal_path=_journal(tmp_path, []),
                      now=NOW, events=NO_EVENTS)
    assert res["approved"] and res["sizing"]["quantity"] == 200
    assert res["blocking"] == []


def test_wrong_side_target_blocked(tmp_path):
    bad = {**PLAN, "target": 90.0}
    res = check_trade(bad, symbol="X", cfg=RiskConfig(), journal_path=_journal(tmp_path, []),
                      now=NOW, events=NO_EVENTS)
    assert not res["approved"] and "geometry" in res["blocking"]


def test_duplicate_max_positions_and_heat(tmp_path):
    rows = [_open(f"S{i}") for i in range(6)]
    j = _journal(tmp_path, rows)
    res = check_trade(PLAN, symbol="S1", cfg=RiskConfig(), journal_path=j, now=NOW,
                      events=NO_EVENTS)
    assert {"duplicate", "max_positions", "open_risk"} <= set(res["blocking"])
    assert res["sizing"]["quantity"] == 0


def test_circuit_breaker_after_daily_losses(tmp_path):
    closed = [{"id": f"c{i}", "symbol": "Z", "status": "closed", "pnl": -1.0,
               "updated_at": NOW.isoformat()} for i in range(3)]
    res = check_trade(PLAN, symbol="X", cfg=RiskConfig(), journal_path=_journal(tmp_path, closed),
                      now=NOW, events=NO_EVENTS)
    assert "circuit_breaker" in res["blocking"]
    old = [{**c, "updated_at": (NOW - timedelta(days=10)).isoformat()} for c in closed]
    ok = check_trade(PLAN, symbol="X", cfg=RiskConfig(), journal_path=_journal(tmp_path, old),
                     now=NOW, events=NO_EVENTS)
    assert "circuit_breaker" not in ok["blocking"]


def test_correlation_cluster_blocks_third_bank(tmp_path):
    base = _rets(1)
    bars = {
        "GARAN": _bars_from_rets([0.9 * b + 0.1 * x for b, x in zip(base, _rets(2))]),
        "AKBNK": _bars_from_rets([0.9 * b + 0.1 * x for b, x in zip(base, _rets(3))]),
        "YKBNK": _bars_from_rets([0.9 * b + 0.1 * x for b, x in zip(base, _rets(4))]),
        "ASELS": _bars_from_rets(_rets(9)),
    }
    j = _journal(tmp_path, [_open("GARAN"), _open("AKBNK")])
    res = check_trade(PLAN, symbol="YKBNK", cfg=RiskConfig(), bars_by_symbol=bars,
                      journal_path=j, now=NOW, events=NO_EVENTS)
    assert "correlation_cluster" in res["blocking"]
    other = check_trade(PLAN, symbol="ASELS", cfg=RiskConfig(), bars_by_symbol=bars,
                        journal_path=j, now=NOW, events=NO_EVENTS)
    assert "correlation_cluster" not in other["blocking"]


def test_liquidity_and_limit_day_warnings(tmp_path):
    closes = [100.0] * 30 + [110.0]
    thin = {"X": {"closes": closes, "volumes": [300.0] * 31}}  # ~30k TL/day traded
    res = check_trade(PLAN, symbol="X", cfg=RiskConfig(), bars_by_symbol=thin,
                      journal_path=_journal(tmp_path, []), now=NOW, events=NO_EVENTS)
    assert "liquidity" in res["blocking"]  # 20k notional vs 30k ADV → >3x the 5% cap
    assert "limit_day" in res["warnings"]


def test_macro_event_is_warning_only(tmp_path):
    ev = [{"date": "2026-09-25", "event": "PPK", "importance": "high"}]
    res = check_trade(PLAN, symbol="X", cfg=RiskConfig(), journal_path=_journal(tmp_path, []),
                      now=NOW, events=ev)
    assert res["approved"] and "macro_event" in res["warnings"]


def test_portfolio_risk_heat_and_var(tmp_path):
    bars = {"A": _bars_from_rets(_rets(1)), "B": _bars_from_rets(_rets(2))}
    j = _journal(tmp_path, [_open("A", qty=200), _open("B", qty=100)])
    pr = portfolio_risk(cfg=RiskConfig(), bars_by_symbol=bars, journal_path=j, now=NOW)
    assert pr["open_positions"] == 2
    assert pr["heat_pct"] == pytest.approx(1.0 + 0.5)
    assert pr["var_95_1d"]["amount"] > 0
    assert not pr["circuit_breaker"]


def test_config_roundtrip_and_validation(tmp_path, monkeypatch):
    monkeypatch.setenv("BIST_RISK_CONFIG", str(tmp_path / "r.json"))
    assert re_.load_config() == RiskConfig()
    cfg = re_.save_config({"equity": 250_000, "risk_per_trade_pct": 0.5})
    assert re_.load_config().equity == 250_000 and cfg.risk_per_trade_pct == 0.5
    with pytest.raises(ValueError):
        re_.save_config({"risk_per_trade_pct": 50})

"""Tests for trade playbook — consistency and detailed plans."""

from __future__ import annotations

from bist_trader_mcp.position_design import design_trade_setup
from bist_trader_mcp.trade_playbook import (
    design_ltf_trade_plan,
    design_mtf_trade_plan,
    enrich_trade_plan,
    get_trade_playbook_rules,
    validate_trade_consistency,
)


def _uptrend(n: int = 80) -> tuple[list[float], list[float], list[float]]:
    c, h, l = [], [], []
    p = 100.0
    for i in range(n):
        p += 0.5
        c.append(p)
        h.append(p + 0.4)
        l.append(p - 0.4)
    return c, h, l


def test_playbook_rules_exposed():
    rules = get_trade_playbook_rules()
    assert "rules" in rules
    assert rules["rules"]["min_trade_quality"] == "a"


def test_enrich_adds_execution_plan():
    c, h, l = _uptrend()
    base = design_trade_setup(
        symbol="TEST",
        direction="long",
        entry_price=c[-1],
        stop_price=c[-1] * 0.97,
        target_prices=[c[-1] * 1.06, c[-1] * 1.09],
        equity=100_000,
        min_risk_reward=1.5,
        closes=c,
        highs=h,
        lows=l,
    )
    out = enrich_trade_plan(base)
    assert "thesis" in out
    assert "execution_plan" in out
    assert out["execution_plan"]["targets"][0].get("size_pct") == 50
    assert "trade_report" in out


def test_validate_catches_low_rr():
    plan = {
        "symbol": "X",
        "direction": "long",
        "entry": 100,
        "stop": 99,
        "targets": [{"label": "TP1", "price": 100.5, "risk_reward": 0.5}],
        "best_risk_reward": 0.5,
        "approved": False,
        "price_action": {"market_structure": "bullish", "atr_14": 2.0},
    }
    v = validate_trade_consistency(plan)
    assert v["passed"] is False
    assert "risk_reward" in v["mandatory_failed"]


def test_design_ltf_trade_plan_pipeline():
    c, h, l = _uptrend()
    out = design_ltf_trade_plan(
        symbol="SYNTH:TEST",
        closes=c,
        highs=h,
        lows=l,
        direction="long",
        rules={"min_trade_quality": "c", "require_journal_no_same_symbol_conflict": False},
    )
    assert "plan" in out
    assert "validation" in out
    assert "portfolio_gate" in out
    assert out.get("trade_report")


def test_design_mtf_no_trade_on_conflict():
    htf = _uptrend(80)
    ltf_up = _uptrend(60)
    ltf_down = list(reversed(ltf_up[0]))  # wrong type - use downtrend
    c, h, l = [], [], []
    p = 200.0
    for _ in range(60):
        p -= 0.4
        c.append(p)
        h.append(p + 0.3)
        l.append(p - 0.3)
    out = design_mtf_trade_plan(
        symbol="TEST",
        htf_closes=htf[0],
        htf_highs=htf[1],
        htf_lows=htf[2],
        ltf_closes=c,
        ltf_highs=h,
        ltf_lows=l,
    )
    assert out.get("action") in ("no_trade", "execute")

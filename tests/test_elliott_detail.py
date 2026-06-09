"""Elliott detail panel tests."""

from bist_trader_mcp.elliott_detail import (
    build_impulse_rule_checklist,
)
from bist_trader_mcp.elliott_wave import analyze_elliott_wave
from tests.test_elliott_wave import _synthetic_bull_impulse_bars


def test_analyze_elliott_includes_detail():
    c, h, l = _synthetic_bull_impulse_bars(100)
    out = analyze_elliott_wave(c, h, l, swing_lookback=3)
    assert "detail" in out
    assert "report_tr" in out
    assert out.get("report_tr")
    prim = out.get("primary")
    if prim:
        assert "rule_checklist" in prim or prim.get("degree") == "correction"


def test_impulse_rule_checklist_on_primary():
    c, h, l = _synthetic_bull_impulse_bars(100)
    out = analyze_elliott_wave(c, h, l, swing_lookback=3)
    prim = out.get("primary")
    if prim and prim.get("degree") == "impulse":
        rules = prim.get("rule_checklist") or build_impulse_rule_checklist(prim)
        assert len(rules) >= 2
        assert any(r.get("rule") == "wave2_not_below_start" for r in rules)


def test_detail_panel_structure():
    c, h, l = _synthetic_bull_impulse_bars(100)
    out = analyze_elliott_wave(c, h, l, swing_lookback=3)
    panel = out.get("detail") or {}
    assert "report_tr" in panel
    assert "top_scores" in panel

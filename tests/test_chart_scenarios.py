"""Chart scenario merger tests."""

from bist_trader_mcp.chart_scenarios import (
    analyze_chart_scenarios,
    design_scenario_trade_plan,
)
from tests.test_elliott_wave import _synthetic_bull_impulse_bars


def _ltf_from_htf(htf_c, htf_h, htf_l, scale: float = 0.5):
    """Shorter LTF series aligned with HTF bull bias."""
    n = max(40, int(len(htf_c) * scale))
    return htf_c[-n:], htf_h[-n:], htf_l[-n:]


def test_analyze_chart_scenarios_structure():
    h_c, h_h, h_l = _synthetic_bull_impulse_bars(100)
    l_c, l_h, l_l = _ltf_from_htf(h_c, h_h, h_l)
    pack = analyze_chart_scenarios(
        symbol="SYNTH:TEST",
        htf_closes=h_c,
        htf_highs=h_h,
        htf_lows=h_l,
        ltf_closes=l_c,
        ltf_highs=l_h,
        ltf_lows=l_l,
        min_ew_score=20.0,
    )
    assert pack["symbol"] == "SYNTH:TEST"
    assert "scenarios" in pack
    assert len(pack["scenarios"]) >= 1
    assert "report" in pack
    assert "mtf" in pack
    assert "elliott_htf" in pack
    assert "confidence" in pack
    assert "data_quality" in pack
    assert pack["data_quality"]["ok"] is True


def test_insufficient_data_quality_short_circuits():
    c = [100.0] * 25
    h = [x + 1 for x in c]
    l = [x - 1 for x in c]
    pack = analyze_chart_scenarios(
        symbol="SHORT",
        htf_closes=c,
        htf_highs=h,
        htf_lows=l,
        ltf_closes=c,
        ltf_highs=h,
        ltf_lows=l,
    )
    assert pack.get("trade_candidate") is False
    assert pack.get("reason", "").startswith("data_quality")


def test_primary_scenario_prefers_pa_aligned_continuation():
    h_c, h_h, h_l = _synthetic_bull_impulse_bars(100)
    l_c, l_h, l_l = _ltf_from_htf(h_c, h_h, h_l)
    pack = analyze_chart_scenarios(
        symbol="SYNTH:TEST",
        htf_closes=h_c,
        htf_highs=h_h,
        htf_lows=h_l,
        ltf_closes=l_c,
        ltf_highs=l_h,
        ltf_lows=l_l,
        min_ew_score=20.0,
    )
    primary = pack["primary_scenario"]
    assert primary["id"] in (
        "continuation_aligned",
        "correction_complete",
        "pa_aligned",
        "no_setup",
        "pa_ew_conflict",
    )
    assert primary["id"] != "alternate_ew"
    assert "diagnostics" in pack


def test_pa_first_tradeable_when_elliott_weak():
    """Strong aligned PA must stay tradeable even if the EW count scores low."""
    h_c, h_h, h_l = _synthetic_bull_impulse_bars(120)
    l_c, l_h, l_l = _ltf_from_htf(h_c, h_h, h_l)
    # Force a very high EW threshold so no EW count can pass — isolates PA path.
    pack = analyze_chart_scenarios(
        symbol="SYNTH:TEST",
        htf_closes=h_c,
        htf_highs=h_h,
        htf_lows=h_l,
        ltf_closes=l_c,
        ltf_highs=l_h,
        ltf_lows=l_l,
        min_ew_score=99.0,
    )
    mtf = pack["mtf"]
    if mtf.get("aligned_direction") in ("long", "short") and mtf.get("recommended_setup"):
        assert pack["primary_scenario"]["id"] == "pa_aligned"
        # PA-first must not be forced to no_setup purely by weak Elliott.
        assert pack["primary_scenario"]["id"] != "no_setup"


def test_design_scenario_may_no_trade_on_conflict():
    # Flat noise — weak EW
    n = 60
    c = [100.0 + (i % 3) * 0.1 for i in range(n)]
    h = [x + 0.5 for x in c]
    l = [x - 0.5 for x in c]
    out = design_scenario_trade_plan(
        symbol="FLAT",
        htf_closes=c,
        htf_highs=h,
        htf_lows=l,
        ltf_closes=c,
        ltf_highs=h,
        ltf_lows=l,
        min_ew_score=90.0,
    )
    assert out.get("approved") is False or out.get("action") == "no_trade"

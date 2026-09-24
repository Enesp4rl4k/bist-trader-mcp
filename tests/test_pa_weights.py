"""Learned PA weights: factor multipliers, track-record veto, isolation."""

import pytest

from bist_trader_mcp import pa_weights
from bist_trader_mcp.pa_setups import score_confluence
from bist_trader_mcp.pa_simple import simple_price_action

from .test_candle_forecast import _series


@pytest.fixture(autouse=True)
def _tmp_weights(tmp_path, monkeypatch):
    monkeypatch.setenv("BIST_PA_WEIGHTS", str(tmp_path / "w.json"))


def _score():
    return score_confluence(
        direction="long", close=100.0,
        supports=[{"price": 99.5}], resistances=[{"price": 105.0}],
        structure="bullish", atr_val=2.0, volumes=None,
    )


def test_no_file_means_neutral_weights():
    assert pa_weights.factor_weight("bullish_structure") == 1.0
    assert pa_weights.setup_track_record("trend_retest") is None


def test_dropped_factor_contributes_nothing():
    base = _score()
    with pa_weights.use_weights({"factor_weights": {"bullish_structure": 0.0}}):
        dropped = _score()
    assert base["score"] - dropped["score"] == pytest.approx(22.0)
    assert "bullish_structure" in dropped["factors"]  # still reported, just not scored


def test_saved_weights_apply_only_when_active():
    doc = {"active": False, "factor_weights": {"bullish_structure": 0.0}}
    pa_weights.save_weights(doc)
    assert _score() == score_confluence(
        direction="long", close=100.0, supports=[{"price": 99.5}],
        resistances=[{"price": 105.0}], structure="bullish", atr_val=2.0, volumes=None,
    )
    pa_weights.save_weights({**doc, "active": True})
    assert pa_weights.factor_weight("bullish_structure") == 0.0
    with pa_weights.use_weights(None):  # measurement mode ignores the file
        assert pa_weights.factor_weight("bullish_structure") == 1.0


def _first_plan():
    o, h, l, c = _series(n=500, drift=0.004, vol=0.012, seed=3)
    for t in range(150, 500):
        r = simple_price_action(c[:t], h[:t], l[:t], o[:t], debug=True)
        if r["plan"]:
            return (o[:t], h[:t], l[:t], c[:t]), r
    pytest.skip("no plan produced on synthetic series")


def test_verdict_matches_plan():
    _, r = _first_plan()
    assert r["verdict"] == ("AL" if r["plan"]["direction"] == "long" else "SAT")


def test_losing_setup_type_is_vetoed_and_winning_one_annotated():
    bars, r = _first_plan()
    st = r["debug"]["setup_type"]
    o, h, l, c = bars
    bad = {"setup_track_record": {st: {"trades": 40, "win_rate_pct": 20.0, "avg_r": -0.5}}}
    with pa_weights.use_weights(bad):
        vetoed = simple_price_action(c, h, l, o)
    assert vetoed["verdict"] == "BEKLE" and vetoed["plan"] is None
    assert "kaybettirdi" in vetoed["reason"]

    good = {"setup_track_record": {st: {"trades": 40, "win_rate_pct": 55.0, "avg_r": 0.4}}}
    with pa_weights.use_weights(good):
        kept = simple_price_action(c, h, l, o)
    assert kept["verdict"] == r["verdict"]
    assert kept["plan"]["track_record"]["avg_r"] == 0.4

    few = {"setup_track_record": {st: {"trades": 5, "win_rate_pct": 0.0, "avg_r": -1.0}}}
    with pa_weights.use_weights(few):  # too few trades to trust
        assert simple_price_action(c, h, l, o)["verdict"] == r["verdict"]


def test_build_weights_from_attribution():
    attribution = {"factors": [
        {"factor": "a", "action": "keep"}, {"factor": "b", "action": "drop"},
        {"factor": "c", "action": "neutral"},
    ]}
    trades = [{"setup_type": "x", "r": 1.0}, {"setup_type": "x", "r": -1.0}]
    w = pa_weights.build_weights(attribution, trades)
    assert w["factor_weights"] == {"a": pa_weights.KEEP_WEIGHT, "b": 0.0}
    assert w["setup_track_record"]["x"] == {"trades": 2, "win_rate_pct": 50.0, "avg_r": 0.0}

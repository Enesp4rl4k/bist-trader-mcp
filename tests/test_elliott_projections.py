from bist_trader_mcp.elliott_projections import project_impulse_bull
from bist_trader_mcp.elliott_wave import Pivot, analyze_elliott_wave  # noqa: E402
from tests.test_elliott_wave import _synthetic_bull_impulse_bars


def test_wave5_projection_from_wave4():
    seg = [
        Pivot(10, 100.0, "low"),
        Pivot(20, 115.0, "high"),
        Pivot(30, 105.0, "low"),
        Pivot(45, 125.0, "high"),
        Pivot(55, 112.0, "low"),
    ]
    proj = project_impulse_bull(seg, bars_ahead=10, last_bar_index=80)
    assert proj["active_wave"] == "5"
    assert proj["primary_target"] == 127.0  # 112 + (115-100)
    assert len(proj["scenarios"]) >= 3
    assert proj["path_points"][-1]["label"] == "5?"


def test_analyze_includes_forecast():
    c, h, l = _synthetic_bull_impulse_bars(100)
    out = analyze_elliott_wave(c, h, l, swing_lookback=3)
    primary = out.get("primary")
    assert primary is not None
    assert primary.get("forecast") is not None
    assert primary.get("forecast_summary")
    assert primary.get("projected_points")

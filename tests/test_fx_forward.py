"""FX forward / IRP tests — pure math + monkeypatched EVDS."""

from __future__ import annotations

import math

import pytest

from bist_trader_mcp import tools
from bist_trader_mcp.evds import EVDSObservation
from bist_trader_mcp.fx import _tenor_to_days, fx_forward_curve
from bist_trader_mcp.series_catalog import POLICY_RATE_SERIES, USDTRY_SELLING


def test_tenor_parsing():
    assert _tenor_to_days("ON") == 1
    assert _tenor_to_days("1W") == 7
    assert _tenor_to_days("3M") == 90
    assert _tenor_to_days("1Y") == 365
    assert _tenor_to_days("45") == 45


def test_zero_rate_diff_yields_spot():
    pts = fx_forward_curve(spot=38.0, domestic_rate_pct=10.0, foreign_rate_pct=10.0, tenors=["1M", "1Y"])
    for p in pts:
        assert math.isclose(p.forward_outright, 38.0, rel_tol=1e-9)
        assert math.isclose(p.forward_points_pips, 0.0, abs_tol=1e-6)


def test_high_dom_low_for_widens_forward():
    pts = fx_forward_curve(spot=38.0, domestic_rate_pct=45.0, foreign_rate_pct=5.0, tenors=["1M", "1Y"])
    # higher TL rate → TL weaker forward → forward > spot
    assert pts[0].forward_outright > 38.0
    assert pts[1].forward_outright > pts[0].forward_outright  # monotone in T


def test_cip_matches_closed_form():
    spot, r_d, r_f = 38.0, 0.45, 0.05
    pts = fx_forward_curve(spot=spot, domestic_rate_pct=45.0, foreign_rate_pct=5.0, tenors=["3M"])
    expected = spot * math.exp((r_d - r_f) * pts[0].days / 365.0)
    assert math.isclose(pts[0].forward_outright, expected, rel_tol=1e-9)


class _FakeClient:
    def __init__(self, payload):
        self._payload = payload

    async def get_series(self, codes, start, end, **kw):
        out = []
        for code in codes:
            for d, v in self._payload.get(code, []):
                out.append(EVDSObservation(date=d, value=v, series_code=code))
        return out


@pytest.mark.asyncio
async def test_forward_curve_pulls_spot_and_dom_rate(monkeypatch):
    fake = _FakeClient(
        {
            USDTRY_SELLING: [("2026-05-14", 38.0)],
            POLICY_RATE_SERIES["policy_rate_1w_repo"]: [("2026-05-14", 45.0)],
        }
    )

    out = await tools.get_fx_forward_curve(
        pair="USDTRY", foreign_rate_pct=4.5, tenors=["1M", "1Y"], client=fake
    )
    assert "error" not in out
    assert out["spot"] == 38.0
    assert out["domestic_rate_pct"] == 45.0
    assert out["foreign_rate_pct"] == 4.5
    assert len(out["curve"]) == 2
    assert out["curve"][1]["forward_outright"] > out["curve"][0]["forward_outright"]


@pytest.mark.asyncio
async def test_forward_curve_unknown_pair_rejected():
    out = await tools.get_fx_forward_curve(pair="GBPTRY", foreign_rate_pct=5.0, spot=44.0, domestic_rate_pct=45.0)
    assert out["error"] == "unknown_pair"


@pytest.mark.asyncio
async def test_forward_curve_skips_evds_when_inputs_provided():
    """If spot and dom_rate are provided, no EVDS call should happen."""

    class _BrokenClient:
        async def get_series(self, *a, **kw):  # noqa: D401
            raise AssertionError("should not call EVDS")

    out = await tools.get_fx_forward_curve(
        pair="EURTRY",
        spot=42.0,
        domestic_rate_pct=45.0,
        foreign_rate_pct=2.5,
        tenors=["6M"],
        client=_BrokenClient(),
    )
    assert "error" not in out
    assert out["spot"] == 42.0

"""VIOP option chain tool tests — viop fetch monkeypatched."""

from __future__ import annotations

import pytest

from bist_trader_mcp import tools
from bist_trader_mcp.viop import VIOPContract, VIOPSettlement


def _opt(strike: float, right: str, last: float, expiry=(2026, 6)) -> VIOPSettlement:
    yr, mo = expiry
    code = f"O_XU030{mo:02d}{yr % 100:02d}_{right}{strike:.0f}"
    contract = VIOPContract(
        contract_code=code,
        underlying="XU030",
        contract_type="option",
        expiry_year=yr,
        expiry_month=mo,
        option_strike=strike,
        option_right=right,
    )
    return VIOPSettlement(
        contract=contract,
        trade_date="2026-05-14",
        name=code,
        last_price=last,
        percent_change=0.0,
        absolute_change=0.0,
        volume_tl=1_000_000.0,
        open_interest=500,
    )


@pytest.mark.asyncio
async def test_chain_no_iv_inputs_returns_rows_only(monkeypatch):
    chain = [_opt(3400, "C", 120.0), _opt(3500, "P", 60.0)]

    async def _fake(**kw):
        return chain

    monkeypatch.setattr(tools, "fetch_option_chain", _fake)

    out = await tools.get_viop_option_chain(underlying="XU030")
    assert out["count"] == 2
    assert out["iv_solved"] is False
    assert all(row["iv_pct"] is None for row in out["rows"])
    assert out["summary_by_expiry"] == []


@pytest.mark.asyncio
async def test_chain_with_iv_inputs_solves_and_summarises(monkeypatch):
    spot = 3500.0
    chain = [
        _opt(3300, "C", 250.0),
        _opt(3500, "C", 120.0),
        _opt(3700, "C", 35.0),
        _opt(3300, "P", 25.0),
        _opt(3500, "P", 110.0),
        _opt(3700, "P", 230.0),
    ]

    async def _fake(**kw):
        return chain

    monkeypatch.setattr(tools, "fetch_option_chain", _fake)

    out = await tools.get_viop_option_chain(
        underlying="XU030",
        spot_price=spot,
        risk_free_rate_pct=45.0,
    )
    assert out["count"] == 6
    assert out["iv_solved"] is True
    # most rows should have an IV solution
    iv_solved_rows = [r for r in out["rows"] if r["iv_pct"] is not None]
    assert len(iv_solved_rows) >= 4

    assert len(out["summary_by_expiry"]) == 1
    summ = out["summary_by_expiry"][0]
    assert summ["atm_strike"] == 3500.0
    assert summ["atm_iv_pct"] is not None
    assert summ["atm_iv_pct"] > 0


@pytest.mark.asyncio
async def test_chain_filters_to_specific_expiry(monkeypatch):
    chain = [
        _opt(3500, "C", 120.0, expiry=(2026, 6)),
        _opt(3500, "C", 200.0, expiry=(2026, 9)),
    ]
    captured: dict = {}

    async def _fake(**kw):
        captured.update(kw)
        # apply the filter the real fetch would
        return [
            r
            for r in chain
            if (
                kw.get("expiry_year") in (None, r.contract.expiry_year)
                and kw.get("expiry_month") in (None, r.contract.expiry_month)
            )
        ]

    monkeypatch.setattr(tools, "fetch_option_chain", _fake)

    out = await tools.get_viop_option_chain(
        underlying="XU030",
        expiry_year=2026,
        expiry_month=6,
    )
    assert captured["expiry_year"] == 2026
    assert captured["expiry_month"] == 6
    assert out["count"] == 1
    assert out["rows"][0]["expiry_month"] == 6

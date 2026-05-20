"""Repo / money-market curve tool tests — EVDS client monkeypatched."""

from __future__ import annotations

import pytest

from bist_trader_mcp import tools
from bist_trader_mcp.evds import EVDSObservation
from bist_trader_mcp.series_catalog import POLICY_RATE_SERIES


class _FakeClient:
    def __init__(self, payload: dict[str, list[tuple[str, float | None]]]):
        self._payload = payload

    async def get_series(self, series_codes, start, end, **kw):
        out: list[EVDSObservation] = []
        for code in series_codes:
            for d, v in self._payload.get(code, []):
                out.append(EVDSObservation(date=d, value=v, series_code=code))
        return out


@pytest.mark.asyncio
async def test_repo_curve_happy_path():
    payload = {
        POLICY_RATE_SERIES["policy_rate_1w_repo"]: [("2026-05-14", 45.0)],
        POLICY_RATE_SERIES["tlref_overnight"]: [("2026-05-14", 46.5)],
        POLICY_RATE_SERIES["bist_overnight_repo"]: [("2026-05-14", 47.2)],
    }
    out = await tools.get_repo_curve(client=_FakeClient(payload))
    assert "error" not in out
    panel = {row["key"]: row for row in out["panel"]}
    assert panel["policy_rate_1w_repo"]["rate_pct"] == 45.0
    assert panel["tlref_overnight"]["rate_pct"] == 46.5
    assert panel["bist_overnight_repo"]["rate_pct"] == 47.2

    spreads = out["spreads_bps"]
    assert spreads["tlref_minus_policy_bps"] == pytest.approx(150.0)
    assert spreads["bist_overnight_minus_policy_bps"] == pytest.approx(220.0)
    assert spreads["bist_overnight_minus_tlref_bps"] == pytest.approx(70.0)


@pytest.mark.asyncio
async def test_repo_curve_picks_latest_non_null():
    payload = {
        POLICY_RATE_SERIES["policy_rate_1w_repo"]: [
            ("2026-05-12", 45.0),
            ("2026-05-13", None),
            ("2026-05-14", None),
        ],
        POLICY_RATE_SERIES["tlref_overnight"]: [],
        POLICY_RATE_SERIES["bist_overnight_repo"]: [],
    }
    out = await tools.get_repo_curve(client=_FakeClient(payload))
    panel = {row["key"]: row for row in out["panel"]}
    assert panel["policy_rate_1w_repo"]["rate_pct"] == 45.0
    assert panel["policy_rate_1w_repo"]["as_of"] == "2026-05-12"
    # missing series come back as None, not an error
    assert panel["tlref_overnight"]["rate_pct"] is None
    # spreads with a missing leg are None, not crashes
    assert out["spreads_bps"]["tlref_minus_policy_bps"] is None

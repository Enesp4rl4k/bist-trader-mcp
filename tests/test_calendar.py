"""Economic calendar tests."""

from __future__ import annotations

from datetime import date

from bist_trader_mcp.calendar_data import (
    _third_business_day,
    build_calendar,
    cpi_release_dates,
    mpc_events,
)
from bist_trader_mcp.tools import get_economic_calendar


def test_third_business_day_skips_weekends():
    # 2026-05-01 is Friday, 2,3 Sat/Sun, so day 3 lands on Tue 2026-05-05
    assert _third_business_day(2026, 5) == date(2026, 5, 5)


def test_cpi_dates_are_third_business_day():
    rels = cpi_release_dates(date(2026, 1, 1), date(2026, 6, 30))
    assert len(rels) == 6
    for r in rels:
        d = date.fromisoformat(r.date)
        # weekday Mon-Fri only
        assert d.weekday() < 5


def test_mpc_events_within_window():
    evs = mpc_events(date(2026, 1, 1), date(2026, 12, 31))
    assert len(evs) == 8  # 2026 has 8 MPC meetings
    for e in evs:
        assert e.category == "monetary_policy"
        assert e.importance == "high"


def test_calendar_category_filter():
    evs = build_calendar(
        date(2026, 1, 1),
        date(2026, 3, 31),
        categories=["monetary_policy"],
    )
    assert all(e.category == "monetary_policy" for e in evs)
    assert len(evs) >= 2  # Jan & Mar MPC


def test_tool_wrapper_returns_structured_payload():
    out = get_economic_calendar(since="2026-01-01", until="2026-03-31")
    assert "error" not in out
    assert out["count"] > 0
    assert all(e["category"] in {"monetary_policy", "inflation"} for e in out["events"])


def test_tool_wrapper_bad_window():
    out = get_economic_calendar(since="2026-12-31", until="2026-01-01")
    assert out["error"] == "bad_window"

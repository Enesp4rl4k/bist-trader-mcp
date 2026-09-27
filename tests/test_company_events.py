"""Company events: SPK filing windows, KAP classification, risk-check wiring."""

from datetime import date, datetime, timezone

import pytest

from bist_trader_mcp import company_events as ce
from bist_trader_mcp.risk_engine import RiskConfig, check_trade


def test_filing_deadlines_follow_spk_day_counts():
    periods = {p["period"]: p for p in ce.filing_periods(date(2026, 1, 15))}
    annual = periods["2025 Yıllık"]
    assert annual["deadline_standalone"] == date(2026, 3, 1)       # +60
    assert annual["deadline_consolidated"] == date(2026, 3, 11)    # +70
    q3 = {p["period"]: p for p in ce.filing_periods(date(2026, 10, 5))}["2026 9M"]
    assert (q3["deadline_standalone"], q3["deadline_consolidated"]) == \
        (date(2026, 10, 30), date(2026, 11, 9))
    h1 = {p["period"]: p for p in ce.filing_periods(date(2026, 7, 10))}["2026 H1"]
    assert (h1["deadline_standalone"], h1["deadline_consolidated"]) == \
        (date(2026, 8, 19), date(2026, 8, 29))


def test_earnings_window_states():
    inside = ce.earnings_window(date(2026, 10, 20))
    assert inside["in_window"] and inside["period"] == "2026 9M" and inside["days_left"] == 20
    done = ce.earnings_window(date(2026, 10, 20), reported_since=date(2026, 10, 15))
    assert not done["in_window"] and done["reported"] is True
    old_report = ce.earnings_window(date(2026, 10, 20), reported_since=date(2026, 8, 20))
    assert old_report["in_window"] and old_report["reported"] is False
    between = ce.earnings_window(date(2026, 9, 15))
    assert not between["in_window"] and between["window_opens"] == "2026-10-01"


@pytest.mark.parametrize("subject,kind", [
    ("Finansal Rapor", "financial_report"),
    ("Genel Kurul İşlemlerine İlişkin Bildirim", "general_assembly"),
    ("Kâr Payı Dağıtım İşlemlerine İlişkin Bildirim", "dividend"),
    ("Sermaye Artırımı - Azaltımı İşlemlerine İlişkin Bildirim", "capital_change"),
    ("Özel Durum Açıklaması (Genel)", "special_situation"),
    ("Pay Geri Alımına İlişkin Bildirim", "buyback"),
    ("Sorumluluk Beyanı", None),
])
def test_kap_subject_classification(subject, kind):
    assert ce.classify_disclosure(subject) == kind


def test_company_events_flags():
    disc = [
        {"company_ticker": "THYAO", "subject": "Finansal Rapor", "publish_date": "2026-10-12T18:30"},
        {"company_ticker": "ASELS", "subject": "Bedelsiz Sermaye Artırımı",
         "publish_date": "2026-10-01T09:00"},
        {"company_ticker": "OTHER", "subject": "Finansal Rapor", "publish_date": "2026-10-10"},
    ]
    out = ce.company_events(["THYAO", "ASELS"], disc, today=date(2026, 10, 20))
    assert not out["THYAO"]["earnings"]["in_window"]          # already reported
    assert out["ASELS"]["earnings"]["reported"] is False       # KAP known, not reported
    assert any("sermaye" in f for f in out["ASELS"]["flags"])
    assert "OTHER" not in out


PLAN = {"direction": "long", "entry": 100.0, "stop": 95.0, "target": 115.0}


def _check(now, company=None):
    return check_trade(PLAN, symbol="X", cfg=RiskConfig(), now=now, events=[],
                       company=company)


def test_risk_warns_only_near_deadline_without_kap():
    early = _check(datetime(2026, 10, 5, tzinfo=timezone.utc))      # 35 days left
    late = _check(datetime(2026, 11, 1, tzinfo=timezone.utc))       # 8 days left
    assert "earnings_window" not in early["warnings"]
    assert "earnings_window" in late["warnings"] and late["approved"]


def test_risk_warns_whole_window_when_kap_says_not_reported():
    info = ce.company_events(["X"], [], today=date(2026, 10, 5))["X"]
    res = _check(datetime(2026, 10, 5, tzinfo=timezone.utc), company=info)
    assert "earnings_window" in res["warnings"]


def test_dashboard_calendar_lists_filing_deadlines(monkeypatch):
    from bist_trader_mcp import dashboard_data as dd

    class FakeDate(date):
        @classmethod
        def today(cls):
            return date(2026, 10, 25)

    monkeypatch.setattr(dd, "date", FakeDate)
    items = dd.section_calendar()
    deadlines = [i for i in items if i.get("category") == "earnings"]
    assert {i["date"] for i in deadlines} == {"2026-10-30", "2026-11-09"}
    assert items == sorted(items, key=lambda e: e["date"])

"""Static TR macro / monetary policy calendar.

Maintainership: TCMB publishes MPC dates annually around year-end. TÜİK
releases follow a deterministic pattern — CPI on day 3 of next month,
TÜFE/ÜFE detail simultaneously, GSYH (GDP) quarterly. This module
exposes:

    - MPC_DATES: TCMB Para Politikası Kurulu announcement dates (calendar)
    - RECURRING_RELEASES: rule-based generators (CPI, FAVÖK, etc.)

Update protocol:
    1) When TCMB publishes the new year's MPC schedule (late Dec),
       extend MPC_DATES with that year's entries.
    2) Recurring rules don't need updating unless TÜİK changes its
       release-day convention (rare).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta


@dataclass
class CalendarEvent:
    date: str          # YYYY-MM-DD
    event: str         # short label
    category: str      # "monetary_policy" | "inflation" | "growth" | "labour" | "trade"
    importance: str    # "high" | "medium" | "low"
    notes: str | None = None


# TCMB Para Politikası Kurulu (Monetary Policy Committee) — announcement dates.
# Source: TCMB annual schedule published end of each year.
# Update when TCMB releases the next year's calendar.
MPC_DATES: list[tuple[str, str]] = [
    # 2025
    ("2025-01-23", "TCMB PPK toplantısı (faiz kararı)"),
    ("2025-03-06", "TCMB PPK toplantısı (faiz kararı)"),
    ("2025-04-17", "TCMB PPK toplantısı (faiz kararı)"),
    ("2025-06-19", "TCMB PPK toplantısı (faiz kararı)"),
    ("2025-07-24", "TCMB PPK toplantısı (faiz kararı)"),
    ("2025-09-11", "TCMB PPK toplantısı (faiz kararı)"),
    ("2025-10-23", "TCMB PPK toplantısı (faiz kararı)"),
    ("2025-12-11", "TCMB PPK toplantısı (faiz kararı)"),
    # 2026
    ("2026-01-22", "TCMB PPK toplantısı (faiz kararı)"),
    ("2026-03-05", "TCMB PPK toplantısı (faiz kararı)"),
    ("2026-04-16", "TCMB PPK toplantısı (faiz kararı)"),
    ("2026-06-18", "TCMB PPK toplantısı (faiz kararı)"),
    ("2026-07-23", "TCMB PPK toplantısı (faiz kararı)"),
    ("2026-09-10", "TCMB PPK toplantısı (faiz kararı)"),
    ("2026-10-22", "TCMB PPK toplantısı (faiz kararı)"),
    ("2026-12-10", "TCMB PPK toplantısı (faiz kararı)"),
]


def _third_business_day(year: int, month: int) -> date:
    """TÜİK CPI/PPI publish on the 3rd business day of each month."""
    d = date(year, month, 1)
    business_days = 0
    while True:
        if d.weekday() < 5:  # 0-4 = Mon-Fri
            business_days += 1
            if business_days == 3:
                return d
        d += timedelta(days=1)


def cpi_release_dates(since: date, until: date) -> list[CalendarEvent]:
    """TÜFE / Tüketici fiyat endeksi — 3rd business day of each month, covers prior month."""
    out: list[CalendarEvent] = []
    y, m = since.year, since.month
    while date(y, m, 1) <= until:
        d = _third_business_day(y, m)
        if since <= d <= until:
            prev_m = m - 1 or 12
            prev_y = y if m > 1 else y - 1
            out.append(
                CalendarEvent(
                    date=d.isoformat(),
                    event=f"TÜİK TÜFE {prev_y}/{prev_m:02d}",
                    category="inflation",
                    importance="high",
                    notes="Aylık ve yıllık TÜFE; çekirdek C dahil alt kalemler.",
                )
            )
        m += 1
        if m > 12:
            m = 1
            y += 1
    return out


def ppi_release_dates(since: date, until: date) -> list[CalendarEvent]:
    """Yİ-ÜFE — 3rd business day of each month (same day as CPI), covers prior month."""
    out: list[CalendarEvent] = []
    y, m = since.year, since.month
    while date(y, m, 1) <= until:
        d = _third_business_day(y, m)
        if since <= d <= until:
            prev_m = m - 1 or 12
            prev_y = y if m > 1 else y - 1
            out.append(
                CalendarEvent(
                    date=d.isoformat(),
                    event=f"TÜİK Yİ-ÜFE {prev_y}/{prev_m:02d}",
                    category="inflation",
                    importance="medium",
                    notes="Yurt içi üretici fiyatları — TÜFE'yi öncüleyen kalem.",
                )
            )
        m += 1
        if m > 12:
            m = 1
            y += 1
    return out


def mpc_events(since: date, until: date) -> list[CalendarEvent]:
    out: list[CalendarEvent] = []
    for iso_d, label in MPC_DATES:
        d = date.fromisoformat(iso_d)
        if since <= d <= until:
            out.append(
                CalendarEvent(
                    date=iso_d,
                    event=label,
                    category="monetary_policy",
                    importance="high",
                    notes="Politika faizi ve metin değişiklikleri; piyasa anlık tepki verir.",
                )
            )
    return out


def build_calendar(
    since: date,
    until: date,
    categories: list[str] | None = None,
) -> list[CalendarEvent]:
    """Compose the calendar from all generators within [since, until]."""
    events = [
        *mpc_events(since, until),
        *cpi_release_dates(since, until),
        *ppi_release_dates(since, until),
    ]
    if categories:
        wanted = {c.lower() for c in categories}
        events = [e for e in events if e.category in wanted]
    events.sort(key=lambda e: (e.date, e.importance))
    return events

"""Company event calendar — earnings windows and corporate actions.

**Earnings windows** come from the legal filing deadlines (SPK Communiqué
II-14.1): after each period end a company must publish within

| period              | standalone | consolidated |
|---------------------|-----------:|-------------:|
| Q1 / 9M (quarterly) | 30 days    | 40 days      |
| H1 (6-month)        | 50 days    | 60 days      |
| annual              | 60 days    | 70 days      |

Between the period end and the consolidated deadline a report can land any
day — overnight gap risk for an open position. Banks follow BDDK timing and
often report earlier; the window is a risk flag, not a date prediction.

**Corporate actions** are classified from recent KAP disclosure subjects:
financial report, general assembly, dividend, capital increase / bonus issue
(prices may need split adjustment), share buyback, special situation.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

# (period end month, day, label, standalone days, consolidated days)
_PERIODS = [
    (3, 31, "Q1", 30, 40),
    (6, 30, "H1", 50, 60),
    (9, 30, "9M", 30, 40),
    (12, 31, "Yıllık", 60, 70),
]

_KAP_KINDS = [
    ("financial_report", ("finansal rapor", "financial report")),
    ("general_assembly", ("genel kurul",)),
    ("dividend", ("kar payı", "kâr payı", "temettü")),
    ("capital_change", ("sermaye artırım", "sermaye azaltım", "bedelsiz", "bedelli")),
    ("buyback", ("geri alım",)),
    ("special_situation", ("özel durum",)),
]
_KIND_TR = {
    "financial_report": "finansal rapor", "general_assembly": "genel kurul",
    "dividend": "kâr payı", "capital_change": "sermaye değişikliği",
    "buyback": "pay geri alımı", "special_situation": "özel durum",
}


def filing_periods(today: date) -> list[dict[str, Any]]:
    """The latest period whose filing window is open or upcoming, plus the next."""
    out = []
    for year in (today.year - 1, today.year):
        for m, d, label, solo, cons in _PERIODS:
            end = date(year, m, d)
            out.append({
                "period": f"{year} {label}",
                "period_end": end,
                "deadline_standalone": end + timedelta(days=solo),
                "deadline_consolidated": end + timedelta(days=cons),
            })
    return [p for p in out if p["deadline_consolidated"] >= today - timedelta(days=1)][:2]


def earnings_window(
    today: date, reported_since: date | None = None, kap_checked: bool = False
) -> dict[str, Any]:
    """Is ``today`` inside a filing window, and has the company already reported?

    ``reported_since``: date of the company's latest financial-report disclosure
    (from KAP) — a report after the period end closes the window.
    ``kap_checked``: KAP was actually read, so "no report found" means *not yet
    reported* (False) rather than *unknown* (None).
    """
    for p in filing_periods(today):
        if p["period_end"] < today <= p["deadline_consolidated"]:
            reported = reported_since is not None and reported_since > p["period_end"]
            known = kap_checked or reported_since is not None
            return {
                "in_window": not reported,
                "reported": reported if known else None,
                "period": p["period"],
                "deadline_standalone": p["deadline_standalone"].isoformat(),
                "deadline_consolidated": p["deadline_consolidated"].isoformat(),
                "days_left": (p["deadline_consolidated"] - today).days,
            }
    nxt = filing_periods(today)[0]
    return {"in_window": False, "reported": None, "period": nxt["period"],
            "window_opens": (nxt["period_end"] + timedelta(days=1)).isoformat(),
            "deadline_consolidated": nxt["deadline_consolidated"].isoformat(),
            "days_left": None}


def classify_disclosure(subject: str | None) -> str | None:
    s = (subject or "").lower()
    for kind, keys in _KAP_KINDS:
        if any(k in s for k in keys):
            return kind
    return None


def company_events(
    symbols: list[str],
    disclosures: list[dict[str, Any]] | None,
    today: date | None = None,
) -> dict[str, Any]:
    """Per symbol: earnings-window status + recent corporate actions from KAP."""
    today = today or date.today()
    by_sym: dict[str, list[dict[str, Any]]] = {s.upper(): [] for s in symbols}
    for d in disclosures or []:
        sym = (d.get("company_ticker") or "").upper()
        kind = classify_disclosure(d.get("subject"))
        if sym in by_sym and kind:
            by_sym[sym].append({"date": (d.get("publish_date") or "")[:10], "kind": kind,
                                "kind_tr": _KIND_TR[kind], "subject": d.get("subject"),
                                "url": d.get("url")})
    out = {}
    for sym, evs in by_sym.items():
        evs.sort(key=lambda e: e["date"], reverse=True)
        reports = [e for e in evs if e["kind"] == "financial_report" and e["date"]]
        last_report = date.fromisoformat(reports[0]["date"]) if reports else None
        win = earnings_window(today, last_report, kap_checked=disclosures is not None)
        flags = []
        if win["in_window"]:
            flags.append(f"bilanço dönemi ({win['period']}), son gün "
                         f"{win['deadline_consolidated']} — rapor her an gelebilir")
        if any(e["kind"] == "capital_change" for e in evs):
            flags.append("sermaye değişikliği bildirimi — fiyat düzeltmesini kontrol et")
        if any(e["kind"] == "dividend" for e in evs):
            flags.append("kâr payı bildirimi — hak kullanım günü fiyat düşer")
        out[sym] = {"earnings": win, "recent": evs[:8], "flags": flags}
    return out


__all__ = ["classify_disclosure", "company_events", "earnings_window", "filing_periods"]

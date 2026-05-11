"""KAP (Kamuyu Aydınlatma Platformu) disclosure fetcher.

Implementation note:
    KAP's UI is a Next.js SPA that calls the in-house API
    `POST https://www.kap.org.tr/tr/api/disclosure/list/main`. Direct calls
    from outside the browser session are blocked by their WAF (custom 666
    error page or read timeout). We get around this with a real Playwright
    Chromium session — visit the homepage so cookies + state load, then
    issue the API call as an in-page fetch() so the WAF sees a same-origin
    XHR.

    Live discovery 2026-05-11: capture confirmed the canonical body shape:
        {
          "fromDate": "DD.MM.YYYY",
          "toDate":   "DD.MM.YYYY",
          "memberTypes": ["IGS", "DDK"]
        }
    Response is a JSON array of `{disclosureBasic, disclosureDetail}`
    objects.

Install requirement:
    `pip install bist-trader-mcp[browser]` then `python -m playwright
    install chromium`. Without these, this module raises a structured
    `endpoint_discovery_pending`-style error so the tool layer can fall
    back to the WIP payload.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from ._browser import BrowserCallError, call_json_xhr, playwright_available
from ._wip import wip_error
from .http_utils import SourceError

KAP_API_URL = "https://www.kap.org.tr/tr/api/disclosure/list/main"
KAP_PAGE_URL = "https://www.kap.org.tr/tr"

# Substring filters used by the (rough) materiality heuristic. KAP itself
# does not flag rows as material; we approximate by subject keyword.
MATERIAL_DISCLOSURE_KEYWORDS = (
    "Özel Durum",
    "Pay Geri Alım",
    "Sermaye Artırımı",
    "Kar Payı",
    "Kâr Payı",
    "Bağımsız Denetim",
    "Önemli Niteli",  # "Önemli Nitelikteki İşlem"
    "Birleşme",
    "Maddi Duran Varlık",
    "Sözleşme",
    "İhale",
    "Yönetim Kurulu",
    "Genel Kurul",
)


@dataclass
class KAPDisclosure:
    disclosure_id: str
    publish_date: str  # ISO YYYY-MM-DDTHH:MM
    company_ticker: str | None
    company_name: str | None
    subject: str
    summary: str | None
    is_late: bool
    is_material: bool
    url: str | None


def _looks_material(subject: str) -> bool:
    return bool(subject) and any(kw in subject for kw in MATERIAL_DISCLOSURE_KEYWORDS)


def _normalize_publish_date(raw: Any) -> str:
    if not raw:
        return ""
    if isinstance(raw, int | float):
        try:
            return datetime.fromtimestamp(raw / 1000).isoformat(timespec="minutes")
        except (OverflowError, OSError, ValueError):
            return ""
    if isinstance(raw, str):
        for fmt in (
            "%d.%m.%Y %H:%M:%S",
            "%d.%m.%Y %H:%M",
            "%Y-%m-%dT%H:%M:%S",
        ):
            try:
                return datetime.strptime(raw, fmt).isoformat(timespec="minutes")
            except ValueError:
                continue
        return raw
    return str(raw)


def _parse(row: dict[str, Any]) -> KAPDisclosure | None:
    basic = row.get("disclosureBasic") or {}
    if not basic:
        return None

    disclosure_id = str(basic.get("disclosureId") or "") or None
    disclosure_index = basic.get("disclosureIndex")
    publish_iso = _normalize_publish_date(basic.get("publishDate"))
    ticker = basic.get("stockCode") or None
    name = basic.get("companyTitle") or None
    subject = basic.get("title") or ""
    summary = basic.get("summary") or None
    is_late = bool(basic.get("isLate", False))

    url: str | None = None
    if disclosure_index:
        url = f"https://www.kap.org.tr/tr/Bildirim/{disclosure_index}"

    return KAPDisclosure(
        disclosure_id=disclosure_id or str(disclosure_index or ""),
        publish_date=publish_iso,
        company_ticker=ticker,
        company_name=name,
        subject=subject,
        summary=summary,
        is_late=is_late,
        is_material=_looks_material(subject),
        url=url,
    )


def _kap_date(d: date) -> str:
    """KAP's API expects DD.MM.YYYY."""
    return d.strftime("%d.%m.%Y")


def _coerce(value: date | str) -> date:
    if isinstance(value, date):
        return value
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d.%m.%Y"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    raise SourceError("kap", f"bad date: {value!r}")


async def fetch_disclosures(
    ticker: str | None = None,
    since: date | str | None = None,
    until: date | str | None = None,
    only_material: bool = False,
    limit: int = 100,
) -> list[KAPDisclosure]:
    """Pull KAP disclosures within a date window.

    Args:
        ticker: BIST stock ticker (e.g. "THYAO"). None → all companies.
        since: Lower bound (default: 7 days ago).
        until: Upper bound (default: today).
        only_material: If True, keep entries whose subject matches a
            keyword from the heuristic material list.
        limit: Max rows after filtering (hard cap 500).
    """
    if not playwright_available():
        raise wip_error(
            "kap",
            "Playwright not installed; KAP requires browser session — install "
            "with `pip install bist-trader-mcp[browser]` and `python -m "
            "playwright install chromium`.",
        )

    since_date = _coerce(since) if since else date.today() - timedelta(days=7)
    until_date = _coerce(until) if until else date.today()
    limit = max(1, min(int(limit), 500))

    body: dict[str, Any] = {
        "fromDate": _kap_date(since_date),
        "toDate": _kap_date(until_date),
        "memberTypes": ["IGS", "DDK"],
    }
    if ticker:
        # KAP supports a `stockCodes` filter (comma-separated list).
        body["stockCodes"] = ticker.upper().strip()

    try:
        payload = await call_json_xhr(
            api_url=KAP_API_URL,
            page_url=KAP_PAGE_URL,
            method="POST",
            body=body,
            extra_headers={"Referer": KAP_PAGE_URL, "Origin": "https://www.kap.org.tr"},
        )
    except BrowserCallError as e:
        raise SourceError("kap", str(e)) from e

    if not isinstance(payload, list):
        raise SourceError("kap", f"unexpected payload shape: {type(payload)}")

    parsed = [_parse(r) for r in payload if isinstance(r, dict)]
    out = [d for d in parsed if d is not None]

    if ticker:
        upper_t = ticker.upper().strip()
        out = [d for d in out if (d.company_ticker or "").upper() == upper_t]
    if only_material:
        out = [d for d in out if d.is_material]

    # Newest first.
    out.sort(key=lambda d: d.publish_date, reverse=True)
    return out[:limit]

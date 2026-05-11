"""KAP (Kamuyu Aydınlatma Platformu) disclosure fetcher.

KAP publishes a semi-public JSON endpoint that powers their own UI. The
schema is owned by KAP and changes without notice; this client targets the
"memberDisclosureQuery" pattern observed in late 2025 / early 2026.

If KAP changes the endpoint or response shape, only this module needs to be
fixed; tools.py will surface a structured `source_error` to the LLM.

NOTE: This is a community client over a public-facing JSON endpoint. Respect
KAP's terms of service and rate limits. We add a polite User-Agent and back
off on transient errors.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from ._wip import wip_error
from .http_utils import SourceError, fetch_json  # noqa: F401  retained for v0.3

KAP_DISCLOSURES_URL = (
    "https://www.kap.org.tr/tr/api/disclosures"
)

# These are the high-signal disclosure type codes KAP uses. Subset; expand
# as needed. Materiality is largely encoded via the "subjects" filter and the
# `weight` field returned by KAP for some categories.
MATERIAL_DISCLOSURE_KEYWORDS = (
    "Özel Durum",
    "Maddi Duran Varlık",
    "Pay Geri Alım",
    "Sermaye Artırımı",
    "Kar Payı",
    "Yönetim Kurulu",
    "Bağımsız Denetim",
    "Önemli Niteli",  # "Önemli Nitelikteki İşlem"
    "Birleşme",
    "İhale",
    "Sözleşme",
)


@dataclass
class KAPDisclosure:
    """One disclosure row, normalised to a stable shape."""

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
    if not subject:
        return False
    upper = subject
    return any(kw in upper for kw in MATERIAL_DISCLOSURE_KEYWORDS)


def _parse_disclosure(row: dict[str, Any]) -> KAPDisclosure:
    """Map KAP's payload onto our normalised dataclass.

    KAP nests company info under varying keys depending on disclosure type;
    we try a couple before giving up.
    """
    basic = row.get("basic", row)
    disclosure_id = str(basic.get("disclosureIndex") or basic.get("id") or "")
    publish_raw = (
        basic.get("publishDate")
        or basic.get("kapTitle", {}).get("publishDate")
        or ""
    )
    # KAP publishes dates as "DD.MM.YYYY HH:MM:SS" or millisecond epoch.
    publish_iso = _normalize_publish_date(publish_raw)

    # Ticker may live under several keys.
    ticker = basic.get("stockCode") or basic.get("companyTicker") or None
    name = basic.get("companyName") or basic.get("title") or None
    subject = basic.get("subject") or basic.get("kapTitle", {}).get("subject") or ""
    summary = basic.get("summary") or None
    is_late = bool(basic.get("isLate", False))

    url: str | None = None
    if disclosure_id:
        url = f"https://www.kap.org.tr/tr/Bildirim/{disclosure_id}"

    return KAPDisclosure(
        disclosure_id=disclosure_id,
        publish_date=publish_iso,
        company_ticker=ticker,
        company_name=name,
        subject=subject,
        summary=summary,
        is_late=is_late,
        is_material=_looks_material(subject),
        url=url,
    )


def _normalize_publish_date(raw: Any) -> str:
    if not raw:
        return ""
    if isinstance(raw, int | float):
        try:
            return datetime.fromtimestamp(raw / 1000).isoformat(timespec="minutes")
        except (OverflowError, OSError, ValueError):
            return ""
    if isinstance(raw, str):
        # Try a couple of common KAP formats.
        for fmt in ("%d.%m.%Y %H:%M:%S", "%d.%m.%Y %H:%M", "%Y-%m-%dT%H:%M:%S"):
            try:
                return datetime.strptime(raw, fmt).isoformat(timespec="minutes")
            except ValueError:
                continue
        return raw
    return str(raw)


async def fetch_disclosures(
    ticker: str | None = None,
    since: date | str | None = None,
    until: date | str | None = None,
    only_material: bool = False,
    limit: int = 100,
) -> list[KAPDisclosure]:
    """Pull disclosures from KAP, optionally filtered.

    v0.2 STATUS: KAP serves disclosure data through a UI consumed via a
    session-bound API and rejects unauthenticated direct fetches with a
    custom 666 error page or read timeouts. Endpoint discovery is tracked
    for v0.3 (browser-automated fallback). The data parser, dataclasses
    and material-detection logic in this module are ready to plug in once
    the real endpoint pattern is captured.
    """
    raise wip_error(
        "kap",
        f"ticker={ticker} since={since} until={until} "
        f"only_material={only_material} limit={limit}",
    )


def _coerce_date(value: date | str) -> date:
    if isinstance(value, date):
        return value
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d.%m.%Y"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    raise SourceError("kap", f"bad date: {value!r}")

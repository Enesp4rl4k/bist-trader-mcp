"""MKK — marketwide system statistics + per-ticker foreign ownership.

MKK (Merkezi Kayıt Kuruluşu, Türkiye's central registry depository)
publishes two kinds of investor data:

1. **Marketwide monthly system statistics** — a public PDF released
   monthly with a 12-month trailing time series of investor counts
   (total investors, investors with equity / gov debt / corp bond /
   mutual fund / structured product positions), transaction counts
   and nominal/market values. URL pattern:
       https://www.mkk.com.tr/sites/default/files/<YYYY>-<MM>/
       MKK_SYSTEM_STATISTICS_<MONTH>_EN.pdf
   For data month April 2026 the publish folder is `2026-05`.
   We parse with pdfplumber + regex (same pattern as hazine.py).

2. **Per-ticker foreign ownership ratio** — what `get_foreign_ownership`
   was originally designed to surface. This lives behind authenticated
   MKK e-ŞİRKET / API portal access (apiportal.mkk.com.tr) and the
   public-facing portal at i-mks.mkk.com.tr/info/ does not respond to
   anonymous requests. We keep the per-ticker fetcher as `wip_error`
   until v0.3 wires the gated portal flow.

The marketwide view is still high-signal: tracks retail vs institutional
growth, equity vs fixed-income participation, transaction throughput.
A trend break in any of these is a macro tell for TR markets.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

import httpx

from ._cache import cache_get, cache_set
from ._wip import wip_error
from .http_utils import USER_AGENT, SourceError

MKK_STATS_PDF_BASE = "https://www.mkk.com.tr/sites/default/files"
DEFAULT_CACHE_TTL_SECONDS = 24 * 3600

# Display labels for each canonical row identifier. The PDF's printed
# labels are mangled by pdfplumber (column letters split across spaces)
# so we treat the row number as the source of truth.
ROW_LABELS = {
    "1":   "monthly_accounts_opened",
    "2":   "total_investors",
    "3":   "investors_with_securities_holdings",
    "3.1": "investors_with_equity_balance",
    "3.2": "investors_with_government_debt_balance",
    "3.3": "investors_with_corporate_bond_balance",
    "3.4": "investors_with_mutual_funds_balance",
    "3.5": "investors_with_exchange_mutual_funds_balance",
    "3.6": "investors_with_other_securities_balance",
    "3.7": "investors_with_structured_products_balance",
    "4":   "total_accounts",
    "5":   "accounts_with_securities_holdings",
    "6.1": "securities_transfers_count",
    "6.2": "securities_transfers_nominal_value_tl",
    "6.3": "securities_transfers_market_value_million_tl",
    "7.1": "total_transactions_count",
    "7.2": "total_transactions_nominal_value_tl",
    "7.3": "total_transactions_market_value_million_tl",
}

# Turkish thousands-grouped number: 443.811 or 2.101.907.819.385
_NUMBER_RX = re.compile(r"\b\d{1,3}(?:\.\d{3})+\b|\b\d+\b")


def _detect_row_id(line: str) -> str | None:
    """Extract the row identifier (e.g. "1", "3.1", "6.2") from a line whose
    label may be character-scrambled by pdfplumber.

    pdfplumber occasionally interleaves letters from multi-line PDF cells
    so a row like ``3.1 - Number of Investors with Balance in Equities``
    is rendered as ``3 B . a 1 l a - n N c u …``. We rely on the
    invariant that the label ends with the first ' - ' or '-' separator
    and that digits (with optional '.') always appear before it.
    """
    head = line[:80]
    dash = head.find(" - ")
    if dash < 0:
        dash = head.find("-")
    if dash < 0:
        return None
    prefix = head[:dash]
    digit_groups = re.findall(r"\d+", prefix)
    if not digit_groups:
        return None
    # Filter out pure year tokens (>= 2000) — they belong to the header,
    # not to the data rows.
    head_digit = digit_groups[0]
    if len(head_digit) >= 4:
        return None
    if "." in prefix and len(digit_groups) >= 2 and len(digit_groups[1]) <= 2:
        return f"{head_digit}.{digit_groups[1]}"
    return head_digit


@dataclass
class MKKMarketStatsRow:
    """One labelled row of the monthly MKK system-statistics matrix."""
    row_id: str        # e.g. "3.1"
    metric: str        # canonical snake_case label
    monthly_values: list[float | None]   # length = months_in_header


@dataclass
class MKKMarketStats:
    """Parsed marketwide stats PDF — header months + body rows."""
    source_url: str
    fetched_at: str
    months: list[str]   # ISO YYYY-MM in the same order as monthly_values
    rows: list[MKKMarketStatsRow]


# Header line in the PDF looks like:
#   "2025 - MAY 2025 - JUNE ... 2026 - APRIL"
# We translate Turkish/English month names back into ISO YYYY-MM tokens.
_MONTH_EN_TO_NUM = {
    "JANUARY": 1, "FEBRUARY": 2, "MARCH": 3, "APRIL": 4, "MAY": 5, "JUNE": 6,
    "JULY": 7, "AUGUST": 8, "SEPTEMBER": 9, "OCTOBER": 10, "NOVEMBER": 11, "DECEMBER": 12,
}
_HEADER_TOKEN_RX = re.compile(r"(20\d{2})\s*-\s*([A-Z]+)")
_MONTH_NAMES_EN = list(_MONTH_EN_TO_NUM.keys())


def _parse_header_months(text: str) -> list[str]:
    months: list[str] = []
    for m in _HEADER_TOKEN_RX.finditer(text):
        year = int(m.group(1))
        month_num = _MONTH_EN_TO_NUM.get(m.group(2))
        if month_num is None:
            continue
        months.append(f"{year:04d}-{month_num:02d}")
    return months


def _parse_numbers(line: str) -> list[float | None]:
    nums: list[float | None] = []
    for token in _NUMBER_RX.findall(line):
        clean = token.replace(".", "")
        try:
            nums.append(float(clean))
        except ValueError:
            nums.append(None)
    return nums


def _parse_pdf_text(text: str, source_url: str) -> MKKMarketStats:
    months: list[str] = []
    rows: list[MKKMarketStatsRow] = []

    lines = text.splitlines()
    for line in lines:
        if _HEADER_TOKEN_RX.search(line):
            months = _parse_header_months(line)
            break

    for line in lines:
        row_id = _detect_row_id(line)
        if not row_id:
            continue
        # Strip off the label portion: numbers always come after the
        # final " - " separator in the line.
        last_dash = line.rfind(" - ")
        remainder = line[last_dash + 3:] if last_dash >= 0 else line
        nums = _parse_numbers(remainder)
        # Heuristic: a real data row carries at least 6 numbers (months).
        if len(nums) < 6:
            continue
        canonical = ROW_LABELS.get(row_id, f"row_{row_id}")
        rows.append(MKKMarketStatsRow(
            row_id=row_id, metric=canonical, monthly_values=nums,
        ))

    return MKKMarketStats(
        source_url=source_url,
        fetched_at=datetime.now().isoformat(timespec="seconds"),
        months=months,
        rows=rows,
    )


def _candidate_pdf_urls(as_of: date) -> list[str]:
    """Generate likely URLs for the most recent monthly stats PDF.

    Publish folder is usually 1 month after the data month. We probe the
    4 most-recent candidates so the freshest available wins.
    """
    candidates: list[str] = []
    for back in range(0, 4):
        data_month = as_of.month - back
        data_year = as_of.year
        while data_month <= 0:
            data_month += 12
            data_year -= 1
        publish_month = data_month + 1
        publish_year = data_year
        if publish_month > 12:
            publish_month -= 12
            publish_year += 1
        month_name = _MONTH_NAMES_EN[data_month - 1]
        candidates.append(
            f"{MKK_STATS_PDF_BASE}/{publish_year:04d}-{publish_month:02d}/"
            f"MKK_SYSTEM_STATISTICS_{month_name}_EN.pdf"
        )
    return candidates


def _download_pdf(url: str) -> bytes:
    with httpx.Client(
        timeout=30.0, headers={"User-Agent": USER_AGENT, "Accept": "*/*"}
    ) as client:
        resp = client.get(url, follow_redirects=True)
        resp.raise_for_status()
        return resp.content


def _extract_pdf_text(content: bytes) -> str:
    import pdfplumber

    parts: list[str] = []
    with pdfplumber.open(io.BytesIO(content)) as pdf:
        for page in pdf.pages:
            t = page.extract_text() or ""
            if t:
                parts.append(t)
    return "\n".join(parts)


async def fetch_market_stats(
    *,
    pdf_url: str | None = None,
    use_cache: bool = True,
    cache_ttl_seconds: int = DEFAULT_CACHE_TTL_SECONDS,
) -> MKKMarketStats:
    """Pull the most recent marketwide MKK system-statistics PDF."""
    cache_key = f"mkk.market_stats:{pdf_url or 'auto'}"
    if use_cache:
        cached = cache_get(cache_key, ttl_seconds=cache_ttl_seconds)
        if isinstance(cached, dict) and cached.get("rows"):
            return _stats_from_dict(cached)

    urls = [pdf_url] if pdf_url else _candidate_pdf_urls(date.today())
    last_err: Exception | None = None
    for candidate in urls:
        try:
            pdf_bytes = _download_pdf(candidate)
        except httpx.HTTPError as e:
            last_err = e
            continue
        try:
            text = _extract_pdf_text(pdf_bytes)
        except Exception as e:
            last_err = e
            continue
        stats = _parse_pdf_text(text, source_url=candidate)
        if not stats.rows:
            last_err = SourceError("mkk", f"parser found no rows in {candidate}")
            continue
        cache_set(cache_key, _stats_to_dict(stats), ttl_seconds=cache_ttl_seconds)
        return stats

    raise SourceError(
        "mkk",
        f"no MKK stats PDF resolved (last error: {last_err})",
    )


def _stats_to_dict(s: MKKMarketStats) -> dict[str, Any]:
    return {
        "source_url": s.source_url,
        "fetched_at": s.fetched_at,
        "months": s.months,
        "rows": [
            {"row_id": r.row_id, "metric": r.metric, "monthly_values": r.monthly_values}
            for r in s.rows
        ],
    }


def _stats_from_dict(d: dict[str, Any]) -> MKKMarketStats:
    return MKKMarketStats(
        source_url=str(d.get("source_url", "")),
        fetched_at=str(d.get("fetched_at", "")),
        months=[str(m) for m in d.get("months", [])],
        rows=[
            MKKMarketStatsRow(
                row_id=str(r.get("row_id", "")),
                metric=str(r.get("metric", "")),
                monthly_values=[
                    (None if v is None else float(v))
                    for v in r.get("monthly_values", [])
                ],
            )
            for r in d.get("rows", [])
        ],
    )


# ---------------------------------------------------------------------------
# Per-ticker foreign ownership — gated; kept as WIP scaffold for v0.3.
# ---------------------------------------------------------------------------

@dataclass
class ForeignOwnershipPoint:
    ticker: str
    date: str
    foreign_pct_of_freefloat: float | None
    foreign_pct_of_total: float | None
    foreign_investor_count: int | None


async def fetch_foreign_ownership(
    ticker: str,
    since: date | str | None = None,
    until: date | str | None = None,
) -> list[ForeignOwnershipPoint]:
    """Daily per-ticker foreign-ownership ratio.

    v0.2 STATUS: data lives behind authenticated MKK portals
    (apiportal.mkk.com.tr / i-mks.mkk.com.tr/info/) that do not respond
    to anonymous requests. The marketwide trend is exposed via
    `fetch_market_stats` instead. v0.3 will wire the gated portal once
    an access pathway is identified.
    """
    raise wip_error(
        "mkk",
        f"per-ticker foreign ownership requires MKK portal auth — "
        f"ticker={ticker} since={since} until={until} "
        "(use get_mkk_market_stats for marketwide investor trends)",
    )


async def fetch_latest_snapshot(
    tickers: list[str],
) -> dict[str, ForeignOwnershipPoint | None]:
    """v0.2 STATUS: blocked on fetch_foreign_ownership."""
    raise wip_error("mkk", f"per-ticker snapshot blocked: tickers={tickers}")


__all__ = [
    "MKKMarketStats",
    "MKKMarketStatsRow",
    "ROW_LABELS",
    "fetch_market_stats",
    "ForeignOwnershipPoint",
    "fetch_foreign_ownership",
    "fetch_latest_snapshot",
]

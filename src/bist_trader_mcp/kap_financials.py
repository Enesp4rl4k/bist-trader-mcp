"""KAP financial statements → point-in-time PanelStore → valuation / analysis.

Source: İş Yatırım's ``MaliTablo`` service, which republishes the statements
companies file with KAP (same line items, one JSON call for up to four periods).
KAP itself has no stable public JSON for statements, so this is the practical
"official figures" path; the Yahoo timeseries in ``fundamental_data`` stays as
the fallback.

Look-ahead safety: every row is written with ``known_at`` = the KAP publish
date when the caller supplies it, otherwise the **legal filing deadline**
(SPK II-14.1, consolidated: Q1/9M +40, H1 +60, annual +70 days). The deadline
is the latest the figures could have become public, so a backtest using it can
only be late, never early.

Conventions worth knowing:

- Turkish interim statements are cumulative (Q3 = nine months). Only the
  annual (month 12) rows are used for the multi-year history.
- TMS 29 (inflation accounting) applies from FY2023 for non-financials; those
  rows are flagged ``is_inflation_adjusted``. Banks were exempted, so their rows
  are not flagged. Do not compare a restated year with an older unrestated one.
- Line items are matched by their Turkish/English description, not by code,
  so a renamed code does not silently shift values. Unmatched rows are kept
  out; ``parse_mali_tablo`` reports which canonical items were found.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime, timedelta, timezone
from typing import Any

from ._cache import cache_get, cache_set
from .http_utils import fetch_json

MALI_TABLO_URL = (
    "https://www.isyatirim.com.tr/_layouts/15/IsYatirim.Website/Common/Data.aspx/MaliTablo"
)
CACHE_TTL = 12 * 3600
GROUP_INDUSTRIAL = "XI_29"
GROUP_BANK = "UFRS"
TMS29_FROM = "2023-12-31"
# consolidated filing deadline (days after period end) by period-end month
DEADLINE_DAYS = {3: 40, 6: 60, 9: 40, 12: 70}

# (canonical item, statement, [description keywords]) — first match wins, in
# statement order; keywords are matched on the folded description (TR or EN).
_RULES: list[tuple[str, str, tuple[str, ...]]] = [
    ("revenue", "income", ("satis gelirleri", "revenue", "hasilat")),
    ("cogs", "income", ("satislarin maliyeti", "cost of sales")),
    ("gross_profit", "income", ("brut kar", "gross profit")),
    ("selling_expense", "income", ("pazarlama", "satis ve dagitim", "marketing")),
    ("admin_expense", "income", ("genel yonetim", "general administrative")),
    ("rd_expense", "income", ("arastirma ve gelistirme", "research and development")),
    ("operating_income", "income", ("faaliyet kari", "operating profit")),
    ("interest_expense", "income", ("finansman giderleri", "finance expense",
                                    "financial expense")),
    ("pretax_income", "income", ("vergi oncesi", "before tax")),
    ("tax_expense", "income", ("vergi gideri", "vergi geliri", "tax income",
                               "tax expense")),
    ("net_income_parent", "income", ("ana ortaklik paylari", "ana ortakliga ait",
                                     "attributable to equity holders",
                                     "net profit after minority")),
    ("net_income", "income", ("net donem kari", "net profit for the period")),
    ("total_assets", "balance", ("toplam varliklar", "total assets")),
    ("current_assets", "balance", ("donen varliklar", "current assets")),
    ("cash", "balance", ("nakit ve nakit benzerleri", "cash and cash equivalents")),
    ("receivables", "balance", ("ticari alacaklar", "trade receivables")),
    ("inventory", "balance", ("stoklar", "inventories")),
    ("ppe", "balance", ("maddi duran varliklar", "property, plant",
                        "property plant")),
    ("current_liabilities", "balance", ("kisa vadeli yukumlulukler",
                                        "short term liabilities",
                                        "current liabilities")),
    ("long_term_liabilities", "balance", ("uzun vadeli yukumlulukler",
                                          "long term liabilities")),
    ("financial_debt", "balance", ("finansal borclar", "financial liabilities",
                                   "financial debt")),
    ("total_equity", "balance", ("ozkaynaklar", "shareholders equity",
                                 "total equity")),
    ("minority_interest", "balance", ("kontrol gucu olmayan", "azinlik paylari",
                                      "minority interest", "non-controlling")),
    ("paid_in_capital", "balance", ("odenmis sermaye", "paid-in capital",
                                    "paid in capital")),
    ("retained_earnings", "balance", ("gecmis yillar kar", "retained earnings")),
    ("depreciation", "cashflow", ("amortisman", "depreciation")),
    ("operating_cash_flow", "cashflow", ("isletme faaliyetlerinden",
                                         "operating activities")),
    ("capex", "cashflow", ("duran varlik alim", "capital expenditure",
                           "purchase of property")),
    ("free_cash_flow", "cashflow", ("serbest nakit", "free cash flow")),
    ("dividends_paid", "cashflow", ("odenen temettu", "odenen kar pay",
                                    "dividends paid")),
]
# rules that must not match a more specific line (e.g. "Net Faaliyet Kar" for EBIT
# is fine, but "Diğer Faaliyetlerden Gelirler" is not an EBIT line)
_EXCLUDE = {
    "operating_income": ("diger faaliyet", "other operating", "esas faaliyet disi"),
    "revenue": ("diger", "other", "finansal", "faiz"),
    "total_equity": ("toplam kaynaklar", "yukumlulukler ve", "liabilities and"),
    "cash": ("kisitli", "restricted"),
    "tax_expense": ("ertelenmis", "deferred", "oncesi", "before"),
    "net_income": ("kontrol gucu olmayan", "azinlik", "minority", "non controlling"),
    "net_income_parent": ("ozkaynak",),  # "Ana Ortaklığa Ait Özkaynaklar" is equity
    "current_assets": ("non current", "duran varlik"),
    "current_liabilities": ("non current", "uzun vadeli"),
}
_FIRST_ONLY = {"financial_debt"}  # occurs under short then long term; summed below


def _fold(text: Any) -> str:
    s = str(text or "").replace("İ", "i").replace("I", "ı").lower()
    s = s.replace("ı", "i")
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", re.sub(r"[()\-–:]+", " ", s)).strip()


def _num(v: Any) -> float | None:
    if v is None or v == "":
        return None
    try:
        x = float(str(v).replace(",", "")) if isinstance(v, str) else float(v)
    except (TypeError, ValueError):
        return None
    return x if x == x and abs(x) != float("inf") else None


def _compiled() -> list[tuple[str, tuple[str, ...], tuple[str, ...]]]:
    return [(item, tuple(_fold(k) for k in keys),
             tuple(_fold(x) for x in _EXCLUDE.get(item, ())))
            for item, _st, keys in _RULES]


def _match(desc: str) -> str | None:
    for item, keys, excl in _MATCHERS:
        if any(k in desc for k in keys) and not any(x in desc for x in excl):
            return item
    return None


_MATCHERS = _compiled()


def period_end(year: int, month: int) -> str:
    day = {3: 31, 6: 30, 9: 30, 12: 31}[month]
    return date(year, month, day).isoformat()


def parse_mali_tablo(
    payload: Any, periods: list[tuple[int, int]]
) -> dict[str, dict[str, float]]:
    """``{period_end: {item: value}}`` from one MaliTablo response.

    ``periods`` are the ``(year, month)`` pairs in request order (value1..value4).
    Financial debt appears twice (short- then long-term) and is split into
    ``short_term_debt`` / ``long_term_debt``; ``total_debt`` is their sum.
    """
    rows = (payload or {}).get("value") if isinstance(payload, dict) else payload
    out: dict[str, dict[str, float]] = {period_end(y, m): {} for y, m in periods}
    debt_seen: dict[str, int] = {}
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        desc = _fold(row.get("itemDescTr")) + " | " + _fold(row.get("itemDescEng"))
        item = _match(desc)
        if item is None:
            continue
        for i, (y, m) in enumerate(periods, start=1):
            v = _num(row.get(f"value{i}"))
            if v is None:
                continue
            pe = period_end(y, m)
            if item == "financial_debt":
                n = debt_seen.get(pe, 0)
                debt_seen[pe] = n + 1
                key = "short_term_debt" if n == 0 else "long_term_debt" if n == 1 else None
                if key:
                    out[pe][key] = v
                continue
            out[pe].setdefault(item, v)  # first (top-level) line wins
    for items in out.values():
        _derive(items)
    return {pe: items for pe, items in out.items() if items}


def _derive(it: dict[str, float]) -> None:
    # the parent's share is what the per-share valuation needs
    if "net_income_parent" in it:
        it["net_income"] = it.pop("net_income_parent")
    if "short_term_debt" in it or "long_term_debt" in it:
        it["total_debt"] = it.get("short_term_debt", 0.0) + it.get("long_term_debt", 0.0)
    if "total_assets" in it and "total_equity" in it:
        it.setdefault("total_liabilities", it["total_assets"] - it["total_equity"])
    if "operating_income" in it and "depreciation" in it:
        it.setdefault("ebitda", it["operating_income"] + abs(it["depreciation"]))
    if "operating_cash_flow" in it and "capex" in it:
        it.setdefault("free_cash_flow", it["operating_cash_flow"] - abs(it["capex"]))
    sga = [it[k] for k in ("selling_expense", "admin_expense") if k in it]
    if sga:
        it.setdefault("sga", sum(abs(x) for x in sga))
    # BIST shares have 1 TL nominal value: paid-in capital ≈ share count
    if "paid_in_capital" in it:
        it.setdefault("shares_outstanding", it["paid_in_capital"])


def statement_of(item: str) -> str:
    for name, st, _ in _RULES:
        if name == item:
            return st
    return "balance" if item in {"short_term_debt", "long_term_debt", "total_debt",
                                 "total_liabilities", "shares_outstanding"} else (
        "cashflow" if item == "free_cash_flow" else "income")


def estimated_known_at(pe: str) -> str:
    """Latest legal (consolidated) publish date for a period end — conservative."""
    d = date.fromisoformat(pe)
    return (d + timedelta(days=DEADLINE_DAYS.get(d.month, 70) + 1)).isoformat()


def to_store_rows(
    ticker: str,
    statements: dict[str, dict[str, float]],
    *,
    publish_dates: dict[str, str] | None = None,
    bank: bool = False,
    currency: str = "TRY",
) -> list[dict[str, Any]]:
    """PanelStore rows; ``known_at`` from the KAP date, else the filing deadline."""
    publish_dates = publish_dates or {}
    rows = []
    for pe, items in statements.items():
        pub = publish_dates.get(pe)
        known = pub or estimated_known_at(pe)
        restated = not bank and pe >= TMS29_FROM
        for item, value in items.items():
            rows.append({
                "ticker": ticker, "period_end": pe, "statement": statement_of(item),
                "line_item": item, "value": value, "currency": currency,
                "is_inflation_adjusted": restated, "kap_publish_date": known,
            })
    return rows


def default_periods(today: date | None = None, years: int = 5) -> list[tuple[int, int]]:
    """Last ``years`` annual periods plus the quarters filed this year, newest first."""
    today = today or date.today()
    out: list[tuple[int, int]] = []
    for m in (9, 6, 3):
        if date.fromisoformat(estimated_known_at(period_end(today.year, m))) <= today:
            out.append((today.year, m))
    last_annual = today.year - 1 if date.fromisoformat(
        estimated_known_at(period_end(today.year - 1, 12))) <= today else today.year - 2
    out += [(last_annual - i, 12) for i in range(years)]
    return out


async def fetch_statements(
    ticker: str,
    periods: list[tuple[int, int]] | None = None,
    *,
    bank: bool | None = None,
    fetch=None,
) -> dict[str, Any]:
    """Pull statements for ``periods`` (4 per request) and parse them."""
    from .company_valuation import BANKS

    t = ticker.strip().upper().split(":")[-1].removesuffix(".IS")
    is_bank = (t in BANKS) if bank is None else bank
    periods = periods or default_periods()
    fetch = fetch or _fetch_chunk
    out: dict[str, dict[str, float]] = {}
    for i in range(0, len(periods), 4):
        chunk = periods[i:i + 4]
        payload = await fetch(t, chunk, GROUP_BANK if is_bank else GROUP_INDUSTRIAL)
        for pe, items in parse_mali_tablo(payload, chunk).items():
            out.setdefault(pe, {}).update(items)
    return {"ticker": t, "bank": is_bank, "statements": dict(sorted(out.items())),
            "source": "kap (İş Yatırım MaliTablo)"}


async def _fetch_chunk(ticker: str, chunk: list[tuple[int, int]], group: str) -> Any:
    params: dict[str, Any] = {"companyCode": ticker, "exchange": "TRY", "financialGroup": group}
    for i, (y, m) in enumerate(chunk, start=1):
        params[f"year{i}"], params[f"period{i}"] = y, m
    key = "isy.malitablo:" + ":".join([ticker, group] + [f"{y}{m:02d}" for y, m in chunk])
    payload = cache_get(key, ttl_seconds=CACHE_TTL)
    if payload is None:
        payload = await fetch_json(MALI_TABLO_URL, params=params, source="isyatirim")
        cache_set(key, payload, ttl_seconds=CACHE_TTL)
    return payload


async def ingest(
    ticker: str,
    store: Any,
    *,
    periods: list[tuple[int, int]] | None = None,
    publish_dates: dict[str, str] | None = None,
    fetch=None,
) -> dict[str, Any]:
    """Fetch → PanelStore. Idempotent (rows are upserted by period/item)."""
    res = await fetch_statements(ticker, periods, fetch=fetch)
    rows = to_store_rows(res["ticker"], res["statements"], publish_dates=publish_dates,
                         bank=res["bank"])
    n = store.upsert_fundamentals(rows)
    return {"ticker": res["ticker"], "periods": list(res["statements"]), "rows": n,
            "bank": res["bank"], "source": res["source"],
            "known_at": "kap" if publish_dates else "filing_deadline_estimate"}


# ---------------------------------------------------------------------------
# Point-in-time reads
# ---------------------------------------------------------------------------

def _as_of_ts(as_of: str | int | None) -> int:
    if as_of is None:
        return int(datetime.now(timezone.utc).timestamp())
    if isinstance(as_of, int):
        return as_of
    return int(datetime.strptime(as_of[:10], "%Y-%m-%d")
               .replace(tzinfo=timezone.utc).timestamp())


def statements_as_of(
    store: Any, ticker: str, as_of: str | int | None = None, *, annual_only: bool = True
) -> dict[str, dict[str, float]]:
    """``{period_end: {item: value}}`` using only rows public at ``as_of``."""
    rows = store.fundamental_rows(ticker, _as_of_ts(as_of))
    out: dict[str, dict[str, float]] = {}
    for r in rows:
        if annual_only and not r["period_end"].endswith("-12-31"):
            continue
        if r["value"] is not None:
            out.setdefault(r["period_end"], {})[r["line_item"]] = r["value"]
    return dict(sorted(out.items()))


# canonical item → fundamental_data history field
_HISTORY_FIELDS = {
    "revenue": "revenue", "operating_income": "ebit", "ebitda": "ebitda",
    "net_income": "net_income", "depreciation": "da", "capex": "capex",
    "free_cash_flow": "fcf", "total_debt": "total_debt", "cash": "cash",
    "total_equity": "equity", "minority_interest": "minority_interest",
    "shares_outstanding": "shares", "dividends_paid": "dividends_paid",
}


def history_from_statements(st: dict[str, dict[str, float]]) -> dict[str, list[tuple[str, float]]]:
    """Annual statements → the ``{field: [(date, value)]}`` shape ``derive_drivers`` uses."""
    h: dict[str, list[tuple[str, float]]] = {}
    for pe, it in sorted(st.items()):
        for src, dst in _HISTORY_FIELDS.items():
            if src in it:
                v = abs(it[src]) if src in ("depreciation", "capex") else it[src]
                h.setdefault(dst, []).append((pe, v))
        if all(k in it for k in ("current_assets", "current_liabilities")):
            nwc = it["current_assets"] - it.get("cash", 0.0) - (
                it["current_liabilities"] - it.get("short_term_debt", 0.0))
            h.setdefault("working_capital", []).append((pe, nwc))
        if it.get("pretax_income") and "tax_expense" in it and it["pretax_income"] > 0:
            h.setdefault("tax_rate", []).append(
                (pe, min(max(abs(it["tax_expense"]) / it["pretax_income"], 0.0), 0.5)))
    return h


def financial_periods_as_of(
    store: Any, ticker: str, as_of: str | int | None = None
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """(current, prior) annual periods as ``FinancialPeriod`` kwargs, point-in-time."""
    st = statements_as_of(store, ticker, as_of)
    if not st:
        return None, None
    ends = sorted(st)

    def fp(pe: str) -> dict[str, Any]:
        it = st[pe]
        keys = ("revenue", "cogs", "gross_profit", "sga", "operating_income", "ebitda",
                "depreciation", "interest_expense", "pretax_income", "tax_expense",
                "net_income", "total_assets", "current_assets", "cash", "inventory",
                "receivables", "ppe", "current_liabilities", "short_term_debt",
                "long_term_debt", "total_debt", "total_liabilities", "total_equity",
                "retained_earnings", "shares_outstanding", "operating_cash_flow", "capex",
                "free_cash_flow", "dividends_paid")
        d: dict[str, Any] = {k: it[k] for k in keys if k in it}
        for k in ("cogs", "interest_expense", "tax_expense", "depreciation"):
            if k in d:
                d[k] = abs(d[k])
        d["period_end"] = pe
        d["is_inflation_adjusted"] = pe >= TMS29_FROM
        return d

    cur = fp(ends[-1])
    prior = fp(ends[-2]) if len(ends) > 1 else None
    if prior and cur["is_inflation_adjusted"] != prior["is_inflation_adjusted"]:
        cur["_note"] = ("Önceki yıl TMS 29 öncesi; trend metrikleri (Piotroski, "
                        "Beneish, büyüme) karşılaştırılamaz olabilir.")
    return cur, prior


__all__ = [
    "default_periods", "estimated_known_at", "fetch_statements", "financial_periods_as_of",
    "history_from_statements", "ingest", "parse_mali_tablo", "statements_as_of",
    "to_store_rows",
]

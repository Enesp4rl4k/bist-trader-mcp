"""KAP statements: parsing, point-in-time storage, valuation/analysis wiring."""

import asyncio
from datetime import date

import pytest

from bist_trader_mcp import kap_financials as kf
from bist_trader_mcp.data_store import PanelStore
from bist_trader_mcp.fundamental_data import derive_drivers


def _row(tr, en, *vals):
    r = {"itemCode": "x", "itemDescTr": tr, "itemDescEng": en}
    for i, v in enumerate(vals, start=1):
        r[f"value{i}"] = v
    return r


# Shape of a MaliTablo response (two annual periods, values as strings or numbers)
PAYLOAD = {"value": [
    _row("Dönen Varlıklar", "CURRENT ASSETS", "600", "500"),
    _row("Nakit ve Nakit Benzerleri", "Cash and Cash Equivalents", 100, 80),
    _row("Ticari Alacaklar", "Trade Receivables", 200, 180),
    _row("Stoklar", "Inventories", 150, 140),
    _row("Duran Varlıklar", "NON-CURRENT ASSETS", 900, 800),
    _row("Maddi Duran Varlıklar", "Property, Plant and Equipment", 700, 650),
    _row("TOPLAM VARLIKLAR", "TOTAL ASSETS", 1500, 1300),
    _row("Kısa Vadeli Yükümlülükler", "SHORT TERM LIABILITIES", 400, 350),
    _row("Finansal Borçlar", "Financial Liabilities", 120, 100),
    _row("Uzun Vadeli Yükümlülükler", "LONG TERM LIABILITIES", 300, 280),
    _row("Finansal Borçlar", "Financial Liabilities", 200, 210),
    _row("Özkaynaklar", "SHAREHOLDERS EQUITY", 800, 670),
    _row("Ana Ortaklığa Ait Özkaynaklar", "Equity Attributable to Equity Holders", 750, 630),
    _row("Ödenmiş Sermaye", "Paid-in Capital", 50, 50),
    _row("Kontrol Gücü Olmayan Paylar", "Minority Interest", 50, 40),
    _row("Satış Gelirleri", "Revenue", 2000, 1600),
    _row("Satışların Maliyeti (-)", "Cost of Sales (-)", -1400, -1150),
    _row("BRÜT KAR (ZARAR)", "GROSS PROFIT (LOSS)", 600, 450),
    _row("Pazarlama, Satış ve Dağıtım Giderleri (-)", "Marketing, Selling and Distribution "
         "Expenses (-)", -100, -90),
    _row("Genel Yönetim Giderleri (-)", "General Administrative Expenses (-)", -80, -70),
    _row("Diğer Faaliyet Gelirleri", "Other Operating Income", 999, 999),
    _row("FAALİYET KARI (ZARARI)", "OPERATING PROFITS", 400, 280),
    _row("Finansman Giderleri (-)", "Financial Expenses (-)", -60, -50),
    _row("SÜRDÜRÜLEN FAALİYETLER VERGİ ÖNCESİ KARI", "PROFIT BEFORE TAX", 300, 220),
    _row("Dönem Vergi Geliri (Gideri)", "Tax Income/Expense", -75, -55),
    _row("Ertelenmiş Vergi Geliri", "Deferred Tax Income", 5, 5),
    _row("DÖNEM KARI (ZARARI)", "Net Profit for the Period", 225, 165),
    _row("Kontrol Gücü Olmayan Paylar", "Minority Interest", 25, 15),
    _row("Ana Ortaklık Payları", "Net Profit after Minority Interest", 200, 150),
    _row("Amortisman Giderleri", "Depreciation & Amortization", 90, 80),
    _row("İşletme Faaliyetlerinden Kaynaklanan Net Nakit", "Net Cash from Operating "
         "Activities", 350, 260),
    _row("Maddi ve Maddi Olmayan Duran Varlık Alımları", "Capital Expenditures", -150, -120),
    _row("Ödenen Temettüler", "Dividends Paid", -40, None),
    _row("Bilinmeyen kalem", "Unknown", 1, 1),
]}
PERIODS = [(2024, 12), (2023, 12)]


def _fetch(payload=PAYLOAD, calls=None):
    async def fetch(ticker, chunk, group):
        if calls is not None:
            calls.append((ticker, list(chunk), group))
        return payload
    return fetch


def test_parse_maps_line_items_and_derives():
    st = kf.parse_mali_tablo(PAYLOAD, PERIODS)
    cur = st["2024-12-31"]
    assert cur["revenue"] == 2000.0
    assert cur["current_assets"] == 600.0  # not overwritten by "NON-CURRENT ASSETS"
    assert cur["operating_income"] == 400.0  # "Other Operating Income" is not EBIT
    assert cur["net_income"] == 200.0  # parent share, not the 225 consolidated
    assert cur["total_equity"] == 800.0
    assert cur["minority_interest"] == 50.0  # balance sheet line comes first
    assert cur["tax_expense"] == -75.0  # deferred tax line ignored
    assert (cur["short_term_debt"], cur["long_term_debt"], cur["total_debt"]) == (120, 200, 320)
    assert cur["total_liabilities"] == 700.0
    assert cur["ebitda"] == 490.0
    assert cur["free_cash_flow"] == 200.0
    assert cur["sga"] == 180.0
    assert cur["shares_outstanding"] == 50.0  # 1 TL nominal → paid-in capital
    assert "dividends_paid" not in st["2023-12-31"]  # None stays missing


def test_parse_tolerates_garbage():
    assert kf.parse_mali_tablo(None, PERIODS) == {}
    assert kf.parse_mali_tablo({"value": [None, "x", _row("Satış Gelirleri", "", "n/a")]},
                               PERIODS) == {}


def test_known_at_is_publish_date_or_filing_deadline():
    st = kf.parse_mali_tablo(PAYLOAD, PERIODS)
    rows = kf.to_store_rows("THYAO", st, publish_dates={"2024-12-31": "2025-03-05"})
    by = {(r["period_end"], r["line_item"]): r for r in rows}
    assert by[("2024-12-31", "revenue")]["kap_publish_date"] == "2025-03-05"
    # no KAP date → latest legal date (annual consolidated +70 days, +1)
    assert by[("2023-12-31", "revenue")]["kap_publish_date"] == "2024-03-11"
    assert by[("2024-12-31", "revenue")]["statement"] == "income"
    assert by[("2024-12-31", "total_debt")]["statement"] == "balance"
    assert by[("2024-12-31", "capex")]["statement"] == "cashflow"
    assert all(r["is_inflation_adjusted"] for r in rows)  # FY2023+ non-bank → TMS 29
    bank_rows = kf.to_store_rows("GARAN", st, bank=True)
    assert not any(r["is_inflation_adjusted"] for r in bank_rows)
    assert kf.estimated_known_at("2025-03-31") == "2025-05-11"


def test_point_in_time_reads_never_see_unpublished_figures():
    with PanelStore(":memory:") as store:
        res = asyncio.run(kf.ingest("THYAO", store, periods=PERIODS, fetch=_fetch()))
        assert res["rows"] > 40 and res["known_at"] == "filing_deadline_estimate"
        assert kf.statements_as_of(store, "THYAO", "2024-03-10") == {}
        early = kf.statements_as_of(store, "THYAO", "2024-06-01")
        assert list(early) == ["2023-12-31"]
        late = kf.statements_as_of(store, "THYAO", "2025-06-01")
        assert list(late) == ["2023-12-31", "2024-12-31"]
        cur, prior = kf.financial_periods_as_of(store, "THYAO", "2024-06-01")
        assert cur["period_end"] == "2023-12-31" and prior is None


def test_ingest_is_idempotent_and_publish_date_replaces_estimate():
    with PanelStore(":memory:") as store:
        asyncio.run(kf.ingest("THYAO", store, periods=PERIODS, fetch=_fetch()))
        n1 = store.counts()["fundamentals"]
        asyncio.run(kf.ingest("THYAO", store, periods=PERIODS, fetch=_fetch(),
                              publish_dates={"2024-12-31": "2025-02-20"}))
        assert store.counts()["fundamentals"] == n1
        assert list(kf.statements_as_of(store, "THYAO", "2025-02-21")) == [
            "2023-12-31", "2024-12-31"]


def test_fetch_chunks_by_four_and_picks_group():
    calls = []
    periods = [(2024, 9), (2024, 6), (2024, 3), (2023, 12), (2022, 12)]
    asyncio.run(kf.fetch_statements("BIST:THYAO", periods, fetch=_fetch(calls=calls)))
    assert [len(c[1]) for c in calls] == [4, 1]
    assert calls[0][0] == "THYAO" and calls[0][2] == kf.GROUP_INDUSTRIAL
    calls.clear()
    asyncio.run(kf.fetch_statements("GARAN", PERIODS, fetch=_fetch(calls=calls)))
    assert calls[0][2] == kf.GROUP_BANK


def test_default_periods_only_include_filed_periods():
    p = kf.default_periods(date(2025, 4, 1), years=3)
    assert p == [(2024, 12), (2023, 12), (2022, 12)]  # Q1 2025 not due before May
    p = kf.default_periods(date(2025, 11, 15), years=2)
    assert p == [(2025, 9), (2025, 6), (2025, 3), (2024, 12), (2023, 12)]
    p = kf.default_periods(date(2025, 3, 1), years=1)
    assert p == [(2023, 12)]  # FY2024 deadline (Mar 12) not reached yet


def test_history_feeds_valuation_drivers():
    st = kf.parse_mali_tablo(PAYLOAD, PERIODS)
    d = derive_drivers(kf.history_from_statements(st))
    assert d["available"] and d["revenue0"] == 2000.0
    assert d["revenue_cagr"] == pytest.approx(0.25)
    assert d["capex_pct_revenue"] == pytest.approx((150 / 2000 + 120 / 1600) / 2, abs=1e-4)
    assert d["debt"] == 320.0 and d["cash"] == 100.0 and d["shares_outstanding"] == 50.0
    assert d["tax_rate"] == 0.25
    assert d["roe"] == pytest.approx(0.25)


def test_value_company_prefers_kap_and_falls_back_to_yahoo(monkeypatch):
    from bist_trader_mcp import company_valuation as cv
    from bist_trader_mcp import fundamental_data as fd

    async def kap_ok(symbol):
        return {"available": True, "revenue0": 1.0, "source": "kap"}

    async def kap_fail(symbol):
        raise RuntimeError("blocked")

    async def yahoo(ticker, years=6):
        return {"history": {"revenue": [("2024-12-31", 5.0)]}}

    monkeypatch.setattr(fd, "fetch_financial_history", yahoo)
    monkeypatch.setattr(cv, "_kap_history", kap_ok)
    assert asyncio.run(cv._default_history("THYAO"))["source"] == "kap"
    monkeypatch.setattr(cv, "_kap_history", kap_fail)
    out = asyncio.run(cv._default_history("THYAO"))
    assert out["source"] == "yahoo" and out["revenue0"] == 5.0


def test_tool_returns_point_in_time_analysis(monkeypatch):
    from bist_trader_mcp import tools

    monkeypatch.setattr(kf, "_fetch_chunk", _fetch())
    monkeypatch.setattr(kf, "default_periods", lambda today=None, years=5: PERIODS)
    out = asyncio.run(tools.get_kap_financials("THYAO", as_of="2025-06-01", years=2))
    assert out["symbol"] == "THYAO" and list(out["annual"]) == ["2023-12-31", "2024-12-31"]
    assert out["analysis"]["selection"]["score"] is not None
    # local DB only, before anything was public → clear "no_data", no network
    monkeypatch.setattr(kf, "_fetch_chunk", None)
    out = asyncio.run(tools.get_kap_financials("THYAO", as_of="2020-01-01", refresh=False))
    assert out["error"] == "no_data"
    assert asyncio.run(tools.get_kap_financials("bad sym!"))["error"] == "bad_input"

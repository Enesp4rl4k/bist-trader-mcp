"""Parser-level unit tests — network-free.

These exercise the pure-Python parsing logic in each fetcher against
hand-crafted text fixtures that mirror the live document shapes. Goals:

- Catch regressions in the regex / text-parsing layer without hitting
  the actual TR data sources.
- Make sure parser quirks (pdfplumber character scramble, KAP date
  format quirks, etc.) stay covered by tests.
- Keep CI green even when upstream sites are down or rate-limiting.
"""

from __future__ import annotations

from bist_trader_mcp.hazine import _parse_pdf_text as parse_hazine_pdf
from bist_trader_mcp.kap import _looks_material, _normalize_publish_date, _parse
from bist_trader_mcp.mkk import _detect_row_id
from bist_trader_mcp.mkk import _parse_pdf_text as parse_mkk_pdf
from bist_trader_mcp.takasbank import _to_int, _to_number

# ---------------------------------------------------------------------------
# Hazine — quarterly DİBS auction calendar PDF
# ---------------------------------------------------------------------------


HAZINE_FIXTURE = """\
2026 Yılı Ocak Ayı İhraç Takvimi
İhale Tarihi Valör Tarihi İtfa Tarihi Senet Türü Vadesi İhraç Yöntemi
5.01.2026 7.01.2026 6.01.2027 Kuponsuz Devlet Tahvili 12Ay / 364 Gün İhale / İlk ihraç
6.01.2026 7.01.2026 5.01.2028 Kira Sertifikası 2Yıl / 728 Gün Doğrudan Satış
6 ayda bir kira ödemeli
12.01.2026 14.01.2026 13.10.2027 Sabit Kuponlu Devlet Tahvili 2Yıl / 637 Gün İhale / Yeniden ihraç
6 ayda bir kupon ödemeli
12.01.2026 14.01.2026 8.01.2031 TÜFE'ye Endeksli Devlet Tahvili 5Yıl / 1820 Gün İhale / İlk ihraç
6 ayda bir kupon ödemeli
"""


def test_hazine_parser_extracts_all_auctions():
    rows = parse_hazine_pdf(HAZINE_FIXTURE)
    assert len(rows) == 4
    auction_dates = [r.auction_date for r in rows]
    assert auction_dates == ["2026-01-05", "2026-01-06", "2026-01-12", "2026-01-12"]


def test_hazine_parser_extracts_tenor_and_method():
    rows = parse_hazine_pdf(HAZINE_FIXTURE)
    first = rows[0]
    assert first.instrument == "Kuponsuz Devlet Tahvili"
    assert first.tenor_days == 364
    assert first.tenor_label == "12Ay"
    assert first.issuance_method == "İhale / İlk ihraç"


def test_hazine_parser_attaches_coupon_frequency_continuation():
    rows = parse_hazine_pdf(HAZINE_FIXTURE)
    # Row 2 is the Kira Sertifikası — the line below it carries the
    # coupon-frequency note which the parser should attach.
    kira = rows[1]
    assert kira.instrument == "Kira Sertifikası"
    assert kira.coupon_frequency == "6 ayda bir kira ödemeli"


def test_hazine_parser_handles_inflation_indexed_apostrophe():
    rows = parse_hazine_pdf(HAZINE_FIXTURE)
    tufeli = rows[3]
    assert tufeli.instrument == "TÜFE'ye Endeksli Devlet Tahvili"
    assert tufeli.tenor_days == 1820
    assert tufeli.coupon_frequency == "6 ayda bir kupon ödemeli"


# ---------------------------------------------------------------------------
# MKK — marketwide monthly system statistics PDF
# ---------------------------------------------------------------------------


# This mirrors how pdfplumber renders the MKK PDF: header line with
# year-month tokens, then rows where the labels are character-scrambled
# (single-digit row 1, sub-row 3.1, sub-row 3.2 all appear with letters
# interleaved between the digits and the dash).
MKK_FIXTURE = """\
MKK SYSTEM STATISTICS
2025 - MAY 2025 - JUNE 2025 - JULY 2025 - AUGUST 2025 - SEPTEMBER 2025 - OCTOBER 2025 - NOVEMBER 2025 - DECEMBER 2026 - JANUARY 2026 - FEBRUARY 2026 - MARCH 2026 - APRIL
System Data
1 M o - n N t u h m ly ber of Accounts Opened 443.811 440.468 517.474 689.583 594.246 653.113 672.896 584.547 789.612 696.057 596.817 495.087
2 - Number of Investors 36.607.954 36.704.978 36.815.404 36.951.560 37.468.816 37.648.312 37.797.686 37.944.546 38.100.350 38.231.387 38.356.219 38.457.843
3 H o - l N d u in m g b s er of Investors with Securities 10.450.297 10.435.076 10.427.957 10.531.564 10.516.620 10.618.805 10.572.796 10.642.453 10.710.763 10.900.236 10.584.519 10.582.981
3 B . a 1 l a - n N c u e m in b E er q u o i f t i I e n s vestors with 6.544.274 6.484.812 6.421.972 6.402.813 6.398.503 6.500.266 6.442.502 6.513.731 6.566.740 6.779.188 6.428.437 6.411.705
3 in .2 G - o N v u e m rn b m e e r n o f t f D In e v b e t s S to e r c s u r w it i i t e h s Balance 22.663 24.057 20.696 23.418 25.184 25.859 28.963 32.162 34.270 31.354 33.086 33.229
"""


def test_mkk_row_id_detector_handles_simple_prefix():
    assert _detect_row_id("2 - Number of Investors 36.607.954") == "2"


def test_mkk_row_id_detector_handles_mangled_main_row():
    # "1 M o - n N t u h m ly ber..." — single digit, letters before dash
    assert _detect_row_id("1 M o - n N t u h m ly ber of Accounts 443.811") == "1"


def test_mkk_row_id_detector_handles_mangled_sub_row():
    # "3 B . a 1 l a - n N c..." — should resolve to 3.1
    line = "3 B . a 1 l a - n N c u e m in b E er q u o 6.544.274"
    assert _detect_row_id(line) == "3.1"


def test_mkk_row_id_detector_rejects_year_token():
    # The header line starts with "2025 - MAY ..." and must NOT register
    # as a row identifier.
    line = "2025 - MAY 2025 - JUNE 2025 - JULY"
    assert _detect_row_id(line) is None


def test_mkk_parser_picks_header_months():
    stats = parse_mkk_pdf(MKK_FIXTURE, source_url="fixture://")
    assert stats.months[0] == "2025-05"
    assert stats.months[-1] == "2026-04"
    assert len(stats.months) == 12


def test_mkk_parser_extracts_main_and_sub_rows():
    stats = parse_mkk_pdf(MKK_FIXTURE, source_url="fixture://")
    row_ids = [r.row_id for r in stats.rows]
    assert "1" in row_ids
    assert "2" in row_ids
    assert "3" in row_ids
    assert "3.1" in row_ids
    assert "3.2" in row_ids


def test_mkk_parser_emits_correct_latest_value():
    stats = parse_mkk_pdf(MKK_FIXTURE, source_url="fixture://")
    total_investors = next(r for r in stats.rows if r.row_id == "2")
    # Last column in the fixture is 38,457,843
    assert total_investors.monthly_values[-1] == 38_457_843


# ---------------------------------------------------------------------------
# Takasbank — small numeric parsing helpers
# ---------------------------------------------------------------------------


def test_takasbank_to_number_parses_turkish_format():
    assert _to_number("113.405") == 113405.0
    assert _to_number("404.002.374,47") == 404002374.47
    assert _to_number("96.174.374.438,15") == 96174374438.15


def test_takasbank_to_number_returns_none_for_garbage():
    assert _to_number(None) is None
    assert _to_number("") is None
    assert _to_number("-") is None
    assert _to_number("abc") is None


def test_takasbank_to_int_truncates():
    assert _to_int("113.405") == 113405
    assert _to_int("113.405,99") == 113405
    assert _to_int(None) is None


# ---------------------------------------------------------------------------
# KAP — disclosure normalisation helpers
# ---------------------------------------------------------------------------


def test_kap_material_keyword_match():
    assert _looks_material("Pay Geri Alım Bildirimi")
    assert _looks_material("Kar Payı Dağıtım İşlemlerine İlişkin Bildirim")
    assert _looks_material("Önemli Nitelikteki İşlem")
    assert not _looks_material("Sermaye Piyasası Kurulu Onayı")  # not in keyword list
    assert not _looks_material("")


def test_kap_publish_date_iso_normalisation_tr_format():
    assert _normalize_publish_date("11.05.2026 17:36:52") == "2026-05-11T17:36"


def test_kap_publish_date_iso_normalisation_idempotent():
    # Already-ISO inputs pass through (Python keeps them as-is via fallback)
    iso_in = "2026-05-11T17:36:00"
    assert _normalize_publish_date(iso_in) == "2026-05-11T17:36"


def test_kap_parse_full_row():
    row = {
        "disclosureBasic": {
            "disclosureId": "4028e4a14bcf2a06014be4d7e6e256b6",
            "disclosureIndex": 1604852,
            "publishDate": "11.05.2026 17:36:52",
            "stockCode": "THYAO",
            "companyTitle": "TÜRK HAVA YOLLARI A.O.",
            "title": "Özel Durum Açıklaması (Genel)",
            "summary": "Test summary",
            "isLate": False,
        }
    }
    d = _parse(row)
    assert d is not None
    assert d.disclosure_id == "4028e4a14bcf2a06014be4d7e6e256b6"
    assert d.publish_date == "2026-05-11T17:36"
    assert d.company_ticker == "THYAO"
    assert d.company_name == "TÜRK HAVA YOLLARI A.O."
    assert d.subject == "Özel Durum Açıklaması (Genel)"
    assert d.is_material is True   # "Özel Durum" matches the heuristic
    assert d.url == "https://www.kap.org.tr/tr/Bildirim/1604852"
    assert d.is_late is False


def test_kap_parse_handles_missing_basic():
    assert _parse({"other": "noise"}) is None

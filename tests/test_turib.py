"""TÜRİB public parser."""

from bist_trader_mcp.turib import TURIB_INDEX_CATALOG, _parse_endeks_cards


def test_catalog_has_hububat():
    assert "hububat" in TURIB_INDEX_CATALOG


def test_parse_endeks_cards_empty_html():
    assert _parse_endeks_cards("<html></html>") == []


def test_parse_endeks_cards_sample():
    html = "Hububat Endeksi 12,345.67 +1.2% Buğday Endeksi 10,000.00 -0.5%"
    cards = _parse_endeks_cards(html)
    assert len(cards) >= 1

"""Unit tests for bist_snapshot module — parsing logic, no network."""

from __future__ import annotations

from bist_trader_mcp.bist_snapshot import (
    MARKET_SUMMARY_SYMBOLS,
    PriceSnapshot,
    _empty_snapshot,
    _round,
    _sf,
    _to_yahoo,
)


def test_to_yahoo_plain_bist_ticker():
    assert _to_yahoo("THYAO") == "THYAO.IS"
    assert _to_yahoo("garan") == "GARAN.IS"


def test_to_yahoo_already_suffixed():
    assert _to_yahoo("THYAO.IS") == "THYAO.IS"


def test_to_yahoo_index():
    assert _to_yahoo("^XU100") == "^XU100"


def test_to_yahoo_alias():
    assert _to_yahoo("USDTRY") == "USDTRY=X"
    assert _to_yahoo("XU100") == "^XU100"


def test_to_yahoo_fx():
    assert _to_yahoo("EURTRY") == "EURTRY=X"


def test_safe_float_normal():
    assert _sf(42.5) == 42.5
    assert _sf("123") == 123.0


def test_safe_float_none():
    assert _sf(None) is None


def test_safe_float_nan():
    assert _sf(float("nan")) is None


def test_safe_float_string_garbage():
    assert _sf("garbage") is None


def test_round_helper():
    assert _round(1.23456, 2) == 1.23
    assert _round(None) is None


def test_empty_snapshot_fields():
    snap = _empty_snapshot("THYAO")
    assert snap.ticker == "THYAO"
    assert snap.last_price is None
    assert snap.change is None
    assert snap.as_of  # non-empty string


def test_market_summary_symbols_covers_key_assets():
    assert "XU100" in MARKET_SUMMARY_SYMBOLS
    assert "XU030" in MARKET_SUMMARY_SYMBOLS
    assert "USDTRY" in MARKET_SUMMARY_SYMBOLS
    assert "EURTRY" in MARKET_SUMMARY_SYMBOLS
    assert "GOLD_USD" in MARKET_SUMMARY_SYMBOLS


def test_price_snapshot_dataclass():
    snap = PriceSnapshot(
        ticker="THYAO",
        last_price=380.5,
        previous_close=370.0,
        open=372.0,
        day_high=382.0,
        day_low=370.0,
        change=10.5,
        change_pct=2.84,
        volume=5_000_000,
        market_state="REGULAR",
        currency="TRY",
        as_of="2026-05-12T10:00:00",
    )
    assert snap.ticker == "THYAO"
    assert snap.change_pct == 2.84
    assert snap.currency == "TRY"

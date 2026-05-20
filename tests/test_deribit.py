"""Tests for Deribit instrument parser + surface builder."""

from __future__ import annotations

from datetime import date


from bist_trader_mcp.deribit import (
    DeribitOption,
    _parse_expiry,
    _parse_instrument,
    build_deribit_surface,
)


def test_parse_expiry_standard():
    assert _parse_expiry("27JUN26") == date(2026, 6, 27)
    assert _parse_expiry("3SEP24") == date(2024, 9, 3)
    assert _parse_expiry("30AUG25") == date(2025, 8, 30)


def test_parse_expiry_invalid():
    assert _parse_expiry("BADXX26") is None
    assert _parse_expiry("27XXX26") is None
    assert _parse_expiry("") is None


def test_parse_instrument_btc_call():
    raw = {
        "instrument_name": "BTC-27JUN26-100000-C",
        "mark_price": 0.05,
        "mark_iv": 45.0,
        "last": 0.045,
        "volume": 100.0,
        "open_interest": 1000.0,
    }
    opt = _parse_instrument(raw)
    assert opt is not None
    assert opt.underlying == "BTC"
    assert opt.strike == 100000.0
    assert opt.right == "C"
    assert opt.expiry == date(2026, 6, 27)
    assert opt.mark_iv_pct == 45.0


def test_parse_instrument_eth_put():
    raw = {
        "instrument_name": "ETH-30AUG25-3500-P",
        "mark_iv": 55.0,
    }
    opt = _parse_instrument(raw)
    assert opt is not None
    assert opt.underlying == "ETH"
    assert opt.right == "P"
    assert opt.strike == 3500.0


def test_parse_instrument_skips_non_option():
    # Perpetual / futures should be filtered out (only 2 dashes)
    assert _parse_instrument({"instrument_name": "BTC-PERPETUAL"}) is None
    assert _parse_instrument({"instrument_name": "BTC-27JUN26"}) is None


def test_build_deribit_surface_groups_by_expiry():
    today = date.today()
    future_date = date(today.year + 1, today.month, 15)
    chain = [
        DeribitOption(
            instrument="BTC-X-100000-C", underlying="BTC",
            expiry=future_date, strike=100000.0, right="C",
            mark_price=0.05, mark_iv_pct=45.0,
            last_price=None, volume_24h=None, open_interest=None,
        ),
        DeribitOption(
            instrument="BTC-X-100000-P", underlying="BTC",
            expiry=future_date, strike=100000.0, right="P",
            mark_price=0.04, mark_iv_pct=50.0,
            last_price=None, volume_24h=None, open_interest=None,
        ),
        DeribitOption(
            instrument="BTC-X-110000-C", underlying="BTC",
            expiry=future_date, strike=110000.0, right="C",
            mark_price=0.02, mark_iv_pct=42.0,
            last_price=None, volume_24h=None, open_interest=None,
        ),
    ]
    surface = build_deribit_surface(chain=chain, spot=100000.0)
    assert surface["meta"]["points"] == 3
    assert future_date.isoformat() in surface["by_expiry"]
    # ATM IV should be set (call closest to spot)
    bucket = surface["by_expiry"][future_date.isoformat()]
    assert bucket["atm_iv_pct"] is not None


def test_build_deribit_surface_skips_zero_iv():
    today = date.today()
    chain = [
        DeribitOption(
            instrument="BTC-X-100000-C", underlying="BTC",
            expiry=date(today.year + 1, today.month, 15),
            strike=100000.0, right="C",
            mark_price=None, mark_iv_pct=0.5,  # below default min_iv
            last_price=None, volume_24h=None, open_interest=None,
        ),
    ]
    surface = build_deribit_surface(chain=chain, spot=100000.0)
    assert surface["meta"]["points"] == 0

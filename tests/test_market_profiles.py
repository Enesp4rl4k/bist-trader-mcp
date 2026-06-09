"""Market profile detection and TV symbol normalization."""

from bist_trader_mcp.market_profiles import (
    detect_asset_class,
    get_market_profile,
    normalize_tv_symbol,
    resolve_assistant_config,
)


def test_crypto_detect_and_tv():
    assert detect_asset_class("BINANCE:BTCUSDT") == "crypto"
    assert normalize_tv_symbol("BTCUSDT") == "BINANCE:BTCUSDT"
    cfg = resolve_assistant_config("BINANCE:ETHUSDT")
    assert cfg["ltf_timeframe"] == "60"
    assert cfg["htf_timeframe"] == "240"
    assert cfg["ohlcv_bars"] == 300


def test_bist_equity():
    p = get_market_profile("THYAO")
    assert p["asset_class"] == "bist_equity"
    assert p["symbol_tv"] == "BIST:THYAO"
    assert p["defaults"]["default_htf_timeframe"] == "D"


def test_bist_index():
    p = get_market_profile("XU030")
    assert p["asset_class"] == "bist_index"
    assert p["defaults"]["min_trade_quality"] == "a_plus"


def test_viop_future():
    p = get_market_profile("F_XU0300625")
    assert p["asset_class"] == "viop_future"
    assert p["symbol_tv"] == "BIST:F_XU0300625"
    assert p["underlying"] == "XU030"
    assert p["defaults"]["default_ltf_timeframe"] == "15"
    assert p["defaults"]["risk_per_trade_pct"] == 0.5


def test_viop_option():
    assert detect_asset_class("O_XU0300625_C5500") == "viop_option"


def test_market_override():
    assert detect_asset_class("FOO", market="crypto") == "crypto"

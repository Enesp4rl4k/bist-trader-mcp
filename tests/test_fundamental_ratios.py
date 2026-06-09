"""Pure ratio-scoring tests for fundamental_ratios (no network)."""

from bist_trader_mcp.fundamental_ratios import (
    EquityFundamentals,
    score_fundamental_ratios,
    summarize_fundamentals_tr,
)


def test_none_is_unavailable():
    sp = score_fundamental_ratios(None)
    assert sp["available"] is False
    assert sp["bias"] == "neutral"


def test_empty_fundamentals_unavailable():
    sp = score_fundamental_ratios(EquityFundamentals(ticker="X"))
    assert sp["available"] is False
    assert sp["grade"] == "NA"


def test_quality_value_stock_scores_bullish():
    # Cheap, profitable, growing, low leverage (GARAN-like).
    f = EquityFundamentals(
        ticker="GARAN",
        trailing_pe=4.5,
        price_to_book=1.2,
        return_on_equity=0.30,
        profit_margin=0.32,
        debt_to_equity=0.4,
        earnings_growth=0.32,
        revenue_growth=0.25,
    )
    sp = score_fundamental_ratios(f)
    assert sp["available"] is True
    assert sp["bias"] == "bullish"
    assert sp["grade"] in ("A", "B")
    assert sp["score"] > 30
    assert "cheap_pe" in sp["factors"]
    assert "strong_roe" in sp["factors"]


def test_expensive_lossmaking_scores_bearish():
    f = EquityFundamentals(
        ticker="BAD",
        trailing_pe=80.0,
        price_to_book=6.0,
        return_on_equity=-0.05,
        profit_margin=-0.10,
        debt_to_equity=3.0,
        earnings_growth=-0.30,
    )
    sp = score_fundamental_ratios(f)
    assert sp["bias"] == "bearish"
    assert sp["score"] < -15
    assert "expensive_pe" in sp["factors"]
    assert "high_leverage" in sp["factors"]


def test_negative_earnings_flagged():
    f = EquityFundamentals(ticker="L", trailing_pe=-3.0)
    sp = score_fundamental_ratios(f)
    assert "negative_earnings" in sp["factors"]
    assert sp["components"]["pe"] < 0


def test_debt_to_equity_percent_normalised():
    # Yahoo gives D/E as a percent; the scorer expects a ratio. We pass the
    # already-normalised ratio here and confirm low leverage is rewarded.
    f = EquityFundamentals(ticker="LOWLEV", debt_to_equity=0.3)
    sp = score_fundamental_ratios(f)
    assert sp["components"]["debt_to_equity"] > 0


def test_summary_tr_contains_key_ratios():
    f = EquityFundamentals(
        ticker="GARAN", trailing_pe=4.5, price_to_book=1.2,
        return_on_equity=0.30, profit_margin=0.32,
    )
    txt = summarize_fundamentals_tr(f)
    assert "F/K" in txt
    assert "ROE" in txt
    assert "skor" in txt.lower()

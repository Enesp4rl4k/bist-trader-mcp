"""Unified TA + fundamental market context."""

from bist_trader_mcp.market_assistant import analyze_market_context


def _ohlc(n: int, trend: float = 1.0) -> tuple[list[float], list[float], list[float]]:
    closes = [100.0 + i * trend for i in range(n)]
    highs = [c + 2 for c in closes]
    lows = [c - 2 for c in closes]
    return closes, highs, lows


def test_analyze_market_context_structure():
    hc, hh, hl = _ohlc(80, 0.5)
    lc, lh, ll = _ohlc(120, 0.3)
    out = analyze_market_context(
        symbol="THYAO",
        htf_closes=hc,
        htf_highs=hh,
        htf_lows=hl,
        ltf_closes=lc,
        ltf_highs=lh,
        ltf_lows=ll,
        market="bist",
    )
    assert "technical" in out
    assert "fundamental" in out
    assert out["fundamental"].get("recommended_mcp_tools")
    assert "executive_summary_tr" in out
    assert "elliott_mtf" in out
    assert out["technical"].get("elliott_htf") is not None

"""Unified TA + fundamental market context."""

import asyncio

from bist_trader_mcp.market_assistant import _run_async, analyze_market_context


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


def test_analyze_market_context_backtest_and_scaling():
    hc, hh, hl = _ohlc(80, 0.5)
    lc, lh, ll = _ohlc(120, 0.3)
    
    # Mock a fundamental snapshot with a minor warning
    mock_fund_enrich = {
        "complete": True,
        "fetched": {
            "fundamental_ratios_score": {
                "available": True,
                "score": -35.0,
                "grade": "F",
                "bias": "bearish",
                "factors": ["weak_fundamentals_vs_long"]
            }
        }
    }
    
    out = analyze_market_context(
        symbol="THYAO",
        htf_closes=hc,
        htf_highs=hh,
        htf_lows=hl,
        ltf_closes=lc,
        ltf_highs=lh,
        ltf_lows=ll,
        market="bist",
        fetch_fundamentals=True,
        fund_enrich=mock_fund_enrich,
    )
    
    assert "backtest_metrics" in out["technical"]
    assert out["technical"]["backtest_metrics"] is not None
    assert "fusion" in out
    assert out["fusion"]["position_scale_factor"] < 1.0


def test_run_async_works_inside_running_loop():
    """Regression: run_market_assistant fetches fundamentals via _run_async, not
    raw asyncio.run(). Under the MCP server the tool runs inside an already-active
    event loop, where asyncio.run() raises RuntimeError. _run_async must offload
    to a worker thread and still return the result."""

    async def _coro() -> int:
        await asyncio.sleep(0)
        return 42

    async def _host() -> int:
        # A loop is now running on this thread — mirrors the MCP _call_tool path.
        return _run_async(_coro())

    assert asyncio.run(_host()) == 42


def test_run_async_works_without_running_loop():
    async def _coro() -> str:
        return "ok"

    assert _run_async(_coro()) == "ok"


"""MCP prompts: every referenced tool exists; workflows render with and without args."""

import asyncio
import re

import pytest

from bist_trader_mcp import server as srv
from bist_trader_mcp.workflows import WORKFLOWS

CALL_RX = re.compile(r"\b([a-z][a-z0-9_]{3,})\(")
NOT_TOOLS = {"get_job"}  # registered, listed here only to document polling calls


TEXT_ARGS = {"symbol", "company", "underlying", "ticker", "market", "peers", "asset",
             "category", "categories", "positions"}


def _sample_args(name):
    info = srv.PROMPTS_REGISTRY[name]
    return {a.name: ("THYAO" if a.name in TEXT_ARGS else "5") for a in info["arguments"]}


def test_numeric_prompt_args_tolerate_free_text():
    text = srv.PROMPTS_REGISTRY["aksam-rutini"]["render"]({"top_n": "beş"})
    assert "'top_n': 5" in text


@pytest.mark.parametrize("name", sorted(WORKFLOWS))
def test_workflow_tools_exist_and_are_used(name):
    wf = WORKFLOWS[name]
    missing = [t for t in wf["tools"] if t not in srv.TOOL_REGISTRY]
    assert not missing, f"{name} lists unknown tools {missing}"
    text = srv.PROMPTS_REGISTRY[name]["render"]({"symbol": "ASELS", "risk_free": 0.3,
                                                 "expected_inflation": 0.25,
                                                 "peers": "PGSUS, tavhl"})
    for t in wf["tools"]:
        assert t in text, f"{name}: tool {t} listed but not mentioned"
    assert "Yatırım tavsiyesi değildir" in text


def test_workflows_render_with_only_required_args():
    for name, wf in WORKFLOWS.items():
        required = {n: ("0.3" if "risk" in n else "GARAN") for n, _, r in wf["arguments"] if r}
        assert srv.PROMPTS_REGISTRY[name]["render"](required)


def test_stock_analysis_asks_for_risk_free_when_missing():
    text = srv.PROMPTS_REGISTRY["hisse-analizi"]["render"]({"symbol": "thyao"})
    assert "risksiz faizi" in text and "THYAO" in text
    with_rf = srv.PROMPTS_REGISTRY["hisse-analizi"]["render"]({"symbol": "THYAO",
                                                              "risk_free": 0.3})
    assert "value_company(symbol='THYAO', risk_free=0.3)" in with_rf


def test_valuation_prompt_formats_peers():
    text = srv.PROMPTS_REGISTRY["sirket-degerleme"]["render"](
        {"symbol": "THYAO", "risk_free": 0.3, "peers": "pgsus, tavhl ,"})
    assert "peers=['PGSUS', 'TAVHL']" in text


@pytest.mark.parametrize("name", sorted(srv.PROMPTS_REGISTRY))
def test_every_prompt_only_calls_registered_tools(name):
    text = srv.PROMPTS_REGISTRY[name]["render"](_sample_args(name))
    called = set(CALL_RX.findall(text)) - NOT_TOOLS
    unknown = sorted(c for c in called if c not in srv.TOOL_REGISTRY)
    assert not unknown, f"prompt {name} calls unknown tools: {unknown}"


def test_prompts_over_mcp():
    from mcp.shared.memory import create_connected_server_and_client_session

    async def main():
        async with create_connected_server_and_client_session(srv.server) as client:
            names = {p.name for p in (await client.list_prompts()).prompts}
            assert set(WORKFLOWS) <= names
            res = await client.get_prompt("sabah-brifingi", {})
            return res.messages[0].content.text

    assert "get_portfolio_risk" in asyncio.run(main())

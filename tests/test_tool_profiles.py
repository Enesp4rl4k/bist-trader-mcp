"""Tool profiles (token diet) and bounded in-memory caches."""

import asyncio
import json

import pytest

from bist_trader_mcp import server as srv
from bist_trader_mcp._cache import LRUDict
from bist_trader_mcp.tool_profiles import CORE, TRADER, enabled_tools


def _listed(monkeypatch, profile, extra=None):
    monkeypatch.setenv("BIST_TOOL_PROFILE", profile)
    if extra:
        monkeypatch.setenv("BIST_TOOLS_EXTRA", extra)
    return [t.name for t in asyncio.run(srv._list_tools())]


def _tokens(names):
    reg = srv.TOOL_REGISTRY
    return sum(len(json.dumps({"n": n, "d": reg[n]["description"], "s": reg[n]["inputSchema"]}))
               for n in names) // 4


def test_default_profile_is_full(monkeypatch):
    monkeypatch.delenv("BIST_TOOL_PROFILE", raising=False)
    assert len(_listed(monkeypatch, "full")) == len(srv.TOOL_REGISTRY)


def test_profiles_are_smaller_and_nested(monkeypatch):
    core = _listed(monkeypatch, "core")
    trader = _listed(monkeypatch, "trader")
    assert set(core) < set(trader) < set(srv.TOOL_REGISTRY)
    assert _tokens(core) < _tokens(trader) < _tokens(srv.TOOL_REGISTRY) / 1.5
    # the panel's own tools survive every profile
    assert {"open_dashboard", "dashboard_snapshot", "dashboard_action"} <= set(core)


def test_profile_names_exist_or_are_planned():
    planned = {"start_job", "get_job"}  # added with background jobs
    unknown = (CORE | TRADER) - set(srv.TOOL_REGISTRY) - planned
    assert not unknown, f"profile lists unknown tools: {sorted(unknown)}"


def test_hidden_tool_is_refused_and_extra_adds_it(monkeypatch):
    names = _listed(monkeypatch, "core")
    assert "get_viop_iv_surface" not in names
    out = asyncio.run(srv._call_tool("get_viop_iv_surface", {}))
    assert json.loads(out[0].text)["error"] == "tool_disabled"
    assert "get_viop_iv_surface" in _listed(monkeypatch, "core", extra="get_viop_iv_surface")


def test_unknown_profile_falls_back_to_full(monkeypatch):
    monkeypatch.setenv("BIST_TOOL_PROFILE", "nope")
    assert enabled_tools(list(srv.TOOL_REGISTRY)) == list(srv.TOOL_REGISTRY)


def test_lru_dict_evicts_least_recently_used():
    d = LRUDict(2)
    d["a"] = 1
    d["b"] = 2
    assert d.get("a") == 1  # touch a → b is now oldest
    d["c"] = 3
    assert list(d) == ["a", "c"]
    assert d.get("zz", "x") == "x"
    with pytest.raises(KeyError):
        d["b"]

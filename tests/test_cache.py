"""Smoke tests for the on-disk TTL cache.

Uses pytest's tmp_path fixture via monkeypatch on `_cache_root` so we
don't touch the user's real cache directory.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from bist_trader_mcp import _cache


@pytest.fixture(autouse=True)
def _redirect_cache_to_tmp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Force the cache layer to write inside tmp_path for the test session."""

    monkeypatch.setattr(_cache, "_cache_root", lambda: tmp_path / "bist-trader-mcp")


def test_cache_set_then_get_returns_value():
    _cache.cache_set("unit_test_basic", {"hello": "world"}, ttl_seconds=60)
    out = _cache.cache_get("unit_test_basic", ttl_seconds=60)
    assert out == {"hello": "world"}


def test_cache_miss_returns_none():
    assert _cache.cache_get("no_such_key", ttl_seconds=60) is None


def test_cache_expired_returns_none():
    _cache.cache_set("unit_test_expiry", {"x": 1}, ttl_seconds=1)
    # Wait until past TTL.
    time.sleep(1.5)
    assert _cache.cache_get("unit_test_expiry", ttl_seconds=1) is None


def test_cache_handles_non_ascii_key():
    # Cache keys can include unicode (Turkish chars in slugs etc.).
    _cache.cache_set("ünicode/keÿ:1", [1, 2, 3], ttl_seconds=60)
    assert _cache.cache_get("ünicode/keÿ:1", ttl_seconds=60) == [1, 2, 3]


def test_cache_preserves_nested_structures():
    payload = {
        "rows": [
            {"id": 1, "values": [1.5, 2.5, None]},
            {"id": 2, "values": [3.5, None, 4.5]},
        ],
        "meta": {"when": "2026-05-11T20:00"},
    }
    _cache.cache_set("nested", payload, ttl_seconds=60)
    assert _cache.cache_get("nested", ttl_seconds=60) == payload


def test_cache_atomic_write_no_partial_files(tmp_path):
    _cache.cache_set("atomic", "ok", ttl_seconds=60)
    # No .tmp leftovers should remain in the cache dir.
    cache_dir = _cache._cache_root()
    leftovers = list(cache_dir.glob("*.tmp"))
    assert not leftovers

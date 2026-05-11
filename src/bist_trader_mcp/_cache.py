"""Filesystem-backed cache for upstream responses with strict TTL.

Necessary because some TR data sources (notably Takasbank with F5 BIG-IP
TSPD) rate-limit per IP. Most published data is daily anyway, so caching
the fetched value for several hours is functionally lossless while
dramatically reducing the chance of hitting WAF cooldowns during a
chatty Claude session.

Cache layout:
    %LOCALAPPDATA%\\bist-trader-mcp\\cache\\<key>.json    (Windows)
    ~/.cache/bist-trader-mcp/<key>.json                  (POSIX)

Each file stores:
    {
        "saved_at":   ISO timestamp,
        "ttl_seconds": int,
        "value":      <whatever the caller stored>
    }

API:
    `cache_get(key, ttl_seconds)`  → returns value or None if stale/missing
    `cache_set(key, value, ttl_seconds)` → writes
    `cache_path_for(key)` → underlying path (debug)
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _cache_root() -> Path:
    """Return the platform-appropriate cache directory for this package."""
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        return Path(base) / "bist-trader-mcp" / "cache"
    return Path(os.path.expanduser("~")) / ".cache" / "bist-trader-mcp"


def _safe_key(key: str) -> str:
    """Sanitise an arbitrary key into a safe filename."""
    return re.sub(r"[^A-Za-z0-9._-]+", "_", key)[:200] or "default"


def cache_path_for(key: str) -> Path:
    return _cache_root() / f"{_safe_key(key)}.json"


def cache_get(key: str, ttl_seconds: int) -> Any | None:
    """Return cached value if file exists and is not older than TTL."""
    path = cache_path_for(key)
    if not path.is_file():
        return None
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None

    saved_at_raw = data.get("saved_at")
    if not saved_at_raw:
        return None
    try:
        saved_at = datetime.fromisoformat(saved_at_raw)
    except ValueError:
        return None
    if saved_at.tzinfo is None:
        saved_at = saved_at.replace(tzinfo=timezone.utc)

    age_seconds = (datetime.now(timezone.utc) - saved_at).total_seconds()
    if age_seconds > ttl_seconds:
        return None
    return data.get("value")


def cache_set(key: str, value: Any, ttl_seconds: int) -> None:
    """Persist `value` to the cache file."""
    path = cache_path_for(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "saved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "ttl_seconds": ttl_seconds,
        "value": value,
    }
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, default=str)
    os.replace(tmp, path)

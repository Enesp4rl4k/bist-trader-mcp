"""Per-tool call statistics and logging setup.

Logging goes to **stderr** (stdout carries the MCP stdio protocol and must stay
clean) and optionally to a rotating file:

- ``BIST_LOG_LEVEL``  DEBUG / INFO / WARNING (default WARNING)
- ``BIST_LOG_FILE``   path for a rotating log (1 MB × 3)
"""

from __future__ import annotations

import logging
import os
import sys
import threading
from typing import Any

log = logging.getLogger("bist_trader_mcp")

_lock = threading.Lock()
TOOL_STATS: dict[str, dict[str, float]] = {}


def record(tool: str, ms: float, ok: bool, error: str | None = None) -> None:
    with _lock:
        s = TOOL_STATS.setdefault(tool, {"calls": 0, "errors": 0, "total_ms": 0.0,
                                         "max_ms": 0.0})
        s["calls"] += 1
        s["total_ms"] += ms
        s["max_ms"] = max(s["max_ms"], ms)
        if not ok:
            s["errors"] += 1
    if ok:
        log.info("tool %s ok %.0f ms", tool, ms)
    else:
        log.warning("tool %s failed %.0f ms: %s", tool, ms, error)


def tool_stats() -> dict[str, Any]:
    with _lock:
        rows = {
            name: {
                "calls": int(s["calls"]),
                "errors": int(s["errors"]),
                "avg_ms": round(s["total_ms"] / s["calls"], 1) if s["calls"] else None,
                "max_ms": round(s["max_ms"], 1),
            }
            for name, s in TOOL_STATS.items()
        }
    return dict(sorted(rows.items(), key=lambda kv: -kv[1]["calls"]))


def setup_logging() -> None:
    """Configure the package logger once (called when the server starts)."""
    if getattr(setup_logging, "_done", False):
        return
    setup_logging._done = True  # type: ignore[attr-defined]
    level = getattr(logging, (os.environ.get("BIST_LOG_LEVEL") or "WARNING").upper(),
                    logging.WARNING)
    log.setLevel(level)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    err = logging.StreamHandler(sys.stderr)
    err.setFormatter(fmt)
    log.addHandler(err)
    path = os.environ.get("BIST_LOG_FILE")
    if path:
        from logging.handlers import RotatingFileHandler

        fh = RotatingFileHandler(path, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
        fh.setFormatter(fmt)
        log.addHandler(fh)
    log.propagate = False


__all__ = ["log", "record", "setup_logging", "tool_stats"]

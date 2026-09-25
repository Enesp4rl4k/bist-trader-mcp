"""Background jobs for long tool calls (universe backtest, daily pipeline).

A BIST30 backtest pulls 30 symbols through TradingView (~2–4 s each) — longer
than many MCP hosts wait for one tool call. ``start_job`` schedules the work on
the server's event loop and returns immediately; ``get_job`` reports status
and, when finished, the result. Jobs live in memory for an hour.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

JOB_TTL_SECONDS = 3600
MAX_JOBS = 20


def _kinds() -> dict[str, Callable[..., Awaitable[dict[str, Any]]]]:
    from . import tools

    return {
        "backtest_universe": tools.backtest_price_action_universe,
        "backtest": tools.backtest_price_action,
        "daily_pipeline": tools.run_daily_pipeline,
        "forecast_accuracy": tools.evaluate_forecast_accuracy,
    }


_jobs: dict[str, dict[str, Any]] = {}
_tasks: dict[str, asyncio.Task] = {}


def _prune() -> None:
    now = time.time()
    for jid, j in list(_jobs.items()):
        if j["status"] in ("done", "failed") and now - (j["finished_at"] or now) > JOB_TTL_SECONDS:
            _jobs.pop(jid, None)
            _tasks.pop(jid, None)


ToolFn = Callable[..., Awaitable[dict[str, Any]]]


async def _run(jid: str, fn: ToolFn, args: dict[str, Any]) -> None:
    job = _jobs[jid]
    job["status"] = "running"
    try:
        result = await fn(**args)
        failed = isinstance(result, dict) and bool(result.get("error"))
        job.update(status="failed" if failed else "done", result=result,
                   error=result.get("detail") if failed else None)
    except asyncio.CancelledError:
        job.update(status="failed", error="cancelled")
        raise
    except Exception as e:  # noqa: BLE001 — surfaced through get_job
        job.update(status="failed", error=f"{type(e).__name__}: {e}")
    finally:
        job["finished_at"] = time.time()
        job["seconds"] = round(job["finished_at"] - job["started_at"], 2)


async def start_job(kind: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
    kinds = _kinds()
    if kind not in kinds:
        return {"error": "bad_input", "detail": f"unknown job kind {kind!r}; "
                f"use one of {sorted(kinds)}"}
    _prune()
    running = [j for j in _jobs.values() if j["status"] in ("queued", "running")]
    if len(running) >= 2:
        return {"error": "busy", "detail": "2 jobs already running; check them with get_job"}
    if len(_jobs) >= MAX_JOBS:
        oldest = min((j for j in _jobs.values() if j["status"] in ("done", "failed")),
                     key=lambda j: j["started_at"], default=None)
        if oldest:
            _jobs.pop(oldest["id"], None)
    jid = uuid.uuid4().hex[:10]
    _jobs[jid] = {"id": jid, "kind": kind, "args": args or {}, "status": "queued",
                  "started_at": time.time(), "finished_at": None, "seconds": None,
                  "result": None, "error": None}
    _tasks[jid] = asyncio.get_running_loop().create_task(_run(jid, kinds[kind], args or {}))
    return {"job_id": jid, "status": "queued",
            "summary_tr": f"İş başlatıldı ({kind}). Durum için get_job(job_id='{jid}')."}


def get_job(job_id: str | None = None) -> dict[str, Any]:
    """One job (with result when finished) or, without an id, the job list."""
    _prune()
    if not job_id:
        return {"jobs": [{k: j[k] for k in ("id", "kind", "status", "seconds", "error")}
                         for j in _jobs.values()]}
    job = _jobs.get(job_id)
    if job is None:
        return {"error": "not_found", "detail": f"no job {job_id!r} (jobs expire after 1 h)"}
    out = {k: job[k] for k in ("id", "kind", "status", "seconds", "error")}
    if job["status"] == "running":
        out["elapsed"] = round(time.time() - job["started_at"], 1)
    if job["status"] in ("done", "failed"):
        out["result"] = job["result"]
    return out


__all__ = ["get_job", "start_job"]

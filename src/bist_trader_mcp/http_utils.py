"""Shared HTTP helpers used by data-source modules.

Centralises:
- a long-lived singleton httpx.AsyncClient with connection pooling
- async httpx client construction with timeout + exponential backoff retry
- a polite User-Agent string (some TR endpoints reject default httpx UA)
- a small structured error type

v0.3 improvements:
- Singleton AsyncClient with TCP/TLS connection reuse (major perf win for
  EVDS and Yahoo Finance which are called repeatedly against the same host)
- Proper exponential backoff with jitter on transient failures
- Configurable retry for different upstream resilience profiles
"""

from __future__ import annotations

import asyncio
import os
import random
from typing import Any
from urllib.parse import urlsplit

import httpx

DEFAULT_TIMEOUT = 30.0
DEFAULT_RETRIES = 3
DEFAULT_BACKOFF_BASE = 1.0
DEFAULT_BACKOFF_MAX = 10.0

USER_AGENT = (
    "bist-trader-mcp/0.3.0 (+https://github.com/Enesp4rl4k/bist-trader-mcp) "
    "research tool - respects robots.txt"
)


class SourceError(RuntimeError):
    """Generic upstream error for any TR public-data fetcher."""

    def __init__(self, source: str, detail: str) -> None:
        super().__init__(f"[{source}] {detail}")
        self.source = source
        self.detail = detail


# ---------------------------------------------------------------------------
# Singleton async client — connection pooling across all data modules
# ---------------------------------------------------------------------------
_default_headers = {"User-Agent": USER_AGENT, "Accept": "*/*"}

_shared_client: httpx.AsyncClient | None = None
_shared_client_loop: object | None = None


def _current_loop() -> object | None:
    try:
        return asyncio.get_running_loop()
    except RuntimeError:
        return None


def get_shared_client(
    *,
    timeout: float = DEFAULT_TIMEOUT,
    extra_headers: dict[str, str] | None = None,
) -> httpx.AsyncClient:
    """Return a module-level shared httpx.AsyncClient.

    The client reuses TCP/TLS connections across calls to the same host,
    avoiding the per-request DNS lookup + TLS handshake overhead that the
    old `async with httpx.AsyncClient(...) as c:` pattern imposed.

    Loop-safety: an httpx.AsyncClient is bound to the event loop it was created
    on. When the running loop changes (e.g. a fresh ``asyncio.run`` per MCP
    tool call, or a worker-thread loop), the cached client is rebuilt so we
    never hit "Event loop is closed".
    """
    global _shared_client, _shared_client_loop
    loop = _current_loop()
    if (
        _shared_client is None
        or _shared_client.is_closed
        or _shared_client_loop is not loop
    ):
        merged = dict(_default_headers)
        if extra_headers:
            merged.update(extra_headers)
        _shared_client_loop = loop
        _shared_client = httpx.AsyncClient(
            timeout=timeout,
            headers=merged,
            follow_redirects=True,
            # Keep connections alive for reuse
            limits=httpx.Limits(
                max_keepalive_connections=10,
                max_connections=20,
                keepalive_expiry=120,
            ),
        )
    return _shared_client


async def close_shared_client() -> None:
    """Shut down the shared client gracefully (call at server shutdown)."""
    global _shared_client
    if _shared_client is not None and not _shared_client.is_closed:
        await _shared_client.aclose()
        _shared_client = None


def _backoff_sleep(attempt: int, base: float = DEFAULT_BACKOFF_BASE) -> float:
    """Exponential backoff with full jitter: sleep ∈ [0, min(cap, base * 2^attempt)]."""
    cap = min(DEFAULT_BACKOFF_MAX, base * (2 ** attempt))
    return random.uniform(0, cap)  # noqa: S311


# ---------------------------------------------------------------------------
# Retry-aware fetch helpers
# ---------------------------------------------------------------------------

# HTTP status codes considered transient (safe to retry). Every other 4xx
# (401/403/404/422…) is permanent: retrying only burns time and can extend a
# WAF ban, so we fail fast.
_RETRYABLE_STATUS = {408, 425, 429, 500, 502, 503, 504}
_RETRY_AFTER_CAP = 30.0

# Per-host concurrency cap: asyncio.gather over 30 tickers must not open 30
# parallel connections to Yahoo/KAP (that is what triggers rate limits).
PER_HOST_LIMIT = max(1, int(os.environ.get("BIST_HTTP_PER_HOST", "4")))

_host_sems: dict[str, asyncio.Semaphore] = {}
_host_sems_loop: object | None = None
_inflight: dict[tuple[Any, ...], asyncio.Future[Any]] = {}

# Lightweight counters — exposed via get_network_stats().
STATS: dict[str, Any] = {
    "requests": 0,
    "retries": 0,
    "deduplicated": 0,
    "fail_fast_4xx": 0,
    "errors_by_source": {},
    "requests_by_host": {},
}


def _host_semaphore(url: str) -> asyncio.Semaphore:
    global _host_sems, _host_sems_loop, _inflight
    loop = _current_loop()
    if _host_sems_loop is not loop:  # semaphores are loop-bound
        _host_sems = {}
        _inflight = {}
        _host_sems_loop = loop
    host = urlsplit(url).netloc
    sem = _host_sems.get(host)
    if sem is None:
        sem = _host_sems[host] = asyncio.Semaphore(PER_HOST_LIMIT)
    return sem


def _retry_after(resp: httpx.Response) -> float | None:
    raw = resp.headers.get("Retry-After")
    if not raw:
        return None
    try:
        return min(_RETRY_AFTER_CAP, max(0.0, float(raw)))
    except ValueError:
        return None


def _bump(bucket: str, key: str) -> None:
    d = STATS[bucket]
    d[key] = d.get(key, 0) + 1


async def _request(
    url: str,
    *,
    kind: str,
    params: dict[str, Any] | None,
    method: str = "GET",
    json_body: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    retries: int,
    source: str,
) -> Any:
    last_err: Exception | None = None
    client = get_shared_client()
    sem = _host_semaphore(url)
    _bump("requests_by_host", urlsplit(url).netloc)

    for attempt in range(retries + 1):
        wait: float | None = None
        try:
            async with sem:
                STATS["requests"] += 1
                resp = await client.request(
                    method, url, params=params, json=json_body, headers=headers
                )
            if resp.status_code == 404:
                raise SourceError(source, f"404 not found: {url}")
            if resp.status_code in _RETRYABLE_STATUS:
                last_err = SourceError(source, f"HTTP {resp.status_code} (transient)")
                wait = _retry_after(resp)
            elif resp.status_code >= 400:
                STATS["fail_fast_4xx"] += 1
                raise SourceError(source, f"HTTP {resp.status_code} (not retried): {url}")
            else:
                if kind == "json":
                    return resp.json()
                if kind == "text":
                    return resp.text
                return resp.content
        except httpx.TransportError as e:
            last_err = e
        except ValueError as e:  # invalid JSON body
            last_err = e
        except SourceError:
            _bump("errors_by_source", source)
            raise
        if attempt >= retries:
            break
        STATS["retries"] += 1
        await asyncio.sleep(wait if wait is not None else _backoff_sleep(attempt))

    _bump("errors_by_source", source)
    raise SourceError(source, f"failed after {retries + 1} attempts: {last_err}")


async def _dedup(key: tuple[Any, ...], make: Any) -> Any:
    """Coalesce identical concurrent GETs into one upstream request."""
    fut = _inflight.get(key)
    if fut is not None:
        STATS["deduplicated"] += 1
        return await asyncio.shield(fut)
    fut = asyncio.get_running_loop().create_future()
    _inflight[key] = fut
    try:
        result = await make()
    except asyncio.CancelledError:
        fut.cancel()
        raise
    except BaseException as e:
        if not fut.done():
            fut.set_exception(e)
            fut.exception()  # mark retrieved when nobody else is waiting
        raise
    else:
        fut.set_result(result)
        return result
    finally:
        _inflight.pop(key, None)


def _key(kind: str, method: str, url: str, params: Any, headers: Any) -> tuple[Any, ...]:
    return (
        kind,
        method,
        url,
        tuple(sorted((params or {}).items())),
        tuple(sorted((headers or {}).items())),
    )


async def fetch_json(
    url: str,
    *,
    params: dict[str, Any] | None = None,
    method: str = "GET",
    json_body: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    retries: int = DEFAULT_RETRIES,
    source: str = "http",
) -> Any:
    """Fetch a JSON document with exponential backoff retry on transient errors."""
    _host_semaphore(url)  # make sure per-loop state is initialised

    def make() -> Any:
        return _request(url, kind="json", params=params, method=method,
                        json_body=json_body, headers=headers, retries=retries,
                        source=source)

    if method.upper() != "GET" or json_body is not None:
        return await make()
    return await _dedup(_key("json", "GET", url, params, headers), make)


async def fetch_text(
    url: str,
    *,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    retries: int = DEFAULT_RETRIES,
    source: str = "http",
) -> str:
    """Fetch a text document (HTML, CSV) with exponential backoff retry."""
    _host_semaphore(url)
    return await _dedup(
        _key("text", "GET", url, params, headers),
        lambda: _request(url, kind="text", params=params, headers=headers,
                         retries=retries, source=source),
    )


async def fetch_bytes(
    url: str,
    *,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    retries: int = DEFAULT_RETRIES,
    source: str = "http",
) -> bytes:
    """Fetch binary content (PDF, Excel) with exponential backoff retry."""
    _host_semaphore(url)
    return await _dedup(
        _key("bytes", "GET", url, params, headers),
        lambda: _request(url, kind="bytes", params=params, headers=headers,
                         retries=retries, source=source),
    )


def network_stats() -> dict[str, Any]:
    """Snapshot of HTTP counters since process start."""
    return {
        "per_host_limit": PER_HOST_LIMIT,
        **{k: (dict(v) if isinstance(v, dict) else v) for k, v in STATS.items()},
    }

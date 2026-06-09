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
import random
from typing import Any

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

# HTTP status codes considered transient (safe to retry)
_RETRYABLE_STATUS = {429, 500, 502, 503, 504}


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
    last_err: Exception | None = None
    client = get_shared_client()

    for attempt in range(retries + 1):
        try:
            resp = await client.request(
                method,
                url,
                params=params,
                json=json_body,
                headers=headers,
            )
            if resp.status_code == 404:
                raise SourceError(source, f"404 not found: {url}")
            if resp.status_code in _RETRYABLE_STATUS and attempt < retries:
                last_err = SourceError(
                    source,
                    f"HTTP {resp.status_code} (transient, will retry)",
                )
                await asyncio.sleep(_backoff_sleep(attempt))
                continue
            resp.raise_for_status()
            return resp.json()
        except (httpx.TransportError, httpx.HTTPStatusError, ValueError) as e:
            last_err = e
            if attempt >= retries:
                break
            await asyncio.sleep(_backoff_sleep(attempt))

    raise SourceError(source, f"failed after {retries + 1} attempts: {last_err}")


async def fetch_text(
    url: str,
    *,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    retries: int = DEFAULT_RETRIES,
    source: str = "http",
) -> str:
    """Fetch a text document (HTML, CSV) with exponential backoff retry."""
    last_err: Exception | None = None
    client = get_shared_client()

    for attempt in range(retries + 1):
        try:
            resp = await client.get(url, params=params, headers=headers)
            if resp.status_code == 404:
                raise SourceError(source, f"404 not found: {url}")
            if resp.status_code in _RETRYABLE_STATUS and attempt < retries:
                last_err = SourceError(
                    source,
                    f"HTTP {resp.status_code} (transient, will retry)",
                )
                await asyncio.sleep(_backoff_sleep(attempt))
                continue
            resp.raise_for_status()
            return resp.text
        except (httpx.TransportError, httpx.HTTPStatusError) as e:
            last_err = e
            if attempt >= retries:
                break
            await asyncio.sleep(_backoff_sleep(attempt))

    raise SourceError(source, f"failed after {retries + 1} attempts: {last_err}")


async def fetch_bytes(
    url: str,
    *,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    retries: int = DEFAULT_RETRIES,
    source: str = "http",
) -> bytes:
    """Fetch binary content (PDF, Excel) with exponential backoff retry."""
    last_err: Exception | None = None
    client = get_shared_client()

    for attempt in range(retries + 1):
        try:
            resp = await client.get(url, params=params, headers=headers)
            if resp.status_code == 404:
                raise SourceError(source, f"404 not found: {url}")
            if resp.status_code in _RETRYABLE_STATUS and attempt < retries:
                last_err = SourceError(
                    source,
                    f"HTTP {resp.status_code} (transient, will retry)",
                )
                await asyncio.sleep(_backoff_sleep(attempt))
                continue
            resp.raise_for_status()
            return resp.content
        except (httpx.TransportError, httpx.HTTPStatusError) as e:
            last_err = e
            if attempt >= retries:
                break
            await asyncio.sleep(_backoff_sleep(attempt))

    raise SourceError(source, f"failed after {retries + 1} attempts: {last_err}")

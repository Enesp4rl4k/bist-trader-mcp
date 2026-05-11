"""Shared HTTP helpers used by data-source modules.

Centralises:
- async httpx client construction with timeout + retry
- a polite User-Agent string (some TR endpoints reject default httpx UA)
- a small structured error type
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import Any

import httpx

DEFAULT_TIMEOUT = 30.0
DEFAULT_RETRIES = 2
DEFAULT_BACKOFF_SECONDS = 0.75

USER_AGENT = (
    "bist-trader-mcp/0.2.1 (+https://github.com/Enesp4rl4k/bist-trader-mcp) "
    "research tool - respects robots.txt"
)


class SourceError(RuntimeError):
    """Generic upstream error for any TR public-data fetcher."""

    def __init__(self, source: str, detail: str) -> None:
        super().__init__(f"[{source}] {detail}")
        self.source = source
        self.detail = detail


@asynccontextmanager
async def client(
    *,
    timeout: float = DEFAULT_TIMEOUT,
    headers: dict[str, str] | None = None,
) -> Any:
    """Create an async httpx client with sane defaults."""
    merged_headers = {"User-Agent": USER_AGENT, "Accept": "*/*"}
    if headers:
        merged_headers.update(headers)
    async with httpx.AsyncClient(timeout=timeout, headers=merged_headers) as c:
        yield c


async def fetch_json(
    url: str,
    *,
    params: dict[str, Any] | None = None,
    method: str = "GET",
    json_body: dict[str, Any] | None = None,
    retries: int = DEFAULT_RETRIES,
    source: str = "http",
) -> Any:
    """Fetch a JSON document with retry on transient errors."""
    last_err: Exception | None = None
    async with client() as c:
        for attempt in range(retries + 1):
            try:
                resp = await c.request(method, url, params=params, json=json_body)
                if resp.status_code == 404:
                    raise SourceError(source, f"404 not found: {url}")
                resp.raise_for_status()
                return resp.json()
            except (httpx.TransportError, httpx.HTTPStatusError, ValueError) as e:
                last_err = e
                if attempt >= retries:
                    break
                await asyncio.sleep(DEFAULT_BACKOFF_SECONDS * (attempt + 1))
    raise SourceError(source, f"failed after {retries + 1} attempts: {last_err}")


async def fetch_text(
    url: str,
    *,
    params: dict[str, Any] | None = None,
    retries: int = DEFAULT_RETRIES,
    source: str = "http",
) -> str:
    """Fetch a text document (HTML, CSV) with retry."""
    last_err: Exception | None = None
    async with client() as c:
        for attempt in range(retries + 1):
            try:
                resp = await c.get(url, params=params)
                if resp.status_code == 404:
                    raise SourceError(source, f"404 not found: {url}")
                resp.raise_for_status()
                return resp.text
            except (httpx.TransportError, httpx.HTTPStatusError) as e:
                last_err = e
                if attempt >= retries:
                    break
                await asyncio.sleep(DEFAULT_BACKOFF_SECONDS * (attempt + 1))
    raise SourceError(source, f"failed after {retries + 1} attempts: {last_err}")

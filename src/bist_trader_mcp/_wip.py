"""Helpers for modules whose upstream endpoint discovery is not yet complete.

Why this exists: KAP, VIOP, Takasbank, Hazine and MKK all publish data
their websites consume, but they actively block direct API access from
non-browser clients (WAF, custom error 666, timeouts). Doing this right
needs browser-automation (Playwright) or proper session/cookie handling,
which is a v0.3 task.

Rather than ship broken fetchers that mislead callers, the v0.2 modules
import this helper and surface a structured payload that:
    - tells the LLM exactly what's wrong,
    - links to the tracking issue / discovery plan,
    - keeps the same shape downstream tools expect (empty list / dict).

When the endpoint is discovered, the fetcher swaps the WIP call out for
the real HTTP call and the rest of the pipeline keeps working.
"""

from __future__ import annotations

from typing import Any

from .http_utils import SourceError

WIP_DOCS_URL = (
    "https://github.com/Enesp4rl4k/bist-trader-mcp/issues "
    "(endpoint-discovery label)"
)


def wip_error(source: str, note: str = "") -> SourceError:
    """Raise a uniform 'endpoint discovery pending' error.

    Tools wrap this into a `{"error": "endpoint_discovery_pending", ...}`
    payload so the LLM understands it's a known gap, not a runtime crash.
    """
    detail = (
        "endpoint discovery pending — upstream returns 4xx/HTML/timeout "
        "for direct API access; v0.3 will introduce browser-automated "
        f"fallback. See {WIP_DOCS_URL}."
    )
    if note:
        detail = f"{detail} ({note})"
    return SourceError(source, detail)


def wip_payload(source: str, note: str = "") -> dict[str, Any]:
    """Structured payload returned by tool wrappers when their data source
    is still in discovery. Same general shape as a successful response so
    downstream callers don't have to special-case empty results.
    """
    return {
        "error": "endpoint_discovery_pending",
        "source": source,
        "detail": (
            "Upstream public endpoint requires session/captcha/browser "
            "context that this MCP doesn't yet provide. Targeted for v0.3."
        ),
        "note": note,
        "tracking": WIP_DOCS_URL,
        "data": [],
    }

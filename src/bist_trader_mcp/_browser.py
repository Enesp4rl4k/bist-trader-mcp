"""Playwright-backed browser context for sites that block direct HTTP.

Several Turkish data sources (KAP, MKK, Takasbank, parts of BIST) return
HTML SPA shells and load real data via XHR that requires either:
  - session cookies set by the homepage,
  - browser-realistic headers (sec-fetch-*, accept-language: tr),
  - or origin/referer matching their own domain.

Direct httpx calls trip WAF rules and either 404, time out, or return a
custom 666 error page. The cleanest reliable workaround is a real headless
browser. We use Playwright Chromium.

This module exposes:
  - `BrowserCallError` — raised when navigation / API call fails
  - `playwright_available()` — quick boolean for graceful degradation
  - `call_json_xhr(url, body=None, page_url=None, ...)` — visit `page_url`
    so cookies + JS state load, then POST/GET `url` via the page's fetch()
    so the request inherits the same session.

The implementation lazy-imports Playwright so the package stays installable
without the `browser` extra. If Playwright is missing, callers receive a
`BrowserCallError("playwright_not_installed")`.
"""

from __future__ import annotations

import json
from typing import Any


class BrowserCallError(RuntimeError):
    """Wraps any Playwright / navigation / XHR failure."""


def playwright_available() -> bool:
    """True if `playwright` is importable; False otherwise."""
    try:
        import playwright  # noqa: F401
        return True
    except ImportError:
        return False


_DEFAULT_NAV_TIMEOUT_MS = 30_000
_DEFAULT_CALL_TIMEOUT_MS = 20_000


async def call_json_xhr(
    api_url: str,
    *,
    page_url: str,
    method: str = "POST",
    body: dict[str, Any] | None = None,
    accept_language: str = "tr,en;q=0.7",
    extra_headers: dict[str, str] | None = None,
    wait_after_nav_ms: int = 1500,
    nav_timeout_ms: int = _DEFAULT_NAV_TIMEOUT_MS,
    call_timeout_ms: int = _DEFAULT_CALL_TIMEOUT_MS,
) -> Any:
    """Visit `page_url` in a headless browser, then issue an in-page fetch()
    to `api_url` so the request inherits the session and origin.

    Returns the parsed JSON body. Raises `BrowserCallError` on any failure.

    Args:
        api_url: The XHR endpoint to call (e.g. KAP /api/disclosure/list/main).
        page_url: The page to visit first so cookies / JS state are set up
            (e.g. https://www.kap.org.tr/tr).
        method: HTTP method for the fetch.
        body: Optional JSON body for POST.
        accept_language: Accept-Language header value.
        extra_headers: Optional extra headers merged into the fetch.
        wait_after_nav_ms: ms to idle after the page reaches networkidle, to
            let any deferred state load.
        nav_timeout_ms / call_timeout_ms: timeouts in ms.
    """
    try:
        from playwright.async_api import async_playwright
    except ImportError as e:
        raise BrowserCallError(
            "playwright_not_installed — install with `pip install bist-trader-mcp[browser]` "
            "and then `python -m playwright install chromium`"
        ) from e

    headers = {
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": accept_language,
        "Content-Type": "application/json",
    }
    if extra_headers:
        headers.update(extra_headers)

    fetch_init: dict[str, Any] = {"method": method, "headers": headers}
    if body is not None:
        fetch_init["body"] = json.dumps(body, ensure_ascii=False)

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            try:
                ctx = await browser.new_context(
                    locale="tr-TR",
                    extra_http_headers={"Accept-Language": accept_language},
                )
                page = await ctx.new_page()
                await page.goto(page_url, wait_until="networkidle", timeout=nav_timeout_ms)
                if wait_after_nav_ms > 0:
                    await page.wait_for_timeout(wait_after_nav_ms)

                # Drive an in-page fetch — this inherits cookies + origin so
                # the WAF sees a normal same-origin XHR.
                js = """
                  async ({url, init}) => {
                    const r = await fetch(url, init);
                    const text = await r.text();
                    return { status: r.status, body: text };
                  }
                """
                result: dict[str, Any] = await page.evaluate(
                    js, {"url": api_url, "init": fetch_init}
                )
            finally:
                await browser.close()
    except BrowserCallError:
        raise
    except Exception as e:
        raise BrowserCallError(
            f"browser session failed: {type(e).__name__}: {e}"
        ) from e

    status = int(result.get("status", 0))
    body_text = str(result.get("body", ""))
    if status >= 400 or not body_text:
        raise BrowserCallError(
            f"upstream {status} for {api_url} — snippet: {body_text[:200]}"
        )
    try:
        return json.loads(body_text)
    except json.JSONDecodeError as e:
        raise BrowserCallError(
            f"non-JSON response from {api_url}: {e}; snippet: {body_text[:200]}"
        ) from e

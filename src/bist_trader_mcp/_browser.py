"""Playwright-backed browser context for sites that block direct HTTP.

Several Turkish data sources (KAP, MKK, Takasbank, parts of BIST) return
HTML SPA shells and load real data via XHR that requires either:
  - session cookies set by the homepage,
  - browser-realistic headers (sec-fetch-*, accept-language: tr),
  - or origin/referer matching their own domain.

Direct httpx calls trip WAF rules and either 404, time out, or return a
custom 666 error page. The cleanest reliable workaround is a real headless
browser. We use Playwright Chromium, with optional `playwright-stealth`
fingerprint patches for sites running F5 BIG-IP TSPD or similar bot
detection (Takasbank, parts of MKK).

This module exposes:
  - `BrowserCallError` — raised when navigation / API call fails
  - `playwright_available()` — quick boolean for graceful degradation
  - `call_json_xhr(url, body=None, page_url=None, ...)` — visit `page_url`
    so cookies + JS state load, then POST/GET `url` via the page's fetch()
    so the request inherits the same session. Best for SPA + JSON XHR
    backends like KAP.
  - `extract_page_data(page_url, extractor_js, ...)` — visit `page_url`
    with stealth enabled, optionally warm up via a previous page first,
    wait for an anchor element or hardcoded ms, then evaluate a JS
    extractor function over the rendered DOM. Best for pages that
    render visible numbers / tables via async JS (Takasbank dashboard,
    MKK report pages).
  - `stealth_supported()` — checks if `playwright-stealth` is importable
    for the harsher WAFs.

The implementation lazy-imports Playwright + stealth so the package stays
installable without the `browser` extra. If Playwright is missing, callers
receive a `BrowserCallError("playwright_not_installed")`.
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


def stealth_supported() -> bool:
    """True if `playwright-stealth` is importable (anti-fingerprint patches)."""
    try:
        import playwright_stealth  # noqa: F401
        return True
    except ImportError:
        return False


_DEFAULT_NAV_TIMEOUT_MS = 30_000
_DEFAULT_CALL_TIMEOUT_MS = 20_000
_DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
)


async def _make_playwright_ctx(use_stealth: bool):
    """Build a Playwright context manager that optionally wraps Stealth.

    Returns an async context that yields (browser, context, page) ready
    for navigation. Caller is responsible for awaiting __aenter__/__aexit__.
    """
    if use_stealth and stealth_supported():
        from playwright.async_api import async_playwright
        from playwright_stealth import Stealth
        return Stealth().use_async(async_playwright())
    else:
        from playwright.async_api import async_playwright
        return async_playwright()


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


async def extract_page_data(
    page_url: str,
    extractor_js: str,
    *,
    warmup_url: str | None = None,
    wait_for_selector: str | None = None,
    wait_for_text: str | None = None,
    wait_after_nav_ms: int = 4_000,
    use_stealth: bool = True,
    user_agent: str = _DEFAULT_USER_AGENT,
    locale: str = "tr-TR",
    nav_timeout_ms: int = _DEFAULT_NAV_TIMEOUT_MS,
    headless: bool = True,
) -> Any:
    """Visit `page_url` with stealth, wait for content, run a JS extractor.

    Designed for sites whose data is rendered visually via async JS after
    navigation (Takasbank dashboard, MKK reports). Optionally warm up the
    session by visiting `warmup_url` first — many F5 WAF setups assign a
    trusted TSPD cookie on the homepage and then trust subsequent paths.

    Args:
        page_url: The page that renders the data.
        extractor_js: Body of a JS function that returns the data. It is
            wrapped in `() => { <extractor_js> }` so write a final
            `return …` expression.
        warmup_url: Optional homepage / parent page to load first.
        wait_for_selector: CSS selector to wait for before extracting.
        wait_for_text: Text substring; we poll innerText until it appears.
        wait_after_nav_ms: Hard wait after navigation completes (fallback
            for sites without a stable selector).
        use_stealth: If True and `playwright-stealth` is installed, apply
            anti-fingerprint patches. Required for F5 BIG-IP TSPD sites.
        user_agent: UA string to send. Default mimics Chrome on Windows.
        locale: Browser locale.
        nav_timeout_ms: Per-navigation timeout.
        headless: Defaults True; set False to debug bot challenges.

    Returns the value produced by `extractor_js`. Raises
    `BrowserCallError` on any failure (WAF rejection, timeout, etc.).
    """
    if not playwright_available():
        raise BrowserCallError(
            "playwright_not_installed — install with "
            "`pip install bist-trader-mcp[browser]`"
        )

    pw_ctx = await _make_playwright_ctx(use_stealth=use_stealth)
    try:
        async with pw_ctx as p:
            browser = await p.chromium.launch(headless=headless)
            try:
                ctx = await browser.new_context(
                    user_agent=user_agent,
                    locale=locale,
                    viewport={"width": 1920, "height": 1080},
                )
                page = await ctx.new_page()

                # Warm-up: visit homepage first so WAF assigns a session.
                if warmup_url:
                    await page.goto(
                        warmup_url, wait_until="domcontentloaded",
                        timeout=nav_timeout_ms,
                    )
                    await page.wait_for_timeout(1_500)

                await page.goto(
                    page_url, wait_until="domcontentloaded",
                    timeout=nav_timeout_ms,
                )

                # Detect WAF rejection early.
                title = await page.title()
                if "Request Rejected" in title or "Access Denied" in title:
                    raise BrowserCallError(
                        f"WAF rejected request to {page_url} "
                        "(likely IP rate limit or bot detection). "
                        "Retry after cooldown or with a different IP."
                    )

                if wait_for_selector:
                    await page.wait_for_selector(
                        wait_for_selector, timeout=nav_timeout_ms,
                    )
                elif wait_for_text:
                    await page.wait_for_function(
                        f"() => document.body && document.body.innerText.includes({json.dumps(wait_for_text)})",
                        timeout=nav_timeout_ms,
                    )
                elif wait_after_nav_ms > 0:
                    await page.wait_for_timeout(wait_after_nav_ms)

                wrapped = "(async () => { " + extractor_js + " })()"
                result = await page.evaluate(wrapped)
            finally:
                await browser.close()
    except BrowserCallError:
        raise
    except Exception as e:
        raise BrowserCallError(
            f"page extraction failed for {page_url}: "
            f"{type(e).__name__}: {e}"
        ) from e
    return result

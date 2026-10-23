"""Network layer: fail-fast 4xx, Retry-After, request coalescing, per-host cap."""

import asyncio

import httpx
import pytest

from bist_trader_mcp import http_utils as hu


def _install(handler):
    """Point the shared client at a mock transport for the running loop."""
    hu._shared_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    hu._shared_client_loop = asyncio.get_running_loop()


def test_403_is_not_retried():
    calls = []

    async def main():
        def handler(req):
            calls.append(req)
            return httpx.Response(403)

        _install(handler)
        with pytest.raises(hu.SourceError, match="not retried"):
            await hu.fetch_json("https://x.test/a", source="t")

    asyncio.run(main())
    assert len(calls) == 1


def test_503_retries_and_honours_retry_after():
    calls = []

    async def main():
        def handler(req):
            calls.append(req)
            if len(calls) < 3:
                return httpx.Response(503, headers={"Retry-After": "0"})
            return httpx.Response(200, json={"ok": True})

        _install(handler)
        return await hu.fetch_json("https://x.test/b", source="t")

    assert asyncio.run(main()) == {"ok": True}
    assert len(calls) == 3


def test_identical_concurrent_gets_are_coalesced():
    calls = []

    async def main():
        async def handler(req):
            calls.append(req)
            await asyncio.sleep(0.05)
            return httpx.Response(200, json={"n": 1})

        _install(handler)
        return await asyncio.gather(
            *[hu.fetch_json("https://x.test/c", params={"a": 1}) for _ in range(5)],
            hu.fetch_json("https://x.test/c", params={"a": 2}),
        )

    out = asyncio.run(main())
    assert all(o == {"n": 1} for o in out)
    assert len(calls) == 2  # a=1 once, a=2 once


def test_per_host_concurrency_cap(monkeypatch):
    monkeypatch.setattr(hu, "PER_HOST_LIMIT", 2)
    live = {"now": 0, "peak": 0}

    async def main():
        hu._host_sems_loop = None  # force fresh semaphores with the new limit

        async def handler(req):
            live["now"] += 1
            live["peak"] = max(live["peak"], live["now"])
            await asyncio.sleep(0.02)
            live["now"] -= 1
            return httpx.Response(200, text="ok")

        _install(handler)
        await asyncio.gather(*[hu.fetch_text(f"https://y.test/{i}") for i in range(8)])

    asyncio.run(main())
    assert live["peak"] <= 2

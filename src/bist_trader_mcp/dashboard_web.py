"""Local web mode for the dashboard — for hosts without inline MCP Apps (Codex,
terminals) or when you simply want it in a browser tab.

Serves the same ``ui/dashboard.html`` on ``http://127.0.0.1:PORT/?t=TOKEN``;
the page detects the token and talks to ``POST /api/call`` instead of
postMessage. Safety:

- binds to 127.0.0.1 only; ``Host`` header must be localhost/127.0.0.1
  (blocks DNS-rebinding pages from reaching the API)
- random per-process token required on every request
- only the dashboard's own tools can be called (allowlist)

Inside the MCP server it starts lazily on the first ``open_dashboard`` call and
runs in a daemon thread; tool calls are executed on the server's event loop.
Standalone: ``bist-trader-dashboard`` (own loop, opens the browser).
"""

from __future__ import annotations

import asyncio
import json
import os
import secrets
import threading
from collections.abc import Awaitable, Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

ALLOWED_TOOLS = {"dashboard_snapshot", "dashboard_action"}
HTML_PATH = Path(__file__).parent / "ui" / "dashboard.html"

Dispatch = Callable[[str, dict[str, Any]], Awaitable[Any]]

_server: ThreadingHTTPServer | None = None
_url: str | None = None
_lock = threading.Lock()


def dashboard_html() -> str:
    return HTML_PATH.read_text(encoding="utf-8")


def _make_handler(
    token: str, port_ref: list[int], loop: asyncio.AbstractEventLoop, dispatch: Dispatch
) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "bist-trader-dashboard"

        def log_message(self, *args: Any) -> None:  # keep stdio (MCP) clean
            return

        def _host_ok(self) -> bool:
            host = (self.headers.get("Host") or "").lower()
            return host in {f"127.0.0.1:{port_ref[0]}", f"localhost:{port_ref[0]}"}

        def _send(self, code: int, body: bytes, ctype: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
                "connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'",
            )
            self.end_headers()
            self.wfile.write(body)

        def _json(self, code: int, obj: Any) -> None:
            self._send(code, json.dumps(obj, ensure_ascii=False, default=str).encode(),
                       "application/json; charset=utf-8")

        def do_GET(self) -> None:  # noqa: N802
            parts = urlsplit(self.path)
            q = parse_qs(parts.query)
            if not self._host_ok() or parts.path != "/" or \
                    not secrets.compare_digest((q.get("t") or [""])[0], token):
                return self._send(403, b"forbidden", "text/plain")
            self._send(200, dashboard_html().encode("utf-8"), "text/html; charset=utf-8")

        def do_POST(self) -> None:  # noqa: N802
            if not self._host_ok() or urlsplit(self.path).path != "/api/call" or \
                    not secrets.compare_digest(self.headers.get("X-Dashboard-Token") or "", token):
                return self._json(403, {"error": "forbidden"})
            try:
                n = int(self.headers.get("Content-Length") or 0)
                if n > 1_000_000:
                    return self._json(413, {"error": "too_large"})
                req = json.loads(self.rfile.read(n) or b"{}")
                name = str(req.get("name") or "")
                args = req.get("arguments") or {}
            except (ValueError, TypeError):
                return self._json(400, {"error": "bad_request"})
            if name not in ALLOWED_TOOLS or not isinstance(args, dict):
                return self._json(403, {"error": "tool_not_allowed", "detail": name})
            try:
                fut = asyncio.run_coroutine_threadsafe(dispatch(name, args), loop)
                result = fut.result(timeout=120)
            except Exception as e:  # noqa: BLE001
                return self._json(500, {"error": "tool_failed",
                                        "detail": f"{type(e).__name__}: {e}"})
            self._json(200, {"structuredContent": result})

    return Handler


def start(
    loop: asyncio.AbstractEventLoop,
    dispatch: Dispatch,
    *,
    port: int | None = None,
) -> str:
    """Start (once) and return the tokenised local URL."""
    global _server, _url
    with _lock:
        if _server is not None and _url:
            return _url
        token = secrets.token_urlsafe(18)
        want = int(port if port is not None else os.environ.get("BIST_DASHBOARD_PORT", "8765"))
        port_ref = [0]
        handler = _make_handler(token, port_ref, loop, dispatch)
        try:
            srv = ThreadingHTTPServer(("127.0.0.1", want), handler)
        except OSError:
            srv = ThreadingHTTPServer(("127.0.0.1", 0), handler)  # port busy → any free
        srv.daemon_threads = True
        port_ref[0] = srv.server_address[1]
        threading.Thread(target=srv.serve_forever, name="bist-dashboard", daemon=True).start()
        _server = srv
        _url = f"http://127.0.0.1:{port_ref[0]}/?t={token}"
        return _url


def stop() -> None:
    global _server, _url
    with _lock:
        if _server is not None:
            _server.shutdown()
            _server.server_close()
        _server, _url = None, None


def main(argv: list[str] | None = None) -> None:
    """``bist-trader-dashboard``: run the panel in a browser without an AI host."""
    import argparse
    import webbrowser

    from .tools import dashboard_dispatch

    ap = argparse.ArgumentParser(description="BIST Trader live dashboard (browser mode)")
    ap.add_argument("--port", type=int, default=None)
    ap.add_argument("--no-browser", action="store_true")
    args = ap.parse_args(argv)

    loop = asyncio.new_event_loop()
    threading.Thread(target=loop.run_forever, daemon=True).start()
    url = start(loop, dashboard_dispatch, port=args.port)
    print(f"Panel: {url}  (Ctrl+C ile kapat)")
    if not args.no_browser:
        webbrowser.open(url)
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        stop()


if __name__ == "__main__":
    main()


__all__ = ["ALLOWED_TOOLS", "dashboard_html", "main", "start", "stop"]

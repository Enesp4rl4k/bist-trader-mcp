"""Browser check of the live dashboard with synthetic data (no network, no TV).

1. Web mode   — local server + real page; click a symbol, change timeframe,
                run a panel action.
2. MCP host   — a fake host page embeds the view in an iframe and speaks the
                MCP Apps protocol (ui/initialize, tool-result, tools/call,
                ui/update-model-context, size-changed).

Usage: python scripts/e2e_dashboard.py [out_dir]   (needs playwright + chromium)
"""

from __future__ import annotations

import asyncio
import glob
import json
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bist_trader_mcp import dashboard_data as dd  # noqa: E402
from bist_trader_mcp import dashboard_web  # noqa: E402
from tests.test_dashboard import Fakes  # noqa: E402

OUT = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
FAKES = Fakes()
CALLS: list[tuple[str, dict]] = []


async def dispatch(name: str, args: dict) -> dict:
    CALLS.append((name, args))
    if name == "dashboard_snapshot":
        return await dd.build_snapshot(args.get("state"), quotes=FAKES.quotes,
                                       bars=FAKES.bars, news=FAKES.news, risk=FAKES.risk)
    return {"approved": True, "summary_tr": "ONAY — 200 adet, risk %1.0 (1000).",
            "checks": [{"ok": True, "severity": "block", "detail": "stop doğru tarafta"},
                       {"ok": False, "severity": "warn", "detail": "yaklaşan PPK"}]}


def js(obj: object) -> str:
    """JSON safe to inline inside a <script> block."""
    return json.dumps(obj).replace("</", "<\\/")


def chromium() -> str | None:
    hits = glob.glob("/opt/pw-browsers/chromium-*/chrome-linux*/chrome")
    return hits[0] if hits else None


def main() -> None:
    from playwright.sync_api import sync_playwright

    loop = asyncio.new_event_loop()
    threading.Thread(target=loop.run_forever, daemon=True).start()
    url = dashboard_web.start(loop, dispatch, port=0)
    errors: list[str] = []
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=chromium())

        # ---- 1. web mode
        page = b.new_page(viewport={"width": 1400, "height": 1000})
        page.on("pageerror", lambda e: errors.append(f"web: {e}"))
        page.on("console", lambda m: m.type == "error" and errors.append(f"web console: {m.text}"))
        page.goto(url)
        page.wait_for_selector("#wl tr.row", timeout=15000)
        assert page.locator("#ticker .chip").count() >= 10
        page.locator('#wl tr.row[data-sym="ASELS"]').click()
        # (page CSP has no 'unsafe-eval', so wait with locators, not JS predicates)
        page.locator("#chartTitle", has_text="ASELS").wait_for()
        page.locator('#tfBar button[data-tf="240"]').click()
        page.locator("#chartTitle", has_text="240").wait_for()
        page.wait_for_timeout(500)
        if page.locator("#analysis .plan").count():
            page.locator('[data-act="risk_check"]').click()
            page.wait_for_selector("#actResult b")
        page.locator('[data-nf="wl"]').click()
        page.screenshot(path=str(OUT / "dashboard_web.png"), full_page=True)
        states = [a.get("state", {}) for n, a in CALLS if n == "dashboard_snapshot"]
        assert any(s.get("symbol") == "ASELS" and s.get("timeframe") == "240" for s in states)

        # ---- 2. fake MCP Apps host
        snap = asyncio.run_coroutine_threadsafe(
            dispatch("dashboard_snapshot", {"state": {"symbol": "GARAN"}}), loop).result()
        html = dashboard_web.dashboard_html()
        host = f"""<!doctype html><html><body style="margin:0;background:#fff">
<iframe id="v" style="width:1300px;height:1100px;border:0"></iframe>
<iframe id="evil" style="display:none" srcdoc="<p>other frame</p>"></iframe>
<script>
const SNAP = {js(snap)};
window.log = [];
const v = document.getElementById('v');
window.addEventListener('message', (e) => {{
  const m = e.data; if (!m || m.jsonrpc !== '2.0') return;
  window.log.push(m.method || ('response ' + m.id));
  const reply = (result) => v.contentWindow.postMessage({{jsonrpc:'2.0', id:m.id, result}}, '*');
  if (m.method === 'ui/initialize') reply({{protocolVersion:'2026-01-26', hostInfo:{{name:'fake',version:'1'}},
      hostCapabilities:{{}}, hostContext:{{theme:'light', availableDisplayModes:['inline','fullscreen']}}}});
  else if (m.method === 'ui/notifications/initialized') {{
      v.contentWindow.postMessage({{jsonrpc:'2.0', method:'ui/notifications/tool-input', params:{{arguments:{{symbol:'GARAN'}}}}}}, '*');
      v.contentWindow.postMessage({{jsonrpc:'2.0', method:'ui/notifications/tool-result', params:{{content:[{{type:'text',text:'ok'}}], structuredContent:SNAP}}}}, '*');
  }}
  else if (m.method === 'tools/call') reply({{content:[{{type:'text',text:'ok'}}], structuredContent: m.params.name === 'dashboard_snapshot' ? SNAP : {{summary_tr:'ok'}}}});
  else if (m.id !== undefined && m.method) reply({{}});
}});
v.srcdoc = {js(html)};
</script></body></html>"""
        hp = b.new_page(viewport={"width": 1320, "height": 1150})
        hp.on("pageerror", lambda e: errors.append(f"host: {e}"))
        hp.set_content(host)
        frame = hp.frame_locator("#v")
        frame.locator("#wl tr.row").first.wait_for(timeout=15000)
        hp.wait_for_function("window.log.includes('ui/update-model-context')", timeout=5000)
        log = hp.evaluate("window.log")
        for need in ("ui/initialize", "ui/notifications/initialized",
                     "ui/notifications/size-changed", "ui/update-model-context"):
            assert need in log, (need, log)
        assert frame.locator("html[data-theme=light]").count() == 1
        assert frame.locator("#fullBtn:not(.hidden)").count() == 1
        frame.locator('[data-act="ask"]').click()
        hp.wait_for_function("window.log.includes('ui/message')", timeout=5000)
        frame.locator("#refresh").click()
        hp.wait_for_function("window.log.includes('tools/call')", timeout=5000)
        hp.screenshot(path=str(OUT / "dashboard_host.png"))

        # Security: feed links may only open as http(s).
        view = hp.query_selector("#v").content_frame()
        got = view.evaluate("() => [safeUrl('javascript:alert(1)'), safeUrl('data:text/html,x'),"
                            " safeUrl('https://kap.org.tr/a'), safeUrl('')]")
        assert got == [None, None, "https://kap.org.tr/a", None], got

        # Security: a message from any window other than the host must be ignored.
        fake = ("{jsonrpc:'2.0', method:'ui/notifications/tool-result', params:{structuredContent:"
                "{generated_at:'2026-01-01T00:00:00Z', state:{}, sections:{chart:{ok:false,"
                "error:'INJECTED'}}}}}")
        evil = hp.query_selector("#evil").content_frame()
        assert evil is not None and evil != hp.main_frame
        evil.evaluate(f"() => parent.frames[0].postMessage({fake}, '*')")
        hp.wait_for_timeout(400)
        assert frame.locator("#analysis", has_text="INJECTED").count() == 0, "spoofed message accepted"
        # control: the same message from the real host IS rendered (the check above is live)
        hp.evaluate(f"() => document.getElementById('v').contentWindow.postMessage({fake}, '*')")
        frame.locator("#analysis", has_text="INJECTED").wait_for(timeout=3000)
        b.close()
    dashboard_web.stop()
    if errors:
        raise SystemExit("JS errors:\n" + "\n".join(errors))
    print("OK — web mode and MCP host mode passed;", len(CALLS), "tool calls")


if __name__ == "__main__":
    main()

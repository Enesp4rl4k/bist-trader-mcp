import asyncio
from playwright.async_api import async_playwright
import os

html_content = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<style>
    body {
        background-color: #1e1e1e;
        color: #d4d4d4;
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
        padding: 40px;
        display: flex;
        justify-content: center;
        align-items: center;
        height: 100vh;
        margin: 0;
    }
    .chat-bubble {
        background-color: #252526;
        border: 1px solid #3c3c3c;
        border-radius: 8px;
        padding: 24px;
        width: 650px;
        box-shadow: 0 4px 12px rgba(0,0,0,0.5);
    }
    .header {
        font-size: 1.4em;
        font-weight: 600;
        color: #4daafc;
        margin-bottom: 20px;
        display: flex;
        align-items: center;
        border-bottom: 1px solid #3c3c3c;
        padding-bottom: 12px;
    }
    .section-title {
        color: #ce9178;
        font-weight: 600;
        margin-top: 16px;
        margin-bottom: 12px;
    }
    .list-item {
        margin-left: 16px;
        margin-bottom: 8px;
        line-height: 1.5;
    }
    .score {
        color: #b5cea8;
        font-weight: bold;
        margin-top: 12px;
        margin-bottom: 24px;
    }
    .alert {
        background-color: #3e2021;
        border-left: 4px solid #f48771;
        padding: 16px;
        margin-top: 24px;
        border-radius: 4px;
    }
    .alert-title {
        color: #f48771;
        font-weight: bold;
        margin-bottom: 8px;
    }
    .badge {
        background-color: #1b4d3e;
        color: #4CAF50;
        padding: 2px 6px;
        border-radius: 4px;
        font-size: 0.85em;
        font-weight: bold;
        margin-right: 6px;
    }
    .badge-mcp {
        background-color: #4d2b18;
        color: #f48771;
        padding: 2px 6px;
        border-radius: 4px;
        font-size: 0.85em;
        font-weight: bold;
        margin-right: 6px;
    }
    .metric-row {
        display: flex;
        justify-content: space-between;
        margin-left: 16px;
        margin-right: 32px;
        margin-bottom: 6px;
        font-family: 'Consolas', monospace;
        font-size: 0.95em;
        color: #9cdcfe;
    }
    .metric-val {
        color: #ce9178;
    }
    .metric-val-bad {
        color: #f48771;
    }
</style>
</head>
<body>
    <div class="chat-bubble">
        <div class="header">⚡ bist-trader-mcp: Fusion Report (BIST:ASELS)</div>
        
        <div class="section-title">[FINANCIALS & VALUATION (borsa-mcp)]</div>
        <div class="metric-row"><span>P/B (PD/DD)</span><span class="metric-val">6.0x</span></div>
        <div class="metric-row"><span>EV/EBITDA (FD/FAVÖK)</span><span class="metric-val">31.5x</span></div>
        <div class="metric-row"><span>EV/Sales</span><span class="metric-val">8.56x</span></div>
        <div class="metric-row"><span>Owner Earnings</span><span class="metric-val-bad">-6,124.69M TL (Negative)</span></div>
        <div class="metric-row"><span>Buffett Analysis Score</span><span class="metric-val-bad">AVOID</span></div>

        <div class="section-title">[FUNDAMENTAL & MACRO CONTEXT]</div>
        <div class="list-item"><span class="badge-mcp">borsa-mcp</span><b>Warning:</b> "Şirket sürdürülebilir nakit akışı üretmiyor" (Company does not generate sustainable cash flow). Quality of earnings is deeply negative despite high net income.</div>
        <div class="list-item"><span class="badge">KAP</span><b>Contract Flow:</b> Huge recent contracts mask the underlying cash collection issues.</div>
        <div class="score" style="color: #f48771;">=> Fundamental Score: 32/100 (Negative Bias)</div>

        <div class="section-title">[TECHNICAL & FUSION GATE]</div>
        <div class="list-item">• <b>PA Structure:</b> Daily trend is Bullish, but 4H structure shows a bearish shift (Conflict).</div>
        <div class="list-item">• <b>Elliott Wave:</b> Primary wave (4) correction is in progress.</div>
        <div class="score">=> Technical Score: 45/100</div>

        <div class="alert">
            <div class="alert-title">🚨 FUSION DECISION: TRADE_BLOCKED</div>
            <div style="line-height: 1.5">Trade strictly rejected. The 'borsa-mcp' plugin flagged negative owner earnings (-6.12B TL) and gave a Buffett Score of AVOID. Combined with a Multi-Timeframe Structural Conflict on the technical side, the system blocks any Long positioning to protect capital. Wait for cash flow normalization and Elliott Wave (5) alignment.</div>
        </div>
    </div>
</body>
</html>
"""

async def capture():
    os.makedirs("docs/images", exist_ok=True)
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(viewport={"width": 850, "height": 950})
        await page.set_content(html_content)
        await page.locator(".chat-bubble").screenshot(path="docs/images/linkedin-fusion-report.png", omit_background=True)
        await browser.close()
        print("Screenshot saved to docs/images/linkedin-fusion-report.png")

if __name__ == "__main__":
    asyncio.run(capture())

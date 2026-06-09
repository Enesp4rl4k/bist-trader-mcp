# Screenshots

| File | Market | Symbol | Shows |
|------|--------|--------|--------|
| [linkedin-crypto-btc.png](linkedin-crypto-btc.png) | Crypto | BINANCE:BTCUSDT | **PA** 1S+1R · Elliott (son dalgalar) · Short entry direnç retest |
| [linkedin-bist-thyao.png](linkedin-bist-thyao.png) | BIST | THYAO | Aynı pipeline — position yalnızca MTF `a`/`a_plus` |
| [linkedin-bist-xu030.png](linkedin-bist-xu030.png) | BIST | XU030 | Endeks demo — clean overlay |

Regenerate (TradingView CDP on `:9222`):

```powershell
C:\Users\parlak\Downloads\tradingview-mcp\scripts\launch_tv_debug.bat
cd C:\Users\parlak\Downloads\tr-fixedincome-mcp
$env:TRADINGVIEW_MCP_PATH = "C:\Users\parlak\Downloads\tradingview-mcp"
.venv\Scripts\python.exe scripts\capture_linkedin_screenshots.py
```

Before capture: remove old **“PA Trade”** Pine indicator from the chart (duplicate overlay).

# Quickstart — BIST Trader MCP

## 1. Get a free TCMB EVDS API key

Register at <https://evds3.tcmb.gov.tr/> (new portal — the legacy
`evds2.tcmb.gov.tr` host now redirects there). From your profile copy the
API key value (Anahtarınız).

> **Note (post 2024-04-05 breaking change):** The key is sent in the
> HTTP `key` header, not as a URL parameter. This client already does
> that. If you're hand-rolling requests against the new endpoint, set
> `headers={"key": api_key}`.

## 2. Install

```powershell
git clone https://github.com/Enesp4rl4k/bist-trader-mcp.git
cd bist-trader-mcp
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
```

## 3. Smoke test (no MCP client needed)

```powershell
$env:TCMB_EVDS_API_KEY = "your-key"
$env:PYTHONIOENCODING = "utf-8"
python scripts\smoke_test.py
```

Expected output:
```
2 live  /  5 WIP-or-skipped  /  0 unexpected-fail
  [OK ] yahoo_bist_eod
  [WIP] kap / viop / takasbank / hazine / mkk
  [OK ] evds
```

## 4. Run tests

```powershell
pytest -q
```

270+ offline tests (bond/options math, PA, fusion, market assistant mocks). CI runs on push via GitHub Actions.

## 5. Claude Desktop wiring

Edit `%APPDATA%\Claude\claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "bist-trader": {
      "command": "C:\\path\\to\\bist-trader-mcp\\.venv\\Scripts\\python.exe",
      "args": ["-m", "bist_trader_mcp"],
      "env": {
        "TCMB_EVDS_API_KEY": "your-key"
      }
    }
  }
}
```

Restart Claude Desktop. Ask:

> TCMB politika faizi, TLREF gecelik ve son TÜFE yıllık değişimini al, sonra `tr_macro_backdrop` Pine recipe'ini bu verilerle render et.

Claude should:
1. Call `render_pine_recipe(name="tr_macro_backdrop", auto_fetch=true)`
2. Receive Pine v6 source with live numbers embedded
3. Either hand it to [`tradesdontlie/tradingview-mcp`](https://github.com/tradesdontlie/tradingview-mcp) for direct injection into your TradingView Desktop, or quote it back for manual paste.

## 6. Companion — TradingView control

For full TR-data → TradingView pipeline, also install
[`tradesdontlie/tradingview-mcp`](https://github.com/tradesdontlie/tradingview-mcp).
Two MCPs combined: BIST Trader fetches/computes TR data → tradesdontlie
controls your TradingView Desktop via Chrome DevTools Protocol.

## Known status (v0.1.0)

**Live:**
- TCMB EVDS (policy rate, TLREF, BIST overnight repo, CPI YoY, FX)
- Yahoo Finance (BIST EOD OHLCV)
- Bond math (YTM, duration, convexity)
- Black-Scholes (greeks + IV solver)
- Cost-of-carry basis fair value
- Pine v6 recipes (`tr_macro_backdrop`, `tr_basis_monitor`)

**Endpoint discovery pending (v0.3):**
- KAP disclosures
- VIOP daily settlement + term structure
- Takasbank margin parameters + margin-call alerts
- Hazine DİBS auction calendar
- MKK foreign ownership
- DİBS yield curve (needs tenor bucketing over 4046 ISINs)

Each WIP tool returns a structured `{"error": "endpoint_discovery_pending", ...}` payload so the LLM understands the gap and doesn't hallucinate.

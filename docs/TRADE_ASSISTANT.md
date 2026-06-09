# Trade Assistant — Chat + TradingView

**Sürüm:** v0.4.0 · **Tek giriş:** `run_market_assistant`

Detaylı analiz kuralları: [ANALYSIS_PIPELINE.md](ANALYSIS_PIPELINE.md) · Performans: [PERFORMANCE_AND_CONSISTENCY.md](PERFORMANCE_AND_CONSISTENCY.md)

## Önkoşul

1. TradingView Desktop — CDP port `9222` (`scripts/launch_tv_debug.bat` veya `tradingview-mcp`)
2. Cursor MCP: `bist-trader` + `TRADINGVIEW_MCP_PATH`
3. (Opsiyonel) `TCMB_EVDS_API_KEY` — makro overlay

## Tek komut

```text
run_market_assistant(symbol="ASELS")
run_market_assistant(symbol="BINANCE:BTCUSDT")
run_scenario_assistant(symbol="THYAO")   # alias — aynı akış
```

## Çıktı alanları (LLM için)

| Alan | Kullanım |
|------|----------|
| `chat_report.sections` | Yapılandırılmış bölümler (özet, teknik, temel, fusion, işlem) |
| `chat_report.report_tr` | Kullanıcıya okunacak tam Türkçe metin |
| `chat_report.trade_allowed` | **Nihai** işlem izni (fusion sonrası) |
| `fusion` | `fusion_score`, `warnings`, `trade_allowed`, `summary_tr` |
| `market_context.technical` | PA, EW, `confidence`, `trade_candidate` |
| `fundamental_enrich` | Canlı KAP / fiyat / funding / sektör / VIOP |
| `data_quality` | `ok` / `thin` / `insufficient` |
| `symbol_check` | TV sembol eşleşmesi |
| `plan` | Onaylıysa entry, stop, TP, boyut |
| `chart` | TV çizim sonucu (PA, EW, pozisyon) |

### Chat prompt (kopyala-yapıştır)

```text
run_market_assistant(symbol="THYAO") sonucunda:
1) chat_report.sections ve fusion alanlarını kullan
2) ai_presentation_rules_tr kurallarına uy
3) Sayı uydurma; trade_allowed false ise nedenini fusion.warnings ile açıkla
4) remaining_mcp_tools varsa yalnızca eksik veri için öner
```

## Karar akışı (kısa)

```text
Veri insufficient?     → NO TRADE (analiz yok)
Teknik trade_candidate? → Hayır → NO TRADE
Plan approved?          → Hayır → NO TRADE
fusion.trade_allowed?   → Hayır → NO TRADE (grafikte pozisyon yok)
Evet                    → chat özet + isteğe bağlı TV position kutusu
```

Teknik onaylı ama fusion blok örneği: aşırı pozitif funding + long → `fusion_crowded_funding`.

## Parametreler

| Parametre | Varsayılan | Etki |
|-----------|------------|------|
| `fetch_fundamentals` | `true` | KAP, funding, sektör, makro |
| `draw_on_chart` | `true` | TV çizimi |
| `draw_when_no_trade` | `true` | İşlem yokken PA/EW yine çizilir |
| `draw_on_chart=false` | — | Sadece chat (~10 sn kazanç) |
| `fetch_fundamentals=false` | — | Sadece teknik + checklist |
| `ltf_timeframe` / `htf_timeframe` | profil | `get_market_profile` ile gör |

## TV kapalıysa

```text
get_bist_eod_ohlcv(ticker="THYAO", period="6mo")
analyze_market_context(symbol="THYAO", htf_closes=..., ltf_closes=..., ...)
enrich_fundamental_snapshot(symbol="THYAO")   # ayrı
```

Fusion için `fuse_fundamental_technical(technical=..., trade_result=..., fund_enrich=...)` manuel birleştirilir.

## MCP prompt

Cursor / Claude: prompt adı **`trade-assistant`** veya **`price-action-trade-design`**.

## İlgili araçlar (gelişmiş)

| Araç | Ne zaman |
|------|----------|
| `get_market_profile` | TF ve eşik önizleme |
| `get_trade_playbook_rules` | Risk kuralları |
| `analyze_market_context` | OHLCV elinde, TV yok |
| `analyze_chart_scenarios` | Sadece teknik paket |
| `scan_ta_fundamental_watchlist` | Çoklu sembol tarama |

*Yatırım tavsiyesi değildir.*

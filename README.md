# BIST Trader MCP

[![pytest](https://img.shields.io/badge/pytest-12%2F12-success)](https://github.com/Enesp4rl4k/bist-trader-mcp)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)

Türkiye finansal piyasaları için MCP (Model Context Protocol) sunucusu. Açık ve **ücretsiz** TR veri kaynaklarını (TCMB EVDS, KAP, BIST EOD, VIOP bültenleri, MKK) tek bir LLM tool yüzeyi altında birleştirir. Çıktısı **Pine v6 recipe** olarak da hazır — [`tradesdontlie/tradingview-mcp`](https://github.com/tradesdontlie/tradingview-mcp) ile birlikte kullanıldığında Claude doğrudan kullanıcının TradingView Desktop'una indicator + alert basabilir.

> *TR finansal verisini topla → Claude ile analiz et → sonucu TradingView'a Pine recipe olarak indir.*

## Konumlanma

| Proje | Kapsam | İlişki |
|---|---|---|
| [`saidsurucu/borsa-mcp`](https://github.com/saidsurucu/borsa-mcp) | BIST equity fundamentals + TEFAS + kripto + forex | Tamamlayıcı (equity ≠ rates/türev/macro) |
| [`orhoncan/evds-mcp`](https://github.com/orhoncan/evds-mcp) | TCMB EVDS generic seri arama / indirme / analiz | Generic EVDS layer; biz curated rates + Pine recipe sunuyoruz |
| [Fintables Evo MCP](https://fintables.com/evo/mcp) | Ticari, derinleştirilmiş fundamentals | Farklı katman |
| [`tradesdontlie/tradingview-mcp`](https://github.com/tradesdontlie/tradingview-mcp) | TradingView Desktop kontrolü | Birlikte kullanılır (action layer) |
| **bist-trader-mcp (bu repo)** | TR makro + sabit getirili + türev + KAP + MKK + Pine recipe | TR-data + cross-asset analiz tarafı |

Tek cümle: **"TR finans verisini topla, Claude ile analiz et, sonucu TradingView'a Pine recipe olarak indir."**

## Tool yüzeyi (v0.2 — 17 tool)

**Durum etiketleri:**
- ✅ **LIVE** — gerçek veriyle doğrulandı, prod-grade
- 🔑 **NEEDS KEY** — TCMB EVDS anahtarı gerekli; çalışır
- 🚧 **WIP** — upstream endpoint WAF/captcha/HTML arkasında, v0.3'te browser-otomasyon ile bağlanacak. Tool şimdilik `{"error": "endpoint_discovery_pending"}` döner; matematik + parser kodu hazır

### Rates / Hazine / TCMB
- 🔑 `get_yield_curve` — DİBS benchmark eğrisi (1M-10Y), TCMB EVDS
- 🔑 `get_tcmb_policy_rates` — 1w repo + koridor zaman serisi
- ✅ `get_dibs_auctions` — Hazine ihale takvimi (quarterly İç Borçlanma Stratejisi PDF → pdfplumber → 22+ scheduled auction)
- ✅ `calculate_bond_metrics` — YTM, modified duration, convexity (saf hesap)
- 🔑 `list_catalog` — kullanılan EVDS serileri

### Disclosure / equity
- ✅ `get_kap_disclosures` — KAP bildirimi listesi (Playwright-backed, heuristic materyal filtresi)
- ✅ `get_bist_eod_ohlcv` — BIST hisse/endeks günlük OHLCV (Yahoo Finance v8 chart API)
- ✅ `get_mkk_market_stats` — MKK marketwide aylık zaman serisi (toplam yatırımcı, equity/gov-debt/corp-bond/mutual-fund holders, transactions). PDF + pdfplumber + 24h cache.
- 🚧 `get_foreign_ownership` — MKK **per-ticker** yabancı pay oranı (gated portal, v0.3)

### Türev — VIOP & Takasbank
- ✅ `get_viop_dashboard` — **marketwide margin call + volume + OI** snapshot from Takasbank (Playwright + stealth + 6h cache to respect F5 WAF rate limits)
- 🚧 `get_viop_settlement` — per-contract günlük settle (v0.3, free bulletin discovery)
- 🚧 `get_viop_term_structure` — futures vade eğrisi (v0.3)
- 🚧 `get_viop_margin_parameters` — per-contract SPAN parameters (v0.3, file pipeline)
- 🚧 `get_viop_margin_call_alerts` — per-contract teminat oranı %5+ değişenler (v0.3)
- ✅ `calculate_option_greeks` — Black-Scholes Δ Γ Θ Vega ρ (TR-distressed IV brackets)
- ✅ `calculate_implied_volatility` — piyasa fiyatından IV solver

### Cross-asset
- ✅ `calculate_basis_fair_value` — futures vs spot cost-of-carry deviation + implied repo

### TradingView köprüsü
- ✅ `list_pine_recipes` — TR-aware Pine v6 template kataloğu
- ✅ `render_pine_recipe` — placeholders'ı canlı veriyle doldur, Pine kodu döndür

### Test durumu
```
pytest:        12 / 12 PASSED   (bond_math 5/5 + options_math 7/7)
live smoke:    6 live / 1 WIP / 0 unexpected-fail
                 - yahoo_bist_eod:        BIST EOD bars
                 - evds:                  TCMB policy + TLREF + CPI YoY
                 - kap:                   disclosures via Playwright XHR
                 - takasbank dashboard:   marketwide margin call + volume + OI
                                          (Playwright + stealth + 6h cache)
                 - hazine:                DİBS auction calendar
                                          (quarterly PDF + pdfplumber + 24h cache)
                 - mkk market stats:      monthly investor stats time series
                                          (PDF + pdfplumber + 24h cache, 18 rows)
                 - viop per-contract:     WIP — v0.3
```

Live smoke: `python scripts/smoke_test.py` (UTF-8 stdout için `PYTHONIOENCODING=utf-8`).

### Browser otomasyonu (KAP ve diğer SPA siteler için)
Bazı TR siteler (KAP'ı başlatmak üzere, yakında MKK/Takasbank) WAF arkasında veriyi yalnızca tarayıcı session'ına servis ediyor. Bu durumda Playwright tabanlı `_browser.py` helper'ı devreye giriyor. Kurulum:

```powershell
pip install "bist-trader-mcp[browser]"
python -m playwright install chromium
```

Browser extra yüklü değilse ilgili tool'lar yine **structured WIP payload** döner (exception fırlatmaz); LLM bunu yorumlayıp kullanıcıya "browser extra eksik" diye söyler.

## Komposizyon örneği — Claude + tradesdontlie/tradingview-mcp

`%APPDATA%\Claude\claude_desktop_config.json` içine iki MCP'yi de ekleyin:

```json
{
  "mcpServers": {
    "bist-trader": {
      "command": "C:\\path\\to\\bist-trader-mcp\\.venv\\Scripts\\python.exe",
      "args": ["-m", "bist_trader_mcp"],
      "env": { "TCMB_EVDS_API_KEY": "your-key" }
    },
    "tradingview": {
      "command": "node",
      "args": ["C:\\path\\to\\tradingview-mcp\\dist\\index.js"]
    }
  }
}
```

Sonrasında Claude'a doğal dilde sorulabilen örnek workflow:

> "BIST30 sembolünü aç, son 1 yıl. TCMB politika faizi + koridoru + güncel TÜFE'yi backdrop olarak bindir. Geçen ay materyal sayılan KAP bildirimlerini marker olarak işaretle. Yabancı pay oranı %2'den fazla düşerse alert kur."

Bu istek için Claude şu adımları orchestrate eder:

```
1. bist-trader.render_pine_recipe(
     name="tr_macro_backdrop",
     auto_fetch=true,
     data={"PPK_DATES_JSON": [...]}
   )
   → Pine v6 kodu (politika faizi + koridor + CPI table)

2. tradingview.chart_set_symbol("BIST:XU030")
3. tradingview.chart_set_timeframe("1D")

4. tradingview.pine_new(source=<above pine code>)
5. tradingview.pine_smart_compile()
   → indicator chart'a yüklenir, makro snapshot table'ı görünür

6. bist-trader.get_kap_disclosures(
     since="2026-04-01",
     only_material=true
   )
   → 47 materyal olay

7. tradingview.draw_shape (her olay için label)

8. tradingview.alert_create(
     condition="foreign_ownership_drop > 2",
     ...
   )
9. tradingview.capture_screenshot() → Claude kullanıcıya gönderir
```

Tek doğal dil komutu, ~30 saniye, manuel olarak yapılması saatler süren bir araştırma akışı.

## Veri kaynakları

| Kaynak | Kullanım | Auth | Ücretsiz mi? |
|---|---|---|---|
| TCMB EVDS | Faiz, koridor, CPI, FX | API key gerekli (ücretsiz kayıt @ evds3.tcmb.gov.tr) — **header'da gönderilir** (2024-04-05 zorunlu değişiklik) | ✅ |
| KAP | Şirket bildirimleri | Yok | ✅ |
| Borsa İstanbul VIOP bülteni | Türev settle + OI | Yok | ✅ |
| Takasbank risk parametreleri | VIOP teminat (başlangıç/sürdürme) | Yok | ✅ |
| Hazine ve Maliye Bakanlığı | DİBS ihale takvimi + sonuçları | Yok | ✅ |
| Yahoo Finance | BIST EOD OHLCV | Yok | ✅ |
| MKK | Yabancı pay oranı | Yok | ✅ |

Intraday tick / L2 derinlik **bu projenin kapsamında değildir** — o tarafa ihtiyacı olan trader Matriks/Foreks aboneliğini kullanmaya devam etmeli.

## Kurulum & geliştirme

```powershell
git clone https://github.com/Enesp4rl4k/bist-trader-mcp.git
cd bist-trader-mcp
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
pytest -q                              # 12/12 offline math tests
$env:TCMB_EVDS_API_KEY = "your-key"   # EVDS-dependent tools için
python -m bist_trader_mcp              # stdio MCP server (test amaçlı)
```

EVDS anahtarı için (ücretsiz kayıt): https://evds3.tcmb.gov.tr/

Detaylı quickstart + Claude Desktop config: [`docs/quickstart.md`](docs/quickstart.md).

## Yol haritası

**v0.1**
- ✅ Core rates + bond math
- ✅ KAP / BIST EOD / VIOP / MKK data tools
- ✅ İlk Pine recipe (`tr_macro_backdrop`)

**v0.2 (mevcut)**
- ✅ Takasbank günlük teminat (margin call sinyali) + change alerts
- ✅ Black-Scholes greeks + IV solver (TR-distressed range desteği)
- ✅ Hazine DİBS ihale takvimi + sonuçları
- ✅ Cross-asset basis fair value + implied repo
- ✅ İkinci Pine recipe: `tr_basis_monitor`

**v0.3 (sıradaki)**

Öncelik: 5 WIP endpoint için **gerçek upstream pattern keşfi** (her biri browser network-tab inceleme + olası Playwright session reuse):
- KAP — disclosure JSON endpoint (custom 666 + WAF arkasında)
- VIOP — Borsa İstanbul günlük türev bülteni (URL pattern hâlâ aranıyor)
- Takasbank — VIOP teminat parametre Excel/JSON
- Hazine — DİBS ihale takvimi (muhtemelen PDF parse)
- MKK — yabancı pay oranı (oturum/captcha bağımlı)

Sonra:
- TÜİK makro (TÜFE detay, sanayi üretimi, dış ticaret)
- Açığa satış istatistikleri + block trade akışı
- VIOP option chain ingest (toplu IV surface)
- EM peer yield karşılaştırma
- Yeni Pine recipe'ler: `tr_kap_marker`, `tr_foreign_flow`, `tr_margin_pulse`

## Lisans

MIT

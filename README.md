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

## Tool yüzeyi (v0.8 — 60 tool + 8 prompt + 4 resource)

> **v0.8**: **backtester** (signals → equity curve + trades), **performance metrics** (Sharpe/Sortino/Calmar/MaxDD/win rate/profit factor), **Markowitz portfolio optimizer** (efficient frontier + min-var + max-Sharpe), ve **Kelly criterion + ATR position sizing**. Trading mantığını uçtan uca: sinyal → backtest → optimize → boyutlandır.
> **v0.7**: **volatility forecasting** (EWMA + GARCH(1,1)), **BIST sektör rotasyon** analizi, **on-chain** (Etherscan gas + BTC network), **Nelson-Siegel-Svensson yield curve fitter** (herhangi bir tenor'da yield interpolasyonu).
> **v0.6**: **opsiyon strateji simülatörü** (straddle, strangle, iron condor, butterfly, vertical), **realized volatility** (CC + Parkinson + Garman-Klass + IV/RV ratio), ve **finansal news/RSS aggregator** (Investing, Yahoo, Reuters, CoinDesk).
> **v0.5**: kripto opsiyon IV surface (Deribit), crypto F&G sentiment, ve **çok-varlık korelasyon analitiği** eklendi. Mevcut `find_viop_spread_opportunities` artık BTC/ETH option surface'ı için de çalışıyor (aynı şema).
> **v0.4 itibariyle global trader MCP'sine evrildi**: TR-fokuslu rates/türev/macro çekirdeğine **kripto (CoinGecko + Binance perp funding/OI)**, **global spot FX (ECB referans rates)**, **global indices/treasuries/commodities snapshot**, ve **standart teknik göstergeler (RSI/MACD/Bollinger/ATR/EMA/SMA)** eklendi.

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
- ✅ `get_viop_settlement` — **live per-contract snapshot** (last price, % change, volume TL, OI) for all 480+ VIOP futures + options. Source: İş Yatırım viop.aspx + 1h cache.
- ✅ `get_viop_term_structure` — futures vade eğrisi (contango / backwardation, basis hesabı için)
- 🚧 `get_viop_margin_parameters` — per-contract SPAN parameters (v0.4, separate file pipeline)
- 🚧 `get_viop_margin_call_alerts` — per-contract teminat oranı %5+ değişenler (v0.4)
- ✅ `calculate_option_greeks` — Black-Scholes Δ Γ Θ Vega ρ (TR-distressed IV brackets)
- ✅ `calculate_implied_volatility` — piyasa fiyatından IV solver

### Cross-asset
- ✅ `calculate_basis_fair_value` — futures vs spot cost-of-carry deviation + implied repo

### Türev analitiği (v0.3 yeni)
- ✅ `get_viop_iv_surface` — VIOP opsiyon implied vol yüzeyi: per-strike IV/Δ/moneyness, ATM term structure, 25Δ skew, front/back vol slope
- ✅ `find_viop_spread_opportunities` — calendar / vertical / butterfly spread tarayıcı (vol-point edge ile sıralı)
- ✅ `calculate_portfolio_var` — parametric / historical VaR + Expected Shortfall, gamma adjustment
- ✅ `stress_test_portfolio` — built-in senaryolar (rates+200bp, tl_devalue_20pct, xu030_-10pct, vol_spike, broad ±5%) + custom senaryo

### Observability (v0.3 yeni)
- ✅ `get_health_status` — cache freshness + Playwright + EVDS key durumu

### Global piyasalar (v0.4 yeni)
- ✅ `get_global_pulse` — tek çağrıda global özet: SPX/NDX/DAX/FTSE/N225/HSI + UST 3M/5Y/10Y/30Y + WTI/Brent/Gold/Silver/Copper/Natgas + BTC/ETH/SOL
- ✅ `get_global_fx_spot` — ECB referans rates (EURUSD, USDJPY, GBPUSD, ...) — Frankfurter
- ✅ `get_global_fx_history` — günlük FX geçmişi (1-N gün)
- ✅ `get_global_fx_matrix` — G10 bases × EM quotes matrisi

### Kripto (v0.4 yeni)
- ✅ `get_crypto_spots` — CoinGecko spot snapshot (top N coin: fiyat, market cap, 24h vol, 24h/7d % change, ATH)
- ✅ `get_crypto_klines` — Binance spot OHLCV (1m–1w, max 1000 bar)
- ✅ `get_crypto_funding_rates` — Binance USD-M perp funding history + annualised avg (leverage stress sinyali)
- ✅ `get_crypto_open_interest` — perp OI tarihçesi

### Teknik göstergeler (v0.4 yeni)
- ✅ `calculate_technicals` — herhangi bir OHLCV serisi için: SMA 20/50/200, EMA 12/26, RSI(14), MACD(12/26/9), Bollinger(20,2σ), ATR(14) + kategorik label'lar (trend, RSI, BB)

### Kripto opsiyon & sentiment (v0.5 yeni)
- ✅ `get_deribit_iv_surface` — BTC/ETH option IV surface (Deribit mark_iv), `get_viop_iv_surface` ile aynı şema; `find_viop_spread_opportunities` doğrudan üzerine çalışır
- ✅ `get_crypto_fear_greed` — alternative.me composite F&G index + history (kontrarian sinyal)

### Çok-varlık korelasyon (v0.5 yeni)
- ✅ `calculate_correlation_matrix` — N×N pairwise korelasyon + top-10 |ρ| + bottom-10 (diversifying)
- ✅ `calculate_rolling_correlation` — iki seri için rolling correlation (rejim değişimi tespiti, BTC-SPX flip vb.)

### Opsiyon strateji simülatörü (v0.6 yeni)
- ✅ `simulate_option_strategy` — straddle/strangle/iron condor/butterfly/vertical spread için tam P&L grid, max profit/loss, breakevens, net debit/credit. At-expiry veya mid-life (days_forward param).
- ✅ `list_strategy_templates` — kullanılabilir şablonların listesi

### Realized volatility (v0.6 yeni)
- ✅ `calculate_realized_vol` — close-to-close + Parkinson (H/L) + Garman-Klass (O/H/L/C); `iv_atm_pct` ile birlikte IV/RV oranı + spread (opsiyon mean-reversion sinyali)

### Finansal haberler (v0.6 yeni)
- ✅ `get_news_headlines` — RSS aggregator: Investing.com (top/commodities/FX/economy/crypto), Yahoo Finance, Reuters business, CoinDesk. 15-dk cache.

### Volatility forecasting (v0.7 yeni)
- ✅ `calculate_ewma_volatility` — RiskMetrics EWMA (λ=0.94), vol path + next-period forecast
- ✅ `calculate_garch_forecast` — GARCH(1,1) coarse-grid MLE + horizon path + stationary long-run vol

### BIST sektör rotasyon (v0.7 yeni)
- ✅ `get_bist_sector_rotation` — 17 sektör endeksi (XBANK, XUSIN, XGIDA, XKAGT, XHOLD, XKMYA, ...) için total return, recent return, XU100'e karşı relative strength + ranked top-3/bottom-3

### On-chain (v0.7 yeni)
- ✅ `get_eth_gas_oracle` — Etherscan: safe/propose/fast gas (Gwei) + suggested base fee (NFT/airdrop sinyali)
- ✅ `get_btc_network_stats` — blockchain.info: hashrate, difficulty, supply, mempool

### Yield curve fitting (v0.7 yeni)
- ✅ `fit_yield_curve_nss` — Nelson-Siegel veya NSS fit; herhangi bir tenor için yield interpolasyonu (3.5Y'ı 2Y/5Y'dan türet, noisy DİBS auction yields'i pürüzsüzleştir)

### Backtest + performance (v0.8 yeni)
- ✅ `backtest_strategy` — event-driven backtest: closes + signals → equity curve + trades + full performance panel. Built-in sinyal üreticileri: sma_crossover, rsi_thresholds, bollinger_mean_reversion. Commission + slippage cost modeli.
- ✅ `list_signal_generators` — kullanılabilir sinyal üreticileri
- ✅ `calculate_performance_panel` — herhangi bir returns/equity curve/trade list için: Sharpe, Sortino, Calmar, max drawdown, win rate, profit factor, expectancy

### Portfolio optimization (v0.8 yeni)
- ✅ `optimize_portfolio_markowitz` — closed-form Markowitz: min-variance + max-Sharpe (tangency) + 25-noktalı efficient frontier; opsiyonel target-return portföyü

### Position sizing (v0.8 yeni)
- ✅ `calculate_kelly_sizing` — bet Kelly (win prob + W/L ratio) + continuous Kelly (μ/σ²) + fractional variants (%25/%50/%100)
- ✅ `calculate_atr_position_size` — ATR-tabanlı stop loss ile %1 risk kuralı (trend-following standardı)

### TradingView köprüsü (6 recipe)
- ✅ `list_pine_recipes` — TR-aware Pine v6 template kataloğu
- ✅ `render_pine_recipe` — placeholders'ı canlı veriyle doldur, Pine kodu döndür
- `tr_macro_backdrop`, `tr_basis_monitor`, **`tr_kap_marker`** (v0.3), **`tr_foreign_flow`** (v0.3), **`tr_margin_pulse`** (v0.3), **`tr_iv_surface`** (v0.3)

### MCP Resources (v0.3 yeni)
- `bist-trader://catalog/evds-series` — EVDS seri katalogu (JSON)
- `bist-trader://catalog/pine-recipes` — Pine template metadata (JSON)
- `bist-trader://catalog/stress-scenarios` — built-in stres senaryo katalogu (JSON)
- `bist-trader://snapshot/daily-report` — TR markets günlük özet (Markdown, on-read render)

### MCP Prompts (v0.3 yeni)
- `daily-tr-rates-report` — politika faizi + repo curve + ihale takvimi + ekonomik takvim'i tek prompt'a paketler
- `viop-opportunity-scan` — bir underlying için term structure + IV surface + spread tarayıcı + Pine overlay
- `kap-event-impact` — KAP material event'leri × EOD reaksiyon analizi
- `portfolio-risk-overview` — Greeks + VaR + stres test tek bir akışta

### Test durumu
```
pytest:        43 / 43 PASSED   (5 bond_math + 7 options_math
                                + 25 parser unit tests + 6 cache tests)
ruff lint:     clean
live smoke:    7 live / 0 WIP / 0 unexpected-fail  ← FULL SWEEP
                 - yahoo_bist_eod:        BIST EOD bars
                 - evds:                  TCMB policy + TLREF + CPI YoY
                 - kap:                   disclosures via Playwright XHR
                 - takasbank dashboard:   marketwide margin call + volume + OI
                                          (Playwright + stealth + 6h cache)
                 - hazine:                DİBS auction calendar
                                          (quarterly PDF + pdfplumber + 24h cache)
                 - mkk market stats:      monthly investor stats time series
                                          (PDF + pdfplumber + 24h cache, 18 rows)
                 - viop snapshot:         480+ live contracts (futures + options)
                                          (İş Yatırım scrape + 1h cache)
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

**v0.3 (mevcut)**
- ✅ VIOP IV surface + skew + term structure
- ✅ Spread tarayıcı (calendar, vertical, butterfly)
- ✅ Portfolio VaR (parametric + historical) + Expected Shortfall
- ✅ Stress test framework (9 built-in + custom senaryo)
- ✅ 4 yeni Pine recipe (tr_kap_marker, tr_foreign_flow, tr_margin_pulse, tr_iv_surface)
- ✅ MCP Resources (4 dataset) + Prompts (4 hazır akış)
- ✅ Health/observability tool

**v0.4 (mevcut — global trader)**
- ✅ Kripto: CoinGecko spot + Binance klines/funding/OI
- ✅ Global FX (ECB referans) + N×M matris
- ✅ Global piyasalar pulse (US/EU/Asia indices + treasuries + commodities + crypto majors)
- ✅ Teknik göstergeler (RSI, MACD, Bollinger, ATR, EMA, SMA) — herhangi bir seri için

**v0.5 (sıradaki)**

WIP endpoint'leri kapatma:
- MKK per-ticker yabancı pay oranı (gated portal)
- Takasbank VIOP SPAN margin parametreleri (Excel pipeline)
- Yield curve rebuild (TP.ATBPK retired → per-ISIN bie_pydibs)

Yeni kaynaklar:
- TÜİK makro (TÜFE detay, sanayi üretimi, dış ticaret)
- Açığa satış istatistikleri + block trade akışı
- VIOP option chain ingest (toplu IV surface)
- EM peer yield karşılaştırma
- Yeni Pine recipe'ler: `tr_kap_marker`, `tr_foreign_flow`, `tr_margin_pulse`

## Lisans

MIT

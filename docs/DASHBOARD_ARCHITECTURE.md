# Canlı Panel + Risk Katmanı — Mimari Plan

## Amaç
AI masaüstü uygulamalarının (Claude Desktop, claude.ai, Cursor, VS Code) **içinde** canlı ve
etkileşimli bir piyasa paneli: TradingView grafiği, KAP + haber akışı, makro endeksler ve
emtialar, risk özeti. Kullanıcı sembol/periyot/panel seçer, butonlarla analiz, TradingView'a
çizim, risk kontrolü ve günlüğe ekleme yapar. Gömülü arayüz desteklemeyen istemciler (Codex,
terminal) aynı paneli yerel tarayıcı sayfası olarak açar.

Sıra: **1) Risk motoru → 2) Panel v1 → 3) v2 (uyarılar, kağıt işlem, takvim ayrıntısı).**

---

## Temel kısıtlar (tasarımı belirleyen)

| Kısıt | Sonuç |
|---|---|
| MCP Apps (SEP-1865, `2026-01-26`) arayüzü sandbox'lı iframe'de çalışır; CSP varsayılanı dış bağlantı yok | Panel **hiçbir dış siteye bağlanmaz**. Tüm veri `tools/call` ile bizim sunucudan gelir. JS/CSS tek dosyada, kütüphanesiz (grafik canvas ile elle çizilir) |
| claude.ai `frameDomains`'i yok sayıyor (anthropics/claude-ai-mcp#40) | TradingView widget iframe'i kullanılmaz. Grafik, TradingView **Desktop**'tan köprüyle çekilen barlarla panelde çizilir; "TV'de aç / Planı çiz" butonları gerçek TV'yi yönetir |
| Codex/terminal istemcileri gömülü arayüz göstermez | Aynı HTML, `127.0.0.1` üzerinde küçük bir HTTP sunucusundan servis edilir; taşıma katmanı soyut (postMessage **veya** fetch) |
| TradingView'da tek grafik var; sembol değiştirmek kullanıcının grafiğini değiştirir | İzleme listesi TV'ye **dokunmaz** (Yahoo anlık + günlük barlar). Sadece seçili sembolün grafiği TV'den gelir |
| BIST Yahoo verisi ~15 dk gecikmeli | Şerit/izleme listesi "gecikmeli" etiketi taşır; gerçek zamanlı ihtiyaç TV'den |
| `mcp` 1.30 düşük seviye sunucu | `Tool._meta`, `CallToolResult.structuredContent`, kaynak `_meta` destekli — SDK yükseltmesi gerekmez |

---

## Bileşenler

```
                    ┌──────────────── Host (Claude / Cursor / VS Code) ───────────────┐
 kullanıcı ──────▶  │  iframe: dashboard.html  ◀─ postMessage JSON-RPC (ui/*, tools/*) │
                    └───────────────────────────────┬─────────────────────────────────┘
                                                    │ tools/call (app-only araçlar)
 tarayıcı (Codex) ─▶ http://127.0.0.1:PORT/?t=TOKEN │
        fetch POST /api/call ───────────────────────┤
                                                    ▼
┌──────────────────────────── bist-trader MCP sunucusu ─────────────────────────────┐
│ dashboard_tools  open_dashboard · dashboard_snapshot · dashboard_action           │
│ dashboard_data   build_snapshot(state) → bölümler paralel + zaman aşımlı          │
│    ├─ ticker     bist_snapshot + global_markets (60 sn önbellek)                   │
│    ├─ watchlist  Yahoo anlık + günlük barlar → sade PA kararı (TV'ye dokunmaz)     │
│    ├─ chart      _resolve_bars (TV önce) → mumlar + plan + S/R + tahmin bandı     │
│    ├─ news       KAP (varsa) + RSS → izleme listesi eşleşmesi işaretli             │
│    ├─ calendar   calendar_data (PPK, TÜFE, ÜFE)                                    │
│    └─ risk       risk_engine.portfolio_risk                                        │
│ risk_engine      RiskConfig · pozisyon boyutu · check_trade · portfolio_risk       │
│ dashboard_web    ThreadingHTTPServer (127.0.0.1, token, araç allowlist)            │
│ mevcut: pa_simple · candle_forecast · tv_tools · trade_journal · daily_pipeline    │
└───────────────────────────────────────────────────────────────────────────────────┘
```

### 1. Risk motoru — `risk_engine.py`
**RiskConfig** (JSON, `BIST_RISK_CONFIG`; varsayılanlar):

| Alan | Varsayılan | Anlam |
|---|---|---|
| `equity` | 100 000 | Hesap büyüklüğü (TL) |
| `risk_per_trade_pct` | 1.0 | İşlem başı stop riski |
| `max_open_risk_pct` | 6.0 | Tüm açık işlemlerin toplam stop riski |
| `max_positions` | 6 | Eşzamanlı pozisyon |
| `max_cluster_positions` | 2 | Birbiriyle korelasyonu ≥ `cluster_corr` olan grupta en fazla |
| `cluster_corr` | 0.7 | 60 bar log-getiri korelasyonu |
| `daily_loss_limit_pct` / `weekly_loss_limit_pct` | 3 / 6 | Aşılınca yeni işlem yok (devre kesici) |
| `max_adv_pct` | 5.0 | Pozisyon değeri ≤ 20 günlük ort. işlem hacminin %5'i |
| `event_blackout_days` | 1 | Yüksek önemli makro olaydan (PPK, TÜFE) önce uyarı |

**`check_trade(plan, config, bars_by_symbol, journal)`** → `approved`, `quantity`, `risk_amount`,
`checks[]` (her biri `ok`, `severity: block|warn`, açıklama), `summary_tr`. Kontroller:
geometri · devre kesici · aynı sembolde açık işlem · pozisyon sayısı · toplam açık risk ·
korelasyon kümesi · likidite · tavan/taban günü (son bar |%değişim| ≥ 9.5) · makro olay.

**`portfolio_risk(config, bars_by_symbol, journal)`** → açık risk % (heat), pozisyonlar,
gerçekleşen günlük/haftalık sonuç, devre kesici durumu, korelasyon kümeleri, 1 günlük %95
tarihsel VaR.

Açık risk kaynağı: işlem günlüğündeki `open` işlemler. Miktarı olmayan eski kayıtlar
standart risk (`risk_per_trade_pct`) sayılır. Kapanmış işlemlerin sonucu R → % için
`risk_per_trade_pct` ile çarpılır.

**Entegrasyon:** `daily_pipeline` her seçimi `check_trade`'den geçirir; engellenen loglanmaz,
onaylananın miktarı günlüğe yazılır. Araçlar: `get_risk_config`, `set_risk_config`,
`check_trade_risk`, `get_portfolio_risk`.

### 2. Panel — `dashboard_data.py`, `ui/dashboard.html`, `dashboard_web.py`
**Durum (state)** — istemci tutar, her çağrıda gönderir:
`{symbol, timeframe, watchlist[], panels{ticker,watchlist,chart,news,risk,calendar}, chart_source}`

**Araçlar**
| Araç | Görünürlük | İş |
|---|---|---|
| `open_dashboard` | model + app | Paneli açar (`_meta.ui.resourceUri`); metin özet + `structuredContent` ilk görüntü + yerel URL |
| `dashboard_snapshot` | app | Yenileme: seçili panellerin verisi |
| `dashboard_action` | app | `analyze`, `tv_open`, `tv_draw_plan`, `risk_check`, `journal_add` |

Görünürlüğü desteklemeyen host'larda app araçları modele de görünür; açıklamaları "panel içi"
diye işaretlenir, zararsızdır.

**Veri akışı:** her bölüm `asyncio.wait_for` ile ayrı zaman aşımlı (bir kaynak düşerse diğerleri
gelir, bölüm `error` taşır). Önbellekler: şerit 60 sn, haber 5 dk (mevcut), barlar
periyoda göre (mevcut), KAP 5 dk (mevcut).

**Arayüz (tek HTML, kütüphanesiz)**
- Taşıma: iframe içindeyse MCP Apps (`ui/initialize` → `ui/notifications/initialized`,
  `tools/call`, `ui/notifications/tool-result`, `ui/message`, `ui/update-model-context`,
  `ui/open-link`, `ui/notifications/size-changed`); değilse `fetch('/api/call')`.
- Yenileme: 15/30/60 sn/kapalı seçilebilir; sekme gizliyken durur.
- Bölümler: piyasa şeridi · izleme listesi (tıkla → seç) · canvas mum grafiği (plan/S-R/tahmin
  bandı, artı imleci) · haber akışı (KAP işaretli) · risk özeti · makro takvim.
- Aksiyonlar: Analiz et · TV'de aç · Planı çiz · Risk kontrolü · Günlüğe ekle ·
  Claude'a sor (`ui/message`; web modunda panoya kopyala).
- Seçim değişince `ui/update-model-context` ile modele "kullanıcı şu an THYAO 1D'ye bakıyor"
  bağlamı gider.
- Tema: host `theme` + CSS değişkenleri; açık/koyu.

**Yerel web modu:** `dashboard_web.py` — `127.0.0.1`, rastgele token (URL + başlık), yalnızca
`dashboard_snapshot`/`dashboard_action` çağrılabilir. MCP sunucusu içinde ilk
`open_dashboard` çağrısında arka planda başlar; ayrıca `bist-trader-dashboard` CLI.

### 3. v2 (sonraki tur)
Telegram/masaüstü uyarıları (stop/hedef yakın, izleme listesinde KAP) · kağıt işlem modu ·
şirket bazlı olay takvimi (bilanço/genel kurul).

---

## Test stratejisi
- Risk: her kontrol için birim testi (geometri, devre kesici, küme, likidite, tavan/taban,
  miktar yuvarlama), `portfolio_risk` VaR ve heat hesabı, pipeline entegrasyonu.
- Panel verisi: sahte kaynaklarla `build_snapshot`; bir kaynak hata/zaman aşımı verince diğer
  bölümlerin gelmesi; izleme listesinin TV'yi çağırmadığı.
- Protokol: `tools/list` çıktısında `_meta.ui.resourceUri` (+ eski düz anahtar),
  `resources/read` mime `text/html;profile=mcp-app`, `CallToolResult.structuredContent`.
- Arayüz: Playwright ile (a) web modu uçtan uca: sayfa açılır, bölümler dolar, sembol
  tıklanınca grafik değişir; (b) sahte bir host sayfası iframe'e paneli koyup
  `ui/initialize`/`tools/call` akışını taklit eder.
- Web sunucusu: token'sız istek 403, allowlist dışı araç 403, sadece 127.0.0.1.

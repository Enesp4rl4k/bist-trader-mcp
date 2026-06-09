# TÜRİB entegrasyonu ve TradingView analiz boşlukları

## TÜRİB — MCP’ye eklemeli miyiz?

**Evet, ama katmanlı:**

| Katman | Kaynak | MCP durumu |
|--------|--------|------------|
| **A — Kamuya açık özet** | [endeks-anasayfa](https://www.turib.com.tr/endeks-anasayfa/), [piyasa verileri](https://www.turib.com.tr/piyasa-verileri/), bülten/XLS | `get_turib_endeks_overview` (cache’li, bilgi amaçlı) |
| **B — Tarihsel / ürün grubu** | [Veri Merkezi](https://www.turib.com.tr/tarihsel-veri/) | v0.4: Playwright + ürün seçimi |
| **C — Lisanslı feed** | [Veri dağıtım şirketleri](https://www.turib.com.tr/veri-dagitim-sirketleri/), Paket 1–3 | Kurumsal sözleşme; MCP’de yalnızca “hangi araçları çağır” yönlendirmesi |

**Hukuk:** Site metni ticari yeniden dağıtımı yasaklar; MCP çıktısı **araştırma checklist + tek seferlik özet** olmalı, tick feed satışı değil.

**Stratejik uyum:** Repo zaten TR makro + sabit getiri + VIOP. TÜRİB, **XGIDA / tarım / gıda** hisseleri ve **hububat enflasyon** bağlamı için `analyze_market_context` temel katmanını güçlendirir (buğday/mısır endeksi ↔ THYAO benzeri değil, ULKER, BIMAS tedarik zinciri okuması).

---

## TradingView analiz eksiklikleri (BIST hisse)

| Sorun | Etki | Yapılan / öneri |
|-------|------|------------------|
| 1H TV barlarında seans dışı mumlar | Yapı/FVG/EW bozulur, `data_quality` “thin” → analiz dururdu | **Seans filtresi** (`session_filter` + `tv_fetch_mtf_ohlcv`) |
| `data_quality.ok` çok sert | İnce veride tüm senaryo iptal | Yalnızca `insufficient` bloklar; `thin` uyarı ile devam |
| Günlük HTF + 1H LTF gap | Elliott HTF’de gap yorumu | KAP/makro ile doğrula; isteğe bağlı `get_bist_eod_ohlcv` yedek HTF |
| Grafikte FVG kutusu yok | Yalnızca 1 FVG çizgisi + banner | Gelecek: dikdörtgen zone veya çoklu FVG |
| Sembol `THYAO` vs `BIST:THYAO` | TV yanlış enstrüman riski | `normalize_tv_symbol` — state doğrulama (TODO) |
| Tatil / yarım seans | Saat filtresi yeterli değil | v0.4: BIST takvim tablosu |

---

## TradingView analiz eksiklikleri (kripto)

| Sorun | Etki | Yapılan / öneri |
|-------|------|------------------|
| Funding / OI teknik pakette yok | Long squeeze / crowded trade görülmez | `analyze_market_context` → funding/OI araç ipuçları |
| Spot chart, perp metrik | Sembol `BINANCE:BTCUSDT` spot; funding perp | Açıkça `get_crypto_funding_rates` çağrısı |
| 24/7 — seans filtresi yok | Doğru (uygulanmıyor) | — |
| Yüksek vol → chase | Erken giriş | Profil: `max_entry_chase_atr=2.0` (crypto) |
| Likidasyon seviyeleri | TV çizilmiyor | v0.4: heatmap harici veri |

---

## Önerilen akış (düzgün analiz)

```text
run_scenario_assistant(symbol)
  → tv_health_check
  → tv_fetch_mtf_ohlcv  (+ BIST LTF seans filtresi)
  → analyze_chart_scenarios  (thin = uyarı, insufficient = stop)
  → build_fundamental_context (+ TÜRİB gıda / kripto funding)
  → apply_scenario_to_chart (PA + EW + kanal + position)
```

**BIST gıda:** `get_turib_endeks_overview` → `get_kap_disclosures` → senaryo.  
**Kripto:** `get_crypto_funding_rates` + `get_crypto_open_interest` → senaryo.

---

## Sonraki sprint (öncelik)

1. TV sembol doğrulama (`tv_chart_get_state` vs beklenen `symbol_tv`)
2. TÜRİB tarihsel veri (ürün grubu seçimi, Playwright)
3. Kripto funding’i senaryo kapısına bağlama (ör. aşırı pozitif funding + long setup = uyarı)
4. FVG zone çizimi (TV rectangle veya iki çizgi + fill)

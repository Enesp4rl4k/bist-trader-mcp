# Hedge-Fund Seviyesi BIST Analiz Motoru — Yol Haritası

> **Amaç:** Bu MCP'nin BIST hisselerini hem **temel** hem **teknik** olarak
> kurumsal (hedge fund) seviyede analiz etmesi. Hedef iki katmanlı: önce
> **derin tek-hisse dosyası**, sonra aynı metrikleri tüm evrene yayan
> **kesitsel (cross-sectional) kuant sıralama**.
>
> **Veri stratejisi (karar):** Ücretsiz / scrape. **KAP birincil otoritatif
> kaynak**; Yahoo + MKK tamamlayıcı. İleride ücretli besleme takılabilecek
> şekilde kaynak-soyut (source-abstract) tasarım.
>
> Bu belge tasarım + sıralama içindir; kod sonraki adımda gelir.

---

## 1. Mevcut durum teşhisi

| Boyut | Şu an | Kaynak | Hedge-fund çıtası |
|---|---|---|---|
| Finansal tablolar | Yok — Yahoo'nun hazır TTM oranları | [fundamental_ratios.py](../src/bist_trader_mcp/fundamental_ratios.py) | KAP gelir tablosu / bilanço / nakit akış **kalemleri** |
| Enflasyon muhasebesi | Yok (nominal) | — | **TMS 29** reel düzeltme farkındalığı |
| Değerleme | Yok | — | DCF + ters-DCF + peer-relative |
| Kalite / distress | Yok | — | Piotroski F, Altman Z, Beneish M, accruals |
| Kapsam | Tek sembol, anlık | [market_assistant.py](../src/bist_trader_mcp/market_assistant.py) | Tüm evren kesitsel sıralama |
| Tarihsel veri | Yok (her çağrı scrape) | — | Point-in-time panel DB |
| Akışlar | Yabancı oranı WIP | [mkk.py](../src/bist_trader_mcp/mkk.py) | Yabancı takas akışı zaman serisi |
| Risk modeli | VaR/stres var, tek-hisse | [portfolio.py](../src/bist_trader_mcp/portfolio.py) | Kovaryans, XU100 beta, sektör maruziyeti |
| **Teknik** | **Güçlü** (PA+EW+confidence+backtest) | [chart_scenarios.py](../src/bist_trader_mcp/chart_scenarios.py) | Evren-bazlı faktör + sürtünmeli backtest |

**Sonuç:** Teknik taraf görece olgun. Asıl açık → **temel taraf + kalıcı veri
katmanı + kesitsel metodoloji.**

---

## 2. Mimari prensip: önce veri katmanı

Hedge-fund tarzı analizin tek olmazsa-olmazı **point-in-time tarihsel panel
veritabanı**dır. Anlık scrape modeliyle yapılamayanlar:

- **Faktör backtesti** — geçmiş temel veri tutulmadan sinyal doğrulanamaz.
- **Kesitsel sıralama** — tüm evren aynı anda tutulmadan z-score/percentile çıkmaz.
- **Bias'tan kaçınma** — look-ahead ve survivorship bias ancak damgalı geçmişle önlenir.

> **Altın kural:** her veri noktası **"ne zaman bilinebilirdi"** (`known_at`)
> damgasıyla saklanır. KAP bildirim tarihi = finansalın bilinir olduğu an
> (rapor dönemi değil). Bu, mevcut [test_lookahead.py](../tests/test_lookahead.py)
> garantilerinin temel veriye taşınmış halidir.

**Önerilen depo:** DuckDB (tek dosya, kolon-bazlı, pandas/pyarrow dostu, sıfır
sunucu). SQLite alternatif. Şema kabaca:

```
prices(ticker, date, o,h,l,c, volume, adj_factor, known_at)
fundamentals_raw(ticker, period_end, statement, line_item, value, currency,
                 is_inflation_adjusted, kap_publish_date, known_at)
fundamentals_derived(ticker, period_end, metric, value, known_at)   -- F-score, Z, ROIC...
universe(ticker, date, in_xu100, in_xu030, sector, is_active)        -- survivorship
foreign_flow(ticker, date, foreign_ratio, known_at)
```

---

## 3. BIST'e özel zorluklar (genel framework'lerin atladığı)

1. **TMS 29 enflasyon muhasebesi (kritik).** 2022'den beri yüksek enflasyon
   rejiminde nominal büyüme yanıltıcı. Yahoo TTM verisi nominal/karışık dönem.
   Reel vs nominal ayrımı ve TMS29-düzeltilmiş tablo tercih edilmeli; aksi halde
   "kâr büyümesi" sinyali enflasyon gürültüsü olur.
2. **KAP finansal tabloları otoritatif** ama yapısal parse gerektirir (XBRL/PDF).
   Mevcut [kap.py](../src/bist_trader_mcp/kap.py) bildirim listesi çekiyor;
   finansal tablo kalem-bazlı ingest **eklenecek**.
3. **±%10 fiyat limiti + T+2 takas + likidite.** Backtest sürtünmeleri ve
   uygulanabilirlik filtresi BIST'e göre ayarlanmalı (limit-up günü giriş yok).
4. **Vergi/komisyon:** BSMV, damga, komisyon — net getiri hesabına dahil.
5. **Survivorship bias:** delist/iflas eden hisseler evrenden silinmemeli;
   `universe` tablosu point-in-time tutulmalı.
6. **Yahoo kırılganlığı:** crumb handshake + kapsam boşlukları. Kaynak-soyut
   katman, KAP'a düşüş (fallback) ve ücretli beslemeye geçiş kolaylaştırır.

---

## 4. Veri kaynakları (ücretsiz / scrape)

| Veri | Birincil | Tamamlayıcı | Not |
|---|---|---|---|
| Finansal tablolar | **KAP** (XBRL/PDF) | Yahoo `quoteSummary` | KAP otoritatif; Yahoo hızlı prototip |
| Fiyat (EOD) | Yahoo v8 chart | TradingView köprüsü | Mevcut [bist_eod.py](../src/bist_trader_mcp/bist_eod.py) |
| Yabancı takas | MKK | — | Per-ticker gated (WIP), market-wide mevcut |
| Makro (faiz/TÜFE/FX) | TCMB EVDS | — | Mevcut [evds.py](../src/bist_trader_mcp/evds.py); reel düzeltme için TÜFE şart |
| Sektör/endeks üyeliği | BIST/KAP | — | `universe` survivorship için |
| Temettü/sermaye art. | KAP | Yahoo | Toplam getiri düzeltmesi |

---

## 5. Faz planı

### Faz A — BIST veri omurgası *(önkoşul)*
**Çıktı:** point-in-time panel DB + ingest hattı.
- DuckDB şeması + `data/` ingest CLI'ları (idempotent, `known_at` damgalı)
- KAP finansal tablo parser'ı (gelir/bilanço/nakit akış kalemleri)
- Tüm evren için EOD fiyat + temettü düzeltme backfill
- `universe` snapshot'ları (survivorship-safe)
- TÜFE serisi ile reel-düzeltme yardımcı katmanı (TMS29 farkındalığı)

**Kabul kriterleri:** ≥3 yıl geçmiş, en az XU100 evreni; aynı `period_end` için
`known_at` doğru (KAP yayın tarihi); ingest tekrar çalıştırılınca duplikasyon yok.

### Faz B — Hedge-fund **temel motoru** (tek-hisse) *(ilk görünür değer)*
**Çıktı:** bir hisse için kurumsal derinlikte temel dosya.
- **Değerleme:** DCF + ters-DCF (piyasa hangi büyümeyi fiyatlıyor?) + peer-relative çarpan
- **Kalite/distress:** Piotroski F (9), Altman Z (EM kalibreli), Beneish M, accruals oranı
- **Kazanç kalitesi:** nakit akış vs muhasebe kârı, tek seferlik kalemler
- Mevcut [score_fundamental_ratios](../src/bist_trader_mcp/fundamental_ratios.py)'u
  bunlarla **zenginleştir** (geriye uyumlu); kaynak DB → yoksa Yahoo fallback
- Yeni araç: `analyze_equity_fundamentals(ticker)` → tam temel dosya + TR özet

**Kabul kriterleri:** DCF girdileri şeffaf ve test edilebilir (saf fonksiyon);
F/Z/M skorları bilinen örneklerle birim-test; Yahoo yokken KAP/DB'den çalışır.

### Faz C — Kesitsel **kuant katman** (evren) *(asıl hedge-fund metodolojisi)*
**Çıktı:** tüm BIST evrenini sıralayan faktör motoru.
- Faktörler: **Value** (F/K, PD/DD, FD/FAVÖK, FCF yield), **Momentum** (3/6/12ay),
  **Quality** (ROIC, marj istikrarı, F-score), **Low-vol**, **Size**
- Sektör-nötr z-score + birleşik skor; percentile sıralama
- Yeni araç: `rank_bist_universe(factors=..., sector_neutral=True)` → sıralı tablo
- Yeni araç: `screen_bist(criteria)` → kural-bazlı tarama
- BIST-sürtünmeli backtest: ±%10 limit, T+2, BSMV/komisyon, likidite filtresi
  ([backtest.py](../src/bist_trader_mcp/backtest.py) evren-bazlı genişletilir)

**Kabul kriterleri:** faktör IC (information coefficient) ve kademe (decile)
getiri spread'i raporlanır; backtest look-ahead-safe (Faz A `known_at` kullanır);
limit-up günü giriş engellenir.

### Faz D — Portföy & risk + füzyon kalibrasyonu
**Çıktı:** sıralamadan uygulanabilir portföye.
- Kovaryans/XU100-beta risk modeli, sektör/pozisyon limitleri
- Markowitz/risk-parity inşası ([portfolio_opt.py](../src/bist_trader_mcp/portfolio_opt.py))
- **Füzyon kalibrasyonu:** [fundamental_technical_fusion.py](../src/bist_trader_mcp/fundamental_technical_fusion.py)
  eşiklerini (52/58, ağırlıklar) ampirik hale getir — `phase4-fusion-calibration`
  notunu kapatır; temel+teknik birleşik sinyalin gerçek isabetini ölçer

**Kabul kriterleri:** birleşik sinyal için IR (information ratio), hit-rate,
reliability diagram; kalibre eşikler sihirli sayıların yerini alır.

### Faz E — Sağlamlaştırma & izlenebilirlik
- Veri tazeliği/eksik-dönem alarmları (Faz 0 stale tespitinin temele taşınması)
- KAP ingest izleme; kaynak-soyut katmana ücretli besleme adaptörü iskeleti
- WIP uçların kapatılması (MKK per-ticker yabancı oranı)

---

## 6. Eklenecek MCP araçları (özet)

| Araç | Faz | Durum | İşlev |
|---|---|---|---|
| `analyze_financial_statements` | B | ✅ | Oran/DuPont/Piotroski/Altman/Beneish/accruals + selection skoru |
| `value_equity_dcf` | B | ✅ | İki-aşamalı DCF + ters-DCF + güvenlik marjı |
| `rank_equity_universe` | C | ✅ | Kesitsel faktör sıralaması (sektör-nötr opsiyonlu) |
| `screen_equity_universe` | C | ✅ | Kural-bazlı tarama |
| `evaluate_signal_accuracy` | B/D | ✅ | Rank-IC, kuantil spread, IR — "ne kadar doğru" ölçümü |
| `backtest_factor_strategy` | C | ⏳ | BIST-sürtünmeli evren backtesti |
| `build_equity_portfolio` | D | ⏳ | Risk-modelli portföy inşası |

**Füzyon entegrasyonu (✅):** `analyze_financial_statements` çıktısı
`to_fusion_entry` ile füzyona besleniyor; statement-bazlı skor Yahoo oranlarının
önüne geçiyor ve sert red-flag'ler (manipülasyon/iflas) long'u veto ediyor.

**Veri omurgası (✅):** `data_store.PanelStore` — point-in-time (`known_at`)
panel DB, as-of/survivorship-safe okumalar. KAP parser'ı ile beslenmeyi bekliyor.

---

## 7. Başarı metrikleri

- **Temel motor:** F/Z/M skorlarının bilinen vakalarla tutarlılığı; DCF duyarlılık analizi.
- **Kuant katman:** faktör **IC > 0.03–0.05**, decile spread pozitif ve monotonik.
- **Birleşik sinyal:** **IR > 0.5** hedef, hit-rate kalibre, max drawdown kontrollü.
- **Veri bütünlüğü:** sıfır look-ahead (Faz A `known_at` testleri), survivorship-safe evren.

---

## 8. Riskler & sınırlar

- **Yahoo TMS29 distorsiyonu:** nominal veriyle temel sinyal gürültülü → KAP + reel düzeltme şart.
- **Scrape kırılganlığı:** KAP/Yahoo şema değişimi → kaynak-soyut katman + testlerle azalt.
- **KAP parse maliyeti:** XBRL/PDF kalem eşleme en emek-yoğun parça; Faz A'nın kalbi.
- **Likidite:** küçük hisselerde backtest getirisi uygulanamaz → likidite filtresi zorunlu.
- Bu bir **araştırma/karar-destek** motoru; yatırım tavsiyesi veya emir icrası değil.

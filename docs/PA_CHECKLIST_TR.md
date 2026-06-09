# Price Action + Teknik Analiz Kontrol Listesi (TR)

Teknik katman **kural tabanlıdır**; LLM dalga veya setup uydurmaz. Tam akış: [ANALYSIS_PIPELINE.md](ANALYSIS_PIPELINE.md).

## 1. Veri kalitesi
- `data_quality.flag`: yalnızca **`insufficient`** analizi durdurur
- **`thin`**: analiz çalışır; `confidence.trade_recommended` genelde kapalı
- BIST intraday: seans (10–18 Istanbul) + tatil filtresi
- HTF zayıfsa: EOD fallback (BIST hisse)

## 2. Piyasa yapısı (structure)
- HH/HL veya LH/LL — trend / geçiş / range
- BOS / CHoCH — yön onayı veya iptal
- HTF bias ↔ LTF setup uyumu (`mtf.conflict` → işlem yok)

## 3. Range & konum
- Range kutusu (yüksek/düşük/EQ)
- Discount / premium bölgesi
- Sweep + fade veya breakout setup

## 4. FVG / IFVG
- Açık FVG — **displacement** mum filtresi
- Range ile hizalı imbalance
- IFVG destek/direnç rolü
- TV: FVG ZONE etiketi (üst/alt çizgi)

## 5. Confluence & güven
- `min_pa_confluence` (profil bazlı)
- Chase gate (`max_entry_chase_atr`)
- `analysis_confidence.score` ≥ **58** ve `data_quality.ok`
- `trade_quality` ∈ a_plus, a, b

## 6. Elliott (senaryo katmanı)
- HTF birincil + LTF `elliott_mtf`
- `rules_passed` / `rules_total` — zayıf impulse → aday düşer
- HTF/LTF çelişki → `trade_candidate` false
- Kanal / fib — `report_tr`

## 7. Temel + fusion
- Canlı: `enrich_fundamental_snapshot` (KAP, funding, sektör, …)
- `fundamental_technical_fusion` — funding kalabalık long, KAP negatif, sektör RS
- **Nihai işlem:** `fusion.trade_allowed` (teknik `approved` yetmez)

## 8. Birleşik giriş

```text
run_market_assistant(symbol="...")
```

Chat: `chat_report.sections` + `ai_presentation_rules_tr`

*Yatırım tavsiyesi değildir.*

# Performans ve tutarlılık

## Performans (beklenen süre)

| Adım | Tipik maliyet | Not |
|------|---------------|-----|
| `tv_fetch_mtf_ohlcv` | ~3–5 s | 2× `sleep(1.5)` + CDP OHLCV |
| `analyze_chart_scenarios` | &lt;500 ms | Saf Python, bar sayısı ~200–300 |
| `design_scenario_trade_plan` | &lt;100 ms | `scenario_pack` ile TA **tekrar yok** |
| `enrich_fundamental_snapshot` | 1–8 s | Ağ: KAP, Yahoo, Binance, sektör EOD |
| `apply_scenario_to_chart` | 2–10 s | Çizim sayısına bağlı `sleep` |
| **Toplam RMA** | ~10–25 s | TV + tam fundamental |

### Hızlandırma

```text
run_market_assistant(
  symbol="ASELS",
  fetch_fundamentals=false,   # sadece teknik + fusion skoru düşük temel
  draw_on_chart=false,        # chat-only
  draw_when_no_trade=false,   # işlem yoksa çizim yok
)
```

- Offline analiz: `analyze_market_context` — TV gerekmez
- Watchlist: `scan_ta_fundamental_watchlist` — sembol başına aynı kapılar, batch dışı önerilir

## Tutarlılık garantileri

### Deterministik kurallar

Aynı OHLCV girdisi → aynı:

- `data_quality.flag`
- `mtf.aligned_direction`, `trade_quality`
- `trade_candidate`, `confidence.score`
- `fusion.fusion_score` (aynı `fund_enrich` ile)

Rastgelelik veya LLM sıcaklığı analiz skoruna **karışmaz**.

### Tek hesap ilkesi

`run_market_assistant` içinde:

1. `analyze_market_context` → `technical` paketi
2. `design_scenario_trade_plan(..., scenario_pack=technical)` — **ikinci PA/EW yok**

### Kapı hiyerarşisi (çelişki yok)

```text
insufficient → analiz yok
thin → analiz var, confidence genelde kapalı
trade_candidate → plana aday
approved → playbook + RR
trade_allowed → fusion + grafik pozisyonu
```

`chat_report.execution.approved` = `trade_allowed` (fusion sonrası).

### Sembol tutarlılığı

- `normalize_tv_symbol` + `tv_verify_chart_symbol`
- Uyuşmazlık → `fusion.warnings`: `tv_symbol_mismatch`

### Zaman dilimi tutarlılığı

- `resolve_assistant_config` — explicit `ltf_timeframe` / `htf_timeframe` yoksa profil default
- HTF EOD fallback yalnızca BIST equity ve zayıf TV HTF’de

## Test ve CI

```powershell
pytest -q
```

- 271+ offline test (PA, EW, fusion, session, market_assistant mock)
- GitHub Actions: `.github/workflows/pytest.yml`

Kritik test dosyaları:

- `tests/test_fusion.py`
- `tests/test_chart_scenarios.py`
- `tests/test_data_quality.py`
- `tests/test_market_assistant.py`
- `tests/test_chat_report.py`

## Canlı doğrulama checklist

1. `tv_health_check` → `success`
2. `run_market_assistant(symbol="ASELS")` → `fusion`, `chat_report.sections`
3. `data_quality.flag` ≠ `insufficient`
4. Teknik onay + fusion blok → pozisyon **çizilmemeli**
5. `chat_report.trade_allowed` ile grafik `draw_position` uyumlu

## Bilinen performans sınırları

- CDP tek iş parçacığı — paralel sembol taraması TV’de seri
- `enrich` içinde `asyncio.gather` — sektör + EOD ek istek
- Playwright (KAP) soğuk başlangıç yavaş — cache sonrası iyileşir

*Yatırım tavsiyesi değildir.*

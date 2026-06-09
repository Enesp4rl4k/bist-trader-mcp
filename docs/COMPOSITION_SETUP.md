# Claude + bist-trader-mcp (tek MCP — TradingView dahili)

Bu doküman **tek MCP** (`bist-trader`) ile Claude/Cursor akışını anlatır. TR finans datası + price-action plan + TradingView çizimi aynı sunucuda; arka planda `tradingview-mcp` Node CLI olarak çalışır (`TRADINGVIEW_MCP_PATH`).

## Yapıldı ✅ (otomatik kuruldu)

- ✅ Node.js 24.14 + npm 11.11 (zaten kuruluydu)
- ✅ `bist-trader-mcp` kurulu — `C:\Users\parlak\Downloads\tr-fixedincome-mcp\`
- ✅ `tradesdontlie/tradingview-mcp` klonlandı — `C:\Users\parlak\Downloads\tradingview-mcp\`
- ✅ npm install complete (tradingview-mcp CLI)
- ✅ Cursor `.cursor/mcp.json` — yalnızca `bist-trader` (+ `TRADINGVIEW_MCP_PATH`)
- ✅ `tv_*` proxy araçları + `run_trade_assistant` bist-trader içinde kayıtlı

## Senin yapacakların (manuel, 3 adım)

### 1. TradingView Desktop kur ve giriş yap

tradesdontlie/tradingview-mcp **TradingView Desktop app**'ı kontrol ediyor (web TV değil). Resmi indirme:

> https://www.tradingview.com/desktop/

Kur, hesabınla giriş yap. **Free hesap çalışır** ama bazı feature'lar (multi chart, custom indicator) Premium gerektirebilir.

### 2. TradingView'i Chrome DevTools Protocol (CDP) modunda başlat

MCP TV'yi `localhost:9222` portundan kontrol ediyor. Bunun için TV'yi özel bir komutla başlatmalısın. Otomatik script hazır:

```powershell
C:\Users\parlak\Downloads\tradingview-mcp\scripts\launch_tv_debug.bat
```

Bu script:
1. Mevcut TradingView.exe'leri kapatır
2. TV install lokasyonunu otomatik bulur
3. `--remote-debugging-port=9222` ile yeniden başlatır

İlk başlatma sırasında TradingView normal şekilde açılacak — fark yok, sadece arkaplanda CDP port'u açık.

Doğrulama (TV başlatıldıktan sonra, ayrı bir PowerShell'de):
```powershell
curl http://localhost:9222/json/version
```

JSON dönerse CDP aktif.

### 3. Claude Desktop'ı restart et

Config dosyası değişti — Claude Desktop'ın yeni `mcpServers` listesini görmesi için **tamamen kapatıp yeniden açmak gerek** (system tray'dan da kapat).

Yeniden açıldığında settings → MCP bölümünde **yalnızca** `bist-trader` görünmeli (Connected). İkinci `tradingview` satırını config'den kaldırabilirsin — aynı iş `tv_health_check`, `tv_fetch_mtf_ohlcv`, `run_trade_assistant` ile yapılır.

## İlk test (Claude'a yaz)

Yeni bir chat aç ve **TV Desktop açıkken** sırayla şunları dene:

### Health check
```
bist-trader'dan list_pine_recipes çağır
```
→ 2 recipe listesini görmeli (tr_macro_backdrop, tr_basis_monitor)

### TradingView bağlantı testi
```
tv_health_check çalıştır
```
→ TV Desktop'un CDP üzerinden bağlı olduğunu doğrular

### İlk gerçek workflow
```
BIST30 sembolünü TradingView'da aç, üzerine TR makro snapshot
(TCMB politika faizi + TLREF + CPI YoY) indicator'ı ekle
```

Claude şunları yapmalı:
1. `bist-trader.render_pine_recipe(name="tr_macro_backdrop", auto_fetch=true)` → live data + Pine code
2. `tv_chart_set_symbol("BIST:XU030")` → TV BIST30'a geçer
3. Pine inject için `apply_trade_to_chart` veya manuel Pine (PA trade için `run_trade_assistant` önerilir)

Üst sağda canlı verilerle bir snapshot table görmelisin (~40% policy, ~32% CPI YoY).

## Troubleshooting

### "bist-trader is disconnected" / "failed to start"

Genellikle path veya Python venv sorunu. Test:
```powershell
C:\Users\parlak\Downloads\tr-fixedincome-mcp\.venv\Scripts\python.exe -m bist_trader_mcp --help
```
Komut hata verirse venv broken — `pip install -e ".[dev,browser]"` ile yeniden kur.

### "tv_health_check / CDP failed" (ECONNREFUSED localhost:9222)

TV Desktop CDP mode'da başlatılmamış. Tekrar `launch_tv_debug.bat` çalıştır.

### TV açılıyor ama chart'a tepki vermiyor

Genelde TV Desktop tamamen başlatılmadan Claude komut göndermiş. 5-10 sn bekle, sonra yeniden dene.

### "WAF rejected" mesajları (KAP / Takasbank ilk çağrıda)

Beklenir. Cache içinden ikinci çağrı çalışır (5 dakika TTL). Veya 1-2 dakika sonra tekrar dene.

## Konum özetı

| Şey | Yeri |
|---|---|
| Claude Desktop config | `C:\Users\parlak\AppData\Roaming\Claude\claude_desktop_config.json` |
| Config backup | `…\claude_desktop_config.json.backup_20260511_212352` |
| bist-trader-mcp | `C:\Users\parlak\Downloads\tr-fixedincome-mcp\` |
| tradingview-mcp | `C:\Users\parlak\Downloads\tradingview-mcp\` |
| TV CDP launcher | `C:\Users\parlak\Downloads\tradingview-mcp\scripts\launch_tv_debug.bat` |
| TCMB EVDS key (env'de) | `IoIJuWdAOb` (bist-trader env içinde) |

## Piyasa profilleri (BIST / VIOP / kripto)

`get_market_profile(symbol)` otomatik algılar ve ayarlar:

| Sınıf | Örnek sembol | HTF / LTF | Risk |
|--------|----------------|-----------|------|
| Kripto | `BINANCE:BTCUSDT`, `ETHUSDT` | 4H / 1H | %0.75, notional cap %12 |
| BIST hisse | `THYAO`, `BIST:GARAN` | Gün / 1H | %1, cap %20 |
| BIST endeks | `XU030`, `XU100` | Gün / 1H | min kalite A+ |
| VIOP vadeli | `F_XU0300625` | 4H / 15m | %0.5, cap %15 |
| VIOP opsiyon | `O_XU0300625_C5500` | 4H / 15m | %0.35, cap %8 |

Asistanlar (`run_scenario_assistant`, `run_trade_assistant`) timeframe vermeden de çalışır — profil varsayılanlarını kullanır. VIOP için ek bağlam: `get_viop_term_structure`, `get_viop_dashboard`.

## Tek MCP Cursor config örneği

```json
{
  "mcpServers": {
    "bist-trader": {
      "command": "C:\\Users\\parlak\\Downloads\\tr-fixedincome-mcp\\.venv\\Scripts\\python.exe",
      "args": ["-m", "bist_trader_mcp"],
      "env": {
        "TRADINGVIEW_MCP_PATH": "C:\\Users\\parlak\\Downloads\\tradingview-mcp"
      }
    }
  }
}
```

## İki MCP'yi geçici olarak kapatmak

Claude Desktop config'i editle, `mcpServers` altındaki sunucuları kaldır veya yeniden adlandır. Sonra restart. **Mevcut backup ile geri dönülebilir.**

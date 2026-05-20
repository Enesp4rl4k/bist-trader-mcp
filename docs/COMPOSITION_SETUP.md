# Claude + bist-trader-mcp + tradingview-mcp birlikte kullanım

Bu doküman senin makinende **iki MCP'yi Claude Desktop'a bağlama** akışını anlatır. Yan yana çalıştığında Claude TR finans datasını çekiyor, sonra TradingView Desktop'a Pine indicator + chart annotation + alert basıyor.

## Yapıldı ✅ (otomatik kuruldu)

- ✅ Node.js 24.14 + npm 11.11 (zaten kuruluydu)
- ✅ `bist-trader-mcp` kurulu — `C:\Users\parlak\Downloads\tr-fixedincome-mcp\`
- ✅ `tradesdontlie/tradingview-mcp` klonlandı — `C:\Users\parlak\Downloads\tradingview-mcp\`
- ✅ npm install complete (78 tool hazır)
- ✅ Server.js plain start verified (no import/syntax errors)
- ✅ Claude Desktop config güncellendi: `%APPDATA%\Claude\claude_desktop_config.json`
  - Mevcut `preferences` korundu
  - `mcpServers` eklendi: `bist-trader` + `tradingview`
  - Backup: `claude_desktop_config.json.backup_20260511_212352`
- ✅ Tüm path'ler exists ve valid

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

Yeniden açıldığında settings → MCP bölümünde iki sunucu görünmeli:
- `bist-trader` (Python)
- `tradingview` (Node)

İkisi de "Connected" durumunda olmalı. **Eğer hata varsa**: Settings → MCP → Logs bölümünde stderr'leri gör.

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
2. `tradingview.chart_set_symbol("BIST:XU030")` → TV BIST30'a geçer
3. `tradingview.pine_new(source=...)` → Pine editor açılır
4. `tradingview.pine_smart_compile()` → indicator chart'a düşer

Üst sağda canlı verilerle bir snapshot table görmelisin (~40% policy, ~32% CPI YoY).

## Troubleshooting

### "bist-trader is disconnected" / "failed to start"

Genellikle path veya Python venv sorunu. Test:
```powershell
C:\Users\parlak\Downloads\tr-fixedincome-mcp\.venv\Scripts\python.exe -m bist_trader_mcp --help
```
Komut hata verirse venv broken — `pip install -e ".[dev,browser]"` ile yeniden kur.

### "tradingview: ECONNREFUSED localhost:9222"

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

## İki MCP'yi geçici olarak kapatmak

Claude Desktop config'i editle, `mcpServers` altındaki sunucuları kaldır veya yeniden adlandır. Sonra restart. **Mevcut backup ile geri dönülebilir.**

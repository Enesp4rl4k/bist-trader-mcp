"""Guided workflows (MCP prompts) for the daily trading loop.

A prompt is a ready-made instruction the user picks in the AI app ("/" menu
or prompt list); the model then calls the right tools in the right order.
Each workflow lists the tools it relies on in ``tools`` — a test checks they
are all registered, so a renamed tool cannot silently break a workflow.

Shared rules for every workflow (``_RULES``): never invent numbers, say where
data came from, state assumptions, end with "yatırım tavsiyesi değildir".
"""

from __future__ import annotations

from typing import Any

_RULES = (
    "\nKurallar:\n"
    "- Rakam uydurma: her sayı bir araç çıktısından gelsin; araç hata verirse bunu "
    "açıkça yaz ve o bölümü atla.\n"
    "- Veri kaynağını belirt (data_source / sources alanları: TradingView, Yahoo, "
    "kullanıcı, varsayılan). Varsayılan bir varsayım kullanıldıysa söyle.\n"
    "- Kısa, başlıklı, Türkçe yaz. Önce sonuç, sonra gerekçe.\n"
    "- Sonunda: 'Yatırım tavsiyesi değildir.'"
)


def _sym(args: dict[str, Any]) -> str:
    return str(args.get("symbol") or "THYAO").strip().upper()


def _int(value: Any, default: int) -> int:
    """Prompt arguments arrive as free text; never crash on 'beş' or ''."""
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


WORKFLOWS: dict[str, dict[str, Any]] = {
    "hisse-analizi": {
        "description": "Bir hisseyi baştan sona incele: sade PA, 30 olası gelecek, "
                       "şirket olayları, değerleme, KAP ve risk kontrolü — tek rapor.",
        "arguments": [("symbol", "Hisse kodu (ör. THYAO)", True),
                      ("risk_free", "TL risksiz faiz, ondalık (ör. 0.30) — değerleme için",
                       False),
                      ("expected_inflation", "Beklenen enflasyon, ondalık (ör. 0.25)", False)],
        "tools": ["get_simple_price_action", "forecast_next_candles", "get_company_events",
                  "value_company", "get_kap_disclosures", "check_trade_risk"],
        "render": lambda a: (
            f"{_sym(a)} için tam hisse analizi yap:\n"
            f"1. get_simple_price_action(symbol='{_sym(a)}') — trend, destek/direnç, karar.\n"
            f"2. forecast_next_candles(symbol='{_sym(a)}', save_html=true) — yukarı/aşağı %, "
            "aralık; html_path'i ver.\n"
            f"3. get_company_events(symbols=['{_sym(a)}']) — bilanço penceresi, temettü, "
            "sermaye değişikliği.\n"
            + (f"4. value_company(symbol='{_sym(a)}', risk_free={a['risk_free']}"
               + (f", expected_inflation={a['expected_inflation']}"
                  if a.get("expected_inflation") else "")
               + ") — harmanlanmış değer, güvenlik marjı, Monte Carlo olasılığı, "
                 "sanity notları.\n"
               if a.get("risk_free") else
               "4. Değerleme için kullanıcıya risksiz faizi (10Y DİBS) sor; verirse "
               "value_company çalıştır, vermezse bu adımı atla.\n")
            + f"5. get_kap_disclosures(company='{_sym(a)}', only_material=true) — son önemli "
              "bildirimler.\n"
            "6. Adım 1'de plan varsa check_trade_risk ile lot ve risk kontrolü yap.\n"
            "Rapor bölümleri: Özet karar · Teknik · Olasılıklar · Temel/Değerleme · "
            "Olaylar ve KAP · Risk (lot, uyarılar)." + _RULES
        ),
    },
    "sabah-brifingi": {
        "description": "Güne başlarken: piyasa özeti, açık pozisyonlar ve risk, kağıt hesap, "
                       "yeni uyarılar, bugünün olayları ve haber akışı.",
        "arguments": [],
        "tools": ["get_market_summary", "get_global_pulse", "get_portfolio_risk",
                  "get_paper_account", "check_alerts", "get_company_events",
                  "get_economic_calendar", "get_news_headlines"],
        "render": lambda a: (
            "Sabah brifingi hazırla:\n"
            "1. get_market_summary() ve get_global_pulse(categories=['indices','commodities']) "
            "— XU100, TL, emtia, global endeksler.\n"
            "2. get_portfolio_risk() — açık risk, devre kesici, korelasyon.\n"
            "3. get_paper_account() — kağıt hesap durumu ve canlı/backtest kararı.\n"
            "4. check_alerts(send=false) — stopa yaklaşanlar, KAP.\n"
            "5. get_company_events() — açık pozisyonlarda bilanço/temettü riski.\n"
            "6. get_economic_calendar() — bugün ve bu hafta PPK/TÜFE.\n"
            "7. get_news_headlines() — TR'yi etkileyebilecek 3–5 başlık.\n"
            "Sonuç: 'Bugün dikkat' maddeleri (en fazla 5) + pozisyon başına tek satır." + _RULES
        ),
    },
    "aksam-rutini": {
        "description": "Kapanıştan sonra: günlük döngüyü çalıştır, seçimleri ve risk "
                       "reddedilenleri özetle, kağıt hesabı güncelle.",
        "arguments": [("top_n", "Kaydedilecek en iyi plan sayısı (varsayılan 5)", False)],
        "tools": ["start_job", "get_job", "get_paper_account"],
        "render": lambda a: (
            "Akşam rutini:\n"
            f"1. start_job(kind='daily_pipeline', args={{'top_n': {_int(a.get('top_n'), 5)}}}) "
            "başlat; get_job(job_id) ile bitene kadar takip et (birkaç dakika sürebilir).\n"
            "2. Sonuçtan: kapanan/dolan işlemler (tracked_changes), bugünün seçimleri ve "
            "lotları, risk nedeniyle reddedilenler (risk_rejected), html_path.\n"
            "3. get_paper_account() — güncel sermaye, düşüş, canlı/backtest kararı.\n"
            "Tablo: Sembol · Karar · Giriş · Stop · Hedef · Lot · Not." + _RULES
        ),
    },
    "sirket-degerleme": {
        "description": "Şirket değerlemesi: DCF (banka ise artık gelir), duyarlılık, "
                       "senaryolar, Monte Carlo, emsaller ve varsayım kontrolü.",
        "arguments": [("symbol", "Hisse kodu", True),
                      ("risk_free", "TL risksiz faiz, ondalık (ör. 0.30)", True),
                      ("expected_inflation", "Beklenen enflasyon, ondalık", False),
                      ("peers", "Virgülle emsal kodları (ör. PGSUS,TAVHL)", False)],
        "tools": ["value_company", "estimate_equity_beta", "get_company_events"],
        "render": lambda a: (
            f"{_sym(a)} değerlemesi:\n"
            f"1. value_company(symbol='{_sym(a)}', risk_free={a.get('risk_free', '?')}"
            + (f", expected_inflation={a['expected_inflation']}"
               if a.get("expected_inflation") else "")
            + (", peers=[" + ", ".join(f"'{p.strip().upper()}'" for p in
                                      str(a["peers"]).split(",") if p.strip()) + "]"
               if a.get("peers") else "")
            + ")\n"
            "2. 'sources' alanından hangi girdilerin varsayılan olduğunu listele ve "
            "kullanıcıya en kritik 2–3 varsayımı (büyüme, marj, WACC) sor/teyit ettir.\n"
            "3. Duyarlılık tablosundan değerin hangi aralıkta olduğunu ve fiyatın bu "
            "tabloda nereye düştüğünü anlat; senaryolar ve Monte Carlo olasılığı.\n"
            "4. 'notes' (sanity) uyarılarını mutlaka aktar. Beta'nın R²'si düşükse "
            f"(< 0.2) estimate_equity_beta(symbol='{_sym(a)}') ile kontrol et ve sektör "
            "betasıyla karşılaştırmayı öner.\n"
            f"5. get_company_events(symbols=['{_sym(a)}']) — yaklaşan bilanço riski.\n"
            "Sonuç: değer aralığı (düşük/baz/yüksek), güvenlik marjı, en önemli varsayım."
            + _RULES
        ),
    },
    "strateji-dogrulama": {
        "description": "Sistemi gerçek veride ölç: evren backtest'i (ağırlık öğrenme dahil), "
                       "tahmin kalibrasyonu ve kağıt hesap — kabul kriterlerine göre karar.",
        "arguments": [("timeframe", "Periyot (varsayılan 1D)", False)],
        "tools": ["start_job", "get_job", "evaluate_forecast_accuracy", "get_paper_account"],
        "render": lambda a: (
            "Strateji doğrulaması (TradingView açık olmalı):\n"
            f"1. start_job(kind='backtest_universe', args={{'timeframe': "
            f"'{a.get('timeframe') or '1D'}', 'save_weights': true}}) — get_job ile bekle.\n"
            "2. evaluate_forecast_accuracy(symbol='THYAO') ve bir de XU030 için.\n"
            "3. get_paper_account().\n"
            "Kabul kriterleri: evrende ≥ 200 işlem ve maliyet sonrası beklenti > 0; tahmin "
            "p10–p90 kapsaması %65–92; 20+ kağıt işlemde canlı beklenti ≥ backtestin yarısı.\n"
            "Her kriter için GEÇTİ/KALDI/YETERSİZ yaz; kalanlar için ne değişmeli öner. "
            "Öğrenilen ağırlıklar aktif mi (weights.active) ve örneklem dışı sonuç ne?"
            + _RULES
        ),
    },
    "haftalik-degerlendirme": {
        "description": "Haftalık gözden geçirme: kapanan işlemler, kazandıran/kaybettiren "
                       "kurulumlar, risk kullanımı ve çıkarılacak dersler.",
        "arguments": [],
        "tools": ["get_paper_account", "list_trade_journal", "get_portfolio_risk",
                  "get_alerts"],
        "render": lambda a: (
            "Haftalık değerlendirme:\n"
            "1. get_paper_account() — haftalık sonuç, düşüş, son işlemler.\n"
            "2. list_trade_journal(limit=50) — bu hafta kapanan işlemler; kurulum tipine "
            "(plan_snapshot.setup_type) göre grupla: işlem sayısı, ort. R.\n"
            "3. get_portfolio_risk() — risk bütçesinin ne kadarı kullanıldı.\n"
            "4. get_alerts(limit=50) — kaçırılan / stopa yakın uyarılar.\n"
            "Çıktı: 3 iyi giden, 3 kötü giden, 3 somut ders. Kural ihlali (lot, korelasyon, "
            "bilanço öncesi işlem) varsa işaretle." + _RULES
        ),
    },
}


__all__ = ["WORKFLOWS"]

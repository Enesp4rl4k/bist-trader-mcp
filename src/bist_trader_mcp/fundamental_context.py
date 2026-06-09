"""Fundamental / macro context hints — pairs with technical PA pipeline."""

from __future__ import annotations

from typing import Any

from .market_profiles import get_market_profile


def build_fundamental_context(
    symbol: str,
    *,
    market: str | None = None,
) -> dict[str, Any]:
    """Sync research checklist and MCP tools for fundamental layer (no network)."""
    prof = get_market_profile(symbol, market=market)
    ac = prof["asset_class"]
    core = symbol.split(":")[-1].upper()

    tools: list[str] = []
    checklist_tr: list[str] = []
    focus = ""

    if ac == "bist_equity":
        tools = [
            "get_kap_disclosures",
            "get_bist_snapshot",
            "get_bist_eod_ohlcv",
            "get_bist_sector_rotation",
            "get_mkk_market_stats",
        ]
        checklist_tr = [
            f"Son KAP bildirimleri ({core}): bilanço, sermaye, temettü, özel durum.",
            "Sektör rotasyonu: XU100 / sektör endeksi ile göreli güç.",
            "MKK yabancı/takas eğilimi (aylık bulletin).",
            "Makro: TCMB EVDS faiz/enflasyon (get_evds_series).",
            "Tarım/gıda (XGIDA): get_turib_endeks_overview — buğday/mısır/arpa endeksleri.",
        ]
        tools.append("get_turib_endeks_overview")
        focus = "BIST hisse — KAP + sektör + makro (+ TÜRİB tarım endeksi gıda için) ile teknik doğrula."
    elif ac == "bist_index":
        tools = ["get_bist_snapshot", "get_bist_eod_ohlcv", "get_mkk_market_stats", "get_evds_series"]
        checklist_tr = [
            "Endeks bileşen ağırlıkları ve sektör liderleri.",
            "Makro veri takvimi (PPK, enflasyon).",
        ]
        focus = "BIST endeks — makro ve breadth."
    elif ac in ("viop_future", "viop_option"):
        tools = prof.get("viop_tools") or [
            "get_viop_term_structure",
            "get_viop_dashboard",
            "get_viop_settlement",
        ]
        underlying = prof.get("underlying") or core
        checklist_tr = [
            f"VİOP vade yapısı ({underlying}): contango/backwardation.",
            "Teminat ve açık pozisyon (dashboard).",
            "Opsiyonda IV yüzeyi / skew (opsiyon sınıfı).",
        ]
        focus = "VIOP — term structure + margin; teknik yönü vade ile hizala."
    elif ac == "crypto":
        tools = ["get_crypto_klines", "get_deribit_options_summary"]
        checklist_tr = [
            "Funding / open interest (borsa verisi).",
            "Makro risk (DXY, faiz) — EVDS veya haber.",
        ]
        focus = "Kripto — likidite ve türev metrikleri ile PA."
    else:
        tools = ["get_evds_series"]
        checklist_tr = ["Piyasa sınıfını market= ile belirt (bist / viop / crypto)."]
        focus = "Genel — önce get_market_profile."

    return {
        "source": "bist-trader-mcp — fundamental_context",
        "symbol": symbol,
        "asset_class": ac,
        "symbol_tv": prof["symbol_tv"],
        "recommended_mcp_tools": tools,
        "research_checklist_tr": checklist_tr,
        "focus_tr": focus,
        "disclaimer": "Temel analiz MCP araçlarıyla yapılır; otomatik işlem yok.",
    }


def merge_ta_fundamental_summary(
    *,
    ta_summary_tr: str,
    fundamental: dict[str, Any],
    elliott_mtf: dict[str, Any] | None = None,
) -> str:
    """Combined executive lines for assistants."""
    lines = [ta_summary_tr, f"Temel: {fundamental.get('focus_tr', '')}"]
    if elliott_mtf:
        lines.append(elliott_mtf.get("notes_tr", ""))
    return "\n".join(lines)


__all__ = ["build_fundamental_context", "merge_ta_fundamental_summary"]

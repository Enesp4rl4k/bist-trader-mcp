"""TÜRİB (Türkiye Ürün İhtisas Borsası) — public market data (info-only).

Licensed real-time / depth feeds require a TÜRİB data distribution contract
(see https://www.turib.com.tr/turib-verileri-listesi/). This module only
surfaces **public** index overview from the website for macro/commodity context.
"""

from __future__ import annotations

import re
from typing import Any

from ._cache import cache_get, cache_set
from .http_utils import SourceError, fetch_text

TURIB_BASE = "https://www.turib.com.tr"
TURIB_ENDEKS_URL = f"{TURIB_BASE}/endeks-anasayfa/"
CACHE_KEY = "turib_endeks_overview"
CACHE_TTL = 6 * 3600

# Curated index labels (ELÜS / hububat) — aligns with XGIDA / food sector reads
TURIB_INDEX_CATALOG: dict[str, str] = {
    "hububat": "TÜRİB Hububat Endeksi",
    "bugday": "TÜRİB Buğday Endeksi",
    "bugday_ekmeklik": "TÜRİB Buğday Ekmeklik Endeksi",
    "bugday_makarnalik": "TÜRİB Buğday Makarnalık Endeksi",
    "misir": "TÜRİB Mısır Endeksi",
    "misir_1": "TÜRİB Mısır 1.Sınıf Endeksi",
    "misir_2": "TÜRİB Mısır 2.Sınıf Endeksi",
    "arpa": "TÜRİB Arpa Endeksi",
}

DATA_SOURCES_DOC = {
    "public_website": [
        TURIB_ENDEKS_URL,
        f"{TURIB_BASE}/piyasa-verileri/",
        f"{TURIB_BASE}/tarihsel-veri/",
    ],
    "licensed_feeds": f"{TURIB_BASE}/turib-verileri-listesi/",
    "distributors": f"{TURIB_BASE}/veri-dagitim-sirketleri/",
    "legal": (
        "Site verileri bilgi amaçlıdır; ticari yeniden dağıtım için TÜRİB sözleşmesi gerekir."
    ),
}


def _parse_endeks_cards(html: str) -> list[dict[str, Any]]:
    """Best-effort parse of endeks homepage cards (HTML may be JS-hydrated)."""
    cards: list[dict[str, Any]] = []
    re.split(r"(?i)(hububat|buğday|bugday|mısır|misir|arpa)\s*endeks", html)
    for label, key in (
        ("Hububat Endeksi", "hububat"),
        ("Buğday Endeksi", "bugday"),
        ("Buğday Ekmeklik Endeksi", "bugday_ekmeklik"),
        ("Buğday Makarnalık Endeksi", "bugday_makarnalik"),
        ("Mısır Endeksi", "misir"),
        ("Arpa Endeksi", "arpa"),
    ):
        idx = html.lower().find(label.lower().replace("ğ", "g"))
        if idx < 0:
            continue
        window = html[idx : idx + 400]
        pct = re.search(r"([+-]?\d+[,.]?\d*)\s*%", window)
        level = re.search(r"(\d{3,5}[,.]\d{1,4})", window)
        cards.append(
            {
                "id": key,
                "name": TURIB_INDEX_CATALOG.get(key, label),
                "change_pct": float(pct.group(1).replace(",", ".")) if pct else None,
                "level_hint": float(level.group(1).replace(",", ".")) if level else None,
                "parse_confidence": "low" if not pct else "medium",
            }
        )
    return cards


async def fetch_turib_endeks_overview(*, use_cache: bool = True) -> dict[str, Any]:
    """Public TÜRİB index overview (delayed / informational)."""
    if use_cache:
        hit = cache_get(CACHE_KEY)
        if hit:
            return hit

    try:
        html = await fetch_text(TURIB_ENDEKS_URL, headers={"Accept-Language": "tr-TR,tr;q=0.9"})
    except SourceError as e:
        out = {
            "source": "bist-trader-mcp — turib.fetch_turib_endeks_overview",
            "error": "fetch_failed",
            "detail": str(e),
            "data_sources": DATA_SOURCES_DOC,
            "catalog": TURIB_INDEX_CATALOG,
        }
        return out

    indices = _parse_endeks_cards(html)
    out = {
        "source": "bist-trader-mcp — turib.fetch_turib_endeks_overview",
        "as_of": "website_snapshot",
        "indices": indices,
        "index_count": len(indices),
        "catalog": TURIB_INDEX_CATALOG,
        "data_sources": DATA_SOURCES_DOC,
        "mcp_usage_tr": (
            "Gıda/tarım hisseleri (XGIDA) ve makro bağlam: buğday/mısır endeksi trendi "
            "ile BIST teknik senaryoyu çapraz kontrol. Canlı işlem verisi için lisanslı dağıtıcı."
        ),
        "disclaimer": DATA_SOURCES_DOC["legal"],
    }
    if use_cache:
        cache_set(CACHE_KEY, out, CACHE_TTL)
    return out


__all__ = [
    "TURIB_INDEX_CATALOG",
    "DATA_SOURCES_DOC",
    "fetch_turib_endeks_overview",
]

"""Global markets snapshot — extends bist_snapshot to cover non-TR assets.

Wraps Yahoo Finance v8 chart API to return one-shot snapshots for:
- US equity indices: SPX, NDX, DJI, RUT, VIX
- European: DAX, FTSE, CAC, IBEX, FTSE MIB, STOXX 50
- Asian: Nikkei, Hang Seng, Shanghai, Kospi, ASX
- US treasury yields: 2Y, 10Y, 30Y (^IRX, ^FVX, ^TNX, ^TYX)
- Commodities: WTI, Brent, Gold, Silver, Copper, Natural Gas, Wheat, Corn
- Crypto majors (Yahoo's representation): BTC, ETH, SOL, BNB, XRP

Idea: single tool call → full global pulse, similar to get_market_summary
but cross-region. Combine with technicals for "where's everything today".
"""

from __future__ import annotations

import asyncio

from .bist_snapshot import PriceSnapshot, fetch_snapshot

GLOBAL_INDICES = {
    # US
    "SPX":      "^GSPC",     # S&P 500
    "NDX":      "^NDX",       # Nasdaq 100
    "DJI":      "^DJI",
    "RUT":      "^RUT",
    "VIX":      "^VIX",
    # Europe
    "DAX":      "^GDAXI",
    "FTSE":     "^FTSE",
    "CAC":      "^FCHI",
    "IBEX":     "^IBEX",
    "FTSEMIB":  "FTSEMIB.MI",
    "STOXX50":  "^STOXX50E",
    # Asia
    "N225":     "^N225",      # Nikkei
    "HSI":      "^HSI",       # Hang Seng
    "SHANGHAI": "000001.SS",  # Shanghai composite
    "KOSPI":    "^KS11",
    "ASX200":   "^AXJO",
}

US_TREASURIES = {
    "UST_3M":  "^IRX",
    "UST_5Y":  "^FVX",
    "UST_10Y": "^TNX",
    "UST_30Y": "^TYX",
}

COMMODITIES = {
    "WTI":         "CL=F",
    "BRENT":       "BZ=F",
    "GOLD":        "GC=F",
    "SILVER":      "SI=F",
    "COPPER":      "HG=F",
    "NATGAS":      "NG=F",
    "WHEAT":       "ZW=F",
    "CORN":        "ZC=F",
    "PLATINUM":    "PL=F",
}

CRYPTO_MAJORS = {
    "BTCUSD":  "BTC-USD",
    "ETHUSD":  "ETH-USD",
    "SOLUSD":  "SOL-USD",
    "BNBUSD":  "BNB-USD",
    "XRPUSD":  "XRP-USD",
    "ADAUSD":  "ADA-USD",
    "DOGEUSD": "DOGE-USD",
}

# Curated default set for "what's the global market doing right now"
GLOBAL_PULSE_ALIASES = {
    **{k: v for k, v in GLOBAL_INDICES.items() if k in
       ("SPX", "NDX", "VIX", "DAX", "FTSE", "N225", "HSI")},
    **{k: v for k, v in US_TREASURIES.items() if k in ("UST_10Y", "UST_2Y", "UST_30Y")},
    **{k: v for k, v in COMMODITIES.items() if k in
       ("WTI", "GOLD", "SILVER", "COPPER", "NATGAS")},
    **{k: v for k, v in CRYPTO_MAJORS.items() if k in ("BTCUSD", "ETHUSD")},
}


async def fetch_global_pulse(
    categories: list[str] | None = None,
) -> dict[str, dict[str, PriceSnapshot]]:
    """One-shot snapshot of global markets, bucketed by category.

    Args:
        categories: any subset of {"indices","treasuries","commodities","crypto"}.
            Defaults to all.
    """
    cats = set(categories or ["indices", "treasuries", "commodities", "crypto"])
    out: dict[str, dict[str, PriceSnapshot]] = {}

    tasks = []
    cat_for = []

    def add(category: str, aliases: dict[str, str]):
        symbols = list(aliases.values())
        aliases_list = list(aliases.keys())
        tasks.append(fetch_snapshot(symbols))
        cat_for.append((category, aliases_list, symbols))

    if "indices" in cats:
        add("indices", GLOBAL_INDICES)
    if "treasuries" in cats:
        add("treasuries", US_TREASURIES)
    if "commodities" in cats:
        add("commodities", COMMODITIES)
    if "crypto" in cats:
        add("crypto", CRYPTO_MAJORS)

    if not tasks:
        return out

    results = await asyncio.gather(*tasks, return_exceptions=True)
    for (category, aliases_list, symbols), result in zip(cat_for, results,
                                                          strict=False):
        if isinstance(result, BaseException):
            out[category] = {}
            continue
        bucket: dict[str, PriceSnapshot] = {}
        # fetch_snapshot returns list aligned with symbols input
        if isinstance(result, list):
            for alias, snap in zip(aliases_list, result, strict=False):
                if isinstance(snap, PriceSnapshot):
                    bucket[alias] = snap
        out[category] = bucket
    return out


__all__ = [
    "GLOBAL_INDICES",
    "US_TREASURIES",
    "COMMODITIES",
    "CRYPTO_MAJORS",
    "GLOBAL_PULSE_ALIASES",
    "fetch_global_pulse",
]

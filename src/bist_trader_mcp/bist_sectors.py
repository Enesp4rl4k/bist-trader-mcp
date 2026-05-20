"""BIST sector index rotation analysis.

Pulls BIST sector indices via Yahoo Finance EOD (already-integrated) and
computes relative-strength scores, momentum ranks, and correlations vs.
XU100 / XU030 — the canonical inputs for a sector rotation strategy.

Sectors covered (Yahoo symbols):
    XBANK   ^XBANK     Banks
    XUMAL   ^XUMAL     Financials (broad)
    XUSIN   ^XUSIN     Industrials
    XGIDA   ^XGIDA     Food & Beverage
    XKAGT   ^XKAGT     Paper & Pulp
    XKMYA   ^XKMYA     Chemistry/Petroleum/Plastics
    XELKT   ^XELKT     Electricity
    XHOLD   ^XHOLD     Holding & Investment
    XINSA   ^XINSA     Construction
    XTRZM   ^XTRZM     Tourism
    XMANA   ^XMANA     Retail
    XULAS   ^XULAS     Transportation
    XILTM   ^XILTM     Communications
    XBLSM   ^XBLSM     IT
    XTEKS   ^XTEKS     Textile, Leather
    XGMYO   ^XGMYO     REIT
    XSPOR   ^XSPOR     Sports
"""

from __future__ import annotations

import asyncio
from typing import Any

from .bist_eod import fetch_eod_ohlcv

BIST_SECTORS: dict[str, str] = {
    "XBANK":  "^XBANK",
    "XUMAL":  "^XUMAL",
    "XUSIN":  "^XUSIN",
    "XGIDA":  "^XGIDA",
    "XKAGT":  "^XKAGT",
    "XKMYA":  "^XKMYA",
    "XELKT":  "^XELKT",
    "XHOLD":  "^XHOLD",
    "XINSA":  "^XINSA",
    "XTRZM":  "^XTRZM",
    "XMANA":  "^XMANA",
    "XULAS":  "^XULAS",
    "XILTM":  "^XILTM",
    "XBLSM":  "^XBLSM",
    "XTEKS":  "^XTEKS",
    "XGMYO":  "^XGMYO",
    "XSPOR":  "^XSPOR",
}

BENCHMARK_DEFAULT = "XU100"  # XU100 → ^XU100


async def fetch_sector_closes(
    sectors: list[str] | None = None,
    period: str = "3mo",
) -> dict[str, list[float]]:
    """Fetch EOD closes for multiple BIST sector indices in parallel.

    Args:
        sectors: subset of BIST_SECTORS keys. Defaults to all.
        period: Yahoo Finance range string (1mo, 3mo, 6mo, 1y, 2y, ...).

    Returns {alias: [closes,...]}. Failed fetches are skipped silently.
    """
    selected = sectors or list(BIST_SECTORS.keys())
    tickers = [BIST_SECTORS[s] for s in selected if s in BIST_SECTORS]
    aliases = [s for s in selected if s in BIST_SECTORS]

    tasks = [fetch_eod_ohlcv(t, period=period) for t in tickers]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    out: dict[str, list[float]] = {}
    for alias, res in zip(aliases, results, strict=False):
        if isinstance(res, BaseException):
            continue
        if not isinstance(res, list):
            continue
        closes = [bar.get("close") for bar in res
                   if isinstance(bar, dict) and bar.get("close") is not None]
        if len(closes) >= 5:
            out[alias] = [float(c) for c in closes]
    return out


def compute_rotation_metrics(
    sector_closes: dict[str, list[float]],
    benchmark_closes: list[float] | None = None,
    lookback_bars: int = 21,
) -> dict[str, Any]:
    """Compute rotation metrics for each sector.

    Metrics per sector:
      - return_total_pct: total return over lookback
      - return_recent_pct: most recent 5-bar return
      - relative_strength: (sector_return / benchmark_return) - 1
      - rank: 1 = strongest, N = weakest by total return

    Args:
        sector_closes: {alias: closes}.
        benchmark_closes: optional benchmark (e.g. XU100) for RS.
        lookback_bars: trailing window for total return.

    Returns dict with `sectors` list sorted by rank ascending (strongest first).
    """
    rows = []
    for alias, closes in sector_closes.items():
        if len(closes) < 6:
            continue
        window = closes[-lookback_bars:] if len(closes) >= lookback_bars else closes
        total = (window[-1] / window[0] - 1) * 100 if window[0] > 0 else None
        recent = (closes[-1] / closes[-6] - 1) * 100 if closes[-6] > 0 else None
        rs = None
        if benchmark_closes and len(benchmark_closes) >= len(window):
            bench_window = benchmark_closes[-len(window):]
            if bench_window[0] > 0:
                bench_ret = (bench_window[-1] / bench_window[0] - 1) * 100
                if bench_ret != 0 and total is not None:
                    rs = total - bench_ret
        rows.append({
            "sector": alias,
            "return_total_pct": round(total, 3) if total is not None else None,
            "return_recent_pct": round(recent, 3) if recent is not None else None,
            "relative_strength_vs_benchmark_pct":
                round(rs, 3) if rs is not None else None,
            "last_close": closes[-1],
        })

    # Rank by total return descending
    valid = [r for r in rows if r["return_total_pct"] is not None]
    valid.sort(key=lambda r: r["return_total_pct"], reverse=True)
    for i, r in enumerate(valid):
        r["rank"] = i + 1
    nulls = [r for r in rows if r["return_total_pct"] is None]

    return {
        "lookback_bars": lookback_bars,
        "sector_count": len(rows),
        "top_3_sectors": [r["sector"] for r in valid[:3]],
        "bottom_3_sectors": [r["sector"] for r in valid[-3:][::-1]],
        "sectors": valid + nulls,
    }


__all__ = [
    "BIST_SECTORS",
    "BENCHMARK_DEFAULT",
    "fetch_sector_closes",
    "compute_rotation_metrics",
]

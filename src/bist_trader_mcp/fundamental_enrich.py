"""Fetch live fundamental snapshots to pair with technical analysis."""

from __future__ import annotations

import asyncio
from typing import Any

from .bist_eod import fetch_eod_ohlcv
from .bist_sectors import (
    BENCHMARK_DEFAULT,
    compute_rotation_metrics,
    fetch_sector_closes,
)
from .bist_snapshot import fetch_snapshot
from .crypto import fetch_funding_rates, fetch_open_interest_history
from .fear_greed import fetch_fear_greed
from .fundamental_ratios import fetch_equity_fundamentals, score_fundamental_ratios
from .http_utils import SourceError
from .kap import fetch_disclosures
from .macro_overlay import fetch_macro_overlay_brief
from .market_profiles import get_market_profile
from .turib import fetch_turib_endeks_overview
from .viop import fetch_term_structure

# Partial map — extend as needed for sector RS
BIST_TICKER_SECTOR: dict[str, str] = {
    "ASELS": "XUSIN",
    "THYAO": "XULAS",
    "GARAN": "XBANK",
    "AKBNK": "XBANK",
    "YKBNK": "XBANK",
    "EREGL": "XUSIN",
    "KCHOL": "XHOLD",
    "SAHOL": "XHOLD",
    "ULKER": "XGIDA",
    "BIMAS": "XMANA",
    "MGROS": "XMANA",
    "TUPRS": "XKMYA",
    "SISE": "XKMYA",
    "TOASO": "XUSIN",
    "FROTO": "XUSIN",
}

FOOD_BIST_TICKERS = frozenset(
    {
        "ULKER",
        "BIMAS",
        "MGROS",
        "SOKM",
        "TATGD",
        "BANVT",
        "PNSUT",
        "CCOLA",
        "AEFES",
        "PETUN",
        "KRSTL",
        "AVOD",
    }
)


def _perp_symbol(symbol: str) -> str:
    core = symbol.split(":")[-1].upper()
    if core.endswith("USDT") or core.endswith("USD"):
        return core
    return f"{core}USDT"


def _bar_close(bar: Any) -> float | None:
    if isinstance(bar, dict):
        close = bar.get("close")
    else:
        close = getattr(bar, "close", None)
    if close is None:
        return None
    try:
        return float(close)
    except (TypeError, ValueError):
        return None


async def _sector_rotation_for_ticker(core: str) -> dict[str, Any] | None:
    sector_alias = BIST_TICKER_SECTOR.get(core)
    if not sector_alias:
        return None
    try:
        sector_data, bench_data, ticker_eod = await asyncio.gather(
            fetch_sector_closes([sector_alias], period="3mo"),
            fetch_sector_closes([BENCHMARK_DEFAULT], period="3mo"),
            fetch_eod_ohlcv(core, period="3mo"),
            return_exceptions=True,
        )
        if isinstance(sector_data, BaseException) or not sector_data:
            return None
        bench_closes = []
        if not isinstance(bench_data, BaseException) and bench_data:
            bench_closes = bench_data.get(BENCHMARK_DEFAULT) or []
        rot = compute_rotation_metrics(sector_data, benchmark_closes=bench_closes or None)
        sectors = rot.get("sectors") or []
        row = sectors[0] if sectors else {}
        ticker_rs = None
        if not isinstance(ticker_eod, BaseException) and ticker_eod:
            closes = [_bar_close(bar) for bar in ticker_eod]
            closes = [close for close in closes if close is not None]
            if len(closes) >= 22 and closes[0] > 0:
                ticker_rs = round((closes[-1] / closes[-22] - 1) * 100, 2)
        return {
            "sector_alias": sector_alias,
            "sector_rank": row.get("rank"),
            "sector_return_pct": row.get("return_total_pct"),
            "ticker_relative_strength_pct": ticker_rs,
            "benchmark": BENCHMARK_DEFAULT,
        }
    except Exception:
        return None


async def enrich_fundamental_snapshot(
    symbol: str,
    *,
    market: str | None = None,
    include_turib: bool = True,
    include_sector: bool = True,
    include_macro: bool = True,
) -> dict[str, Any]:
    """Pull KAP / snapshot / crypto funding / TÜRİB when network allows."""
    prof = get_market_profile(symbol, market=market)
    ac = prof["asset_class"]
    core = symbol.split(":")[-1].upper()
    fetched: dict[str, Any] = {}
    highlights_tr: list[str] = []
    errors: list[str] = []

    if ac == "bist_equity":
        try:
            fund = await fetch_equity_fundamentals(core)
            score_pack = score_fundamental_ratios(fund)
            fetched["fundamentals"] = fund.to_dict()
            fetched["fundamental_ratios_score"] = score_pack
            if score_pack.get("available"):
                from .fundamental_ratios import summarize_fundamentals_tr

                highlights_tr.append(summarize_fundamentals_tr(fund, score_pack))
        except (SourceError, Exception) as e:
            errors.append(f"fundamentals:{e}")

        try:
            items = await fetch_disclosures(
                ticker=core,
                only_material=True,
                limit=6,
            )
            fetched["kap_disclosures"] = [
                {
                    "date": d.publish_date,
                    "title": (d.subject or "")[:120],
                    "material": d.is_material,
                }
                for d in items[:6]
            ]
            if items:
                highlights_tr.append(
                    f"KAP: son bildirim — {items[0].publish_date} "
                    f"{(items[0].subject or '')[:60]}"
                )
        except (SourceError, Exception) as e:
            errors.append(f"kap:{e}")

        try:
            snaps = await fetch_snapshot([core])
            if snaps:
                s = snaps[0]
                fetched["bist_snapshot"] = {
                    "last_price": s.last_price,
                    "change_pct": s.change_pct,
                    "volume": s.volume,
                    "market_state": s.market_state,
                }
                if s.change_pct is not None:
                    highlights_tr.append(f"BIST spot: {s.last_price} ({s.change_pct:+.2f}%)")
        except (SourceError, Exception) as e:
            errors.append(f"snapshot:{e}")

        if include_turib and core in FOOD_BIST_TICKERS:
            try:
                tur = await fetch_turib_endeks_overview()
                fetched["turib"] = tur
                idx = tur.get("indices") or []
                if idx:
                    ch = idx[0].get("change_pct")
                    name = idx[0].get("name") or "endeks"
                    if ch is not None:
                        highlights_tr.append(f"TÜRİB: {name} ({ch}%)")
                    else:
                        highlights_tr.append(f"TÜRİB: {len(idx)} endeks özeti")
            except (SourceError, Exception) as e:
                errors.append(f"turib:{e}")

        if include_sector:
            rot = await _sector_rotation_for_ticker(core)
            if rot:
                fetched["sector_rotation"] = rot
                rs = rot.get("ticker_relative_strength_pct")
                if rs is not None:
                    highlights_tr.append(
                        f"Sektör {rot.get('sector_alias')}: ticker RS ~{rs}% (21g)"
                    )

    elif ac == "crypto":
        perp = _perp_symbol(symbol)
        try:
            rates = await fetch_funding_rates(symbol=perp, limit=12)
            if rates:
                last = rates[-1]
                avg = sum(r.funding_rate for r in rates) / len(rates)
                fetched["funding"] = {
                    "symbol": perp,
                    "last_rate_pct": round(last.funding_rate * 100, 4),
                    "avg_rate_pct": round(avg * 100, 4),
                }
                highlights_tr.append(
                    f"Funding {perp}: son {fetched['funding']['last_rate_pct']}% "
                    f"(ort {fetched['funding']['avg_rate_pct']}%)"
                )
        except (SourceError, Exception) as e:
            errors.append(f"funding:{e}")

        try:
            oi_hist = await fetch_open_interest_history(symbol=perp, period="1h", limit=24)
            if oi_hist:
                last_oi = oi_hist[-1]
                oi_val = last_oi.get("open_interest")
                fetched["open_interest"] = {
                    "symbol": perp,
                    "open_interest": oi_val,
                    "timestamp_ms": last_oi.get("timestamp_ms"),
                }
                if oi_val is not None:
                    highlights_tr.append(f"OI {perp}: {float(oi_val):,.0f}")
        except (SourceError, Exception) as e:
            errors.append(f"oi:{e}")

        try:
            fng = await fetch_fear_greed(limit=2)
            if fng:
                latest = fng[0]
                fetched["fear_greed"] = {
                    "value": latest.value,
                    "classification": latest.classification,
                    "date": latest.date,
                }
                highlights_tr.append(
                    f"Fear&Greed: {latest.value} ({latest.classification})"
                )
        except (SourceError, Exception) as e:
            errors.append(f"fear_greed:{e}")

    elif ac in ("viop_future", "viop_option"):
        und = (prof.get("underlying") or core).upper()
        try:
            ts = await fetch_term_structure(und)
            if ts:
                fetched["viop_term_structure"] = [
                    {
                        "contract": s.contract.contract_code,
                        "last_price": s.last_price,
                        "expiry": f"{s.contract.expiry_year}-{s.contract.expiry_month:02d}",
                    }
                    for s in ts[:6]
                ]
                highlights_tr.append(f"VIOP {und}: {len(ts)} vadeli kontrat")
        except (SourceError, Exception) as e:
            errors.append(f"viop_ts:{e}")
        highlights_tr.append(
            f"VIOP: get_viop_dashboard ({und})"
        )

    if include_macro:
        macro = await fetch_macro_overlay_brief()
        if macro:
            fetched["macro_overlay"] = macro
            if macro.get("summary_tr"):
                highlights_tr.append(macro["summary_tr"])

    fetched["news_headlines"] = list(fetched.get("kap_disclosures") or [])[:4]

    return {
        "source": "bist-trader-mcp — fundamental_enrich.enrich_fundamental_snapshot",
        "symbol": symbol,
        "asset_class": ac,
        "fetched": fetched,
        "highlights_tr": highlights_tr,
        "errors": errors,
        "complete": len(errors) == 0,
    }


__all__ = ["enrich_fundamental_snapshot", "FOOD_BIST_TICKERS"]

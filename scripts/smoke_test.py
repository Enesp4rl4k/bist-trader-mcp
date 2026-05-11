"""Live smoke test runner - hits every external endpoint once.

Run this manually after deploys / weekly to catch endpoint drift. Each
section reports HTTP status, sample count and a small payload snippet.
TCMB EVDS requires TCMB_EVDS_API_KEY in the environment; if unset, that
section is skipped (not failed).
"""

from __future__ import annotations

import asyncio
import os
import sys
import traceback
from datetime import date, timedelta


def banner(title: str) -> None:
    print()
    print("=" * 70)
    print(f"  {title}")
    print("=" * 70)


def ok(msg: str) -> None:
    print(f"  [OK]    {msg}")


def fail(msg: str) -> None:
    print(f"  [FAIL]  {msg}")


def warn(msg: str) -> None:
    print(f"  [WARN]  {msg}")


def wip(msg: str) -> None:
    print(f"  [WIP]   {msg}")


def info(msg: str) -> None:
    print(f"  [info]  {msg}")


def _is_wip(err: BaseException) -> bool:
    """Heuristic: SourceError raised by the _wip helper contains a fixed phrase."""
    return "endpoint discovery pending" in str(err)


async def test_yahoo_bist() -> bool | None:
    banner("Yahoo Finance - BIST EOD (THYAO)")
    try:
        from bist_trader_mcp.bist_eod import fetch_eod_ohlcv

        bars = await fetch_eod_ohlcv(
            "THYAO", since=date.today() - timedelta(days=14)
        )
        if not bars:
            warn("returned 0 bars - symbol or window might be empty")
            return False
        ok(f"received {len(bars)} daily bars")
        last = bars[-1]
        info(f"latest: {last.date} close={last.close} volume={last.volume}")
        return True
    except Exception as e:
        fail(f"{type(e).__name__}: {e}")
        traceback.print_exc()
        return False


async def test_kap() -> bool | None:
    banner("KAP - disclosures")
    try:
        from bist_trader_mcp.kap import fetch_disclosures

        items = await fetch_disclosures(
            since=date.today() - timedelta(days=3), limit=5
        )
        if not items:
            warn("0 disclosures (could be a weekend or endpoint drift)")
            return False
        ok(f"received {len(items)} disclosures")
        for d in items[:3]:
            info(f"{d.publish_date} | {d.company_ticker} | {d.subject[:60]}")
        return True
    except Exception as e:
        if _is_wip(e):
            wip("endpoint discovery pending (expected for v0.2)")
            return None
        fail(f"{type(e).__name__}: {e}")
        return False


async def test_viop() -> bool | None:
    banner("Borsa Istanbul VIOP - daily settlement")
    try:
        from bist_trader_mcp.viop import fetch_daily_settlement

        rows = await fetch_daily_settlement(
            trade_date=date.today() - timedelta(days=1)
        )
        if not rows:
            warn("0 rows (could be a holiday or endpoint drift)")
            return False
        ok(f"received {len(rows)} contract rows")
        # Show one future and one option if present
        sample_fut = next(
            (r for r in rows if r.contract.contract_type == "future"), None
        )
        sample_opt = next(
            (r for r in rows if r.contract.contract_type == "option"), None
        )
        if sample_fut:
            info(
                f"future: {sample_fut.contract.contract_code} "
                f"settle={sample_fut.settle_price} OI={sample_fut.open_interest}"
            )
        if sample_opt:
            info(
                f"option: {sample_opt.contract.contract_code} "
                f"settle={sample_opt.settle_price} OI={sample_opt.open_interest}"
            )
        return True
    except Exception as e:
        if _is_wip(e):
            wip("endpoint discovery pending (expected for v0.2)")
            return None
        fail(f"{type(e).__name__}: {e}")
        return False


async def test_takasbank() -> bool | None:
    banner("Takasbank - VIOP marketwide dashboard")
    try:
        from bist_trader_mcp.takasbank import fetch_viop_margin_snapshot

        snap = await fetch_viop_margin_snapshot(use_cache=True)
        if not snap.margin_call_total and not snap.margined_account_count:
            warn("snapshot returned but values empty (WAF cooldown? cache stale?)")
            return False
        ok(
            f"margin call {snap.margin_call_total:,.2f} TL / required "
            f"{snap.required_margin_total:,.2f} TL"
        )
        info(
            f"accounts={snap.margined_account_count:,}  "
            f"futures_vol={snap.futures_volume_tl:,.0f} TL  "
            f"futures_oi={snap.futures_oi_count:,}"
        )
        return True
    except Exception as e:
        if _is_wip(e):
            wip("endpoint discovery pending (expected for v0.2)")
            return None
        fail(f"{type(e).__name__}: {e}")
        return False


async def test_hazine() -> bool | None:
    banner("Hazine - DİBS auction calendar")
    try:
        from bist_trader_mcp.hazine import fetch_auctions

        # Use the Tr01 PDF's calendar window so the smoke runs regardless
        # of today's date relative to the registered strategy quarter.
        rows = await fetch_auctions(since="2026-01-01", until="2026-04-30")
        if not rows:
            warn("0 auctions found in the strategy window")
            return False
        ok(f"received {len(rows)} scheduled auctions from strategy PDF")
        for a in rows[:3]:
            info(
                f"{a.auction_date} | {a.instrument[:40]} | "
                f"{a.tenor_label or '?'} / {a.tenor_days or '?'}d"
            )
        return True
    except Exception as e:
        if _is_wip(e):
            wip("endpoint discovery pending (expected for v0.2)")
            return None
        fail(f"{type(e).__name__}: {e}")
        return False


async def test_mkk() -> bool | None:
    banner("MKK - marketwide system statistics")
    try:
        from bist_trader_mcp.mkk import fetch_market_stats

        stats = await fetch_market_stats(use_cache=True)
        if not stats.rows:
            warn("no rows parsed from PDF")
            return False
        ok(f"parsed {len(stats.rows)} rows over {len(stats.months)} months")
        # Pick one signature metric for the info line.
        total = next(
            (r for r in stats.rows if r.metric == "total_investors"), None
        )
        if total and total.monthly_values:
            info(
                f"latest month {stats.months[-1]} — "
                f"total_investors={total.monthly_values[-1]:,.0f}"
            )
        return True
    except Exception as e:
        if _is_wip(e):
            wip("endpoint discovery pending (expected for v0.2)")
            return None
        fail(f"{type(e).__name__}: {e}")
        return False


async def test_evds() -> bool | None:
    banner("TCMB EVDS - policy rate series")
    api_key = os.environ.get("TCMB_EVDS_API_KEY")
    if not api_key:
        warn("TCMB_EVDS_API_KEY not set - skipping (free key at https://evds2.tcmb.gov.tr/)")
        return None
    try:
        from bist_trader_mcp.evds import EVDSClient
        from bist_trader_mcp.series_catalog import POLICY_RATE_SERIES

        client = EVDSClient(api_key=api_key)
        obs = await client.get_series(
            [POLICY_RATE_SERIES["policy_rate_1w_repo"]],
            start=date.today() - timedelta(days=30),
        )
        if not obs:
            warn("0 observations")
            return False
        latest = next((o for o in reversed(obs) if o.value is not None), None)
        if latest:
            ok(
                f"received {len(obs)} observations; "
                f"latest 1w repo = {latest.value}% on {latest.date}"
            )
        else:
            warn(f"received {len(obs)} observations but all values null")
        return True
    except Exception as e:
        if _is_wip(e):
            wip("endpoint discovery pending (expected for v0.2)")
            return None
        fail(f"{type(e).__name__}: {e}")
        return False


async def main() -> None:
    # True = live OK, None = expected WIP / skipped, False = unexpected fail
    results: dict[str, bool | None] = {}
    results["yahoo_bist_eod"] = await test_yahoo_bist()
    results["kap"] = await test_kap()
    results["viop"] = await test_viop()
    results["takasbank"] = await test_takasbank()
    results["hazine"] = await test_hazine()
    results["mkk"] = await test_mkk()
    results["evds"] = await test_evds()

    banner("SUMMARY")
    live = sum(1 for v in results.values() if v is True)
    wip_n = sum(1 for v in results.values() if v is None)
    failed = sum(1 for v in results.values() if v is False)
    print(f"  {live} live  /  {wip_n} WIP-or-skipped  /  {failed} unexpected-fail")
    for name, v in results.items():
        if v is True:
            tag = "OK  "
        elif v is None:
            tag = "WIP "
        else:
            tag = "FAIL"
        print(f"    [{tag}] {name}")

    # Only an unexpected failure should fail the script — WIP is expected.
    if failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())

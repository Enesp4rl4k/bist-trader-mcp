"""Daily loop — scan → rank → log → track outcomes → report.

One call (MCP tool ``run_daily_pipeline`` or ``python -m bist_trader_mcp.daily_pipeline``
from Task Scheduler / cron after the close):

1. **Track**: every earlier pipeline plan in the trade journal is replayed on the
   new bars with the same rules as the backtest (limit fill window, stop wins
   ties, gaps, max hold) → planned → open → closed with the result in R.
2. **Scan**: simple PA + candle forecast on every symbol (TradingView bars).
3. **Rank**: plans that agree with the forecast majority come first, then the
   setup type's learned track record (``pa_weights``), then R:R and confluence.
4. **Log**: the top N new plans go to the trade journal (one per symbol).
5. **Report**: market breadth, picks, open trades and the pipeline's own
   realised performance → a single HTML page.

The bar loader is injected so the logic is testable without TradingView.
"""

from __future__ import annotations

import asyncio
import html as _html
import zlib
from collections.abc import Awaitable, Callable
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from .candle_forecast import forecast_candles
from .data_quality import assess_ohlcv_quality
from .pa_backtest import _exit, _fill, summarize_trades
from .pa_simple import simple_price_action
from .trade_journal import _default_journal_path, _load, log_trade_plan, update_trade_status

BarLoader = Callable[[str], Awaitable[dict[str, Any]]]

PIPELINE_TAG = "daily_pipeline"
FILL_WINDOW = 3


# --------------------------------------------------------------------------- track


def _signal_index(times: list[int], signal_time: int) -> int | None:
    """Index of the bar the plan was generated on (last bar <= signal_time)."""
    idx = None
    for i, t in enumerate(times):
        if t <= signal_time:
            idx = i
        else:
            break
    return idx


def replay_plan(plan: dict[str, Any], bars: dict[str, Any], cost_pct: float) -> dict[str, Any]:
    """Replay one journal plan on bars → {status, fill, exit, reason, r}."""
    times = bars.get("times") or []
    if not times:
        return {"status": "planned", "note": "bars have no timestamps"}
    t = _signal_index(times, int(plan["signal_time"]))
    if t is None:
        return {"status": "planned", "note": "signal bar not in loaded history"}
    o, h, lo, c = bars["opens"], bars["highs"], bars["lows"], bars["closes"]
    direction, entry, stop = plan["direction"], float(plan["entry"]), float(plan["stop"])
    target = float((plan.get("targets") or [plan.get("target")])[0])
    market = bool(plan.get("market"))
    if t + 1 >= len(c):
        return {"status": "planned", "note": "waiting for the next bar"}
    filled = _fill(direction, entry, stop, market, t, o, h, lo, FILL_WINDOW)
    if filled is None:
        if len(c) - 1 >= t + FILL_WINDOW or market:
            return {"status": "cancelled", "reason": "not_filled"}
        return {"status": "planned", "note": "waiting for fill"}
    fill_bar, fill_px = filled
    exit_bar, exit_px, reason = _exit(
        direction, fill_bar, stop, target, market, o, h, lo, c,
        int(plan.get("max_hold") or 20),
    )
    if reason == "open":
        return {"status": "open", "fill": fill_px, "mark": c[-1]}
    risk = abs(fill_px - stop)
    sign = 1.0 if direction == "long" else -1.0
    r = sign * (exit_px - fill_px) / risk - cost_pct * (fill_px + exit_px) / risk
    return {"status": "closed", "fill": fill_px, "exit": exit_px, "reason": reason,
            "r": round(r, 4), "exit_time": times[exit_bar]}


def track_journal(
    bars_by_symbol: dict[str, dict[str, Any]],
    *,
    journal_path: str | Path | None = None,
    cost_pct: float = 0.002,
) -> list[dict[str, Any]]:
    """Advance planned/open pipeline trades using fresh bars; return the changes."""
    path = Path(journal_path) if journal_path else _default_journal_path()
    changes = []
    for row in _load(path):
        snap = row.get("plan_snapshot") or {}
        if snap.get("source") != PIPELINE_TAG or row.get("status") not in ("planned", "open"):
            continue
        bars = bars_by_symbol.get(str(row.get("symbol")))
        if not bars:
            continue
        res = replay_plan(snap, bars, cost_pct)
        new = res["status"]
        if new == row["status"] and new != "open":
            continue
        if new == "closed":
            update_trade_status(
                row["id"], "closed", exit_price=res["exit"], pnl=res["r"],
                notes=f"{res['reason']} fill={res['fill']:.4f}", journal_path=path,
            )
        elif new == "cancelled":
            update_trade_status(row["id"], "cancelled", notes="not filled", journal_path=path)
        elif new == "open" and row["status"] == "planned":
            update_trade_status(
                row["id"], "open", notes=f"filled {res['fill']:.4f}", journal_path=path
            )
        else:
            continue
        changes.append({"trade_id": row["id"], "symbol": row.get("symbol"),
                        "from": row["status"], **res})
    return changes


def pipeline_performance(journal_path: str | Path | None = None) -> dict[str, Any]:
    path = Path(journal_path) if journal_path else _default_journal_path()
    rows = [r for r in _load(path)
            if (r.get("plan_snapshot") or {}).get("source") == PIPELINE_TAG]
    closed = [{"r": float(r["pnl"])} for r in rows
              if r.get("status") == "closed" and r.get("pnl") is not None]
    stats = summarize_trades(closed, min_trades=20)
    return {
        "planned": sum(1 for r in rows if r.get("status") == "planned"),
        "open": sum(1 for r in rows if r.get("status") == "open"),
        "closed": len(closed),
        "cancelled": sum(1 for r in rows if r.get("status") == "cancelled"),
        "stats": stats,
        "open_trades": [
            {k: r.get(k) for k in ("id", "symbol", "direction", "entry", "stop", "targets",
                                    "status", "logged_at")}
            for r in rows if r.get("status") in ("planned", "open")
        ],
    }


# --------------------------------------------------------------------------- scan


def _seed(symbol: str, day: str) -> int:
    return zlib.crc32(f"{symbol}:{day}".encode())


def scan_symbol(symbol: str, bars: dict[str, Any], *, day: str, min_rr: float) -> dict[str, Any]:
    o, h, lo, c = bars.get("opens"), bars["highs"], bars["lows"], bars["closes"]
    pa = simple_price_action(c, h, lo, o, volumes=bars.get("volumes"), min_rr=min_rr, debug=True)
    fc = forecast_candles(c, h, lo, o, horizon=10, n_paths=30, seed=_seed(symbol, day))
    q = assess_ohlcv_quality(c, h, lo, volumes=bars.get("volumes"))
    plan = pa.get("plan")
    agrees = None
    if plan:
        up = fc["candles"]["up_pct"]
        agrees = up >= 50 if plan["direction"] == "long" else up <= 50
    return {
        "symbol": symbol,
        "price": pa["price"],
        "trend": pa["trend"],
        "verdict": pa["verdict"],
        "reason": pa["reason"],
        "plan": plan,
        "setup_type": pa["debug"]["setup_type"],
        "confluence": pa["debug"]["confluence_score"],
        "forecast_up_pct": fc["candles"]["up_pct"],
        "forecast_change_pct": fc["mean_forecast"]["change_pct"],
        "forecast_agrees": agrees,
        "data_issues": q.get("issues") or [],
        "signal_time": (bars.get("times") or [None])[-1],
    }


def rank_candidates(scans: list[dict[str, Any]]) -> list[dict[str, Any]]:
    # Unadjusted splits make levels meaningless; other quality notes are shown only.
    cands = [
        s for s in scans
        if s["plan"] and not any(i.startswith("suspect_split") for i in s["data_issues"])
    ]

    def key(s: dict[str, Any]) -> tuple:
        rec = (s["plan"] or {}).get("track_record") or {}
        return (
            1 if s["forecast_agrees"] else 0,
            float(rec.get("avg_r", 0.0)),
            float(s["plan"].get("risk_reward") or 0.0),
            float(s["confluence"] or 0.0),
        )

    return sorted(cands, key=key, reverse=True)


# --------------------------------------------------------------------------- run


async def run_pipeline(
    symbols: list[str],
    load_bars: BarLoader,
    *,
    timeframe: str = "1D",
    top_n: int = 5,
    min_rr: float = 1.5,
    max_hold: int = 20,
    cost_pct: float = 0.002,
    log_to_journal: bool = True,
    journal_path: str | Path | None = None,
    store_prices: bool = True,
    html_dir: Path | None = None,
) -> dict[str, Any]:
    day = date.today().isoformat()
    bars_by_symbol: dict[str, dict[str, Any]] = {}
    failed = []
    for sym in symbols:
        try:
            bars_by_symbol[sym] = await load_bars(sym)
        except Exception as e:  # noqa: BLE001 — one bad symbol must not stop the run
            failed.append({"symbol": sym, "detail": f"{type(e).__name__}: {e}"})

    tracked = track_journal(bars_by_symbol, journal_path=journal_path, cost_pct=cost_pct)

    scans = []
    for sym, bars in bars_by_symbol.items():
        try:
            scans.append(await asyncio.to_thread(scan_symbol, sym, bars, day=day,
                                                 min_rr=min_rr))
        except (ValueError, KeyError, TypeError) as e:
            failed.append({"symbol": sym, "detail": f"scan: {e}"})
    ranked = rank_candidates(scans)

    from .risk_engine import check_trade, load_config

    cfg = load_config()
    picks: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    logged = []
    for s in ranked:
        if len(picks) >= max(0, int(top_n)):
            break
        # Each check sees the plans logged earlier in this run (they are
        # "planned" rows in the journal), so heat and clusters add up correctly.
        risk = check_trade(s["plan"], symbol=s["symbol"], cfg=cfg,
                           bars_by_symbol=bars_by_symbol, journal_path=journal_path)
        s["risk"] = {k: risk[k] for k in ("approved", "sizing", "blocking", "warnings",
                                          "summary_tr")}
        if not risk["approved"]:
            rejected.append({"symbol": s["symbol"], "blocking": risk["blocking"]})
            continue
        picks.append(s)
        if log_to_journal:
            p = s["plan"]
            if s["signal_time"] is None:
                continue
            res = log_trade_plan(
                {
                    "symbol": s["symbol"], "direction": p["direction"], "entry": p["entry"],
                    "stop": p["stop"], "targets": [p["target"]],
                    "best_risk_reward": p["risk_reward"], "source": PIPELINE_TAG,
                    "signal_time": int(s["signal_time"]), "timeframe": timeframe,
                    "market": abs(p["entry"] - s["price"]) <= 1e-9 * max(1.0, s["price"]),
                    "max_hold": max_hold, "setup_type": s["setup_type"],
                    "forecast_up_pct": s["forecast_up_pct"],
                    "sizing": risk["sizing"],
                },
                notes=f"{PIPELINE_TAG} {day}",
                journal_path=journal_path,
            )
            logged.append(res["trade_id"])

    stored = 0
    if store_prices and timeframe.upper() in ("1D", "D"):
        stored = _store_daily_prices(bars_by_symbol)

    trend_counts: dict[str, int] = {}
    for s in scans:
        trend_counts[s["trend"]] = trend_counts.get(s["trend"], 0) + 1
    up_share = (
        round(sum(1 for s in scans if s["forecast_up_pct"] > 50) * 100 / len(scans))
        if scans else None
    )
    perf = pipeline_performance(journal_path)
    result = {
        "date": day,
        "timeframe": timeframe,
        "symbols_scanned": len(scans),
        "symbols_failed": failed,
        "breadth": {"trend_counts": trend_counts, "forecast_up_share_pct": up_share},
        "picks": [
            {k: s[k] for k in ("symbol", "verdict", "price", "plan", "setup_type",
                               "forecast_up_pct", "forecast_agrees", "reason", "risk")}
            for s in picks
        ],
        "risk_rejected": rejected,
        "logged_trade_ids": logged,
        "tracked_changes": tracked,
        "performance": perf,
        "prices_stored": stored,
        "summary_tr": _summary_tr(len(scans), trend_counts, picks, tracked, perf),
    }
    if html_dir is not None:
        html_dir.mkdir(parents=True, exist_ok=True)
        path = html_dir / f"daily_{day}.html"
        path.write_text(render_dashboard(result, scans), encoding="utf-8")
        result["html_path"] = str(path)
    return result


def _store_daily_prices(bars_by_symbol: dict[str, dict[str, Any]]) -> int:
    from .data_store import PanelStore

    rows = []
    for sym, b in bars_by_symbol.items():
        times = b.get("times") or []
        if len(times) != len(b["closes"]):
            continue
        for i, t in enumerate(times):
            rows.append({
                "ticker": sym,
                "date": datetime.fromtimestamp(int(t), tz=timezone.utc).date().isoformat(),
                "open": (b.get("opens") or b["closes"])[i], "high": b["highs"][i],
                "low": b["lows"][i], "close": b["closes"][i],
                "volume": (b.get("volumes") or [None] * len(times))[i],
                "known_at": int(t) + 86_400,  # a daily bar is known after its session
            })
    if not rows:
        return 0
    try:
        with PanelStore() as store:
            return store.upsert_prices(rows)
    except Exception:  # noqa: BLE001 — storage is best-effort, never fail the scan
        return 0


def _summary_tr(n, trends, picks, tracked, perf) -> str:
    t = ", ".join(f"{k} {v}" for k, v in sorted(trends.items())) or "-"
    p = ", ".join(f"{s['symbol']} {s['verdict']}" for s in picks) or "yok"
    closed = [c for c in tracked if c["status"] == "closed"]
    st = perf["stats"]
    perf_txt = (
        f"Pipeline geçmişi: {perf['closed']} kapanmış işlem, beklenti {st['expectancy_r']}R."
        if perf["closed"] else "Pipeline henüz kapanmış işlem üretmedi."
    )
    return (
        f"{n} sembol tarandı (trend: {t}). Bugünün seçimleri: {p}. "
        f"{len(closed)} işlem kapandı, {perf['open']} açık, {perf['planned']} bekleyen. "
        f"{perf_txt}"
    )


# --------------------------------------------------------------------------- html


def render_dashboard(result: dict[str, Any], scans: list[dict[str, Any]]) -> str:
    e = _html.escape

    def row(cells: list[str]) -> str:
        return "<tr>" + "".join(f"<td>{c}</td>" for c in cells) + "</tr>"

    picks = "".join(
        row([
            f"<b>{e(p['symbol'])}</b>",
            f"<span class='{'up' if p['verdict'] == 'AL' else 'dn'}'>{e(p['verdict'])}</span>",
            f"{p['plan']['entry']}", f"{p['plan']['stop']}", f"{p['plan']['target']}",
            f"{p['plan']['risk_reward']}", f"%{p['forecast_up_pct']}",
            e(str(p["setup_type"])),
        ])
        for p in result["picks"]
    ) or "<tr><td colspan=8>Bugün kriterlere uyan kurulum yok.</td></tr>"
    scan_rows = "".join(
        row([e(s["symbol"]), e(s["trend"]), e(s["verdict"]), f"{s['price']:.2f}",
             f"%{s['forecast_up_pct']}", f"{s['forecast_change_pct']:+.2f}%",
             e("; ".join(s["data_issues"])[:60])])
        for s in sorted(scans, key=lambda s: s["symbol"])
    )
    perf = result["performance"]
    st = perf["stats"]
    open_rows = "".join(
        row([e(str(t["symbol"])), e(str(t["direction"])), f"{t['entry']}", f"{t['stop']}",
             f"{(t.get('targets') or ['-'])[0]}", e(str(t["status"]))])
        for t in perf["open_trades"]
    ) or "<tr><td colspan=6>Açık işlem yok.</td></tr>"
    breadth = result["breadth"]
    trends = " · ".join(f"{e(k)}: <b>{v}</b>" for k, v in breadth["trend_counts"].items())
    return f"""<!doctype html>
<html lang="tr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Günlük Tarama {e(result['date'])}</title>
<style>
:root {{ --bg:#131722; --panel:#1b2030; --line:#2a3042; --fg:#d1d4dc; --muted:#8a90a2;
  --up:#26a69a; --dn:#ef5350; --acc:#f5a623; }}
body {{ margin:0; background:var(--bg); color:var(--fg); font:14px/1.45 system-ui,sans-serif; }}
main {{ max-width:1100px; margin:0 auto; padding:16px; }}
h1 {{ font-size:20px; margin:4px 0 12px; }} h2 {{ font-size:13px; color:var(--muted);
  text-transform:uppercase; letter-spacing:.06em; margin:0 0 8px; }}
.grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(200px,1fr)); gap:10px; }}
.card {{ background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:12px;
  margin-bottom:12px; overflow-x:auto; }}
.big {{ font-size:22px; font-weight:700; }}
table {{ width:100%; border-collapse:collapse; font-size:13px; }}
td {{ padding:6px 8px; border-top:1px solid var(--line); white-space:nowrap; }}
.up {{ color:var(--up); font-weight:700; }} .dn {{ color:var(--dn); font-weight:700; }}
.muted {{ color:var(--muted); font-size:12px; }}
</style></head><body><main>
<h1>Günlük tarama — {e(result['date'])} ({e(result['timeframe'])})</h1>
<div class="card muted">{e(result['summary_tr'])}</div>
<div class="grid">
  <div class="card"><h2>Taranan</h2><div class="big">{result['symbols_scanned']}</div>
    <div class="muted">{trends}</div></div>
  <div class="card"><h2>Tahmin yukarı payı</h2><div class="big">%{breadth['forecast_up_share_pct']}</div>
    <div class="muted">30 koşunun çoğunluğu yukarı biten semboller</div></div>
  <div class="card"><h2>Pipeline beklentisi</h2><div class="big">{st['expectancy_r'] if st['expectancy_r'] is not None else '-'}R</div>
    <div class="muted">{perf['closed']} kapanmış işlem · isabet %{st['win_rate_pct'] if st['win_rate_pct'] is not None else '-'}</div></div>
</div>
<div class="card"><h2>Bugünün seçimleri</h2><table>
<tr class="muted"><td>Sembol</td><td>Karar</td><td>Giriş</td><td>Stop</td><td>Hedef</td><td>R:R</td><td>Tahmin ↑</td><td>Kurulum</td></tr>
{picks}</table></div>
<div class="card"><h2>Açık / bekleyen işlemler</h2><table>
<tr class="muted"><td>Sembol</td><td>Yön</td><td>Giriş</td><td>Stop</td><td>Hedef</td><td>Durum</td></tr>
{open_rows}</table></div>
<div class="card"><h2>Tüm semboller</h2><table>
<tr class="muted"><td>Sembol</td><td>Trend</td><td>Karar</td><td>Fiyat</td><td>Tahmin ↑</td><td>Ort. tahmin</td><td>Veri uyarısı</td></tr>
{scan_rows}</table></div>
<div class="muted">Olasılık ve geçmiş performans; yatırım tavsiyesi değildir.</div>
</main></body></html>
"""


# --------------------------------------------------------------------------- CLI


def main(argv: list[str] | None = None) -> None:
    """CLI for Task Scheduler / cron: ``bist-trader-daily --top 5``."""
    import argparse
    import json

    from .tools import run_daily_pipeline

    ap = argparse.ArgumentParser(description="BIST Trader daily scan → journal → report")
    ap.add_argument("--symbols", nargs="*", help="default ≈BIST30")
    ap.add_argument("--timeframe", default="1D")
    ap.add_argument("--top", type=int, default=5)
    ap.add_argument("--data-source", default="auto", choices=["auto", "tradingview", "public"])
    ap.add_argument("--no-journal", action="store_true")
    args = ap.parse_args(argv)
    res = asyncio.run(run_daily_pipeline(
        symbols=args.symbols, timeframe=args.timeframe, top_n=args.top,
        data_source=args.data_source, log_to_journal=not args.no_journal,
    ))
    print(res.get("summary_tr") or json.dumps(res, ensure_ascii=False))
    if res.get("html_path"):
        print(res["html_path"])


if __name__ == "__main__":
    main()


__all__ = [
    "pipeline_performance",
    "rank_candidates",
    "render_dashboard",
    "replay_plan",
    "run_pipeline",
    "scan_symbol",
    "track_journal",
]

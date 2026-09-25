"""Paper account — what the pipeline / dashboard plans would have done in TL.

Nothing here places orders. The daily tracker replays every logged plan on
real bars (fill window, stop-first, gaps, max hold) and stores the result in R;
this module turns that into an account:

- P&L in TL per trade: R × the risk amount the plan was sized with
  (quantity × |entry − stop|, else one standard risk unit)
- equity curve from ``equity`` in the risk config, max drawdown, return %
- open positions marked to the latest close
- **live vs backtest**: live expectancy compared with the out-of-sample
  expectancy saved by ``backtest_price_action_universe(save_weights=true)`` —
  the Phase-3 acceptance check ("live ≥ half of backtest").
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .pa_backtest import summarize_trades

MIN_LIVE_TRADES = 20


def _risk_amount(row: dict[str, Any], equity: float, risk_pct: float) -> float:
    sizing = row.get("sizing") or (row.get("plan_snapshot") or {}).get("sizing") or {}
    try:
        qty = float(sizing.get("quantity") or 0)
        if qty > 0:
            return qty * abs(float(row["entry"]) - float(row["stop"]))
    except (TypeError, ValueError, KeyError, AttributeError):
        pass
    return equity * risk_pct / 100.0


def _qty(row: dict[str, Any], risk_amt: float) -> float:
    sizing = row.get("sizing") or {}
    if isinstance(sizing, dict) and sizing.get("quantity"):
        return float(sizing["quantity"])
    per = abs(float(row["entry"]) - float(row["stop"]))
    return risk_amt / per if per > 0 else 0.0


def backtest_expectancy() -> dict[str, Any] | None:
    """Out-of-sample expectancy saved with the learned weights, if any."""
    from .pa_weights import load_weights

    w = load_weights() or {}
    oos = ((w.get("validation") or {}).get("oos_baseline")) or {}
    if oos.get("expectancy_r") is None:
        return None
    return {"expectancy_r": float(oos["expectancy_r"]), "trades": oos.get("trades"),
            "created_at": w.get("created_at")}


def compare_live_to_backtest(live_exp: float | None, live_n: int,
                             bt: dict[str, Any] | None) -> dict[str, Any]:
    if bt is None:
        return {"verdict": "no_backtest",
                "summary_tr": "Karşılaştırma için önce backtest_price_action_universe"
                              "(save_weights=true) çalıştırılmalı."}
    if live_n < MIN_LIVE_TRADES or live_exp is None:
        return {"verdict": "insufficient", "backtest_expectancy_r": bt["expectancy_r"],
                "summary_tr": f"Canlı örnek az ({live_n}/{MIN_LIVE_TRADES} işlem); "
                              "karar için bekle."}
    bt_e = bt["expectancy_r"]
    if bt_e <= 0:
        verdict = "backtest_negative"
        text = f"Backtest beklentisi zaten negatif ({bt_e:+.2f}R); strateji düzeltilmeli."
    elif live_exp >= 0.5 * bt_e:
        verdict = "consistent"
        text = (f"Canlı {live_exp:+.2f}R/işlem, backtest {bt_e:+.2f}R — tutarlı "
                "(en az yarısı tutuyor).")
    elif live_exp > 0:
        verdict = "weaker"
        text = (f"Canlı {live_exp:+.2f}R pozitif ama backtestin ({bt_e:+.2f}R) yarısının "
                "altında — aşırı uyum olabilir, pozisyonu küçült.")
    else:
        verdict = "diverging"
        text = (f"Canlı {live_exp:+.2f}R, backtest {bt_e:+.2f}R — sapma var; gerçek para "
                "koyma, stratejiyi yeniden ölç.")
    return {"verdict": verdict, "live_expectancy_r": live_exp,
            "backtest_expectancy_r": bt_e, "summary_tr": text}


def paper_account(
    *,
    journal_path: str | Path | None = None,
    bars_by_symbol: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    from .daily_pipeline import is_tracked
    from .risk_engine import load_config
    from .trade_journal import _default_journal_path, _load

    cfg = load_config()
    bars_by_symbol = bars_by_symbol or {}
    rows = [r for r in _load(Path(journal_path) if journal_path else _default_journal_path())
            if is_tracked(r)]
    closed = [r for r in rows if r.get("status") == "closed" and r.get("pnl") is not None]
    closed.sort(key=lambda r: r.get("updated_at") or r.get("logged_at") or "")

    equity = cfg.equity
    peak = equity
    max_dd = 0.0
    curve = [{"time": rows[0].get("logged_at") if rows else None, "equity": equity}]
    trades = []
    for r in closed:
        risk_amt = _risk_amount(r, cfg.equity, cfg.risk_per_trade_pct)
        pnl = float(r["pnl"]) * risk_amt
        equity += pnl
        peak = max(peak, equity)
        max_dd = min(max_dd, (equity - peak) / peak * 100.0)
        curve.append({"time": r.get("updated_at"), "equity": round(equity, 2)})
        trades.append({"id": r.get("id"), "symbol": r.get("symbol"), "r": float(r["pnl"]),
                       "pnl": round(pnl, 2), "closed_at": r.get("updated_at")})

    open_pos = []
    open_pnl = 0.0
    for r in rows:
        if r.get("status") != "open":
            continue
        b = bars_by_symbol.get(str(r.get("symbol")).upper())
        last = b["closes"][-1] if b and b.get("closes") else None
        risk_amt = _risk_amount(r, cfg.equity, cfg.risk_per_trade_pct)
        upnl = None
        if last is not None:
            sign = 1 if r.get("direction") == "long" else -1
            upnl = round(sign * (last - float(r["entry"])) * _qty(r, risk_amt), 2)
            open_pnl += upnl
        open_pos.append({"id": r.get("id"), "symbol": r.get("symbol"),
                         "direction": r.get("direction"), "entry": r.get("entry"),
                         "stop": r.get("stop"), "last": last, "unrealised": upnl})

    stats = summarize_trades([{"r": t["r"]} for t in trades], min_trades=MIN_LIVE_TRADES)
    live_exp = stats["expectancy_r"]
    cmp_ = compare_live_to_backtest(live_exp, len(trades), backtest_expectancy())
    first = rows[0].get("logged_at") if rows else None
    days = None
    if first:
        try:
            started = datetime.fromisoformat(first)
            if started.tzinfo is None:
                started = started.replace(tzinfo=timezone.utc)
            days = (datetime.now(timezone.utc) - started).days
        except ValueError:
            days = None
    ret = (equity / cfg.equity - 1) * 100.0
    return {
        "starting_equity": cfg.equity,
        "equity": round(equity, 2),
        "equity_with_open": round(equity + open_pnl, 2),
        "return_pct": round(ret, 2),
        "max_drawdown_pct": round(max_dd, 2),
        "days_running": days,
        "closed_trades": len(trades),
        "open_positions": open_pos,
        "pending_plans": sum(1 for r in rows if r.get("status") == "planned"),
        "stats": stats,
        "live_vs_backtest": cmp_,
        "equity_curve": curve[-200:],
        "recent_trades": trades[-10:],
        "summary_tr": (
            f"Kağıt hesap: {cfg.equity:,.0f} → {equity:,.0f} TL ({ret:+.2f}%), "
            f"{len(trades)} kapanmış işlem, en kötü düşüş %{max_dd:.2f}, "
            f"{len(open_pos)} açık pozisyon. {cmp_['summary_tr']}"
        ),
    }


__all__ = ["backtest_expectancy", "compare_live_to_backtest", "paper_account"]

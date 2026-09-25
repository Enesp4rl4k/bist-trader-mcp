"""Walk-forward backtest of the simple price action verdicts — "does PA work?".

At every bar ``t`` we run :func:`pa_simple.simple_price_action` on the prefix
``[:t+1]`` only (no look-ahead), and when it gives a plan (AL/SAT) we simulate
the trade on the bars that follow:

- market entries fill at the next bar's open; limit entries must be touched
  within ``fill_window`` bars or the order is cancelled
- exit on the first touch of stop or target; if both are inside the same bar
  we assume the **stop** hit first (conservative); gaps through a level fill
  at the open; after ``max_hold`` bars we exit at the close
- one position at a time; P&L is measured in **R** (multiples of initial risk)
  after round-trip costs

:func:`pa_factor_attribution` then asks which confluence factors actually
improved the outcome, and whether a higher confluence score meant better trades.
Pure math — feed bars from TradingView (``tv_fetch_ohlcv``) or any OHLCV source.
"""

from __future__ import annotations

from contextlib import nullcontext
from typing import Any

from .factor_eval import quantile_spread, rank_ic
from .pa_simple import simple_price_action
from .pa_weights import use_weights
from .performance import trade_statistics


def _fill(
    direction: str,
    entry: float,
    stop: float,
    market: bool,
    t: int,
    opens: list[float],
    highs: list[float],
    lows: list[float],
    fill_window: int,
) -> tuple[int, float] | None:
    """Return (fill_bar, fill_price) or None when not filled / invalidated."""
    n = len(opens)
    long = direction == "long"
    if market:
        j = t + 1
        if j >= n:
            return None
        px = opens[j]
        if (long and px <= stop) or (not long and px >= stop):
            return None  # gapped through the stop before we could enter
        return j, px
    for j in range(t + 1, min(n, t + 1 + fill_window)):
        if long and lows[j] <= entry:
            return j, min(entry, opens[j])
        if not long and highs[j] >= entry:
            return j, max(entry, opens[j])
    return None


def _exit(
    direction: str,
    fill_bar: int,
    stop: float,
    target: float,
    market: bool,
    opens: list[float],
    highs: list[float],
    lows: list[float],
    closes: list[float],
    max_hold: int,
) -> tuple[int, float, str]:
    n = len(closes)
    long = direction == "long"
    last = min(n - 1, fill_bar + max_hold)
    for j in range(fill_bar, last + 1):
        if j > fill_bar:  # gap through a level at the open
            if (long and opens[j] <= stop) or (not long and opens[j] >= stop):
                return j, opens[j], "stop_gap"
            if (long and opens[j] >= target) or (not long and opens[j] <= target):
                return j, opens[j], "target_gap"
        hit_stop = lows[j] <= stop if long else highs[j] >= stop
        # On a limit fill bar we don't know if the target printed before the
        # fill, so only the stop counts there.
        hit_target = (highs[j] >= target if long else lows[j] <= target) and (
            market or j > fill_bar
        )
        if hit_stop:
            return j, stop, "stop"
        if hit_target:
            return j, target, "target"
    # "open" = data ran out before max_hold; marked-to-market at the last close
    return last, closes[last], "timeout" if last == fill_bar + max_hold else "open"


def group_trades(trades: list[dict[str, Any]], key: str) -> dict[str, Any]:
    out: dict[str, dict[str, Any]] = {}
    for tr in trades:
        k = str(tr.get(key))
        out.setdefault(k, []).append(tr["r"])  # type: ignore[arg-type]
    return {
        k: {
            "trades": len(rs),
            "win_rate_pct": round(100.0 * sum(1 for r in rs if r > 0) / len(rs), 1),
            "avg_r": round(sum(rs) / len(rs), 3),
        }
        for k, rs in out.items()
    }


def _max_drawdown_r(rs: list[float]) -> float:
    peak = cum = 0.0
    dd = 0.0
    for r in rs:
        cum += r
        peak = max(peak, cum)
        dd = min(dd, cum - peak)
    return round(dd, 3)


def summarize_trades(trades: list[dict[str, Any]], min_trades: int = 30) -> dict[str, Any]:
    """Stats in R + a plain Turkish verdict."""
    rs = [t["r"] for t in trades]
    st = trade_statistics(rs)
    exp = st["expectancy"]
    stats = {
        "trades": st["trades"],
        "win_rate_pct": None if st["win_rate_pct"] is None else round(st["win_rate_pct"], 1),
        "expectancy_r": None if exp is None else round(exp, 3),
        "profit_factor": None if st["profit_factor"] is None else round(st["profit_factor"], 2),
        "avg_win_r": None if st["avg_win"] is None else round(st["avg_win"], 3),
        "avg_loss_r": None if st["avg_loss"] is None else round(st["avg_loss"], 3),
        "total_r": round(sum(rs), 3),
        "max_drawdown_r": _max_drawdown_r(rs),
    }
    if st["trades"] < min_trades:
        verdict = "yetersiz örnek"
        text = (
            f"Sadece {st['trades']} işlem var (<{min_trades}); sonuç istatistiksel "
            "olarak anlamlı değil. Daha uzun geçmiş veya daha çok sembol kullan."
        )
    elif exp is not None and exp >= 0.10:
        verdict = "pozitif beklenti"
        text = f"İşlem başına ortalama {exp:+.2f}R kazanç — sistem geçmişte çalışmış."
    elif exp is not None and exp <= -0.10:
        verdict = "negatif beklenti"
        text = f"İşlem başına ortalama {exp:+.2f}R kayıp — bu kurulumlar geçmişte kaybettirmiş."
    else:
        verdict = "anlamsız (başa baş)"
        text = f"Beklenti {exp:+.2f}R — maliyet sonrası kenar (edge) yok gibi."
    return {**stats, "verdict": verdict, "verdict_tr": text}


def backtest_simple_pa(
    opens: list[float],
    highs: list[float],
    lows: list[float],
    closes: list[float],
    *,
    dates: list[Any] | None = None,
    warmup: int = 120,
    step: int = 1,
    max_hold: int = 20,
    fill_window: int = 3,
    min_rr: float = 1.5,
    cost_pct: float = 0.002,
    min_trades: int = 30,
    weights: dict[str, Any] | None = None,
    use_saved_weights: bool = False,
    lookback_bars: int = 300,
) -> dict[str, Any]:
    """Walk-forward test of ``simple_price_action`` AL/SAT plans.

    By default learned weights are *disabled* so the baseline engine is measured.
    Pass ``weights`` (a pa_weights document) to test a candidate set, or
    ``use_saved_weights=True`` to test whatever is saved and active on disk.

    ``lookback_bars``: each decision sees only the last N bars — the same
    window the live pipeline analyses — which also keeps the cost O(n).
    """
    if weights is not None:
        ctx = use_weights(weights)
    elif use_saved_weights:
        ctx = nullcontext()
    else:
        ctx = use_weights(None)
    with ctx:
        return _run_backtest(
            opens, highs, lows, closes, dates=dates, warmup=warmup, step=step,
            max_hold=max_hold, fill_window=fill_window, min_rr=min_rr,
            cost_pct=cost_pct, min_trades=min_trades, lookback_bars=lookback_bars,
        )


def _run_backtest(
    opens: list[float],
    highs: list[float],
    lows: list[float],
    closes: list[float],
    *,
    dates: list[Any] | None,
    warmup: int,
    step: int,
    max_hold: int,
    fill_window: int,
    min_rr: float,
    cost_pct: float,
    min_trades: int,
    lookback_bars: int = 300,
) -> dict[str, Any]:
    n = len(closes)
    if not (n == len(opens) == len(highs) == len(lows)):
        raise ValueError("opens, highs, lows, closes must be equal length")
    if n < warmup + 10:
        raise ValueError(f"need at least warmup+10 = {warmup + 10} bars, got {n}")
    step = max(1, int(step))

    trades: list[dict[str, Any]] = []
    counts = {"AL": 0, "SAT": 0, "BEKLE": 0, "unfilled": 0}
    t = warmup
    while t < n - 1:
        lo = max(0, t + 1 - lookback_bars)
        sig = simple_price_action(
            closes[lo: t + 1], highs[lo: t + 1], lows[lo: t + 1], opens[lo: t + 1],
            min_rr=min_rr, debug=True,
        )
        counts[sig["verdict"]] += 1
        plan = sig.get("plan")
        if not plan:
            t += step
            continue
        dbg = sig.get("debug") or {}
        direction = plan["direction"]
        entry, stop, target = plan["entry"], plan["stop"], plan["target"]
        style = str(dbg.get("entry_style") or "market")
        market = style.startswith("market") or abs(entry - closes[t]) <= 1e-9 * max(1.0, entry)
        filled = _fill(direction, entry, stop, market, t, opens, highs, lows, fill_window)
        if filled is None:
            counts["unfilled"] += 1
            t += step
            continue
        fill_bar, fill_px = filled
        risk = abs(fill_px - stop)
        if risk <= 0:
            t += step
            continue
        exit_bar, exit_px, reason = _exit(
            direction, fill_bar, stop, target, market, opens, highs, lows, closes, max_hold
        )
        sign = 1.0 if direction == "long" else -1.0
        gross_r = sign * (exit_px - fill_px) / risk
        cost_r = cost_pct * (fill_px + exit_px) / risk
        trades.append(
            {
                "signal_bar": t,
                "entry_bar": fill_bar,
                "exit_bar": exit_bar,
                "signal_date": dates[t] if dates else None,
                "exit_date": dates[exit_bar] if dates else None,
                "direction": direction,
                "entry": round(fill_px, 6),
                "stop": stop,
                "target": target,
                "exit": round(exit_px, 6),
                "exit_reason": reason,
                "bars_held": exit_bar - fill_bar,
                "r": round(gross_r - cost_r, 4),
                "trend": sig["trend"],
                "zone": sig.get("zone"),
                "setup_type": dbg.get("setup_type"),
                "confluence_score": dbg.get("confluence_score"),
                "factors": dbg.get("factors") or [],
            }
        )
        t = max(t + step, exit_bar + 1)  # one position at a time

    stats = summarize_trades(trades, min_trades=min_trades)
    return {
        "method": "walk-forward, prefix-only signals (no look-ahead), R-multiples after costs",
        "bars": n,
        "params": {
            "warmup": warmup, "step": step, "max_hold": max_hold,
            "lookback_bars": lookback_bars,
            "fill_window": fill_window, "min_rr": min_rr, "cost_pct": cost_pct,
        },
        "signals": counts,
        "stats": stats,
        "by_direction": group_trades(trades, "direction"),
        "by_trend": group_trades(trades, "trend"),
        "by_setup_type": group_trades(trades, "setup_type"),
        "by_exit_reason": group_trades(trades, "exit_reason"),
        "trades": trades,
    }


def pa_factor_attribution(
    trades: list[dict[str, Any]],
    *,
    min_samples: int = 10,
    edge_r: float = 0.10,
) -> dict[str, Any]:
    """Which confluence factors helped? Compare avg R with vs without each factor.

    ``keep``  : trades with the factor beat trades without it by >= ``edge_r``
    ``drop``  : trades with the factor are worse by >= ``edge_r``
    ``neutral`` otherwise; ``insufficient`` when either side has < ``min_samples``.
    Also checks whether the confluence score ranks outcomes (rank IC + quintiles).
    """
    all_factors = sorted({f for t in trades for f in (t.get("factors") or [])})
    rows = []
    for f in all_factors:
        with_f = [t["r"] for t in trades if f in (t.get("factors") or [])]
        without = [t["r"] for t in trades if f not in (t.get("factors") or [])]
        avg_w = sum(with_f) / len(with_f) if with_f else None
        avg_wo = sum(without) / len(without) if without else None
        if len(with_f) < min_samples or len(without) < min_samples:
            action = "insufficient"
        elif avg_w - avg_wo >= edge_r:  # type: ignore[operator]
            action = "keep"
        elif avg_wo - avg_w >= edge_r:  # type: ignore[operator]
            action = "drop"
        else:
            action = "neutral"
        rows.append(
            {
                "factor": f,
                "n_with": len(with_f),
                "n_without": len(without),
                "avg_r_with": None if avg_w is None else round(avg_w, 3),
                "avg_r_without": None if avg_wo is None else round(avg_wo, 3),
                "win_rate_with_pct": (
                    round(100.0 * sum(1 for r in with_f if r > 0) / len(with_f), 1)
                    if with_f else None
                ),
                "edge_r": (
                    None if avg_w is None or avg_wo is None else round(avg_w - avg_wo, 3)
                ),
                "action": action,
            }
        )
    rows.sort(key=lambda r: (r["edge_r"] is None, -(r["edge_r"] or 0)))

    scores = [t.get("confluence_score") for t in trades]
    rs = [t["r"] for t in trades]
    ic = rank_ic(scores, rs)  # type: ignore[arg-type]
    buckets = quantile_spread(scores, rs, n_quantiles=min(5, max(2, len(trades) // 10)))  # type: ignore[arg-type]
    if ic is None:
        score_text = "Skor-sonuç ilişkisi için yeterli işlem yok."
    elif ic >= 0.05:
        score_text = f"Yüksek confluence skoru daha iyi sonuç vermiş (IC {ic:+.2f})."
    elif ic <= -0.05:
        score_text = f"Confluence skoru ters çalışıyor (IC {ic:+.2f}) — ağırlıklar yanlış."
    else:
        score_text = f"Confluence skoru sonucu tahmin etmiyor (IC {ic:+.2f})."
    return {
        "factors": rows,
        "keep": [r["factor"] for r in rows if r["action"] == "keep"],
        "drop": [r["factor"] for r in rows if r["action"] == "drop"],
        "confluence_score_check": {"rank_ic": ic, "quantiles_r": buckets, "summary_tr": score_text},
    }


__all__ = [
    "backtest_job",
    "backtest_simple_pa",
    "default_workers",
    "group_trades",
    "pa_factor_attribution",
    "run_backtests",
    "summarize_trades",
]


def backtest_job(kwargs: dict[str, Any]) -> dict[str, Any]:
    """Picklable entry point for process pools: ``backtest_simple_pa(**kwargs)``."""
    return backtest_simple_pa(**kwargs)


def default_workers() -> int:
    import os

    env = os.environ.get("BIST_WORKERS")
    if env and env.isdigit():
        return int(env)
    return max(1, min(4, (os.cpu_count() or 2) - 1))


def run_backtests(jobs: list[dict[str, Any]], workers: int | None = None) -> list[Any]:
    """Run many backtests, in parallel processes when it pays off.

    Returns results in input order; a job that raised returns its exception.
    Falls back to in-process execution if a pool cannot be started (restricted
    sandboxes, frozen apps) — the answer is the same, only slower.
    """
    workers = default_workers() if workers is None else workers

    def inline() -> list[Any]:
        out: list[Any] = []
        for j in jobs:
            try:
                out.append(backtest_simple_pa(**j))
            except Exception as e:  # noqa: BLE001 — reported per symbol by the caller
                out.append(e)
        return out

    if workers <= 1 or len(jobs) <= 1:
        return inline()
    from concurrent.futures import ProcessPoolExecutor
    from concurrent.futures.process import BrokenProcessPool

    try:
        with ProcessPoolExecutor(max_workers=min(workers, len(jobs))) as pool:
            futs = [pool.submit(backtest_job, j) for j in jobs]
            out = []
            for f in futs:
                try:
                    out.append(f.result())
                except BrokenProcessPool:
                    raise
                except Exception as e:  # noqa: BLE001
                    out.append(e)
            return out
    except (OSError, BrokenProcessPool, RuntimeError):
        return inline()

"""Portfolio risk engine — sizing, limits and circuit breakers for every new trade.

A signal is only half a trade. Before anything is logged or drawn,
:func:`check_trade` answers: how many shares, and is the *portfolio* allowed to
take this risk right now?

Checks (``block`` stops the trade, ``warn`` is shown but allowed):

- geometry            stop/target on the right side of the entry          block
- circuit breaker     realised loss today / this week beyond the limit     block
- duplicate           already holding this symbol                          block
- max positions       too many open trades                                 block
- open risk (heat)    sum of stop risk would exceed the cap                block
- correlation cluster too many open trades moving together (60-bar corr)  block
- liquidity           position value vs 20-day average traded value        warn / block at 3x
- limit day           last bar moved ≥ 9.5% (BIST ±10% tavan/taban)        warn
- macro event         high-importance TCMB/CPI event within N days         warn

Positions come from the trade journal: ``open`` trades, plus ``planned`` ones
when checking a new trade (a queued plan reserves its risk). Rows without
a stored quantity count as one standard risk unit. Closed trades store P&L in R,
converted to % of equity with ``risk_per_trade_pct``.
"""

from __future__ import annotations

import json
import math
import os
from dataclasses import asdict, dataclass, fields
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

LIMIT_DAY_MOVE = 0.095


@dataclass
class RiskConfig:
    equity: float = 100_000.0
    risk_per_trade_pct: float = 1.0
    max_open_risk_pct: float = 6.0
    max_positions: int = 6
    max_cluster_positions: int = 2
    cluster_corr: float = 0.7
    daily_loss_limit_pct: float = 3.0
    weekly_loss_limit_pct: float = 6.0
    max_adv_pct: float = 5.0
    event_blackout_days: int = 1
    lot_size: int = 1

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RiskConfig:
        names = {f.name: f.type for f in fields(cls)}
        clean: dict[str, Any] = {}
        for k, v in (data or {}).items():
            if k not in names or v is None:
                continue
            clean[k] = int(v) if k in ("max_positions", "max_cluster_positions",
                                       "event_blackout_days", "lot_size") else float(v)
        cfg = cls(**clean)
        cfg.validate()
        return cfg

    def validate(self) -> None:
        if self.equity <= 0:
            raise ValueError("equity must be > 0")
        if not 0 < self.risk_per_trade_pct <= 10:
            raise ValueError("risk_per_trade_pct must be in (0, 10]")
        if self.max_open_risk_pct < self.risk_per_trade_pct:
            raise ValueError("max_open_risk_pct must be >= risk_per_trade_pct")
        if self.max_positions < 1 or self.lot_size < 1:
            raise ValueError("max_positions and lot_size must be >= 1")
        if not 0 < self.cluster_corr <= 1:
            raise ValueError("cluster_corr must be in (0, 1]")


def config_path() -> Path:
    env = os.environ.get("BIST_RISK_CONFIG")
    if env:
        return Path(env)
    from .data_store import default_db_path

    return default_db_path().parent / "risk_config.json"


def load_config() -> RiskConfig:
    try:
        return RiskConfig.from_dict(json.loads(config_path().read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError):
        return RiskConfig()


def save_config(updates: dict[str, Any]) -> RiskConfig:
    from ._fileio import atomic_write_text, locked

    path = config_path()
    with locked(path):  # read-modify-write: concurrent partial updates must not collide
        cfg = RiskConfig.from_dict({**asdict(load_config()), **(updates or {})})
        atomic_write_text(path, json.dumps(asdict(cfg), indent=1))
    return cfg


# --------------------------------------------------------------------------- journal


def _journal_rows(journal_path: str | Path | None) -> list[dict[str, Any]]:
    from .trade_journal import _default_journal_path, _load

    return _load(Path(journal_path) if journal_path else _default_journal_path())


def _row_risk_amount(row: dict[str, Any], cfg: RiskConfig) -> float:
    sizing = row.get("sizing") or (row.get("plan_snapshot") or {}).get("sizing") or {}
    qty = sizing.get("quantity") if isinstance(sizing, dict) else None
    try:
        if qty:
            return float(qty) * abs(float(row["entry"]) - float(row["stop"]))
    except (KeyError, TypeError, ValueError):
        pass
    return cfg.equity * cfg.risk_per_trade_pct / 100.0


def _parse_ts(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def realised_pnl_pct(
    rows: list[dict[str, Any]], cfg: RiskConfig, now: datetime
) -> dict[str, float]:
    """Realised P&L (% of equity) of trades closed today / in the last 7 days."""
    day = week = 0.0
    for r in rows:
        if r.get("status") != "closed" or r.get("pnl") is None:
            continue
        ts = _parse_ts(r.get("updated_at") or r.get("logged_at"))
        if ts is None:
            continue
        pct = float(r["pnl"]) * cfg.risk_per_trade_pct
        if ts.date() == now.date():
            day += pct
        if now - ts <= timedelta(days=7):
            week += pct
    return {"today_pct": round(day, 3), "week_pct": round(week, 3)}


# --------------------------------------------------------------------------- math


def _log_returns(closes: list[float], n: int = 60) -> list[float]:
    c = [x for x in closes[-(n + 1):] if x and x > 0]
    return [math.log(b / a) for a, b in zip(c, c[1:], strict=False)]


def _corr(a: list[float], b: list[float]) -> float | None:
    k = min(len(a), len(b))
    if k < 20:
        return None
    a, b = a[-k:], b[-k:]
    ma, mb = sum(a) / k, sum(b) / k
    va = sum((x - ma) ** 2 for x in a)
    vb = sum((y - mb) ** 2 for y in b)
    if va <= 0 or vb <= 0:
        return None
    return sum((x - ma) * (y - mb) for x, y in zip(a, b, strict=True)) / math.sqrt(va * vb)


def position_size(entry: float, stop: float, cfg: RiskConfig) -> dict[str, Any]:
    per_share = abs(entry - stop)
    if per_share <= 0:
        return {"quantity": 0, "risk_amount": 0.0, "notional": 0.0, "risk_pct": 0.0}
    budget = cfg.equity * cfg.risk_per_trade_pct / 100.0
    qty = int(budget / per_share) // cfg.lot_size * cfg.lot_size
    # never more notional than the whole account (no leverage by default)
    max_qty = int(cfg.equity / entry) // cfg.lot_size * cfg.lot_size if entry > 0 else 0
    qty = max(0, min(qty, max_qty))
    risk_amount = qty * per_share
    return {
        "quantity": qty,
        "risk_amount": round(risk_amount, 2),
        "notional": round(qty * entry, 2),
        "risk_pct": round(100.0 * risk_amount / cfg.equity, 3),
    }


# --------------------------------------------------------------------------- checks


def _check(name: str, ok: bool, detail: str, severity: str = "block") -> dict[str, Any]:
    return {"name": name, "ok": ok, "severity": severity, "detail": detail}


def check_trade(
    plan: dict[str, Any],
    *,
    symbol: str,
    cfg: RiskConfig | None = None,
    bars_by_symbol: dict[str, dict[str, Any]] | None = None,
    journal_path: str | Path | None = None,
    now: datetime | None = None,
    events: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Size a plan and run every portfolio check against it."""
    cfg = cfg or load_config()
    now = now or datetime.now(timezone.utc)
    bars_by_symbol = bars_by_symbol or {}
    sym = symbol.strip().upper()
    rows = _journal_rows(journal_path)
    # Planned (not yet filled) trades reserve risk too — otherwise a scan could
    # queue five 1% plans on top of a full book.
    open_rows = [r for r in rows if r.get("status") in ("open", "planned")]
    checks: list[dict[str, Any]] = []

    direction = plan.get("direction")
    entry = float(plan["entry"])
    stop = float(plan["stop"])
    target = plan.get("target")
    if target is None and plan.get("targets"):
        target = plan["targets"][0]
    target = float(target) if target is not None else None
    geom = (
        (direction == "long" and stop < entry and (target is None or target > entry))
        or (direction == "short" and stop > entry and (target is None or target < entry))
    )
    checks.append(_check("geometry", geom, "stop/hedef giriş ile doğru tarafta"
                         if geom else "stop veya hedef girişin yanlış tarafında"))

    pnl = realised_pnl_pct(rows, cfg, now)
    day_ok = pnl["today_pct"] > -cfg.daily_loss_limit_pct
    week_ok = pnl["week_pct"] > -cfg.weekly_loss_limit_pct
    checks.append(_check(
        "circuit_breaker", day_ok and week_ok,
        f"bugün %{pnl['today_pct']:+.2f} (limit -%{cfg.daily_loss_limit_pct}), "
        f"7 gün %{pnl['week_pct']:+.2f} (limit -%{cfg.weekly_loss_limit_pct})",
    ))

    dup = any(str(r.get("symbol", "")).upper() == sym for r in open_rows)
    checks.append(_check("duplicate", not dup,
                         f"{sym} için zaten açık/bekleyen işlem var" if dup
                         else "açık işlem yok"))

    n_open = len(open_rows)
    checks.append(_check("max_positions", n_open < cfg.max_positions,
                         f"{n_open}/{cfg.max_positions} pozisyon açık"))

    size = position_size(entry, stop, cfg)
    open_risk_pct = 100.0 * sum(_row_risk_amount(r, cfg) for r in open_rows) / cfg.equity
    after = open_risk_pct + size["risk_pct"]
    checks.append(_check(
        "open_risk", after <= cfg.max_open_risk_pct + 1e-9,
        f"açık risk %{open_risk_pct:.2f} → %{after:.2f} (limit %{cfg.max_open_risk_pct})",
    ))
    checks.append(_check("size", size["quantity"] > 0,
                         f"{size['quantity']} adet, risk {size['risk_amount']} "
                         f"(%{size['risk_pct']})"))

    # correlation cluster
    cand = bars_by_symbol.get(sym)
    if cand and open_rows:
        rc = _log_returns(cand["closes"])
        mates = []
        for r in open_rows:
            osym = str(r.get("symbol", "")).upper()
            ob = bars_by_symbol.get(osym)
            if not ob:
                continue
            c = _corr(rc, _log_returns(ob["closes"]))
            if c is not None and c >= cfg.cluster_corr:
                mates.append(f"{osym} ({c:.2f})")
        ok = len(mates) < cfg.max_cluster_positions
        checks.append(_check(
            "correlation_cluster", ok,
            (f"birlikte hareket eden açık pozisyonlar: {', '.join(mates)}"
             if mates else "yüksek korelasyonlu açık pozisyon yok")
            + f" (limit {cfg.max_cluster_positions})",
        ))

    # liquidity
    if cand and cand.get("volumes"):
        vals = [c * v for c, v in zip(cand["closes"][-20:], cand["volumes"][-20:], strict=False)
                if v]
        if vals:
            adv = sum(vals) / len(vals)
            share = 100.0 * size["notional"] / adv if adv > 0 else 0.0
            sev = "block" if share > cfg.max_adv_pct * 3 else "warn"
            checks.append(_check(
                "liquidity", share <= cfg.max_adv_pct,
                f"pozisyon, 20 günlük ort. işlem hacminin %{share:.1f}'i "
                f"(limit %{cfg.max_adv_pct})", sev,
            ))

    # limit day (tavan / taban)
    if cand and len(cand["closes"]) >= 2 and cand["closes"][-2] > 0:
        mv = cand["closes"][-1] / cand["closes"][-2] - 1.0
        checks.append(_check(
            "limit_day", abs(mv) < LIMIT_DAY_MOVE,
            f"son bar %{mv * 100:+.1f}" + (" — tavan/taban günü, ertesi gün boşluk riski"
                                           if abs(mv) >= LIMIT_DAY_MOVE else ""),
            "warn",
        ))

    # macro events
    if events is None:
        events = _upcoming_events(now.date(), cfg.event_blackout_days)
    hot = [e for e in events if e.get("importance") == "high"]
    checks.append(_check(
        "macro_event", not hot,
        ("yaklaşan önemli olay: " + ", ".join(f"{e['date']} {e['event']}" for e in hot))
        if hot else "yakın önemli makro olay yok",
        "warn",
    ))

    blocks = [c for c in checks if not c["ok"] and c["severity"] == "block"]
    warns = [c for c in checks if not c["ok"] and c["severity"] == "warn"]
    approved = not blocks
    if approved:
        text = (f"ONAY — {size['quantity']} adet, risk %{size['risk_pct']} "
                f"({size['risk_amount']}).")
        if warns:
            text += " Uyarılar: " + "; ".join(c["detail"] for c in warns) + "."
    else:
        text = "RED — " + "; ".join(c["detail"] for c in blocks) + "."
    return {
        "symbol": sym,
        "approved": approved,
        "sizing": size if approved else {**size, "quantity": 0},
        "checks": checks,
        "blocking": [c["name"] for c in blocks],
        "warnings": [c["name"] for c in warns],
        "summary_tr": text,
    }


def _upcoming_events(today: date, days: int) -> list[dict[str, Any]]:
    if days <= 0:
        return []
    from .calendar_data import build_calendar

    return [asdict(e) for e in build_calendar(today, today + timedelta(days=days))]


# --------------------------------------------------------------------------- portfolio


def portfolio_risk(
    *,
    cfg: RiskConfig | None = None,
    bars_by_symbol: dict[str, dict[str, Any]] | None = None,
    journal_path: str | Path | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Heat, positions, realised P&L, breaker state, clusters, 1-day 95% VaR."""
    cfg = cfg or load_config()
    now = now or datetime.now(timezone.utc)
    bars_by_symbol = bars_by_symbol or {}
    rows = _journal_rows(journal_path)
    open_rows = [r for r in rows if r.get("status") == "open"]
    positions = []
    for r in open_rows:
        sym = str(r.get("symbol", "")).upper()
        risk_amt = _row_risk_amount(r, cfg)
        b = bars_by_symbol.get(sym)
        last = b["closes"][-1] if b and b.get("closes") else None
        qty = ((r.get("sizing") or {}) if isinstance(r.get("sizing"), dict) else {}).get(
            "quantity"
        )
        if not qty and r.get("entry") and r.get("stop"):
            per = abs(float(r["entry"]) - float(r["stop"]))
            qty = risk_amt / per if per > 0 else 0
        open_pnl = None
        if last is not None and qty and r.get("entry"):
            sign = 1 if r.get("direction") == "long" else -1
            open_pnl = round(sign * (last - float(r["entry"])) * float(qty), 2)
        positions.append({
            "id": r.get("id"), "symbol": sym, "direction": r.get("direction"),
            "entry": r.get("entry"), "stop": r.get("stop"), "last": last,
            "quantity": round(float(qty or 0), 2),
            "risk_pct": round(100.0 * risk_amt / cfg.equity, 3), "open_pnl": open_pnl,
        })
    heat = round(sum(p["risk_pct"] for p in positions), 3)
    pending = [r for r in rows if r.get("status") == "planned"]
    pending_risk = round(
        sum(100.0 * _row_risk_amount(r, cfg) / cfg.equity for r in pending), 3
    )
    pnl = realised_pnl_pct(rows, cfg, now)
    breaker = (pnl["today_pct"] <= -cfg.daily_loss_limit_pct
               or pnl["week_pct"] <= -cfg.weekly_loss_limit_pct)

    # clusters among open positions
    syms = [p["symbol"] for p in positions if p["symbol"] in bars_by_symbol]
    rets = {s: _log_returns(bars_by_symbol[s]["closes"]) for s in syms}
    pairs = []
    for i, a in enumerate(syms):
        for b in syms[i + 1:]:
            c = _corr(rets[a], rets[b])
            if c is not None and c >= cfg.cluster_corr:
                pairs.append({"a": a, "b": b, "corr": round(c, 2)})

    var95 = _historical_var(positions, rets)
    return {
        "equity": cfg.equity,
        "open_positions": len(positions),
        "max_positions": cfg.max_positions,
        "heat_pct": heat,
        "pending_plans": len(pending),
        "pending_risk_pct": pending_risk,
        "max_open_risk_pct": cfg.max_open_risk_pct,
        "realised": pnl,
        "circuit_breaker": breaker,
        "correlated_pairs": pairs,
        "var_95_1d": var95,
        "positions": positions,
        "summary_tr": (
            f"{len(positions)}/{cfg.max_positions} pozisyon, açık risk %{heat:.2f} "
            f"(limit %{cfg.max_open_risk_pct}), bekleyen {len(pending)} plan "
            f"%{pending_risk:.2f}. Bugün %{pnl['today_pct']:+.2f}, 7 gün "
            f"%{pnl['week_pct']:+.2f}."
            + (" DEVRE KESİCİ AKTİF — yeni işlem yok." if breaker else "")
            + (f" 1 günlük %95 VaR ≈ {var95['amount']:,.0f} (%{var95['pct']})."
               if var95 else "")
        ),
    }


def _historical_var(
    positions: list[dict[str, Any]], rets: dict[str, list[float]]
) -> dict[str, Any] | None:
    legs = [(p, rets[p["symbol"]]) for p in positions
            if p["symbol"] in rets and p.get("last") and p.get("quantity")]
    if not legs:
        return None
    k = min(len(r) for _, r in legs)
    if k < 20:
        return None
    pnl = []
    for i in range(1, k + 1):
        day = 0.0
        for p, r in legs:
            sign = 1 if p["direction"] == "long" else -1
            day += sign * float(p["quantity"]) * float(p["last"]) * (math.exp(r[-i]) - 1)
        pnl.append(day)
    pnl.sort()
    loss = -pnl[max(0, int(0.05 * len(pnl)) - 1)]
    exposure = sum(float(p["quantity"]) * float(p["last"]) for p, _ in legs)
    return {"amount": round(max(0.0, loss), 2),
            "pct": round(100.0 * max(0.0, loss) / exposure, 2) if exposure else None,
            "days": k}


__all__ = [
    "RiskConfig",
    "check_trade",
    "config_path",
    "load_config",
    "portfolio_risk",
    "position_size",
    "save_config",
]

"""Local trade journal — log plans, track open positions, monitor risk."""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from ._fileio import atomic_write_text, locked

Status = Literal["planned", "open", "closed", "cancelled"]


def _default_journal_path() -> Path:
    override = os.environ.get("BIST_TRADE_JOURNAL")
    if override:
        path = Path(override)
        path.parent.mkdir(parents=True, exist_ok=True)
        return path
    base = Path.home() / ".bist-trader"
    base.mkdir(parents=True, exist_ok=True)
    return base / "trade_journal.json"


def _load(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        # Never let the next save overwrite a damaged journal: keep a copy.
        backup = path.with_name(
            f"{path.name}.corrupt-{datetime.now(timezone.utc):%Y%m%dT%H%M%S}"
        )
        try:
            os.replace(path, backup)
        except OSError:
            pass
        return []
    return data if isinstance(data, list) else []


def _save(path: Path, rows: list[dict[str, Any]]) -> None:
    atomic_write_text(path, json.dumps(rows, indent=2, ensure_ascii=False))


def log_trade_plan(
    plan: dict[str, Any],
    *,
    status: Status = "planned",
    notes: str | None = None,
    journal_path: str | Path | None = None,
) -> dict[str, Any]:
    """Persist a design_trade_setup / design_from_price_action output."""
    path = Path(journal_path) if journal_path else _default_journal_path()
    with locked(path):
        return _log_locked(path, plan, status, notes)


def _log_locked(
    path: Path, plan: dict[str, Any], status: Status, notes: str | None
) -> dict[str, Any]:
    rows = _load(path)
    trade_id = str(uuid.uuid4())[:8]
    row = {
        "id": trade_id,
        "logged_at": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "symbol": plan.get("symbol"),
        "direction": plan.get("direction"),
        "entry": plan.get("entry"),
        "stop": plan.get("stop"),
        "targets": plan.get("targets"),
        "best_risk_reward": plan.get("best_risk_reward"),
        "approved": plan.get("approved"),
        "sizing": plan.get("sizing"),
        "notes": notes,
        "plan_snapshot": plan,
    }
    rows.append(row)
    _save(path, rows)
    return {
        "source": "bist-trader-mcp — trade_journal.log_trade_plan",
        "journal_path": str(path),
        "trade_id": trade_id,
        "logged": row,
    }


def list_trade_journal(
    *,
    status: Status | None = None,
    symbol: str | None = None,
    limit: int = 50,
    journal_path: str | Path | None = None,
) -> dict[str, Any]:
    path = Path(journal_path) if journal_path else _default_journal_path()
    rows = _load(path)
    if status:
        rows = [r for r in rows if r.get("status") == status]
    if symbol:
        sym = symbol.upper()
        rows = [r for r in rows if str(r.get("symbol", "")).upper() == sym]
    rows = sorted(rows, key=lambda r: r.get("logged_at") or "", reverse=True)[:limit]
    open_rows = [r for r in _load(path) if r.get("status") == "open"]
    return {
        "source": "bist-trader-mcp — trade_journal.list_trade_journal",
        "journal_path": str(path),
        "count": len(rows),
        "open_count": len(open_rows),
        "trades": rows,
    }


def update_trade_status(
    trade_id: str,
    status: Status,
    *,
    exit_price: float | None = None,
    pnl: float | None = None,
    notes: str | None = None,
    journal_path: str | Path | None = None,
) -> dict[str, Any]:
    path = Path(journal_path) if journal_path else _default_journal_path()
    with locked(path):
        return _update_locked(path, trade_id, status, exit_price, pnl, notes)


def _update_locked(
    path: Path,
    trade_id: str,
    status: Status,
    exit_price: float | None,
    pnl: float | None,
    notes: str | None,
) -> dict[str, Any]:
    rows = _load(path)
    found = None
    for r in rows:
        if r.get("id") == trade_id:
            r["status"] = status
            r["updated_at"] = datetime.now(timezone.utc).isoformat()
            if exit_price is not None:
                r["exit_price"] = exit_price
            if pnl is not None:
                r["pnl"] = pnl
            if notes:
                r["notes"] = (r.get("notes") or "") + f" | {notes}"
            found = r
            break
    if not found:
        return {"error": "not_found", "detail": f"trade_id {trade_id} not in journal"}
    _save(path, rows)
    return {"source": "bist-trader-mcp — trade_journal.update_trade_status", "trade": found}


def monitor_open_trades(
    mark_prices: dict[str, float] | None = None,
    *,
    journal_path: str | Path | None = None,
) -> dict[str, Any]:
    """Check open journal trades against optional latest prices."""
    path = Path(journal_path) if journal_path else _default_journal_path()
    open_rows = [r for r in _load(path) if r.get("status") == "open"]
    alerts: list[dict[str, Any]] = []

    for r in open_rows:
        sym = str(r.get("symbol") or "")
        entry = float(r.get("entry") or 0)
        stop = float(r.get("stop") or 0)
        direction = r.get("direction")
        price = (mark_prices or {}).get(sym)
        if price is None:
            continue
        risk = abs(entry - stop) if entry and stop else 0
        if direction == "long":
            if price <= stop:
                alerts.append({"trade_id": r["id"], "symbol": sym, "alert": "stop_hit", "price": price})
            elif risk and price >= entry + risk * 2:
                alerts.append({"trade_id": r["id"], "symbol": sym, "alert": "tp2_zone", "price": price})
        elif direction == "short":
            if price >= stop:
                alerts.append({"trade_id": r["id"], "symbol": sym, "alert": "stop_hit", "price": price})
            elif risk and price <= entry - risk * 2:
                alerts.append({"trade_id": r["id"], "symbol": sym, "alert": "tp2_zone", "price": price})

    return {
        "source": "bist-trader-mcp — trade_journal.monitor_open_trades",
        "open_count": len(open_rows),
        "open_trades": open_rows,
        "alerts": alerts,
        "notes": "Pass mark_prices from quote_get / latest bar close for live monitoring.",
    }


__all__ = [
    "log_trade_plan",
    "list_trade_journal",
    "update_trade_status",
    "monitor_open_trades",
]

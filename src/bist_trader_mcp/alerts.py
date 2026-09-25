"""Alerts — Telegram + local outbox, deduplicated.

What triggers an alert:

- **Trade lifecycle** from the daily pipeline / tracker: a plan filled, hit its
  stop or target, timed out, or was cancelled.
- **New picks** logged by the daily pipeline.
- **Stop proximity**: an open trade's price is within ``near_stop_r`` of its
  stop (default 0.3 R), from delayed Yahoo quotes.
- **KAP**: a material disclosure for a symbol you hold or plan to trade.

Every alert is appended to a local outbox (``alerts.jsonl``) so nothing is lost
when Telegram is not configured; with ``BIST_TELEGRAM_BOT_TOKEN`` and
``BIST_TELEGRAM_CHAT_ID`` set it is also sent to Telegram. Each alert has a key
and is sent once. The bot token never appears in results, errors or logs.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ._fileio import atomic_write_text, locked

TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"
MAX_TEXT = 3900  # Telegram limit is 4096; leave room
STATE_KEEP = 2000


def _data_dir() -> Path:
    from .data_store import default_db_path

    return default_db_path().parent


def outbox_path() -> Path:
    return Path(os.environ.get("BIST_ALERTS_FILE") or (_data_dir() / "alerts.jsonl"))


def _state_path() -> Path:
    return outbox_path().with_name("alerts_state.json")


def telegram_configured() -> bool:
    return bool(os.environ.get("BIST_TELEGRAM_BOT_TOKEN") and
                os.environ.get("BIST_TELEGRAM_CHAT_ID"))


def _redact(text: str) -> str:
    token = os.environ.get("BIST_TELEGRAM_BOT_TOKEN")
    return text.replace(token, "***") if token else text


# --------------------------------------------------------------------------- build


def alert(key: str, kind: str, symbol: str | None, text: str,
          severity: str = "info") -> dict[str, Any]:
    return {"key": key, "kind": kind, "symbol": symbol, "text": text, "severity": severity,
            "time": datetime.now(timezone.utc).isoformat(timespec="seconds")}


_LIFECYCLE_TR = {
    "open": "pozisyon açıldı (giriş doldu)",
    "cancelled": "plan iptal (giriş dolmadı)",
}
_REASON_TR = {"target": "HEDEF", "target_gap": "HEDEF (boşlukla)", "stop": "STOP",
              "stop_gap": "STOP (boşlukla)", "timeout": "süre doldu"}


def from_tracked_changes(changes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for c in changes:
        sym, tid, st = c.get("symbol"), c.get("trade_id"), c.get("status")
        if st == "closed":
            r = c.get("r")
            reason = _REASON_TR.get(c.get("reason"), c.get("reason"))
            sev = "good" if (r or 0) > 0 else "bad"
            text = f"{sym}: {reason} — işlem kapandı, sonuç {r:+.2f}R (çıkış {c.get('exit')})."
            out.append(alert(f"trade:{tid}:closed", "trade_closed", sym, text, sev))
        elif st in _LIFECYCLE_TR:
            out.append(alert(f"trade:{tid}:{st}", f"trade_{st}", sym,
                             f"{sym}: {_LIFECYCLE_TR[st]}.", "info"))
    return out


def from_new_picks(picks: list[dict[str, Any]], day: str) -> list[dict[str, Any]]:
    out = []
    for p in picks:
        plan = p.get("plan") or {}
        qty = ((p.get("risk") or {}).get("sizing") or {}).get("quantity")
        text = (f"{p['symbol']} {p.get('verdict')}: giriş {plan.get('entry')}, stop "
                f"{plan.get('stop')}, hedef {plan.get('target')} (R:R {plan.get('risk_reward')})"
                + (f", {qty} adet" if qty else "") + ".")
        out.append(alert(f"pick:{day}:{p['symbol']}", "new_pick", p["symbol"], text, "info"))
    return out


def near_stop_alerts(
    open_rows: list[dict[str, Any]], prices: dict[str, float], near_stop_r: float = 0.3
) -> list[dict[str, Any]]:
    out = []
    for r in open_rows:
        sym = str(r.get("symbol") or "").upper()
        px = prices.get(sym)
        try:
            entry, stop = float(r["entry"]), float(r["stop"])
        except (KeyError, TypeError, ValueError):
            continue
        risk = abs(entry - stop)
        if px is None or risk <= 0:
            continue
        dist_r = (px - stop) / risk if r.get("direction") == "long" else (stop - px) / risk
        if dist_r <= near_stop_r:
            text = (f"{sym}: fiyat {px:.2f} stopa çok yakın ({stop:.2f}, "
                    f"{max(dist_r, 0):.2f}R kaldı).")
            day = datetime.now(timezone.utc).date().isoformat()
            out.append(alert(f"near_stop:{r.get('id')}:{day}", "near_stop", sym, text, "bad"))
    return out


def kap_alerts(disclosures: list[dict[str, Any]], symbols: set[str]) -> list[dict[str, Any]]:
    out = []
    for d in disclosures:
        sym = (d.get("company_ticker") or "").upper()
        if sym in symbols and d.get("is_material"):
            out.append(alert(f"kap:{d.get('disclosure_id')}", "kap", sym,
                             f"KAP — {sym}: {d.get('subject')}", "info"))
    return out


# --------------------------------------------------------------------------- deliver


async def _send_telegram(text: str) -> tuple[bool, str | None]:
    from .http_utils import SourceError, fetch_json

    token = os.environ.get("BIST_TELEGRAM_BOT_TOKEN", "")
    chat = os.environ.get("BIST_TELEGRAM_CHAT_ID", "")
    try:
        res = await fetch_json(
            TELEGRAM_API.format(token=token), method="POST",
            json_body={"chat_id": chat, "text": text[:MAX_TEXT],
                       "disable_web_page_preview": True},
            retries=2, source="telegram",
        )
    except SourceError as e:
        return False, _redact(str(e))
    if isinstance(res, dict) and res.get("ok"):
        return True, None
    return False, _redact(str((res or {}).get("description") or "telegram error"))


async def deliver(alerts: list[dict[str, Any]], *, send: bool = True) -> dict[str, Any]:
    """Drop already-sent keys, append the rest to the outbox, push to Telegram."""
    if not alerts:
        return {"new": 0, "sent": 0, "telegram": telegram_configured(), "errors": []}
    state_p = _state_path()
    with locked(state_p):
        try:
            sent_keys: list[str] = json.loads(state_p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            sent_keys = []
        seen = set(sent_keys)
        fresh = [a for a in alerts if a["key"] not in seen]
        # mark before sending: a crash mid-send must not spam on the next run
        sent_keys = (sent_keys + [a["key"] for a in fresh])[-STATE_KEEP:]
        atomic_write_text(state_p, json.dumps(sent_keys))
    if not fresh:
        return {"new": 0, "sent": 0, "telegram": telegram_configured(), "errors": []}
    box = outbox_path()
    with locked(box):
        with box.open("a", encoding="utf-8") as f:
            for a in fresh:
                f.write(json.dumps(a, ensure_ascii=False) + "\n")
    sent, errors = 0, []
    if send and telegram_configured():
        icon = {"good": "✅", "bad": "⚠️", "info": "ℹ️"}
        text = "\n".join(f"{icon.get(a['severity'], '•')} {a['text']}" for a in fresh)
        ok, err = await _send_telegram("BIST Trader\n" + text)
        sent = len(fresh) if ok else 0
        if err:
            errors.append(err)
    return {"new": len(fresh), "sent": sent, "telegram": telegram_configured(),
            "errors": errors, "alerts": fresh}


def recent_alerts(limit: int = 50) -> list[dict[str, Any]]:
    box = outbox_path()
    if not box.is_file():
        return []
    lines = box.read_text(encoding="utf-8").splitlines()[-limit:]
    out = []
    for ln in reversed(lines):
        try:
            out.append(json.loads(ln))
        except json.JSONDecodeError:
            continue
    return out


__all__ = [
    "deliver", "from_new_picks", "from_tracked_changes", "kap_alerts", "near_stop_alerts",
    "outbox_path", "recent_alerts", "telegram_configured",
]

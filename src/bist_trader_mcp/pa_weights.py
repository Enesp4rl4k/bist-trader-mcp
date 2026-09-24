"""Learned PA weights — what the backtest taught us, fed back into live analysis.

``backtest_price_action_universe(save_weights=True)`` writes a JSON file with:

- ``factor_weights``: multiplier per confluence factor (drop → 0.0, keep → 1.25,
  otherwise 1.0). ``pa_setups.score_confluence`` multiplies each factor's points
  by this, so factors that lost money stop pushing setups over the threshold.
- ``setup_track_record``: historical trades / win rate / avg R per setup type.
  ``pa_simple`` shows it next to the plan and downgrades AL/SAT to BEKLE when a
  setup type has a proven negative expectancy.
- ``validation``: out-of-sample check (weights fitted on the first 2/3 of
  history, compared on the last 1/3). Weights are only ``active`` when they did
  not make the out-of-sample result worse.

Backtests run with weights *disabled* by default (:func:`use_weights(None)`) so
a measurement is never contaminated by what it is measuring.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

KEEP_WEIGHT = 1.25
DROP_WEIGHT = 0.0
MIN_TRACK_RECORD = 20  # trades before a setup's history can change a verdict

_DISABLED = object()
_override: ContextVar[Any] = ContextVar("pa_weights_override", default=None)
_file_cache: dict[str, Any] = {"path": None, "mtime": None, "data": None}


def weights_path() -> Path:
    env = os.environ.get("BIST_PA_WEIGHTS")
    if env:
        return Path(env)
    from .data_store import default_db_path

    return default_db_path().parent / "pa_weights.json"


def load_weights() -> dict[str, Any] | None:
    """Saved weights file (cached by mtime), or None."""
    path = weights_path()
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return None
    if _file_cache["path"] == str(path) and _file_cache["mtime"] == mtime:
        return _file_cache["data"]
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    _file_cache.update(path=str(path), mtime=mtime, data=data)
    return data


def save_weights(data: dict[str, Any]) -> str:
    path = weights_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)
    return str(path)


def _effective() -> dict[str, Any] | None:
    ov = _override.get()
    if ov is _DISABLED:
        return None
    if ov is not None:
        return ov
    data = load_weights()
    if not data or not data.get("active", False):
        return None
    return data


def factor_weight(name: str) -> float:
    """Multiplier for one confluence factor (1.0 when nothing is learned)."""
    data = _effective()
    if not data:
        return 1.0
    return float((data.get("factor_weights") or {}).get(name, 1.0))


def setup_track_record(setup_type: str | None) -> dict[str, Any] | None:
    """Historical record of a setup type once it has enough trades."""
    data = _effective()
    if not data or not setup_type:
        return None
    rec = (data.get("setup_track_record") or {}).get(setup_type)
    if not rec or int(rec.get("trades") or 0) < MIN_TRACK_RECORD:
        return None
    return rec


@contextmanager
def use_weights(data: dict[str, Any] | None) -> Iterator[None]:
    """Temporarily apply ``data`` as the weights; ``None`` disables learning."""
    token = _override.set(_DISABLED if data is None else data)
    try:
        yield
    finally:
        _override.reset(token)


def build_weights(
    attribution: dict[str, Any],
    trades: list[dict[str, Any]],
    *,
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Turn a factor attribution + trade list into a weights document."""
    fw: dict[str, float] = {}
    for row in attribution.get("factors") or []:
        if row["action"] == "drop":
            fw[row["factor"]] = DROP_WEIGHT
        elif row["action"] == "keep":
            fw[row["factor"]] = KEEP_WEIGHT
    by_setup: dict[str, list[float]] = {}
    for t in trades:
        by_setup.setdefault(str(t.get("setup_type")), []).append(float(t["r"]))
    track = {
        k: {
            "trades": len(rs),
            "win_rate_pct": round(100.0 * sum(1 for r in rs if r > 0) / len(rs), 1),
            "avg_r": round(sum(rs) / len(rs), 3),
        }
        for k, rs in by_setup.items()
        if k != "None"
    }
    return {
        "version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "active": True,
        "factor_weights": fw,
        "setup_track_record": track,
        "meta": meta or {},
    }


__all__ = [
    "build_weights",
    "factor_weight",
    "load_weights",
    "save_weights",
    "setup_track_record",
    "use_weights",
    "weights_path",
]

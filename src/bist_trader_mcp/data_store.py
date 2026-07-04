"""Point-in-time panel store — the data backbone for hedge-fund-grade analysis.

This is **Faz A** of ``docs/HEDGE_FUND_GRADE_PLAN.md``: a persistent, survivorship-
safe panel of BIST prices + fundamentals + flows, where every row carries a
``known_at`` timestamp (when the fact could *first* have been known — for KAP
financials this is the disclosure date, not the period end).

The ``known_at`` discipline is what makes look-ahead-free backtests and honest
cross-sectional ranking possible. It extends the causal guarantees already tested
for swing detection (``tests/test_lookahead.py``) down to the fundamental layer.

Implementation note: built on stdlib ``sqlite3`` so it runs and tests with zero
extra dependencies. The public API (upsert / as-of query) is storage-agnostic, so
a DuckDB backend can be swapped in later without touching callers.
"""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Iterable, Sequence
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Location
# ---------------------------------------------------------------------------


def default_db_path() -> Path:
    """Durable, per-user location for the panel DB (env override wins).

    Unlike the response cache (``_cache.py``), this is *not* disposable — it holds
    the historical panel — so it lives under the user-data dir, not the cache dir.
    """
    override = os.environ.get("BIST_PANEL_DB")
    if override:
        return Path(override)
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        root = Path(base) / "bist-trader-mcp"
    else:
        root = Path(os.path.expanduser("~")) / ".local" / "share" / "bist-trader-mcp"
    return root / "panel.db"


def _now_ts() -> int:
    return int(datetime.now(tz=timezone.utc).timestamp())


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS prices (
    ticker      TEXT NOT NULL,
    date        TEXT NOT NULL,          -- ISO yyyy-mm-dd (bar/observation date)
    open        REAL, high REAL, low REAL, close REAL,
    volume      REAL,
    adj_factor  REAL DEFAULT 1.0,       -- cumulative split/dividend adjustment
    known_at    INTEGER NOT NULL,       -- unix sec: when this row was knowable
    PRIMARY KEY (ticker, date)
);

CREATE TABLE IF NOT EXISTS fundamentals (
    ticker                 TEXT NOT NULL,
    period_end             TEXT NOT NULL,   -- reporting period end (yyyy-mm-dd)
    statement              TEXT NOT NULL,   -- income | balance | cashflow | ratio
    line_item              TEXT NOT NULL,   -- e.g. net_income, total_equity, fcf
    value                  REAL,
    currency               TEXT,
    is_inflation_adjusted  INTEGER DEFAULT 0,  -- 1 = TMS 29 restated
    kap_publish_date       TEXT,            -- disclosure date (drives known_at)
    known_at               INTEGER NOT NULL,
    PRIMARY KEY (ticker, period_end, statement, line_item)
);

CREATE TABLE IF NOT EXISTS universe (
    ticker     TEXT NOT NULL,
    date       TEXT NOT NULL,
    in_xu100   INTEGER DEFAULT 0,
    in_xu030   INTEGER DEFAULT 0,
    sector     TEXT,
    is_active  INTEGER DEFAULT 1,         -- 0 once delisted (survivorship-safe)
    known_at   INTEGER NOT NULL,
    PRIMARY KEY (ticker, date)
);

CREATE TABLE IF NOT EXISTS foreign_flow (
    ticker         TEXT NOT NULL,
    date           TEXT NOT NULL,
    foreign_ratio  REAL,
    known_at       INTEGER NOT NULL,
    PRIMARY KEY (ticker, date)
);

CREATE INDEX IF NOT EXISTS idx_fund_lookup
    ON fundamentals (ticker, line_item, known_at);
CREATE INDEX IF NOT EXISTS idx_prices_known
    ON prices (ticker, known_at);
"""


class PanelStore:
    """Thin point-in-time repository over the BIST panel DB.

    Use as a context manager or call :meth:`close` explicitly. Pass
    ``path=":memory:"`` for tests.
    """

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = ":memory:" if path == ":memory:" else Path(path or default_db_path())
        if isinstance(self.path, Path):
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.path))
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    # -- lifecycle ---------------------------------------------------------
    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> PanelStore:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    @contextmanager
    def _tx(self):
        try:
            yield self._conn
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

    # -- writes (idempotent upserts) --------------------------------------
    def upsert_prices(self, rows: Iterable[dict[str, Any]]) -> int:
        """Insert/replace price bars. Each row: ticker, date, o/h/l/c, volume,
        optional adj_factor, optional known_at (defaults to now)."""
        sql = (
            "INSERT OR REPLACE INTO prices "
            "(ticker, date, open, high, low, close, volume, adj_factor, known_at) "
            "VALUES (?,?,?,?,?,?,?,?,?)"
        )
        params = [
            (
                r["ticker"], r["date"],
                r.get("open"), r.get("high"), r.get("low"), r.get("close"),
                r.get("volume"), float(r.get("adj_factor", 1.0)),
                int(r.get("known_at") or _now_ts()),
            )
            for r in rows
        ]
        return self._executemany(sql, params)

    def upsert_fundamentals(self, rows: Iterable[dict[str, Any]]) -> int:
        """Insert/replace fundamental line items.

        ``known_at`` defaults to the KAP publish date (if given) else now — never
        the period end, which would leak future knowledge into backtests.
        """
        sql = (
            "INSERT OR REPLACE INTO fundamentals "
            "(ticker, period_end, statement, line_item, value, currency, "
            " is_inflation_adjusted, kap_publish_date, known_at) "
            "VALUES (?,?,?,?,?,?,?,?,?)"
        )
        params = []
        for r in rows:
            known = r.get("known_at")
            if known is None and r.get("kap_publish_date"):
                known = _date_to_ts(r["kap_publish_date"])
            params.append(
                (
                    r["ticker"], r["period_end"], r["statement"], r["line_item"],
                    r.get("value"), r.get("currency"),
                    1 if r.get("is_inflation_adjusted") else 0,
                    r.get("kap_publish_date"),
                    int(known or _now_ts()),
                )
            )
        return self._executemany(sql, params)

    def upsert_universe(self, rows: Iterable[dict[str, Any]]) -> int:
        sql = (
            "INSERT OR REPLACE INTO universe "
            "(ticker, date, in_xu100, in_xu030, sector, is_active, known_at) "
            "VALUES (?,?,?,?,?,?,?)"
        )
        params = [
            (
                r["ticker"], r["date"],
                1 if r.get("in_xu100") else 0,
                1 if r.get("in_xu030") else 0,
                r.get("sector"),
                0 if r.get("is_active") is False else 1,
                int(r.get("known_at") or _now_ts()),
            )
            for r in rows
        ]
        return self._executemany(sql, params)

    def upsert_foreign_flow(self, rows: Iterable[dict[str, Any]]) -> int:
        sql = (
            "INSERT OR REPLACE INTO foreign_flow "
            "(ticker, date, foreign_ratio, known_at) VALUES (?,?,?,?)"
        )
        params = [
            (r["ticker"], r["date"], r.get("foreign_ratio"),
             int(r.get("known_at") or _now_ts()))
            for r in rows
        ]
        return self._executemany(sql, params)

    def _executemany(self, sql: str, params: Sequence[tuple]) -> int:
        params = list(params)
        if not params:
            return 0
        with self._tx() as conn:
            conn.executemany(sql, params)
        return len(params)

    # -- point-in-time reads ----------------------------------------------
    def get_fundamental_as_of(
        self, ticker: str, line_item: str, as_of: int | str,
        *, statement: str | None = None,
    ) -> dict[str, Any] | None:
        """Latest known value of ``line_item`` for ``ticker`` as of a timestamp.

        Returns the row with the most recent ``period_end`` whose ``known_at`` is
        at or before ``as_of`` — i.e. only facts that were already public. This is
        the look-ahead-safe primitive every fundamental backtest must use.
        """
        ts = as_of if isinstance(as_of, int) else _date_to_ts(as_of)
        sql = (
            "SELECT * FROM fundamentals "
            "WHERE ticker=? AND line_item=? AND known_at<=? "
            + ("AND statement=? " if statement else "")
            + "ORDER BY period_end DESC, known_at DESC LIMIT 1"
        )
        args: list[Any] = [ticker, line_item, ts]
        if statement:
            args.append(statement)
        row = self._conn.execute(sql, args).fetchone()
        return dict(row) if row else None

    def get_price_as_of(
        self, ticker: str, as_of: int | str,
    ) -> dict[str, Any] | None:
        """Most recent price bar for ``ticker`` knowable at ``as_of``."""
        ts = as_of if isinstance(as_of, int) else _date_to_ts(as_of)
        row = self._conn.execute(
            "SELECT * FROM prices WHERE ticker=? AND known_at<=? "
            "ORDER BY date DESC LIMIT 1",
            (ticker, ts),
        ).fetchone()
        return dict(row) if row else None

    def active_universe_as_of(self, as_of: int | str) -> list[str]:
        """Tickers active (not delisted) as of a timestamp — survivorship-safe.

        Takes each ticker's latest universe snapshot knowable at ``as_of`` and
        keeps those still flagged active.
        """
        ts = as_of if isinstance(as_of, int) else _date_to_ts(as_of)
        rows = self._conn.execute(
            "SELECT u.ticker, u.is_active FROM universe u "
            "JOIN (SELECT ticker, MAX(date) AS d FROM universe "
            "      WHERE known_at<=? GROUP BY ticker) m "
            "  ON u.ticker=m.ticker AND u.date=m.d "
            "WHERE u.known_at<=?",
            (ts, ts),
        ).fetchall()
        return sorted(r["ticker"] for r in rows if r["is_active"])

    def counts(self) -> dict[str, int]:
        """Row counts per table — quick ingest sanity check."""
        out: dict[str, int] = {}
        for t in ("prices", "fundamentals", "universe", "foreign_flow"):
            out[t] = self._conn.execute(f"SELECT COUNT(*) AS n FROM {t}").fetchone()["n"]
        return out


def _date_to_ts(d: str) -> int:
    """ISO yyyy-mm-dd → unix seconds (UTC midnight). Pass-through for ints."""
    return int(datetime.strptime(d[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp())


__all__ = ["PanelStore", "default_db_path"]

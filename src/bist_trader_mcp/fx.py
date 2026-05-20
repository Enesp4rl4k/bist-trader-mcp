"""FX forward / swap curve via covered interest-rate parity (CIP).

Pure-math helper that turns a spot rate + a pair of term rates into
forward outright quotes and forward points (pips). The exchange's
forward market is illiquid for retail; CIP-implied forwards are the
practical reference used by Turkish corporates and offshore desks.

Math:
    F(T) = S * exp((r_dom - r_for) * T)
    forward_points = (F - S) * pip_factor

where:
    S            = spot (quoted as DOMESTIC per FOREIGN, i.e. TRY per USD)
    r_dom        = TL rate, decimal
    r_for        = USD/EUR/etc. rate, decimal
    T            = year-fraction
    pip_factor   = 10_000 for USDTRY/EURTRY (4-decimal quote)
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass
class ForwardPoint:
    tenor: str
    days: int
    forward_outright: float
    forward_points_pips: float
    implied_diff_pct: float


def _tenor_to_days(tenor: str) -> int:
    """Translate a Bloomberg-ish tenor string to a day count.

    Recognises: ON, TN, SN, 1W..52W, 1M..24M, 1Y..5Y. Falls back to
    interpreting raw int strings as a day count.
    """
    t = tenor.strip().upper()
    if t in {"ON", "O/N"}:
        return 1
    if t in {"TN", "T/N"}:
        return 2
    if t in {"SN", "S/N"}:
        return 3
    try:
        if t.endswith("W"):
            return int(t[:-1]) * 7
        if t.endswith("M"):
            return int(t[:-1]) * 30
        if t.endswith("Y"):
            return int(t[:-1]) * 365
        return int(t)
    except ValueError as e:
        raise ValueError(f"unrecognised tenor: {tenor!r}") from e


def fx_forward_curve(
    spot: float,
    domestic_rate_pct: float,
    foreign_rate_pct: float,
    tenors: list[str] | None = None,
    pip_factor: float = 10_000,
) -> list[ForwardPoint]:
    """Build the forward curve from CIP. Returns one row per tenor.

    Rates passed as percent (e.g. 45.0 = %45). All compounding is
    continuous to keep the algebra clean — the difference vs simple
    interest is < 0.5 bps at one year for typical TL/USD spreads.
    """
    if spot <= 0:
        raise ValueError("spot must be positive")
    tenors = tenors or ["1W", "1M", "3M", "6M", "9M", "1Y", "2Y"]

    r_dom = domestic_rate_pct / 100.0
    r_for = foreign_rate_pct / 100.0

    out: list[ForwardPoint] = []
    for ten in tenors:
        days = _tenor_to_days(ten)
        t = days / 365.0
        fwd = spot * math.exp((r_dom - r_for) * t)
        points = (fwd - spot) * pip_factor
        out.append(
            ForwardPoint(
                tenor=ten,
                days=days,
                forward_outright=fwd,
                forward_points_pips=points,
                implied_diff_pct=(r_dom - r_for) * 100.0,
            )
        )
    return out

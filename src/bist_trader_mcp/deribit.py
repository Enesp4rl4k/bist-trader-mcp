"""Deribit BTC/ETH option chain — composable with iv_surface.

Deribit's `/public/get_book_summary_by_currency` returns a list of all
active instruments (futures + options + perp) with mark price, mark IV
(server-computed Black-76), volume, and OI. The endpoint is free, no
auth, no rate limit at normal usage.

We adapt the raw Deribit instruments into the `VIOPSettlement` shape
used by `iv_surface.build_iv_surface` so the same surface analytics
work for crypto options (with spot fetched separately).

Instrument naming on Deribit:
    BTC-27JUN26-100000-C
    ETH-30AUG25-3500-P
    BTC-PERPETUAL
    BTC-PERP             (variant)

Mark IV is already in % units (45 = 45%).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from ._cache import cache_get, cache_set
from .http_utils import SourceError, fetch_json

DERIBIT_BASE = "https://www.deribit.com/api/v2"
DEFAULT_TTL = 5 * 60   # option quotes refresh quickly

_MONTH_MAP = {
    "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
    "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12,
}


@dataclass
class DeribitOption:
    instrument: str
    underlying: str       # "BTC" | "ETH"
    expiry: date
    strike: float
    right: str            # "C" | "P"
    mark_price: float | None
    mark_iv_pct: float | None
    last_price: float | None
    volume_24h: float | None
    open_interest: float | None


async def fetch_deribit_option_chain(
    currency: str = "BTC",
    use_cache: bool = True,
) -> list[DeribitOption]:
    """Fetch the full live option book summary for BTC or ETH."""
    cur = currency.upper().strip()
    if cur not in ("BTC", "ETH", "SOL"):
        raise SourceError("deribit", f"unsupported currency: {currency}")
    key = f"deribit.chain.{cur}"
    if use_cache:
        cached = cache_get(key, ttl_seconds=DEFAULT_TTL)
        if isinstance(cached, list):
            return [_opt_from_dict(d) for d in cached]

    params = {"currency": cur, "kind": "option"}
    try:
        data = await fetch_json(
            f"{DERIBIT_BASE}/public/get_book_summary_by_currency",
            source="deribit",
            params=params,
        )
    except SourceError:
        raise

    if not isinstance(data, dict) or "result" not in data:
        raise SourceError("deribit", f"unexpected response: {data}")
    rows = data.get("result") or []

    out: list[DeribitOption] = []
    for r in rows:
        try:
            opt = _parse_instrument(r)
        except (KeyError, ValueError, TypeError):
            continue
        if opt is not None:
            out.append(opt)
    cache_set(key, [_opt_to_dict(o) for o in out], ttl_seconds=DEFAULT_TTL)
    return out


def _parse_instrument(r: dict[str, Any]) -> DeribitOption | None:
    name = str(r.get("instrument_name") or "")
    parts = name.split("-")
    if len(parts) != 4:
        return None
    cur, expiry_token, strike_str, right = parts
    if right not in ("C", "P"):
        return None
    try:
        strike = float(strike_str)
    except ValueError:
        return None
    exp = _parse_expiry(expiry_token)
    if exp is None:
        return None
    return DeribitOption(
        instrument=name,
        underlying=cur,
        expiry=exp,
        strike=strike,
        right=right,
        mark_price=_f(r.get("mark_price")),
        mark_iv_pct=_f(r.get("mark_iv")),
        last_price=_f(r.get("last")),
        volume_24h=_f(r.get("volume")),
        open_interest=_f(r.get("open_interest")),
    )


def _parse_expiry(token: str) -> date | None:
    """Parse '27JUN26' / '3SEP24' etc into a date."""
    if len(token) < 5:
        return None
    # split numeric prefix from alpha month + 2-digit year
    i = 0
    while i < len(token) and token[i].isdigit():
        i += 1
    if i == 0 or i >= len(token):
        return None
    day_s = token[:i]
    rest = token[i:]
    if len(rest) < 5:
        return None
    month_s = rest[:3]
    year_s = rest[3:]
    try:
        day = int(day_s)
        year = 2000 + int(year_s)
        month = _MONTH_MAP.get(month_s.upper())
        if month is None:
            return None
        return date(year, month, day)
    except ValueError:
        return None


def _f(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _opt_to_dict(o: DeribitOption) -> dict[str, Any]:
    return {
        "instrument": o.instrument,
        "underlying": o.underlying,
        "expiry": o.expiry.isoformat(),
        "strike": o.strike,
        "right": o.right,
        "mark_price": o.mark_price,
        "mark_iv_pct": o.mark_iv_pct,
        "last_price": o.last_price,
        "volume_24h": o.volume_24h,
        "open_interest": o.open_interest,
    }


def _opt_from_dict(d: dict[str, Any]) -> DeribitOption:
    return DeribitOption(
        instrument=str(d["instrument"]),
        underlying=str(d["underlying"]),
        expiry=date.fromisoformat(d["expiry"]),
        strike=float(d["strike"]),
        right=str(d["right"]),
        mark_price=d.get("mark_price"),
        mark_iv_pct=d.get("mark_iv_pct"),
        last_price=d.get("last_price"),
        volume_24h=d.get("volume_24h"),
        open_interest=d.get("open_interest"),
    )


# ---------------------------------------------------------------------------
# Direct surface helpers (Deribit already publishes mark_iv, so we can build
# a surface without re-solving — much faster + matches market convention).
# ---------------------------------------------------------------------------

def build_deribit_surface(
    chain: list[DeribitOption],
    spot: float,
    as_of: date | None = None,
    min_iv: float = 1.0,
) -> dict[str, Any]:
    """Build a surface from Deribit mark_iv values directly (no resolve).

    Returns the same shape as iv_surface.build_iv_surface:
        - points
        - by_expiry
        - atm_term_structure
        - skew_25d_front_month (approximate — uses strike-based proxy
          since we don't have BS deltas here without recomputing)
    """
    as_of = as_of or date.today()
    import math
    points = []
    for o in chain:
        if o.mark_iv_pct is None or o.mark_iv_pct < min_iv:
            continue
        if o.strike <= 0:
            continue
        dte = (o.expiry - as_of).days
        if dte <= 0:
            continue
        moneyness = math.log(o.strike / spot)
        points.append({
            "expiry": o.expiry.isoformat(),
            "days_to_expiry": dte,
            "strike": o.strike,
            "right": o.right,
            "iv_pct": o.mark_iv_pct,
            "mark_price": o.mark_price,
            "moneyness": round(moneyness, 4),
            "open_interest": o.open_interest,
        })

    # Group by expiry; ATM IV = call IV at strike closest to spot
    by_expiry: dict[str, dict[str, Any]] = {}
    for p in points:
        b = by_expiry.setdefault(p["expiry"], {
            "expiry": p["expiry"],
            "days_to_expiry": p["days_to_expiry"],
            "calls": [], "puts": [], "atm_iv_pct": None,
        })
        (b["calls"] if p["right"] == "C" else b["puts"]).append(p)

    for b in by_expiry.values():
        b["calls"].sort(key=lambda r: r["strike"])
        b["puts"].sort(key=lambda r: r["strike"])
        if b["calls"]:
            closest = min(b["calls"], key=lambda r: abs(r["strike"] - spot))
            b["atm_iv_pct"] = closest["iv_pct"]

    term = sorted(
        [{"expiry": k, "days_to_expiry": v["days_to_expiry"],
          "atm_iv_pct": v["atm_iv_pct"]}
         for k, v in by_expiry.items() if v["atm_iv_pct"] is not None],
        key=lambda r: r["days_to_expiry"],
    )

    # Approximate 25-delta skew: take strikes ~25% OTM vs spot.
    skew = _approx_25d_skew(by_expiry, spot)

    slope = None
    if len(term) >= 2 and term[0]["atm_iv_pct"] is not None and term[-1]["atm_iv_pct"] is not None:
        slope = term[0]["atm_iv_pct"] - term[-1]["atm_iv_pct"]

    return {
        "source": "Deribit (mark_iv)",
        "as_of": as_of.isoformat(),
        "spot": spot,
        "underlying": chain[0].underlying if chain else None,
        "meta": {"points": len(points)},
        "points": points,
        "by_expiry": by_expiry,
        "atm_term_structure": term,
        "skew_25d_front_month": skew,
        "term_structure_slope_vol_pts": slope,
    }


def _approx_25d_skew(
    by_expiry: dict[str, dict[str, Any]],
    spot: float,
) -> dict[str, Any] | None:
    """Rough 25Δ skew using strike percentage as a delta proxy.
    OTM put @ 0.85*spot, OTM call @ 1.15*spot — closest to ~25Δ."""
    cands = sorted(
        [v for v in by_expiry.values() if len(v["calls"]) >= 3 and len(v["puts"]) >= 3],
        key=lambda v: v["days_to_expiry"],
    )
    if not cands:
        return None
    b = cands[0]
    put_target = 0.85 * spot
    call_target = 1.15 * spot
    p25 = min(b["puts"], key=lambda r: abs(r["strike"] - put_target))
    c25 = min(b["calls"], key=lambda r: abs(r["strike"] - call_target))
    return {
        "expiry": b["expiry"],
        "days_to_expiry": b["days_to_expiry"],
        "call_25d_iv_pct": c25["iv_pct"],
        "call_25d_strike": c25["strike"],
        "put_25d_iv_pct": p25["iv_pct"],
        "put_25d_strike": p25["strike"],
        "skew_vol_pts": p25["iv_pct"] - c25["iv_pct"],
        "note": "approximate 25Δ via 0.85/1.15 spot strikes (not BS-delta solved)",
    }


__all__ = [
    "DeribitOption",
    "fetch_deribit_option_chain",
    "build_deribit_surface",
]

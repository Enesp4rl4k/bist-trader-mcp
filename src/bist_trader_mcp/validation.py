"""Input validation shared by every tool that takes a symbol, timeframe or price.

Symbols end up in URLs (Yahoo, Binance), file names and — most importantly —
as arguments to the TradingView CLI subprocess. Rejecting anything outside a
small alphabet early gives clear errors instead of odd upstream failures.
"""

from __future__ import annotations

import math
import re
from typing import Any

_SYMBOL_RX = re.compile(r"^[A-Z0-9^][A-Z0-9:._!=^/-]{0,31}$")
_TIMEFRAME_RX = re.compile(r"^(\d{1,4}|\d{0,2}[DWM])$")


def validate_symbol(symbol: Any) -> str:
    """Upper-cased, trimmed symbol, or ValueError.

    Accepts THYAO, BIST:THYAO, XU030, F_XU0300625, BINANCE:BTCUSDT, ^XU100, USDTRY=X.
    """
    if not isinstance(symbol, str):
        raise ValueError("symbol must be a string")
    s = symbol.strip().upper()
    if not _SYMBOL_RX.match(s):
        raise ValueError(f"invalid symbol: {symbol!r}")
    return s


def validate_timeframe(tf: Any) -> str:
    """TradingView-style timeframe (15, 60, 240, 1D, D, 1W, 1M), or ValueError."""
    if not isinstance(tf, str):
        tf = str(tf)
    t = tf.strip().upper()
    if not _TIMEFRAME_RX.match(t) or t in ("0", "0D", "0W", "0M"):
        raise ValueError(f"invalid timeframe: {tf!r} (use e.g. 15, 60, 240, 1D, 1W)")
    return t


def validate_price(value: Any, name: str = "price") -> float:
    """Finite, positive float, or ValueError."""
    try:
        x = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be a number") from None
    if not math.isfinite(x) or x <= 0:
        raise ValueError(f"{name} must be a positive finite number, got {value!r}")
    return x


def validate_direction(direction: Any) -> str:
    d = str(direction or "").strip().lower()
    if d not in ("long", "short"):
        raise ValueError(f"direction must be 'long' or 'short', got {direction!r}")
    return d


__all__ = ["validate_direction", "validate_price", "validate_symbol", "validate_timeframe"]

"""Market profiles — BIST, VIOP, crypto tuned PA / Elliott / assistant defaults."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Literal

AssetClass = Literal[
    "crypto",
    "bist_equity",
    "bist_index",
    "viop_future",
    "viop_option",
    "unknown",
]

VIOP_CODE_RX = re.compile(
    r"^(?:BIST:)?(?:F_|O_)[A-Z0-9]{2,}(?:_\d{2}\d{2})?",
    re.IGNORECASE,
)
CRYPTO_EXCHANGE_RX = re.compile(
    r"^(BINANCE|BYBIT|OKX|COINBASE|KUCOIN|BITGET|GATEIO|HUOBI|KRAKEN):",
    re.IGNORECASE,
)
BIST_TV_PREFIX_RX = re.compile(r"^BIST:", re.IGNORECASE)

BIST_INDICES = frozenset(
    {
        "XU030",
        "XU100",
        "XUSIN",
        "XBANK",
        "XU050",
        "XUTUM",
        "XELKT",
        "XGIDA",
    }
)

# TradingView timeframe strings per asset class
_PROFILES: dict[AssetClass, dict[str, Any]] = {
    "crypto": {
        "default_htf_timeframe": "240",
        "default_ltf_timeframe": "60",
        "ohlcv_bars": 300,
        "swing_lookback": 4,
        "sr_tolerance_pct": 0.005,
        "stop_buffer_pct": 0.0015,
        "min_ew_score": 30.0,
        "min_pa_confluence": 48.0,
        "min_risk_reward": 2.0,
        "risk_per_trade_pct": 0.75,
        "max_single_asset_notional_pct": 12.0,
        "min_trade_quality": "a",
        "max_stop_atr_multiple": 2.5,
        "max_entry_chase_atr": 2.0,
        "range_window_bars": 56,
        "range_max_width_atr": 4.5,
        "session": "24/7",
        "data_hint": "TradingView BINANCE:/BYBIT: symbols; backup: get_crypto_klines",
        "assistant_notes": (
            "Crypto: higher volatility — wider S/R tolerance, faster swings (lookback 4). "
            "Cap notional ~12% equity on spot/perp chart symbols."
        ),
    },
    "bist_equity": {
        "default_htf_timeframe": "D",
        "default_ltf_timeframe": "60",
        "ohlcv_bars": 200,
        "swing_lookback": 5,
        "sr_tolerance_pct": 0.003,
        "stop_buffer_pct": 0.001,
        "min_ew_score": 38.0,
        "min_pa_confluence": 55.0,
        "min_risk_reward": 2.0,
        "risk_per_trade_pct": 1.0,
        "max_single_asset_notional_pct": 20.0,
        "min_trade_quality": "a",
        "max_stop_atr_multiple": 3.0,
        "max_entry_chase_atr": 1.5,
        "range_window_bars": 40,
        "range_max_width_atr": 3.5,
        "session": "BIST cash ~10:00-18:00 Istanbul (check holidays)",
        "data_hint": "TradingView BIST:THYAO; EOD fallback get_bist_eod_ohlcv",
        "assistant_notes": (
            "BIST equity: daily HTF + 1H LTF. Respect session gaps — "
            "gaps can distort Elliott; prefer structure + KAP context."
        ),
    },
    "bist_index": {
        "default_htf_timeframe": "D",
        "default_ltf_timeframe": "60",
        "ohlcv_bars": 220,
        "swing_lookback": 5,
        "sr_tolerance_pct": 0.0025,
        "stop_buffer_pct": 0.001,
        "min_ew_score": 40.0,
        "min_pa_confluence": 58.0,
        "min_risk_reward": 2.0,
        "risk_per_trade_pct": 1.0,
        "max_single_asset_notional_pct": 25.0,
        "min_trade_quality": "a_plus",
        "max_stop_atr_multiple": 2.8,
        "max_entry_chase_atr": 1.2,
        "session": "BIST index session",
        "data_hint": "TradingView BIST:XU030 / BIST:XU100",
        "assistant_notes": (
            "BIST index: cleaner trends than single names; require A+ MTF for new risk."
        ),
    },
    "viop_future": {
        "default_htf_timeframe": "240",
        "default_ltf_timeframe": "15",
        "ohlcv_bars": 280,
        "swing_lookback": 4,
        "sr_tolerance_pct": 0.004,
        "stop_buffer_pct": 0.0012,
        "min_ew_score": 35.0,
        "min_pa_confluence": 52.0,
        "min_risk_reward": 1.8,
        "risk_per_trade_pct": 0.5,
        "max_single_asset_notional_pct": 15.0,
        "min_trade_quality": "a",
        "max_stop_atr_multiple": 2.2,
        "max_entry_chase_atr": 1.0,
        "session": "VIOP ~09:20-18:10 Istanbul + US index night sessions for XU030",
        "data_hint": "TradingView BIST:F_XU030... ; context: get_viop_term_structure",
        "assistant_notes": (
            "VIOP futures: use front contract chart; check margin via get_viop_dashboard. "
            "Tighter entry chase — leveraged product."
        ),
        "viop_tools": ["get_viop_term_structure", "get_viop_settlement", "get_viop_dashboard"],
    },
    "viop_option": {
        "default_htf_timeframe": "240",
        "default_ltf_timeframe": "15",
        "ohlcv_bars": 200,
        "swing_lookback": 3,
        "sr_tolerance_pct": 0.006,
        "stop_buffer_pct": 0.002,
        "min_ew_score": 32.0,
        "min_pa_confluence": 60.0,
        "min_risk_reward": 1.5,
        "risk_per_trade_pct": 0.35,
        "max_single_asset_notional_pct": 8.0,
        "min_trade_quality": "a_plus",
        "max_stop_atr_multiple": 2.0,
        "max_entry_chase_atr": 0.8,
        "session": "VIOP options — theta sensitive",
        "data_hint": "Chart underlying future; greeks: get_viop_option_chain",
        "assistant_notes": (
            "VIOP options: PA assistant plans underlying direction; "
            "size for option premium risk separately."
        ),
        "viop_tools": ["get_viop_option_chain", "get_viop_iv_surface"],
    },
    "unknown": {
        "default_htf_timeframe": "240",
        "default_ltf_timeframe": "60",
        "ohlcv_bars": 200,
        "swing_lookback": 5,
        "sr_tolerance_pct": 0.003,
        "stop_buffer_pct": 0.001,
        "min_ew_score": 35.0,
        "min_pa_confluence": 50.0,
        "min_risk_reward": 2.0,
        "risk_per_trade_pct": 1.0,
        "max_single_asset_notional_pct": 20.0,
        "min_trade_quality": "a",
        "max_stop_atr_multiple": 3.0,
        "max_entry_chase_atr": 1.5,
        "session": "unknown",
        "data_hint": "Set market= explicitly or use BINANCE:/BIST: prefix",
        "assistant_notes": "Generic defaults — pass market='crypto'|'bist'|'viop' if needed.",
    },
}


@dataclass(frozen=True)
class MarketProfile:
    asset_class: AssetClass
    symbol_raw: str
    symbol_tv: str
    underlying: str | None
    defaults: dict[str, Any] = field(default_factory=dict)

    def pa_kwargs(self) -> dict[str, Any]:
        return {
            "swing_lookback": int(self.defaults["swing_lookback"]),
            "sr_tolerance_pct": float(self.defaults["sr_tolerance_pct"]),
            "stop_buffer_pct": float(self.defaults["stop_buffer_pct"]),
        }

    def playbook_rules_overlay(self) -> dict[str, Any]:
        return {
            "min_trade_quality": self.defaults["min_trade_quality"],
            "min_risk_reward": float(self.defaults["min_risk_reward"]),
            "max_stop_atr_multiple": float(self.defaults["max_stop_atr_multiple"]),
            "max_entry_chase_atr": float(self.defaults["max_entry_chase_atr"]),
        }

    def sizing_overlay(self) -> dict[str, Any]:
        return {
            "risk_per_trade_pct": float(self.defaults["risk_per_trade_pct"]),
            "max_single_asset_notional_pct": float(
                self.defaults["max_single_asset_notional_pct"]
            ),
        }


def _strip_prefix(symbol: str) -> str:
    s = symbol.strip().upper()
    if ":" in s:
        return s.split(":", 1)[1]
    return s


def detect_asset_class(symbol: str, market: str | None = None) -> AssetClass:
    """Infer asset class from symbol string or explicit market hint."""
    if market:
        m = market.strip().lower()
        if m in ("crypto", "kripto", "binance"):
            return "crypto"
        if m in ("viop", "future", "futures", "viop_future"):
            return "viop_future"
        if m in ("viop_option", "option", "opsiyon"):
            return "viop_option"
        if m in ("bist", "bist_equity", "equity", "hisse"):
            return "bist_equity"
        if m in ("index", "bist_index", "endeks"):
            return "bist_index"

    raw = symbol.strip().upper()
    if CRYPTO_EXCHANGE_RX.match(raw):
        return "crypto"
    if VIOP_CODE_RX.match(raw):
        core = _strip_prefix(raw)
        if core.startswith("O_"):
            return "viop_option"
        return "viop_future"
    core = _strip_prefix(raw)
    if core.startswith("F_"):
        return "viop_future"
    if core.startswith("O_"):
        return "viop_option"
    if core in BIST_INDICES or core.startswith("XU"):
        return "bist_index"
    if BIST_TV_PREFIX_RX.match(raw) or (len(core) <= 6 and core.isalpha()):
        return "bist_equity"
    if raw.endswith("USDT") or raw.endswith("USD"):
        return "crypto"
    return "unknown"


def normalize_tv_symbol(symbol: str, asset_class: AssetClass | None = None) -> str:
    """TradingView symbol for chart_set_symbol."""
    raw = symbol.strip()
    up = raw.upper()
    ac = asset_class or detect_asset_class(raw)

    if CRYPTO_EXCHANGE_RX.match(up):
        return up
    if up.endswith("USDT") and ":" not in up:
        return f"BINANCE:{up}"
    if up.endswith("USD") and ":" not in up and ac == "crypto":
        return f"BINANCE:{up}"

    core = _strip_prefix(up)
    if ac in ("viop_future", "viop_option"):
        code = core if core.startswith(("F_", "O_")) else up
        return f"BIST:{code}" if not BIST_TV_PREFIX_RX.match(up) else up
    if ac in ("bist_equity", "bist_index"):
        return f"BIST:{core}" if not BIST_TV_PREFIX_RX.match(up) else up
    if BIST_TV_PREFIX_RX.match(up):
        return up
    return raw


def _parse_viop_underlying(symbol: str) -> str | None:
    core = _strip_prefix(symbol.upper())
    if not core.startswith(("F_", "O_")):
        return None
    try:
        from .viop import parse_contract_code

        return parse_contract_code(core).underlying
    except Exception:
        return None


def get_market_profile(
    symbol: str,
    market: str | None = None,
) -> dict[str, Any]:
    """Full profile dict for MCP / assistant (JSON-serializable)."""
    ac = detect_asset_class(symbol, market=market)
    defaults = dict(_PROFILES[ac])
    tv = normalize_tv_symbol(symbol, ac)
    underlying = _parse_viop_underlying(symbol) if ac.startswith("viop") else None
    if ac == "bist_index":
        underlying = _strip_prefix(symbol)

    prof = MarketProfile(
        asset_class=ac,
        symbol_raw=symbol.strip(),
        symbol_tv=tv,
        underlying=underlying,
        defaults=defaults,
    )
    return {
        "source": "bist-trader-mcp — market_profiles.get_market_profile",
        "asset_class": ac,
        "symbol_raw": prof.symbol_raw,
        "symbol_tv": prof.symbol_tv,
        "underlying": underlying,
        "defaults": defaults,
        "pa_kwargs": prof.pa_kwargs(),
        "playbook_rules_overlay": prof.playbook_rules_overlay(),
        "sizing_overlay": prof.sizing_overlay(),
        "assistant_notes": defaults.get("assistant_notes"),
        "viop_tools": defaults.get("viop_tools"),
    }


def resolve_assistant_config(
    symbol: str,
    *,
    market: str | None = None,
    ltf_timeframe: str | None = None,
    htf_timeframe: str | None = None,
    rules: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Merged config for run_scenario_assistant / run_trade_assistant."""
    profile = get_market_profile(symbol, market=market)
    d = profile["defaults"]
    merged_rules = {**profile["playbook_rules_overlay"], **(rules or {})}

    return {
        "profile": profile,
        "symbol_tv": profile["symbol_tv"],
        "asset_class": profile["asset_class"],
        "ltf_timeframe": ltf_timeframe or d["default_ltf_timeframe"],
        "htf_timeframe": htf_timeframe or d["default_htf_timeframe"],
        "ohlcv_bars": int(d["ohlcv_bars"]),
        "min_ew_score": float(d["min_ew_score"]),
        "min_pa_confluence": float(d.get("min_pa_confluence", 52)),
        "max_entry_chase_atr": float(d.get("max_entry_chase_atr", 1.5)),
        "range_window_bars": int(d.get("range_window_bars", 48)),
        "range_max_width_atr": float(d.get("range_max_width_atr", 4.0)),
        "risk_per_trade_pct": float(d["risk_per_trade_pct"]),
        "min_risk_reward": float(d["min_risk_reward"]),
        "max_notional_pct": float(d["max_single_asset_notional_pct"]),
        "rules": merged_rules,
        "pa_kwargs": profile["pa_kwargs"],
    }


__all__ = [
    "AssetClass",
    "MarketProfile",
    "detect_asset_class",
    "normalize_tv_symbol",
    "get_market_profile",
    "resolve_assistant_config",
]

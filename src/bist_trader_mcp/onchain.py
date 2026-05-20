"""On-chain data — Etherscan gas oracle + ETH supply (no key required).

Etherscan exposes a `gasoracle` endpoint that returns current safe/propose/
fast gas prices in Gwei plus the suggested base fee — a high gas estimate
is a real-time congestion signal that often coincides with NFT mints,
airdrops, or risk-on flow.

A free API key dramatically raises the rate limit (5 calls/sec) but the
no-key endpoint works at 1 call/5sec which is plenty for occasional MCP
calls — we cache 30s anyway.

For BTC we use blockchain.info's public `/q/` endpoints for hashrate,
difficulty, mempool size — same anonymous-friendly pattern.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from ._cache import cache_get, cache_set
from .http_utils import SourceError, fetch_json, fetch_text

ETHERSCAN_API = "https://api.etherscan.io/api"
BLOCKCHAIN_INFO = "https://blockchain.info/q"
DEFAULT_TTL = 30


@dataclass
class GasOracleSnapshot:
    safe_gwei: float | None
    propose_gwei: float | None
    fast_gwei: float | None
    suggested_base_fee_gwei: float | None
    gas_used_ratio: float | None
    last_block: int | None


async def fetch_eth_gas_oracle(use_cache: bool = True) -> GasOracleSnapshot:
    """Etherscan gas oracle — current safe / propose / fast gas in Gwei.

    The `apikey` is optional but raises rate-limit. Honors TCMB_EVDS pattern
    of ETHERSCAN_API_KEY env var.
    """
    key = "onchain.etherscan.gas"
    if use_cache:
        cached = cache_get(key, ttl_seconds=DEFAULT_TTL)
        if isinstance(cached, dict) and "safe_gwei" in cached:
            return GasOracleSnapshot(**cached)

    params: dict[str, Any] = {"module": "gastracker", "action": "gasoracle"}
    api_key = os.environ.get("ETHERSCAN_API_KEY")
    if api_key:
        params["apikey"] = api_key
    try:
        data = await fetch_json(ETHERSCAN_API, source="etherscan", params=params)
    except SourceError:
        raise
    if not isinstance(data, dict):
        raise SourceError("etherscan", f"unexpected response: {type(data)}")
    if data.get("status") not in ("1", 1, True):
        raise SourceError("etherscan",
                           f"api error: {data.get('message') or data.get('result')}")
    r = data.get("result") or {}
    snap = GasOracleSnapshot(
        safe_gwei=_f(r.get("SafeGasPrice")),
        propose_gwei=_f(r.get("ProposeGasPrice")),
        fast_gwei=_f(r.get("FastGasPrice")),
        suggested_base_fee_gwei=_f(r.get("suggestBaseFee")),
        gas_used_ratio=_avg_ratio(r.get("gasUsedRatio")),
        last_block=_i(r.get("LastBlock")),
    )
    cache_set(key, snap.__dict__, ttl_seconds=DEFAULT_TTL)
    return snap


@dataclass
class BTCNetworkStats:
    hashrate_th_s: float | None      # network hashrate, TH/s
    difficulty: float | None
    total_btc_in_circulation: float | None
    unconfirmed_tx_count: int | None
    mempool_size_bytes: int | None
    market_price_usd: float | None


async def fetch_btc_network_stats(use_cache: bool = True) -> BTCNetworkStats:
    """Bitcoin network stats via blockchain.info public endpoints."""
    key = "onchain.btc.netstats"
    if use_cache:
        cached = cache_get(key, ttl_seconds=DEFAULT_TTL * 2)
        if isinstance(cached, dict):
            return BTCNetworkStats(**cached)

    async def _q(field: str) -> str | None:
        try:
            return await fetch_text(f"{BLOCKCHAIN_INFO}/{field}",
                                     source=f"blockchain.info:{field}")
        except SourceError:
            return None

    raw = {
        "hashrate":    await _q("hashrate"),
        "difficulty":  await _q("getdifficulty"),
        "totalbc":     await _q("totalbc"),
        "unconfcount": await _q("unconfirmedcount"),
        "mempool":     await _q("mempoolsize"),
        "price":       await _q("24hrprice"),
    }

    snap = BTCNetworkStats(
        hashrate_th_s=_f(raw["hashrate"]),
        difficulty=_f(raw["difficulty"]),
        # totalbc returns satoshis × 10^something; doc says satoshis
        total_btc_in_circulation=(
            float(raw["totalbc"]) / 1e8 if raw["totalbc"] and raw["totalbc"].strip().isdigit()
            else _f(raw["totalbc"])
        ),
        unconfirmed_tx_count=_i(raw["unconfcount"]),
        mempool_size_bytes=_i(raw["mempool"]),
        market_price_usd=_f(raw["price"]),
    )
    cache_set(key, snap.__dict__, ttl_seconds=DEFAULT_TTL * 2)
    return snap


def _f(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(str(v).strip())
    except (TypeError, ValueError):
        return None


def _i(v: Any) -> int | None:
    f = _f(v)
    return int(f) if f is not None else None


def _avg_ratio(raw: Any) -> float | None:
    """Etherscan returns gasUsedRatio as comma-separated decimals."""
    if not raw or not isinstance(raw, str):
        return None
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    nums = [float(p) for p in parts if _safe_float(p) is not None]
    if not nums:
        return None
    return sum(nums) / len(nums)


def _safe_float(s: str) -> float | None:
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


__all__ = [
    "GasOracleSnapshot",
    "fetch_eth_gas_oracle",
    "BTCNetworkStats",
    "fetch_btc_network_stats",
]

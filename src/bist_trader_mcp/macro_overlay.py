"""Short macro overlay when TCMB_EVDS_API_KEY is set."""

from __future__ import annotations

import os
from typing import Any


async def fetch_macro_overlay_brief() -> dict[str, Any] | None:
    """TLREF vs policy spread — funding stress hint."""
    if not os.environ.get("TCMB_EVDS_API_KEY"):
        return None
    try:
        from .tools import get_repo_curve

        repo = await get_repo_curve(window_days=5)
        if repo.get("error"):
            return None
        latest = (repo.get("latest") or {}) if isinstance(repo, dict) else {}
        spreads = repo.get("spreads_bps") or latest.get("spreads_bps") or {}
        tlref_vs = spreads.get("tlref_vs_policy") or spreads.get("tlref_vs_policy_bps")
        if tlref_vs is None:
            return None
        return {
            "tlref_bps_vs_policy": float(tlref_vs),
            "policy_rate": latest.get("policy_rate_1w"),
            "summary_tr": f"Makro: TLREF-policy spread {tlref_vs} bps",
        }
    except Exception:
        return None


__all__ = ["fetch_macro_overlay_brief"]

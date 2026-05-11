"""Curated EVDS series codes — all live-verified against evds3 on 2026-05-11.

Sources of truth:
- https://evds3.tcmb.gov.tr/tumSeriler — browse the live catalog
- https://evds3.tcmb.gov.tr/igmevdsms-dis/datagroups/mode=0&type=json
  → list of all data groups (593 as of 2026-05-11)
- /serieList/code=<group>&type=json → series within a group

When TCMB renames series (they do — APIFON1/2/6 disappeared in the 2024
overhaul), the corresponding entries below stop returning data. Run
`scripts/smoke_test.py` to detect this; refresh by browsing the live
catalog and picking new codes.
"""

from __future__ import annotations

# -----------------------------------------------------------------------------
# Policy / overnight / repo rates  — ALIVE 2026-05-11
# -----------------------------------------------------------------------------
# TCMB 1-week repo policy rate (the headline number the press quotes)
TCMB_POLICY_RATE_1W_REPO = "TP.APIFON4"

# BIST TLREF — daily TL overnight reference rate (the post-2024 effective
# overnight benchmark; the legacy APIFON1/2 corridor concept retired).
BIST_TLREF_RATE = "TP.BISTTLREF.ORAN"
BIST_TLREF_INDEX_CLOSE = "TP.BISTTLREF.KAPANIS"

# Borsa İstanbul overnight repo (weighted avg) — useful for funding-stress reads
BIST_OVERNIGHT_REPO_AVG_RATE = "TP.AOFOBAP"

POLICY_RATE_SERIES: dict[str, str] = {
    "policy_rate_1w_repo": TCMB_POLICY_RATE_1W_REPO,
    "tlref_overnight": BIST_TLREF_RATE,
    "bist_overnight_repo": BIST_OVERNIGHT_REPO_AVG_RATE,
}

# RETIRED — kept for documentation only. These returned HTTP 400 on the
# new evds3 endpoint; do NOT include them in catalog calls.
RETIRED_SERIES_NOTE = {
    "TP.APIFON1": "overnight borrowing (lower corridor) — retired",
    "TP.APIFON2": "overnight lending (upper corridor) — retired",
    "TP.APIFON6": "late liquidity window lending — retired",
}


# -----------------------------------------------------------------------------
# DİBS yields — v0.3 WORK PENDING
# -----------------------------------------------------------------------------
# The legacy TP.ATBPK family (benchmark yields by nominal tenor) was retired.
# evds3 exposes 4046 per-ISIN bond series under group `bie_pydibs` instead.
# Building a tenor-bucketed yield curve requires:
#   1) pulling current "benchmark" ISIN list (Hazine designates these)
#   2) mapping each ISIN to its time-to-maturity bucket (1M, 3M, 6M, 1Y, ...)
#   3) taking median yield per bucket
# This is tracked for v0.3.
DIBS_YIELD_SERIES: dict[str, str] = {}  # intentionally empty until v0.3


# -----------------------------------------------------------------------------
# Inflation  — ALIVE 2026-05-11
# -----------------------------------------------------------------------------
# 2025=100 rebased index family — replaces TP.FG.J0 and TP.FG.J0.C.
# Note: these are INDEX LEVELS, not YoY percent changes. The macro snapshot
# helper computes YoY by comparing the latest reading to the one 12 months
# back.
CPI_INDEX_HEADLINE = "TP.FE25.OKTG01"  # Tüketici Fiyat Endeksi (Genel)
CPI_INDEX_CORE_C = "TP.FE25.OKTG04"    # Çekirdek C (enerji, gıda, vergi, altın hariç)


# -----------------------------------------------------------------------------
# FX  — ALIVE 2026-05-11
# -----------------------------------------------------------------------------
USDTRY_SELLING = "TP.DK.USD.S.YTL"
USDTRY_BUYING = "TP.DK.USD.A.YTL"
EURTRY_SELLING = "TP.DK.EUR.S.YTL"


def list_known_series() -> dict[str, dict[str, str]]:
    """Return a structured catalog for documentation / introspection."""
    return {
        "policy_rates": POLICY_RATE_SERIES,
        "dibs_benchmarks": DIBS_YIELD_SERIES,
        "inflation": {
            "cpi_index_headline": CPI_INDEX_HEADLINE,
            "cpi_index_core_c": CPI_INDEX_CORE_C,
        },
        "fx": {
            "usdtry_selling": USDTRY_SELLING,
            "usdtry_buying": USDTRY_BUYING,
            "eurtry_selling": EURTRY_SELLING,
        },
        "_retired": RETIRED_SERIES_NOTE,
    }


# -----------------------------------------------------------------------------
# Back-compat aliases used by tools.py — keep these names stable.
# -----------------------------------------------------------------------------
# tools.py imports CPI_HEADLINE; map to the new index series so the macro
# snapshot helper keeps working without code changes in tools.py.
CPI_HEADLINE = CPI_INDEX_HEADLINE

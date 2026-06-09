"""Multi-timeframe Elliott — HTF vs LTF count alignment."""

from __future__ import annotations

from typing import Any, Literal

Direction = Literal["long", "short", "neutral"]


def _dir_from_ew(ew_pack: dict[str, Any] | None) -> Direction:
    if not ew_pack:
        return "neutral"
    p = ew_pack.get("primary") or {}
    d = p.get("direction")
    return d if d in ("long", "short") else "neutral"


def analyze_mtf_elliott(
    elliott_htf: dict[str, Any] | None,
    elliott_ltf: dict[str, Any] | None,
) -> dict[str, Any]:
    """Compare HTF and LTF Elliott primary hypotheses."""
    htf_p = (elliott_htf or {}).get("primary")
    ltf_p = (elliott_ltf or {}).get("primary")
    htf_dir = _dir_from_ew(elliott_htf)
    ltf_dir = _dir_from_ew(elliott_ltf)
    htf_score = float((htf_p or {}).get("score") or 0)
    ltf_score = float((ltf_p or {}).get("score") or 0)

    aligned = htf_dir == ltf_dir and htf_dir in ("long", "short")
    conflict = (
        htf_dir in ("long", "short")
        and ltf_dir in ("long", "short")
        and htf_dir != ltf_dir
    )

    quality = "weak"
    if aligned and htf_score >= 45 and ltf_score >= 38:
        quality = "strong"
    elif aligned:
        quality = "moderate"
    elif conflict:
        quality = "conflict"
    elif htf_score >= 40:
        quality = "htf_only"

    score = 0.0
    if aligned:
        score = min(100.0, (htf_score + ltf_score) / 2 + 12)
    elif conflict:
        score = max(0.0, (htf_score - ltf_score) / 2 - 20)
    else:
        score = htf_score * 0.6 + ltf_score * 0.25

    notes_tr = (
        f"HTF EW: {htf_p.get('kind') if htf_p else 'yok'} ({htf_score}) | "
        f"LTF EW: {ltf_p.get('kind') if ltf_p else 'yok'} ({ltf_score}) | "
        f"{'uyumlu' if aligned else ('çelişki' if conflict else 'kısmi')}."
    )

    return {
        "htf_direction": htf_dir,
        "ltf_direction": ltf_dir,
        "aligned": aligned,
        "conflict": conflict,
        "alignment_quality": quality,
        "alignment_score": round(score, 1),
        "htf_primary_kind": (htf_p or {}).get("kind"),
        "ltf_primary_kind": (ltf_p or {}).get("kind"),
        "htf_current_wave": (htf_p or {}).get("current_wave"),
        "ltf_current_wave": (ltf_p or {}).get("current_wave"),
        "notes_tr": notes_tr,
        "trade_with_ew": aligned and score >= 50 and not conflict,
    }


__all__ = ["analyze_mtf_elliott"]

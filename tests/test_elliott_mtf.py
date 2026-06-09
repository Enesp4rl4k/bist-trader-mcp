"""Elliott HTF/LTF alignment."""

from bist_trader_mcp.elliott_mtf import analyze_mtf_elliott


def _ew(direction: str, score: float, kind: str = "impulse_bull") -> dict:
    return {
        "primary": {
            "direction": direction,
            "score": score,
            "kind": kind,
            "current_wave": 4,
        }
    }


def test_mtf_elliott_aligned():
    out = analyze_mtf_elliott(_ew("long", 55), _ew("long", 42))
    assert out["aligned"] is True
    assert out["conflict"] is False
    assert out["alignment_quality"] in ("strong", "moderate")
    assert out["trade_with_ew"] is True


def test_mtf_elliott_conflict():
    out = analyze_mtf_elliott(_ew("long", 50), _ew("short", 48, "impulse_bear"))
    assert out["conflict"] is True
    assert out["alignment_quality"] == "conflict"
    assert out["trade_with_ew"] is False


def test_mtf_elliott_htf_only():
    out = analyze_mtf_elliott(_ew("long", 45), None)
    assert out["ltf_direction"] == "neutral"
    assert out["alignment_quality"] == "htf_only"

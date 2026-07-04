"""Signal evaluation harness — IC, quantile spread, cross-sectional IR."""

from bist_trader_mcp.factor_eval import (
    evaluate_cross_sectional,
    evaluate_signal,
    quantile_spread,
    rank_ic,
)


def test_rank_ic_perfect_positive():
    scores = [1, 2, 3, 4, 5]
    rets = [0.1, 0.2, 0.3, 0.4, 0.5]
    assert rank_ic(scores, rets) == 1.0


def test_rank_ic_perfect_negative():
    scores = [1, 2, 3, 4, 5]
    rets = [0.5, 0.4, 0.3, 0.2, 0.1]
    assert rank_ic(scores, rets) == -1.0


def test_rank_ic_needs_three_points():
    assert rank_ic([1, 2], [0.1, 0.2]) is None


def test_quantile_spread_monotonic():
    # Score and return perfectly aligned → monotonic, positive spread.
    scores = list(range(20))
    rets = [s * 0.01 for s in scores]
    q = quantile_spread(scores, rets, n_quantiles=5)
    assert q["available"] is True
    assert q["monotonic_increasing"] is True
    assert q["top_minus_bottom"] > 0
    assert len(q["bucket_mean_returns"]) == 5


def test_evaluate_signal_pooled():
    obs = [{"score": s, "forward_return": s * 0.01} for s in range(-10, 11)]
    out = evaluate_signal(obs)
    assert out["rank_ic"] == 1.0
    assert out["hit_rate"] == 1.0           # sign of score matches sign of return
    assert out["quantile"]["monotonic_increasing"] is True
    assert "monotonic" in out["verdict"]


def test_evaluate_signal_noise_low_ic():
    obs = [
        {"score": 1, "forward_return": -0.5},
        {"score": 2, "forward_return": 0.4},
        {"score": 3, "forward_return": -0.3},
        {"score": 4, "forward_return": 0.2},
        {"score": 5, "forward_return": -0.1},
    ]
    out = evaluate_signal(obs)
    assert abs(out["rank_ic"]) < 0.6


def test_evaluate_cross_sectional_ir():
    # Three dates, each with a positive cross-sectional IC.
    day = {"records": [{"score": i, "forward_return": i * 0.01} for i in range(5)]}
    out = evaluate_cross_sectional([day, day, day])
    assert out["dates_evaluated"] == 3
    assert out["ic_mean"] == 1.0
    assert out["positive_ic_share"] == 1.0
    assert out["verdict"] == "strong"


def test_evaluate_cross_sectional_empty():
    out = evaluate_cross_sectional([{"records": [{"score": 1, "forward_return": 0.1}]}])
    # single name per date → IC undefined → no datable IC
    assert out["available"] is False

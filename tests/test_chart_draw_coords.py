from bist_trader_mcp.chart_draw_coords import (
    map_points_to_chart_times,
    points_drawable_on_chart,
)


def test_map_htf_indices_to_ltf_times():
    htf = [1000, 2000, 3000, 4000]
    ltf = [1100, 1500, 2100, 2500, 3100, 3900]
    points = [{"index": 0, "price": 10.0, "label": "0"}, {"index": 2, "price": 12.0, "label": "2"}]
    mapped = map_points_to_chart_times(points, htf, ltf)
    assert len(mapped) == 2
    assert mapped[0]["time"] == 1100
    assert mapped[1]["time"] == 3100


def test_points_drawable_requires_in_range():
    times = list(range(1000, 5000, 1000))
    ok = [{"time": 2000, "price": 1}, {"time": 3000, "price": 2}]
    bad = [{"time": 50, "price": 1}, {"time": 60, "price": 2}]
    assert points_drawable_on_chart(ok, times)
    assert not points_drawable_on_chart(bad, times)


def test_out_of_range_points_are_dropped():
    """Points whose HTF timestamp is far outside the LTF range must be dropped,
    not snapped to the first LTF bar (which caused diagonal spikes)."""
    # HTF covers 0..5000 but LTF only covers 3000..5000
    htf = [0, 1000, 2000, 3000, 4000, 5000]
    ltf = [3000, 3500, 4000, 4500, 5000]  # bar gap = 500, tolerance = 1000
    points = [
        {"index": 0, "price": 10.0, "label": "(0)"},  # t=0, way before LTF range
        {"index": 1, "price": 15.0, "label": "(1)"},  # t=1000, way before LTF range
        {"index": 3, "price": 20.0, "label": "(3)"},  # t=3000, in range
        {"index": 5, "price": 25.0, "label": "(5)"},  # t=5000, in range
    ]
    mapped = map_points_to_chart_times(points, htf, ltf)
    # Only the 2 points within the LTF range should remain
    assert len(mapped) == 2
    assert mapped[0]["label"] == "(3)"
    assert mapped[1]["label"] == "(5)"


def test_edge_points_within_tolerance_kept():
    """Points just outside LTF range but within tolerance should be kept."""
    htf = [900, 1000, 2000, 3000]
    ltf = [1000, 1500, 2000, 2500, 3000]  # bar gap = 500, tolerance = 1000
    points = [
        {"index": 0, "price": 10.0, "label": "(0)"},  # t=900, within tolerance of 1000
        {"index": 3, "price": 20.0, "label": "(3)"},  # t=3000, in range
    ]
    mapped = map_points_to_chart_times(points, htf, ltf)
    assert len(mapped) == 2


def test_map_with_preexisting_time_field():
    """Points that already have a 'time' field (from elliott_wave stamping)
    should also be filtered by range."""
    ltf = [5000, 5500, 6000, 6500, 7000]  # bar gap = 500, tolerance = 1000
    points = [
        {"time": 1000, "price": 10.0, "label": "(0)"},  # way before LTF
        {"time": 5000, "price": 15.0, "label": "(1)"},  # in range
        {"time": 7000, "price": 20.0, "label": "(2)"},  # in range
        {"time": 99000, "price": 25.0, "label": "(3)"},  # way after LTF
    ]
    mapped = map_points_to_chart_times(points, None, ltf)
    assert len(mapped) == 2
    assert mapped[0]["label"] == "(1)"
    assert mapped[1]["label"] == "(2)"


def test_no_duplicate_time_collapse():
    """If all points collapse to the same bar, the result should be sparse
    (most dropped), not a cluster of overlapping points."""
    htf = [100, 200, 300, 400, 500]
    ltf = [10000, 10500, 11000]  # all htf points are before range
    points = [
        {"index": i, "price": float(i * 10), "label": f"({i})"}
        for i in range(5)
    ]
    mapped = map_points_to_chart_times(points, htf, ltf)
    # All HTF points are way before LTF range → all should be dropped
    assert len(mapped) == 0

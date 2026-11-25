import pytest

from dfo_optimizer.combat_benchmark import compare_fronts


def test_bounded_quality_compares_points_and_area_across_different_tradeoffs():
    exact = {(1., 4.), (3., 3.), (4., 1.)}
    bounded = {(1., 4.), (2., 2.)}
    q = compare_fronts(exact, bounded)
    assert q["exact_points_recovered"] == 1
    assert q["frontier_recall"] == pytest.approx(1 / 3)
    assert q["dominated_area_fraction"] == pytest.approx(6 / 11)
    assert q["peak_dps_fraction"] == .5
    assert compare_fronts(exact, exact)["dominated_area_fraction"] == 1

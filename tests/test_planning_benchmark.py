import pytest

from dfo_optimizer.planning_benchmark import _compare


def test_frontier_recovery_compares_complete_metric_vectors():
    assert _compare([[1, 2], [4, 0]], [[1, 2], [2, 1]]) == {
        "exact_points": 2, "bounded_points": 2, "exact_points_recovered": 1,
        "frontier_recall": .5,
    }
    assert _compare([], [])["frontier_recall"] is None


@pytest.mark.parametrize("suite", ["progression", "lifecycle"])
def test_installed_planning_benchmark_proves_native_work(suite):
    from dfo_optimizer.planning_benchmark import run_planning_benchmark
    report = run_planning_benchmark(suite, samples=1)
    exact = report["workloads"]["reduced_exact"]
    assert exact["status"] == "optimal_proven" and exact["counters"]["nodes"] > 0
    assert exact["first_replayed_seconds"] >= 0 and exact["frontier"]
    assert report["workloads"]["reduced_bounded"]["quality"]["exact_points"] > 0
    assert report["workloads"]["representative"]["cold_cli_seconds"] > 0
    assert report["extensions"] and report["peak_rss_bytes"] > 0

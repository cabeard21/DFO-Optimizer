import pytest

from dfo_optimizer.discovery_benchmark import compare_points, qualification


def test_measurements_ties_misses_and_missing_incumbents():
    assert compare_points([(2, 3), (4, 1)], [(4, 1), (2 + 1e-13, 3)])["recall"] == 1
    miss = compare_points([(10,)], [(9,)])
    assert miss["regret"] == pytest.approx(0.1)
    assert miss["scalar_success"] is False
    assert compare_points([(0,)], [(-1,)])["regret"] is None
    assert compare_points([(5,)], [])["regret"] is None


def test_gate_fails_on_missing_result():
    result = qualification([{"scalar_success": False, "regret": None, "recall": 0.0, "reference": True}])
    assert not result["passed"]


def test_qualification_inputs_are_frozen_independently_of_guided_presets():
    from dfo_optimizer.discovery_benchmark import frozen_panel
    from dfo_optimizer.progression import digest

    heldout = frozen_panel("qualify")
    development = frozen_panel("development")
    assert len(heldout) == 11
    assert sum(case["designated_reference"] for case in heldout) == 3
    assert (
        digest([r["request"] for r in heldout])
        == "c00835cc42d2e7ca987082fcaea4799bdac5fa311a85c92080ae45f0308c5ced"
    )
    assert not {digest(r["request"]) for r in heldout}.intersection(digest(r["request"]) for r in development)


def test_paired_frontier_compares_matching_panels_and_gates_the_final_result():
    from dfo_optimizer.discovery_benchmark import compare_paired, gate_both

    exact = {"paired_frontiers": {"two stages": [[4, 9], [6, 8]], "one stage": [[6, 8]]}}
    found = {"paired_frontiers": {"two stages": [[6, 8]], "different stage": [[4, 9]]}}
    assert compare_paired(exact, found)["recall"] == pytest.approx(1 / 3)
    rows = [
        {"recall": 1, "reference": True},
        {"recall": 1},
        {"recall": 1, "scalar_success": True, "regret": 0},
    ]
    combined = gate_both(rows, [*rows[:2], {"recall": 0, "scalar_success": False, "regret": 0.1}])
    assert combined["per_roll_passed"] and not combined["paired_family"]["passed"]
    assert not combined["passed"]


def test_node_budget_sets_admission_capacity_before_wall_deadline(monkeypatch):
    from time import perf_counter

    from dfo_optimizer import lifecycle_refinement
    from dfo_optimizer.discovery_benchmark import frozen_panel
    from dfo_optimizer.lifecycle import optimize_build

    request = frozen_panel("qualify")[0]["request"]
    fast = optimize_build(request)
    monkeypatch.setattr(lifecycle_refinement, "perf_counter", lambda: perf_counter() + 2.0)
    slow_clock = optimize_build(request)
    assert fast["class_admission"]["admission_complete"]
    assert fast["input_hash"] == slow_clock["input_hash"]
    assert fast["result_hash"] == slow_clock["result_hash"]

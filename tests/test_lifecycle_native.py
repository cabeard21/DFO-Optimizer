"""Independent reduced graph for cross-stage purchases and checkpoint objectives."""

import pytest


def oracle(stages, prices, ceilings, owned):
    paths = [(owned, 0, (), ())]
    for stage, (offers, ceiling, options) in enumerate(zip(prices, ceilings, stages, strict=True)):
        next_paths = []
        for held, spent, scores, choices in paths:
            for buys in range(1 << len(offers)):
                if held & buys or any(buys >> i & 1 and p < 0 for i, p in enumerate(offers)):
                    continue
                cost = spent + sum(p for i, p in enumerate(offers) if buys >> i & 1)
                if cost > ceiling:
                    continue
                for index, (requires, score) in enumerate(options):
                    if requires & ~(held | buys) == 0:
                        next_paths.append((held | buys, cost, scores + (score,), choices + (index,)))
        paths = next_paths
    all_points = {(spent, scores) for _, spent, scores, _ in paths}
    return {
        a
        for a in all_points
        if not any(
            b != a and b[0] <= a[0] and all(x >= y for x, y in zip(b[1], a[1], strict=True)) for b in all_points
        )
    }


def run(stages, prices, ceilings, owned=0, **limits):
    from dfo_optimizer import _lifecycle

    return _lifecycle.traverse(stages, prices, ceilings, owned, **limits)


def test_early_purchase_keeps_a_tied_loadout_for_later_and_charges_once():
    # Resource 0 is available only before the decisive checkpoint.
    stages = [[(0, 2.0), (1, 2.0)], [(0, 1.0), (1, 8.0)]]
    report = run(stages, [[7], [-1]], [7, 7])
    assert report["termination"] == "exhausted"
    assert {(r["spent"], tuple(r["scores"])) for r in report["routes"]} == {(0, (2.0, 1.0)), (7, (2.0, 8.0))}
    assert report["nodes"] > 0


def test_prebuy_can_be_needed_without_using_the_resource_early():
    report = run([[(0, 1.0)], [(1, 8.0)]], [[4], [-1]], [4, 4])
    assert report["routes"][0]["bought"] == [1, 0]
    assert report["routes"][0]["spent"] == 4


def test_future_training_spending_reserves_gold():
    report = run([[(1, 9.0), (0, 1.0)], [(0, 1.0)]], [[6], [-1]], [8, 5])
    assert [r["scores"] for r in report["routes"]] == [[1.0, 1.0]]


@pytest.mark.parametrize("seed", range(12))
def test_consistent_with_exhaustive_small_graph(seed):
    from random import Random

    rng = Random(seed)
    stages = [[(rng.randrange(8), float(rng.randrange(1, 9))) for _ in range(4)] for _ in range(3)]
    prices = [[rng.choice([-1, 0, 1, 3, 5]) for _ in range(3)] for _ in range(3)]
    ceilings = [rng.randrange(2, 10) for _ in range(3)]
    report = run(stages, prices, ceilings, 1)
    assert {(r["spent"], tuple(r["scores"])) for r in report["routes"]} == oracle(stages, prices, ceilings, 1)


def test_bounded_limits_keep_exactness_truthful():
    opts, offers, ceilings = [[(0, 1.0), (1, 2.0)]] * 5, [[1]] * 5, [9] * 5
    assert run(opts, offers, ceilings, max_nodes=1)["termination"] == "node_limit"
    assert run(opts, offers, ceilings, memory_bytes=1)["termination"] == "memory_limit"
    assert run(opts, offers, ceilings, wall_seconds=1e-12)["termination"] == "time_limit"


@pytest.mark.parametrize(
    "data",
    [
        ([[(2, 1.0)]], [[-1]], [1], 0),
        ([[(1, float("nan"))]], [[2]], [1], 0),
        ([[(1, 1.0)]], [[-1]], [-1], 0),
        ([], [], [], 0),
    ],
)
def test_bad_packed_graph_rejected(data):
    with pytest.raises(ValueError):
        run(*data)


def test_joint_kernel_honors_exact_preparation_boundary():
    import json
    from pathlib import Path

    base = Path(__file__).resolve().parents[1] / "examples"
    from dfo_optimizer.lifecycle import _progress, _families, _rules
    from dfo_optimizer.lifecycle_domain import compile_route
    from dfo_optimizer.lifecycle import _numeric
    from dfo_optimizer.progression import plan_progression
    from dfo_optimizer.progression_inputs import resolve_start

    raw = json.loads((base / "build-lifecycle.json").read_bytes())
    rules = _rules(None)
    start = {**_families(raw, rules)[0][0][1], "roll_seed": 42}
    route = plan_progression(_progress(raw, start), ruleset=rules)["routes"][0]
    domain = compile_route(raw, resolve_start(start, rules=rules)[0], route)
    full = _numeric(domain, {}, None)
    for limit in range(full["preparation_nodes"] - 1, full["preparation_nodes"] + 5):
        stats = _numeric(domain, {"max_nodes": limit}, None)
        assert stats["nodes"] <= limit
        assert stats["termination"] == "node_limit"

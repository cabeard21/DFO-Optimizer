"""Independent exhaustive checks of the compiled traversal, with no search helpers."""
from array import array
from itertools import combinations, product
import json
from pathlib import Path
from random import Random
from concurrent.futures import ThreadPoolExecutor
from time import monotonic, sleep

import pytest

from dfo_optimizer import _native


def request(**changes):
    return {
        "traits": [], "hp_values": [8], "races": [1], "attributes": [[50]] * 8,
        "skills": [[i] for i in range(12)], "target": 0, "top_k": 200,
        "max_nodes": 0, **changes,
    }


def test_batch_boundaries_and_validation():
    def run(hp, positive, negative):
        return _native.evaluate_batch(*(array("i", x) for x in (hp, positive, negative)))

    out = run([4, 7, 8, 30], [0, 0, 0, 10], [-4, 0, 0, -44])
    assert list(out["points"]) == [-12, -2, 0, -12]
    assert list(out["advancement"]) == [0.3 + 2.7 * (p + 12) / 52 for p in out["points"]]
    assert out["rows"] == 4
    assert run([], [], [])["rows"] == 0
    with pytest.raises(ValueError):
        run([7], [], [])
    with pytest.raises(ValueError):
        run([31], [2], [-3])
    with pytest.raises(ValueError):
        run([30], [2**31 - 1], [0])
    assert run([8], [0], [-(2**31)])["points"][0] == -(2**31)


def test_native_rows_match_pinned_node_oracle():
    source = Path(__file__).parent / "fixtures" / "oracle_classes.json"
    rows = json.loads(source.read_text(encoding="utf-8"))["numeric"]
    out = _native.evaluate_batch(*(array("i", (row[k] for row in rows))
                                   for k in ("hp", "advantage", "disadvantage")))
    assert out["rows"] == len(rows) > 0
    assert list(out["points"]) == [row["difficulty"] for row in rows]
    assert list(out["advancement"]) == [row["advancement"] for row in rows]


@pytest.mark.parametrize("seed", range(12))
def test_random_trait_search_equals_powerset(seed):
    random = Random(seed)
    costs = [random.randrange(1, 5) for _ in range(3)] + [-random.randrange(1, 5) for _ in range(5)]
    # Conflict references cross the 64-bit word boundary.
    ids = [0, 3, 65, 71, 92, 100, 109, 127]
    edges = {(a,b) for a,b in combinations(ids, 2) if random.random() < .14}
    required = {ids[0]} if seed % 2 else set()
    traits = [(i, int(k >= 3), costs[k], [b if a == i else a for a,b in edges if i in (a,b)],
               i in required, 0) for k,i in enumerate(ids)]
    expected = set()
    for count in range(9):
        for subset in combinations(ids, count):
            if not required.issubset(subset) or any(a in subset and b in subset for a,b in edges):
                continue
            for hp in [7, 10]:
                points = (hp - 8) * (2 if hp < 8 else 1) + sum(costs[ids.index(i)] for i in subset)
                if points == -2:
                    expected.add((hp, frozenset(subset)))
    out = _native.search_classes(**request(traits=traits, hp_values=[7,10], target=-2, top_k=1024))
    got = {(v["hp"], frozenset(v["traits"])) for v in out["results"]}
    assert got == expected
    assert out["leaves"] == len(expected)
    assert out["termination"] == "exhausted"


def test_order_sensitive_families_and_window_limit():
    traits = [(i, 0, 1, [], True, 1 if i < 3 else 2) for i in range(5)]
    out = _native.search_classes(**request(traits=traits, target=5))
    winners = {tuple([i for i in v["traits"] if i in family][-1]
                     for family in (range(3), (3,4))) for v in out["results"]}
    assert winners == set(product(range(3), (3,4)))
    assert out["leaves"] == 6
    too_many = [(i, 0, 1, [], True, 0) for i in range(8)]
    assert not _native.search_classes(**request(traits=too_many, target=8))["results"]


def test_cost_table_endpoints_in_both_directions():
    rows = [(i, i // 7, 14 if i < 7 else -14, [], True, 0) for i in range(14)]
    for ordered in (rows, rows[::-1]):
        out = _native.search_classes(**request(traits=ordered))
        assert out["leaves"] == 1
        assert set(out["results"][0]["traits"]) == set(range(14))


def test_attribute_skill_race_domains_and_top_k_ties():
    args = request(attributes=[[49,50],[50,51]] + [[50]]*6,
                   skills=[[1,2],[1,2]] + [[i] for i in range(3,13)], races=[1,2])
    out = _native.search_classes(**args, require_magic=True, magic_skills=[1])
    assert out["leaves"] == 8
    assert all(sum(v["attributes"]) == 400 and len(set(v["skills"])) == 12 for v in out["results"])
    ranked = _native.search_classes(**dict(args, top_k=3), objective="max_intelligence")
    assert [v["attributes"][1] for v in ranked["results"]] == [51,51,51]
    assert ranked["results"] == [v for v in out["results"] if v["attributes"][1] == 51][:3]
    assert not _native.search_classes(**args, require_magic=True, magic_skills=[34])["results"]


def test_higher_intelligence_replaces_already_retained_class():
    args = request(attributes=[[50, 49], [50, 51]] + [[50]] * 6, top_k=1)
    out = _native.search_classes(**args, objective="max_intelligence")
    assert out["leaves"] == 2
    assert out["results"][0]["attributes"][:2] == (49, 51)


def test_limits_and_pre_cancelled_search():
    token = _native.CancelToken()
    token.cancel()
    assert _native.search_classes(**request(), cancel=token)["termination"] == "cancelled"
    assert _native.search_classes(**request(memory_bytes=1))["termination"] == "memory_limit"
    assert _native.search_classes(**request(max_nodes=1))["termination"] == "node_limit"
    assert _native.search_classes(**request(top_k=1), stop_after_top=True)["termination"] == "top_k"
    assert _native.search_classes(**request(wall_seconds=1e-15))["termination"] == "time_limit"


def test_another_thread_can_cancel_active_kernel_and_preserve_an_incumbent():
    token = _native.CancelToken()
    assert not token.has_incumbent()
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(_native.search_classes, **request(skills=[range(35)] * 12,
                             top_k=1, wall_seconds=30), cancel=token)
        deadline = monotonic() + 30
        try:
            while not token.has_incumbent() and not future.done() and monotonic() < deadline:
                sleep(0.005)
            assert token.has_incumbent()
        finally:
            token.cancel()
        out = future.result()
    assert out["termination"] == "cancelled"
    assert 0 < out["leaves"] <= out["nodes"]
    assert len(out["results"]) == 1


@pytest.mark.parametrize("changes", [
    {"traits": [(128, 0, 1, [], False, 0)]}, {"skills": [[35]]*12},
    {"attributes": [[50,50]]*8}, {"races": [0]}, {"hp_values": [3]},
    {"target": -13}, {"top_k": 0}, {"wall_seconds": float("nan")},
])
def test_private_boundary_is_checked(changes):
    with pytest.raises((TypeError, ValueError)):
        _native.search_classes(**request(**changes))

"""Small independent enumerations for the class discovery kernel."""
from itertools import permutations

import pytest

from dfo_optimizer.native import require_native
from dfo_optimizer.progression_birth import _rolls, _spend


def search(**changes):
    options = dict(traits=[], races=[1, 5], hp_values=[8], attributes=[[50]] * 8,
                   skills=[[22, 23], [22, 23], [24], [25], [26], [2], [27], [3], [4], [5], [6], [7]],
                   target=0, top_k=16, max_nodes=100_000, magic_skills=list(range(22, 28)),
                   discovery=dict(exhaustive=True, required_masteries=list(range(22, 28)),
                                  roll_seeds=[42, 97], stage_items=[[(1, 0), (2, 0)]]))
    return require_native().search_classes(**{**options, **changes})


def test_reduced_exhaustion_matches_permutation_reference_and_realized_birth():
    r = search()
    expected = {(race, order) for race in [1, 5] for order in permutations([22, 23])}
    assert r["termination"] == "exhausted"
    assert {(c["race"], c["skills"][:2]) for c in r["results"]} == expected
    vals = []
    for seed in (42, 97):
        tape = _rolls({"roll_seed": seed})
        attrs = _spend([50 + v for v in tape["attribute_bonus"]], tape["attribute_pool"], None)
        vals.append((int(attrs[1] * 0.5), 1 + (attrs[6] - 50) / 200))
    for c in r["results"]:
        f = c["screen"]
        assert f["mean_birth_sp"] == sum(row[0] for row in vals) / 2
        assert f["mean_cast_rate"] == pytest.approx(sum(row[1] for row in vals) / 2)
        assert f["birth_hp"] == 33
        assert f["eligible_stage_items"] == [2]


def test_missing_required_skills_and_overfull_group_are_infeasible():
    assert not search(discovery={"exhaustive":True, "required_skills":[0]})["results"]
    slots = [[i] for i in [22,23,0,24,25,26,27,1,2,3,4,5]]
    assert not search(skills=slots)["results"]


def test_sampled_panel_varies_races_and_trait_restrictions_and_is_deterministic():
    traits = [(i, 1, -1, (), False, 0) for i in range(6)]
    opt = dict(exhaustive=False, seed=91, roll_seeds=[11],
               trait_features=[(i, 0, 1 << i, 0, 0) for i in range(6)],
               stage_items=[[(1, 0), (2, 0), (4, 0)]])
    r = search(traits=traits, target=-1, discovery=opt, top_k=8)
    assert r["termination"] in ("sample_limit", "node_limit")
    assert r["results"] == search(traits=traits,target=-1,discovery=opt,top_k=8)["results"]
    assert {c["race"] for c in r["results"]} == {1,5}
    assert len({c["traits"] for c in r["results"]}) > 1
    for c in r["results"]:
        assert c["screen"]["eligible_stage_items"] == [3 - int(c["traits"][0] < 3)]


def test_discovery_honors_limits_before_first_result():
    token = require_native().CancelToken()
    assert token.cancelled() is False
    token.cancel()
    assert token.cancelled() is True
    assert search(cancel=token)["termination"] == "cancelled"
    assert search(memory_bytes=128)["termination"] == "memory_limit"
    assert search(max_nodes=1)["termination"] == "node_limit"


def test_stable_examples_match_exact_prefix_and_count_only_visited_examples():
    opt={"stable_examples":True,"required_masteries":list(range(22,28))}
    small=search(top_k=2,discovery=opt)
    whole=search(top_k=4,discovery={**opt,"exhaustive":True})
    assert small["results"] == whole["results"][:2]
    assert (small["termination"],small["leaves"],small["unique_screened"])==("top_k",2,2)
    assert (whole["termination"],whole["unique_screened"])==("exhausted",4)


def test_census_counts_distinct_documents_when_sampling_revisits():
    sampled = search(discovery={"seed":13}, top_k=4)
    assert sampled["termination"] == "sample_limit"
    assert sampled["leaves"] == sampled["attempts"] == 256
    assert sampled["unique_screened"] == len(sampled["results"]) == 4


def test_exhaustive_mastery_quotas_differential():
    schools = (22, 23, 24)
    slots = (0, 3, 4, 6, 7)
    base = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12]
    cases = []
    for values in permutations((*schools, 13, 14)):
        row = base.copy()
        for slot, skill in zip(slots, values):
            row[slot] = skill
        if sum(i in schools for i in row[6:]) <= 1:
            cases.append(tuple(row))
    domains = [list((*schools, 13, 14)) if i in slots else [n] for i, n in enumerate(base)]
    out = search(skills=domains, races=[1], top_k=150, discovery={"exhaustive":True,"required_masteries":schools})
    assert out["termination"] == "exhausted"
    assert out["unique_screened"] == len(cases)
    assert {c["skills"] for c in out["results"]} == set(cases)


def test_magery_and_gear_features_change_by_trait_selection():
    traits = [(0, 0, 0, (1,), False, 3), (1, 0, 0, (0,), False, 3)]
    opts = dict(exhaustive=True, roll_seeds=[42], trait_features=[(0,12,1,0,3), (1,4,0,2,1)],
                stage_items=[[(1,0),(0,2),(0,4)],[]])
    result=search(traits=traits, races=[1], discovery=opts)
    by_set={c["traits"]: c["screen"] for c in result["results"]}
    assert by_set[(0,)]["absorption_flag"] == 3
    assert by_set[(1,)]["absorption_flag"] == 1
    assert by_set[(0,)]["mean_birth_sp"] == 3 * by_set[(1,)]["mean_birth_sp"]
    assert by_set[()]["eligible_stage_items"] == [3,0]
    assert by_set[(0,)]["eligible_stage_items"] == by_set[(1,)]["eligible_stage_items"] == [2,0]


def test_native_pareto_retains_tradeoff_extremes_and_reports_capacity_loss():
    # A budget transfer trades cast rate against magicka on every tape.
    attrs = [[50] for _ in range(8)]
    attrs[1] = attrs[6] = [30, 40, 50, 60, 70]
    fixed = [[i] for i in (22,23,24,25,26,2,27,3,4,5,6,7)]
    args=dict(attributes=attrs, skills=fixed, races=[1], discovery={"exhaustive":True})
    exact = search(**args, top_k=20)
    panel = search(**args, top_k=4)
    assert exact["pareto_overflows"] == 0
    assert panel["pareto_overflows"] > 0 and panel["pareto_retained"] == 2
    kept = [row["screen"] for row in panel["results"] if row["screen"]["pareto_representative"]]
    for axis in ("mean_birth_sp","mean_cast_rate"):
        assert max(r[axis] for r in kept) == max(r["screen"][axis] for r in exact["results"])


def test_equal_feature_vectors_keep_distinct_material_and_mastery_alternatives():
    traits = [(i, 1, -1, (), False, 0) for i in range(4)]
    args = dict(traits=traits,target=-1,races=[1],top_k=16,discovery={"exhaustive":True})
    r = search(**args)
    assert r["unique_screened"] == len(r["results"]) == 8
    assert r["pareto_retained"] < len(r["results"])
    assert r["pareto_overflows"] == 0


@pytest.mark.parametrize("raw", [
    {"roll_seeds":[]}, {"roll_seeds":[42,42]}, {"stable_examples":1}, {"exhaustive":1},
    {"required_masteries":[35]}, {"trait_features":[(128,2,0,0,0)]},
    {"trait_features":[(1,2,0,0,0)]*2}, {"stage_items":[[]]*33},
    {"stage_items":[[(1,-1)]]}, {"stage_items":[True]}, {"typo":1},
])
def test_invalid_native_discovery_tables(raw):
    with pytest.raises(ValueError):
        search(discovery=raw)

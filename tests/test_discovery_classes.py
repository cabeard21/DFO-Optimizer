from copy import deepcopy
import json
from pathlib import Path

import pytest

from dfo_optimizer.ruleset import load_ruleset
from dfo_optimizer.search import optimize_classes
from dfo_optimizer.search_request import parse_request


PROFILE = {"profile": "spellcaster_discovery_v1"}
RULES = load_ruleset()


def test_named_discovery_domain_preserves_locks_and_balanced_full_resolution():
    spec = parse_request(
        {
            **PROFILE,
            "required_traits": ["increasedMagery/intInSpellPoints3"],
            "excluded_skills": ["Medical"],
            "skill_locks": {"primary_1": "Destruction"},
            "attribute_domains": {"luck": [53]},
        },
        RULES,
    )
    assert spec.required_masteries == tuple(range(22, 28))
    assert spec.skill_domains[0] == (22,)
    assert all(0 not in slot for slot in spec.skill_domains)
    assert spec.attribute_domains[-1] == (53,)
    assert len(spec.attribute_domains[0]) == 66
    assert set(spec.race_ids) == set(range(1, 9))


@pytest.mark.parametrize(
    "fields",
    [
        {"skill_locks": {"whatever": "Destruction"}},
        {"required_traits": ["imaginary"]},
        {"excluded_skills": ["Restoration"]},
        {"required_skills": ["Destruction", 22]},
        {"attribute_grid_step": True},
        {"roll_seeds": []},
    ],
)
def test_invalid_domain(fields):
    with pytest.raises(ValueError):
        parse_request({**PROFILE, **fields}, RULES)


def test_exact_all_schools_and_paired_screen_match_birth():
    from dfo_optimizer.progression_birth import birth_state

    source = json.loads(
        (Path(__file__).resolve().parents[1] / "examples/max-intelligence.json").read_text()
    )
    q = {
        **source,
        **PROFILE,
        "objective": "exhaustive",
        "top_k": 100,
        "skill_domains": [[s] for s in [22, 23, 24, 25, 26, 0, 27, 1, 2, 3, 4, 5]],
        "attribute_domains": {
            a: [50]
            for a in (
                "strength",
                "intelligence",
                "willpower",
                "agility",
                "endurance",
                "personality",
                "speed",
                "luck",
            )
        },
        "roll_seeds": [42, 77],
    }
    original = deepcopy(q)
    r = optimize_classes(q)
    assert r["proof_scope"]["admission_complete"] and r["proof_scope"]["enumeration_complete"]
    assert r["candidates"] and q == original
    for c in r["candidates"]:
        f = c["screening_features"]
        states = [
            birth_state({"class": c["class_doc"], "race_id": c["race_id"], "roll_seed": seed}, RULES)
            for seed in q["roll_seeds"]
        ]
        assert f["mean_birth_sp"] == sum(s["sp"] for s in states) / 2
        assert f["magicka_multiplier"] == 3 and f["birth_hp"] == 55
        assert len(f["required_masteries"]) == 6
        assert c["class_id"] and c["class_doc"]["skills"]["primary"][0] == "Destruction"


def test_default_discovery_visits_different_game_decisions():
    r = optimize_classes({**PROFILE, "max_nodes": 250000, "top_k": 32})
    docs = [c["class_doc"] for c in r["candidates"]]
    assert not r["proof_scope"]["admission_complete"]
    for k in ("attributes", "skills", "disadvantages"):
        assert len({json.dumps(d[k], sort_keys=True) for d in docs}) > 1
    assert len({c["race_id"] for c in r["candidates"]}) > 1


def test_odd_stat_lock_can_be_funded_between_coarse_points():
    q = {**PROFILE, "attribute_domains": {"luck": [53]}, "max_nodes": 80000}
    result = optimize_classes(q)
    assert result["candidates"]
    assert all(c["class_doc"]["attributes"]["luck"] == 53 for c in result["candidates"])


def test_replayable_profile_distinguishes_fine_and_coarse_domains():
    spec = parse_request(PROFILE, RULES)
    encoded = json.loads(json.dumps(spec.snapshot()))
    assert parse_request(encoded, RULES) == spec


def test_regression_document_distinct_from_default_diagnostic():
    from dfo_optimizer.build_baselines import resolve_family_baseline

    source = json.loads(
        (Path(__file__).resolve().parents[1] / "examples/max-intelligence.json").read_text()
    )
    exact = optimize_classes(source)["candidates"][0]
    original = optimize_classes({})["candidates"][0]
    reference = resolve_family_baseline("m1-breton-caster", RULES)
    assert (exact["race_id"], exact["class_doc"]) == (reference["race_id"], reference["class"])
    assert {row["secondary"] for row in exact["class_doc"]["disadvantages"]} == {
        "steel",
        "elven",
        "dwarven",
        "mithril",
        "silver",
        "adamantium",
        "iron",
    }
    assert original["class_doc"]["attributes"]["intelligence"] == 50
    assert exact["class_doc"] != original["class_doc"]


def test_empty_cancelled_and_deadline_prevent_admission_claims():
    from dfo_optimizer.native import require_native

    token = require_native().CancelToken()
    token.cancel()
    for result, reason in (
        (optimize_classes(PROFILE, cancel=token), "cancelled"),
        (optimize_classes({**PROFILE, "wall_seconds": 1e-12}), "time_limit"),
    ):
        assert result["termination"] == reason
        assert result["counters"]["unique_screened"] == 0
        assert not result["proof_scope"]["admission_complete"]
    none = optimize_classes({**PROFILE, "required_traits": ["inabilityToRegen"]})
    assert none["termination"] == "constraint_conflict" and not none["candidates"]


def test_physical_pool_is_scoped_to_availability_and_actual_material():
    from dfo_optimizer.discovery_features import screening_equipment

    q = json.loads((Path(__file__).resolve().parents[1] / "examples/max-intelligence.json").read_text())
    refs = [[s] for s in (22, 23, 24, 25, 26, 0, 27, 1, 2, 3, 4, 5)]
    items = [
        {
            "instance_id": name,
            "item": {"group": "Weapons", "templateIndex": 115, "material": metal},
            "acquisition": {"obtainable": True},
            "stages": [1],
        }
        for name, metal in (("iron", 0), ("ebony", 7))
    ]
    pool = screening_equipment({"offers": items})
    r = optimize_classes(
        {
            **q,
            **PROFILE,
            "objective": "exhaustive",
            "top_k": 100,
            "skill_domains": refs,
            "screen_equipment": pool,
            "attribute_domains": {k: [50] for k in RULES["progression_rules"]["creation"]["attributes"]},
        }
    )
    assert r["candidates"]
    for c in r["candidates"]:
        stages = c["screening_features"]["equipment_class_compatibility"]
        assert stages[0]["eligible"] == []
        assert "iron" in stages[1]["excluded"]
        bans = [p["secondary"] for p in c["class_doc"]["disadvantages"]]
        assert ("ebony" in stages[1]["eligible"]) == ("ebony" not in bans)


def test_stage_limits_are_checked_before_cross_product():
    from dfo_optimizer.discovery_features import screening_equipment

    with pytest.raises(ValueError, match="32 stage"):
        screening_equipment({"offers": [{"stages": list(range(33))}]})

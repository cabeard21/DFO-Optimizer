import json
from pathlib import Path

import pytest

from dfo_optimizer import beginner_classes as beginner


def test_hand_built_families_certify_on_paired_births():
    families = beginner.manual_classes()
    assert {f["start"]["race_id"] for f in families} == {1, 5}
    for f in families:
        c = f["compliance"]
        assert c["passed"] and not c["failures"]
        assert c["advancement_multiplier"] == 0.3
        assert c["backup_weapons"] and "Iron" in c["plate"]["allowed_materials"]
        assert [len(c["mastery_groups"][name]) for name in ("primary", "major", "minor")] == [3, 2, 1]
        assert [b["seed"] for b in c["births"]] == [42, 43]
        assert min(b["headroom_kg"] for b in c["births"]) >= 0


def test_downloaded_winning_class_fails_beginner_gates():
    saved = json.loads((Path(__file__).parent / "fixtures" / "beginner-m8-winner.json").read_bytes())
    verdict = beginner.beginner_compliance(saved["class"], saved["race_id"])
    assert not verdict["passed"]
    assert "plate_forbidden" in verdict["failures"]
    assert saved["result_hash"].startswith("61702c9f")


def test_quick_includes_meaningfully_distinct_native_discoveries():
    run = beginner.beginner_roster("quick", max_nodes=120000)
    families = run["families"]
    assert len(families) == len({f["id"] for f in families})
    assert len(families) >= 4 and all(f["compliance"]["passed"] for f in families)
    discovered = [f for f in families if f["origin"] == "discovered"]
    assert len(discovered) >= 2
    assert {f["compliance"]["advancement_multiplier"] == 0.3 for f in discovered} == {
        False,
        True,
    }
    assert 0 < run["counts"]["legal"] <= run["counts"]["screened"]
    assert run["counts"]["nodes"] <= 120000 and not run["proof_scope"]["admission_complete"]


def test_native_and_replay_agree_on_reduced_domain():
    f = beginner.manual_classes()[0]
    doc = f["start"]["class"]
    names = [
        *doc["skills"]["primary"],
        *doc["skills"]["major"],
        *doc["skills"]["minor"],
    ]
    domain = {
        "race_ids": [1, 5],
        "difficulty_values": [-12],
        "top_k": 100,
        "attribute_domains": {k: [v] for k, v in doc["attributes"].items()},
        "skill_domains": [[s] for s in names],
        "trait_ids": [23, 65, 60, 58, 62, 64, 56, 66],
    }
    run = beginner.beginner_roster("quick", domain=domain, exhaustive=True, max_nodes=10000)
    assert run["proof_scope"]["admission_complete"]
    assert len([f for f in run["families"] if f["origin"] == "discovered"]) >= 1


@pytest.mark.parametrize("difficulty", [-13, 41, True])
def test_invalid_difficulty_domain(difficulty):
    with pytest.raises(ValueError):
        beginner.beginner_roster(domain={"difficulty_values": [difficulty]})


def test_hard_conflict_and_bounded_miss_never_relax_the_class_or_claim_a_winner():
    reference = beginner.manual_classes()[0]
    attrs = {k: [v] for k, v in reference["start"]["class"]["attributes"].items()}
    conflict = beginner.beginner_roster(
        "quick",
        domain={
            "difficulty_values": [-12],
            "attribute_domains": attrs,
            "required_trait_ids": [55],
        },
    )  # forbidden plate contradicts the requested profile
    assert conflict["proof_scope"]["enumeration_complete"] and conflict["proof_scope"]["admission_complete"]
    assert conflict["proof_scope"]["conflicts"] and conflict["proof_scope"]["suggested_edits"]
    assert [(e["remove_id"], e["witness"]) for e in conflict["proof_scope"]["verified_minimal_edits"]] == [
        (55, reference["id"])
    ]
    assert conflict["counts"]["legal"] == conflict["counts"]["admitted"] == 0
    assert all(f["origin"] == "manual" for f in conflict["families"])
    miss = beginner.beginner_roster("quick", max_nodes=1)
    assert not miss["proof_scope"]["enumeration_complete"] and not miss["proof_scope"]["admission_complete"]
    assert not miss["proof_scope"]["suggested_edits"] and miss["counts"]["admitted"] == 0


def test_hard_class_saves_and_unverified_regen_are_rejected_even_if_creation_succeeds():
    from copy import deepcopy

    manual = beginner.manual_classes()[0]["start"]
    for key, value, reason in [
        ("inabilityToRegen", "", "uncertain_regeneration_behavior"),
        ("lowTolerance", "toMagic", "class_save_vulnerability"),
    ]:
        doc = deepcopy(manual["class"])
        doc["disadvantages"][-1] = {
            "primary": key,
            **({"secondary": value} if value else {}),
        }
        verdict = beginner.beginner_compliance(doc, manual["race_id"])
        assert not verdict["passed"] and any(reason in f for f in verdict["failures"])


def test_catalog_counts_include_template_weapon_armor_and_material_bans():
    reference = beginner.manual_classes()[0]["compliance"]
    catalog = reference["catalog_eligibility"]
    assert catalog["by_family"]["weapons"]["excluded"] > 0
    assert catalog["by_family"]["armor"]["excluded"] > 0
    assert 513 in catalog["by_type"]["Armor/Cuirass"]["excluded_materials"]
    assert 0 in catalog["by_type"]["Weapons/Broadsword"]["eligible_materials"]
    assert reference["plate_weapon_materials"] == len(reference["plate_weapon_material_names"]) == 4


def test_tiers_keep_the_reference_control_and_discovery_prefix():
    quick, standard, thorough = [
        beginner.beginner_roster(level) for level in ("quick", "standard", "thorough")
    ]
    previous = []
    for expected, panel in zip((4, 24, 100), (quick, standard, thorough), strict=True):
        families = panel["families"]
        ids = [f["id"] for f in families]
        assert len(set(ids)) == len(ids) and ids[: len(previous)] == previous
        previous = ids
        assert panel["counts"]["admitted"] == expected
        assert all(
            len(f["compliance"]["kit_sensitivity"]) == 6
            and all(k["passed"] for k in f["compliance"]["kit_sensitivity"])
            for f in families
        )
    base, _, race, material = quick["families"][:4]
    assert race["origin"] == "race_comparison" and race["start"]["class"] == base["start"]["class"]
    assert (
        race["start"]["race_id"] != base["start"]["race_id"]
        and race["counterfactual"]["reference_id"] == base["id"]
    )
    assert material["counterfactual"]["from"] == "adamantium" and material["counterfactual"]["to"] == "ebony"
    assert material["compliance"]["difficulty_points"] == base["compliance"]["difficulty_points"]
    assert material["compliance"]["plate"]["material"] != base["compliance"]["plate"]["material"]


def test_a_backup_outside_the_reviewed_catalog_on_alternate_tapes_cannot_pass():
    from copy import deepcopy

    family = beginner.manual_classes()[0]
    doc = deepcopy(family["start"]["class"])
    doc["skills"]["major"][-1] = "Axe"
    check = beginner.beginner_compliance(doc, 1)
    assert check["backup_weapons"] and not check["passed"]
    assert any(k["passed"] for k in check["kit_sensitivity"])
    assert "sampled_kit_without_usable_backup_or_carry" in check["failures"]
    names = [*doc["skills"]["primary"], *doc["skills"]["major"], *doc["skills"]["minor"]]
    from dfo_optimizer.native import require_native

    token = require_native().CancelToken()
    domain = {
        "race_ids": [1],
        "difficulty_values": [-12],
        "skill_domains": [[s] for s in names],
        "attribute_domains": {k: [v] for k, v in doc["attributes"].items()},
        "trait_ids": [23, 65, 60, 58, 62, 64, 56, 66],
        "top_k": 1,
    }
    exact = beginner.beginner_roster("quick", domain=domain, exhaustive=True, cancel=token)
    assert exact["counts"]["screened"] == 1 and exact["counts"]["legal"] == 0
    assert exact["proof_scope"]["admission_complete"] and not token.has_incumbent()


def test_cancel_and_memory_stops_have_no_unearned_completeness_claim():
    from dfo_optimizer.native import require_native

    token = require_native().CancelToken()
    token.cancel()
    cancelled = beginner.beginner_roster("quick", cancel=token)
    assert cancelled["proof_scope"]["termination"] == "cancelled" and not cancelled["families"]
    bounded = beginner.beginner_roster("quick", memory_bytes=1)
    assert not bounded["proof_scope"]["admission_complete"] and bounded["counts"]["screened"] == 0
    assert all(s["termination"] == "memory_limit" for s in bounded["proof_scope"]["slices"])


def test_a_caster_can_damage_at_birth_on_each_paired_roll_before_any_purchase():
    from copy import deepcopy

    manual = beginner.manual_classes()[0]
    for birth in manual["compliance"]["births"]:
        assert any(
            s["name"] == "Arcane Arrow" and 0 < s["cost_sp"] <= birth["sp"]
            for s in birth["affordable_starting_damage_spells"]
        )
    doc = deepcopy(manual["start"]["class"])
    primary, minor = doc["skills"]["primary"], doc["skills"]["minor"]
    primary[0], minor[0] = minor[0], primary[0]
    verdict = beginner.beginner_compliance(doc, 1)
    assert not verdict["passed"] and "no_affordable_starting_damage_spell" in verdict["failures"]
    assert verdict["births"][0]["owned_starting_spell_names"]


def test_source_release_price_for_every_possible_primary_and_major_skill():
    from dfo_optimizer.beginner_creation import creation
    from dfo_optimizer.progression_practice import release_cost
    from dfo_optimizer.progression_replay import _cast_price
    from dfo_optimizer.ruleset import _service_rules

    records = {
        s["index"]: s for s in _service_rules(None)["progression_rules"]["creation"]["generated_records"]
    }
    costs = creation()["starter_damage"]
    assert {r["index"] for r in costs["22/primary"]} == {990, 991}
    assert {r["index"] for r in costs["22/major"]} == {991}
    for row in costs["22/primary"]:
        recipe = {"skill": 22, **release_cost(records[row["index"]], 22)}
        assert [_cast_price({"skills": [raw] * 35, "mastered": []}, recipe) for raw in range(41)] == row[
            "costs"
        ]

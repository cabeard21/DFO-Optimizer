"""Source-derived combat outcomes determine the selected objective independently of class screening."""
import json
from pathlib import Path

import pytest

from dfo_optimizer.lifecycle import compare_builds, optimize_build, replay_build

BASE = Path(__file__).parents[1] / "examples"


def query(*, encounter=True):
    request = json.loads((BASE / "build-encounter-reversal.json").read_text())
    request["spellbook"]["maker"]["price_factor"] = 0.0001  # Same declared one-gold quote
    if not encounter:
        request.pop("encounter")
    return request


@pytest.mark.parametrize("encounter", [True, False])
def test_cheaper_per_cast_policy_survives_higher_dps_with_identical_gold(encounter):
    request = query(encounter=encounter)
    damage = optimize_build({**request, "objective": "encounter_damage" if encounter else "endgame_damage"})
    efficiency = optimize_build({**request, "objective": "damage_per_sp"})
    assert replay_build(damage)["validated"] and replay_build(efficiency)["validated"]
    assert {r["checkpoints"][-1]["casting_policy"][0] for r in damage["candidates"]} == {"surge"}
    assert {r["checkpoints"][-1]["casting_policy"][0] for r in efficiency["candidates"]} == {"spark"}
    assert all(r["checkpoints"][-1]["performance"]["damage_per_sp"] > 0 for r in efficiency["candidates"])
    assert {r["final_dps"] for r in efficiency["final_checkpoint_only"]} == {damage["candidates"][0]["checkpoints"][-1]["dps"]}
    with pytest.raises(ValueError, match="same targets"):
        compare_builds([damage, efficiency])


@pytest.mark.parametrize("objective", ["overall_pve", "pareto", "progression_effort", "clear_performance",
                                       "resource_sustain", "survivability"])
def test_focused_outcomes_come_from_replayed_trials(objective):
    request = query()
    request["encounter"]["scenario"]["enemies"][0]["hp"] = 5
    plan = optimize_build({**request, "objective": objective})
    assert replay_build(plan)["validated"] and plan["candidates"]
    step = plan["candidates"][0]["checkpoints"][-1]
    metrics, trial = step["performance"], step["encounter"]
    assert metrics["damage_per_sp"] == pytest.approx(trial["damage"] / trial["spent_sp"])
    assert metrics["censored_clear_us"] == trial["end_us"]
    assert metrics["survived"] is True and metrics["cleared"] is True


def test_unfinished_fight_includes_whole_horizon_and_efficiency_is_undefined_if_no_cast():
    request = query()
    request["encounter"]["scenario"]["enemies"][0]["x_mm"] = 100_000
    plan = optimize_build({**request, "objective": "clear_performance"})
    step = plan["candidates"][0]["checkpoints"][-1]
    assert step["performance"]["cleared"] is False
    assert step["performance"]["damage_per_sp"] is None
    assert step["performance"]["censored_clear_us"] == 500_000


def test_survival_requires_a_fight():
    with pytest.raises(ValueError, match="requires an encounter"):
        optimize_build({**query(encounter=False), "objective": "survivability"})
def test_resolved_enemy_spell_uses_own_catalog_spell_and_racial_save():
    q = query()
    bolt = {"id":"bolt", "recipe":{"element":4,"range_type":2,
            "effects":[{"effect_id":"4,0","base_low":50,"base_high":50,
                        "plus_low":1,"plus_high":1,"per_level":20}]},
            "evidence":"Hypothetical enemy spell, with a verified Spell Maker recipe"}
    q["objective"] = "survivability"
    q["encounter"].update(hostile_spells=[bolt], environment="darkness")
    scene = q["encounter"]["scenario"]
    scene["tape"] = [0.65]*40
    scene["enemies"][0]["level"] = 1
    scene["incoming"] = [{"source":0, "kind":"bundle", "spell":"bolt", "time_us":100,
                          "evidence":"Authored enemy bolt landing in the room"}]
    def incoming_loss(baseline):
        plan = optimize_build({**q,"families":[{"id":"caster","baseline_id":baseline}]})
        assert replay_build(plan)["validated"] and plan["candidates"], plan["gaps"]
        p = plan["candidates"][0]["checkpoints"][-1]
        assert "bolt" not in p["spellbook"]
        return p["encounter"]["initial_hp"] - p["encounter"]["end_hp"]
    assert incoming_loss("m1-breton-caster") < incoming_loss("comparison-high-elf-caster")

def test_no_spell_at_birth_can_learn_and_fight_at_later_checkpoint():
    q = query(encounter=False)
    q["spellbook"].update(allow_unarmed_start=True, include_known=False)
    q["spellbook"]["maker"]["stages"] = [1]
    q["progression"]["stages"] = [[{"kind":"skip"}]]
    q["checkpoints"] = [0,1]
    plan = optimize_build({**q,"objective":"overall_pve"})
    assert plan["candidates"] and replay_build(plan)["validated"], plan["gaps"]
    for row in plan["candidates"]:
        birth, later = row["checkpoints"]
        assert birth["casting_policy"] == [] and birth["dps"] == 0
        assert later["casting_policy"] and later["dps"] > 0

def test_prospective_saves_and_absorption_match_pinned_game_vectors():
    from dfo_optimizer.lifecycle_defenses import career_absorption, player_save_chances
    from dfo_optimizer.ruleset import load_ruleset

    rules = load_ruleset()
    races = {r["id"]:r["flags"] for r in rules["races"]}
    oracle = json.loads((Path(__file__).parent / "fixtures/encounter-oracle.json").read_text())["prospective_defenses"]
    for case in oracle["saves"]:
        career = {**rules["career_defaults"], **case["career"]}
        assert player_save_chances(races[case["raceId"]], career, case["willpower"]) == case["chances"]
    for case in oracle["absorption"]:
        career = {"spellAbsorptionFlags": case["flags"]}
        assert career_absorption(career, "darkness") == case["indoors_day"] == case["outdoors_night"]
        assert career_absorption(career, "daylight") == case["outdoors_day"]

def test_undefined_objective_is_not_reported_as_an_optimum():
    q = query()
    q["encounter"]["scenario"]["enemies"][0]["x_mm"] = 100_000
    plan = optimize_build({**q, "objective":"damage_per_sp"})
    assert plan["exact"] and plan["status"] == "no_defined_objective"
    assert plan["candidates"] == [] and plan["final_checkpoint_witnesses"]
    assert replay_build(plan)["validated"]


def test_comparison_keeps_independently_replayed_final_dps_alternative():
    base = {**query(), "objective": "damage_per_sp"}
    plan = optimize_build(base)
    comparison = compare_builds([plan,plan])
    assert max(r["final_dps"] for r in comparison["final_checkpoint_only"]) == max(
        r["final_dps"] for r in plan["final_checkpoint_only"])
    assert replay_build(plan)["routes_checked"] >= 2

@pytest.mark.parametrize(("kind", "secondary", "label"), [
    ("advantage", "general", "Regenerate Health"),
    ("disadvantage", "fromHolyPlaces", "Damage from Holy Places"),
    ("disadvantage", "fromSunlight", "Damage from Sunlight"),
])
def test_round_sensitive_career_is_a_named_gap_during_exposure(kind, secondary, label):
    from dfo_optimizer.build_baselines import resolve_family_baseline
    from dfo_optimizer.ruleset import load_ruleset

    q = query()
    start = resolve_family_baseline("m1-breton-caster", load_ruleset())
    start["profile"] = "custom"
    doc = start["class"]
    if kind == "disadvantage":
        doc["disadvantages"] = doc["disadvantages"][:3]
    key = "advantages" if kind == "advantage" else "disadvantages"
    doc[key].append({"primary":"regenerateHealth" if kind == "advantage" else "damage","secondary":secondary})
    q["families"] = [{"id":"passive", "start":start}]
    scene = q["encounter"]["scenario"]
    scene.update(first_round_us=1_000_000, incoming=[{"source":0,"kind":"spell","damage":1,"time_us":50}])
    short = optimize_build(q)
    assert short["candidates"] and replay_build(short)["validated"], short["gaps"]
    scene["horizon_us"] = 1_500_000
    result = optimize_build(q)
    assert not result["exact"] and not result["candidates"] and label in str(result["gaps"])

@pytest.mark.parametrize("explicit_layouts", [True, False])
def test_hostile_bundle_skips_only_unsupported_optional_item(explicit_layouts):
    from dfo_optimizer.discovery_presets import discovery_preset
    from dfo_optimizer.build_baselines import resolve_family_baseline
    from dfo_optimizer.ruleset import load_ruleset

    q = discovery_preset("enemy_caster")
    q.pop("class_admission_strategy")
    q.pop("class_search")
    start = resolve_family_baseline("m1-breton-caster", load_ruleset())
    start["profile"] = "custom"
    start["class"]["disadvantages"] = []
    q.update(families=[{"id":"unrestricted", "start":start}], roll_seeds=[42])
    q["search"]["max_nodes"] = 0
    item = next(r for r in q["equipment"]["offers"] if r["item"]["templateIndex"] == 113)
    item["item"]["affixes"] = [{"id":"stat", "param":"willpower", "value":2}]
    if not explicit_layouts:
        q["equipment"].pop("loadouts")
    out = optimize_build(q)
    assert out["candidates"] and replay_build(out)["validated"], out["gaps"]
    assert not out["exact"] and item["instance_id"] in str(out["gaps"])
    assert all(item["instance_id"] not in step["loadout"].values() for row in out["candidates"] for step in row["checkpoints"])


def test_unresolved_optional_spell_skips_only_affected_policy():
    q = query()
    q["spellbook"]["spells"][0]["recipe"]["range_type"] = 4
    out = optimize_build(q)
    assert out["candidates"] and replay_build(out)["validated"], out["gaps"]
    assert not out["exact"] and "self-blast" in str(out["gaps"])
    assert all(row["checkpoints"][0]["casting_policy"] == ["surge"] for row in out["candidates"])

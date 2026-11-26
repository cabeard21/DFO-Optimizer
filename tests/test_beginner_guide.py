"""A printable checklist must reproduce the selected class, race, and witnessed plan."""
import pytest

from dfo_optimizer.build_baselines import resolve_family_baseline
from dfo_optimizer.ruleset import load_ruleset
from dfo_optimizer.workbench_files import export_job


def example():
    start = resolve_family_baseline("m1-breton-caster", load_ruleset())
    return {"id":"first", "role":"recommended", "class":start["class"], "race":"Breton",
            "race_id":start["race_id"], "permanent":{"passed":True, "backup_weapons":[],
            "mastery_groups":{}, "traits":{"advantages":[], "disadvantages":[]}},
            "progression":{}, "outcomes":{}, "metrics":{}, "tradeoff":"An evaluated candidate."}


def test_printable_checklist_has_all_creation_and_development_steps():
    from dfo_optimizer.beginner_guide import build_guide

    row = example()
    guide = build_guide(row)
    assert len(guide["sections"]) == len({s["id"] for s in guide["sections"]}) == 12
    for section in guide["sections"]:
        assert section["title"] in guide["text"]
        assert section["items"] and all(isinstance(i, str) and i in guide["text"] for i in section["items"])
    assert row["race"] in guide["text"] and all(n in guide["text"] for n in row["class"]["skills"]["major"])
    assert "unreported" in guide["text"].lower() or "unavailable" in guide["text"].lower()


def test_selected_class_and_checklist_downloads_match():
    from dfo_optimizer.beginner_guide import build_guide

    lead = example()
    alt = {**lead, "id":"alternative", "class":{**lead["class"], "name":"Second class"}}
    job = {"action":"build recommend", "result":{"kind":"beginner_recommendation",
           "recommendation":lead, "alternatives":[alt], "comparisons":[]}}
    for row in [lead,alt]:
        row["guide"] = build_guide(row)
        doc, filename = export_job(job, {"family":row["id"]})
        assert doc == row["class"] and filename.endswith(".dfclass.json")
        payload, name = export_job(job, {"family":row["id"], "checklist":"1"})
        assert name.endswith(".txt") and payload.decode("utf-8") == row["guide"]["text"]
    with pytest.raises(ValueError, match="published"):
        export_job(job, {"family":"unknown"})

def test_development_checklist_uses_representative_roll_and_owned_copies():
    from dfo_optimizer.beginner_guide import build_guide
    from dfo_optimizer.beginner_progression import CheckpointCache
    from dfo_optimizer.beginner_report import compact_stage

    rules = load_ruleset()
    row = example()
    start = resolve_family_baseline("m1-breton-caster", rules)
    projection = CheckpointCache(rules).project({**start,"roll_seed":42}, levels=(1,))
    point = compact_stage(projection["checkpoints"][0])
    row["progression"] = {"policy":projection["policy"],"representative_seed":42,
                          "rolls":[{"seed":41,"stages":[]},{"seed":42,"stages":[point]}]}
    text = build_guide(row)["text"]
    assert "seed 42" in text and "up to four points to Endurance" in text
    assert "Minor Shock [990]" in text and "Salve Bruise" in text
    assert all(item["name"] in text for item in point["loadout_details"])
    assert "birth:pack:" not in text


@pytest.mark.parametrize(("kind","choice","meaning"), [
    ("criticalWeakness","toMagic","50 points"),("lowTolerance","toShock","25 points"),
    ("damage","fromHolyPlaces","lose health"),("forbiddenArmorType","plate","cannot wear"),
    ("forbiddenShieldTypes","kiteShield","cannot equip"),("forbiddenWeaponry","shortBlade","backup"),
    ("phobia","animals","hit penalty"),("inabilityToRegen","","uncertain"),
    ("darknessPoweredMagery","unableToUseMagicInDaylight","cannot cast in daylight"),
    ("lightPoweredMagery","lowerMagicAbilityDarkness","capacity falls in darkness")
])
def test_disadvantage_has_a_player_facing_consequence(kind, choice, meaning):
    from dfo_optimizer.beginner_guide import build_guide
    row = example()
    row["class"]["disadvantages"] = [{"primary":kind, "secondary":choice}]
    text = build_guide(row)["text"]
    assert meaning in text.lower()

def test_postponed_specialization_names_two_conditional_choices_and_keeps_full_reference():
    from dfo_optimizer.beginner_guide import build_guide
    row = example()
    row["progression"] = {"checkpoints":[{"stage":"cap", "level":45,
                           "state":{"mastered":list(range(22,28)), "arcane_path":None}}]}
    row["outcomes"] = [{"stage":"birth", "status":"replayed","scenario":"physical",
                        "minimum_hp":10,"max_hp":50}]
    guide = build_guide(row)
    choices = next(s["items"] for s in guide["sections"] if s["id"]=="specialization")
    text = " ".join(choices)
    assert "Aegis Bolt" in text and "Unravel" in text and "20%" in text
    assert "shield" in text.lower() and "silence" in text.lower() and "separate" in text.lower()
    assert len(choices) <= 4 and "Trickster" not in text
    assert len(guide["specialization_reference"]) == 15
    assert all(len(r["masteries"])==2 for r in guide["specialization_reference"])

def test_opening_checklist_uses_the_certified_cost_for_its_own_birth():
    from dfo_optimizer.beginner_classes import manual_classes
    from dfo_optimizer.beginner_guide import build_guide
    family = manual_classes(roll_seeds=[42,43])[0]
    row = {**example(), "class":family["start"]["class"], "permanent":family["compliance"],
           "progression":{"representative_seed":43}}
    matching = next(b for b in family["compliance"]["births"] if b["seed"]==43)
    tips = next(s for s in build_guide(row)["sections"] if s["id"]=="spells")["items"]
    for spell in matching["affordable_starting_damage_spells"]:
        assert any(f"{spell['name']} costs {spell['cost_sp']} SP" in line for line in tips)
    assert any(f"{matching['sp']} SP" in line for line in tips)

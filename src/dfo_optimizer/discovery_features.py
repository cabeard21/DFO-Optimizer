"""Compile the screening tables once and independently certify the small retained panel."""

from copy import deepcopy
from math import isclose

from .class_document import ATTRIBUTES, parse_document
from .equipment import _career_gate, _catalog, inspect_item
from .progression_birth import _birth_stats, _rolls
from .search_request import MAGERY_KEYS


def discovery_evidence(rules):
    rows = {
        "birth_and_allocation": (
            "src/systems/chargen.js",
            "rollStats, rollSkills, spendPoolLowest, applyCharacter",
        ),
        "skill_placement": ("src/systems/skills.js", "levelUpSkillSum; mastery quotas in advancement.js"),
        "class_traits": ("src/systems/specialAdvantages.js", "parseCareerData"),
        "ordinary_player_saves": (
            "src/systems/spellcast.js",
            "savingChance, spellHasFlags, careerTolerance",
        ),
        "skill_practice": (
            "src/scenes/hostMagic.js",
            "tallyCastSkills; release cost in systems/spellcost.js",
        ),
        "earned_level_vitals": (
            "src/systems/advancement.js",
            "applyLevelUp; online health floor in renownLayer.js",
        ),
    }
    return {
        "profile": "spellcaster_discovery_v1",
        "source_sha": rules["source_sha"],
        "live_verified": False,
        "verification": "Pinned source, reference replay and finite oracle fixtures.",
        "mechanics": {k: {"path": v[0], "symbols": v[1]} for k, v in rows.items()},
        "related_mechanics": [
            r["mechanic_id"]
            for r in rules["mechanics"]
            if r["mechanic_id"].startswith(("equipment.", "gear.", "spell.", "progression."))
        ],
        "admission": "Bounded screening is an exploration policy. Only replayed lifecycle outcomes score performance.",
    }


def screening_equipment(equipment):
    """Class compatibility of identified offers at each stated stage, before purchase."""
    if not isinstance(equipment, dict):
        raise ValueError("equipment must be an object")
    offers = equipment.get("offers", [])
    if not isinstance(offers, list) or any(not isinstance(o, dict) for o in offers):
        raise ValueError("equipment offers must be objects")
    stages = {0}
    by_stage = {}
    all_stages = []
    for offer in offers:
        if offer.get("stages") is not None:
            if not isinstance(offer["stages"], list) or any(
                type(s) is not int or s < 0 for s in offer["stages"]
            ):
                raise ValueError("invalid offer stages")
            for stage in offer["stages"]:
                stages.add(stage)
                if len(stages) > 32:
                    raise ValueError("screen_equipment supports up to 32 stage pools")
        if isinstance(offer.get("acquisition"), dict) and offer["acquisition"].get("obtainable") is True:
            entry = {"instance_id": offer.get("instance_id"), "item": offer.get("item")}
            if offer.get("stages") is None:
                all_stages.append(entry)
            else:
                for stage in set(offer["stages"]):
                    by_stage.setdefault(stage, []).append(entry)
            if len(all_stages) * len(stages) + sum(map(len, by_stage.values())) > 100_000:
                raise ValueError("equipment screening input too large")
    if len(all_stages) * len(stages) + sum(map(len, by_stage.values())) > 100_000:
        raise ValueError("equipment screening input too large")
    return (
        [{"stage": stage, "items": all_stages + by_stage.get(stage, [])} for stage in sorted(stages)]
        if offers
        else []
    )


def freeze_equipment(stages):
    if not isinstance(stages, (tuple, list)) or len(stages) > 32:
        raise ValueError("screen_equipment supports up to 32 stage pools")
    result, seen, count = [], set(), 0
    for row in stages:
        if not isinstance(row, dict) or set(row) != {"stage", "items"}:
            raise ValueError("each equipment pool requires stage and items")
        stage, items = row["stage"], row["items"]
        if type(stage) is not int or stage < 0 or stage in seen or not isinstance(items, list):
            raise ValueError("invalid or duplicate equipment stage")
        count += len(items)
        if count > 100_000:
            raise ValueError("equipment screening input too large")
        frozen, names = [], set()
        for entry in items:
            if not isinstance(entry, dict) or set(entry) != {"instance_id", "item"}:
                raise ValueError("screened equipment requires instance_id and item")
            name, item = entry["instance_id"], entry["item"]
            if not isinstance(name, str) or not name or name in names:
                raise ValueError("screened physical items require distinct names in each stage")
            inspect_item(item, career={})
            frozen.append((name, deepcopy(item)))
            names.add(name)
        result.append((stage, tuple(frozen)))
        seen.add(stage)
    return tuple(sorted(result))


def _item_masks(item):
    # Derive independent single-bit refusal tests from the existing eligibility service.
    cat = _catalog()
    idx = item["templateIndex"]
    template = cat["templates"].get(str(idx))
    material = item.get("material")
    if template is None:
        return None
    if not inspect_item(item, career={})["placements"]:
        return None

    def refused(key, n):
        return sum(1 << i for i in range(n) if _career_gate(cat, template, idx, material, {key: 1 << i}))

    return refused("forbiddenMaterialsFlags", 10), refused("weaponArmorShieldsBitfield", 13)


def packed_features(spec, rules):
    quarters = {key: int(value * 4) for value, key in MAGERY_KEYS.items()}
    table = []
    for trait in rules["traits"]:
        writes = trait["writes"]

        def bits(field):
            return writes.get(field, {}).get("set", 0)

        table.append(
            (
                trait["id"],
                quarters[trait["secondary"]] if trait["primary"] == "increasedMagery" else 0,
                bits("forbiddenMaterialsFlags"),
                bits("weaponArmorShieldsBitfield"),
                bits("spellAbsorptionFlags"),
            )
        )
    pools = [
        [mask for _, item in items if (mask := _item_masks(item)) is not None]
        for _, items in spec.equipment_stages
    ]
    return {
        "exhaustive": spec.objective == "exhaustive" or spec.exact,
        "seed": spec.discovery_seed,
        "stable_examples": spec.objective == "examples",
        "required_masteries": spec.required_masteries,
        "required_skills": spec.required_skills,
        "roll_seeds": spec.roll_seeds,
        "trait_features": table,
        "stage_items": pools,
    }


def mastery_eligible(skills, mastery, quotas):
    required = set(mastery)
    return required <= set(skills) and all(
        len(required.intersection(group)) <= quotas[name]
        for name, group in (("primary", skills[:3]), ("major", skills[3:6]), ("minor", skills[6:]))
    )


def certified_features(doc, race, check, screen, spec, rules):
    from .lifecycle_defenses import player_save_chances

    draft, _ = parse_document(doc, rules)
    law = rules["progression_rules"]
    race_row = next(r for r in rules["races"] if r["id"] == race)
    quotas = law["limits"]["mastery_slots"]
    if not mastery_eligible(draft.skills, spec.required_masteries, quotas) or not set(
        spec.required_skills
    ) <= set(draft.skills):
        raise RuntimeError("native skill requirements differ from mastery replay")
    rolls = []
    for seed in spec.roll_seeds:
        tape = _rolls({"roll_seed": seed})
        attrs, skills = _birth_stats({}, draft, tape)
        rolls.append(
            {
                "seed": seed,
                "sp": int(attrs[1] * check["magicka_multiplier"]),
                "hp": 25 + draft.hp,
                "cast_rate": 1 + (attrs[6] - 50) / 200,
                "attributes": dict(zip(ATTRIBUTES, attrs, strict=True)),
                "ordinary_incoming_save_percent": player_save_chances(
                    race_row["flags"], check["effective_flags"], attrs[2]
                ),
                "attribute_pool": tape["attribute_pool"],
                "destruction": skills[22],
                "starting_level_sum": sum(skills[k] for k in draft.skills[:3])
                + sum(sorted(skills[k] for k in draft.skills[3:6])[-2:])
                + max(skills[k] for k in draft.skills[6:]),
            }
        )
    for native_key, field in (
        ("mean_birth_sp", "sp"),
        ("mean_cast_rate", "cast_rate"),
        ("mean_birth_destruction", "destruction"),
    ):
        if not isclose(screen[native_key], sum(r[field] for r in rolls) / len(rolls), abs_tol=1e-12):
            raise RuntimeError(f"native screening mismatch for {native_key}")
    flags = check["effective_flags"]
    if screen["birth_hp"] != rolls[0]["hp"] or screen["absorption_flag"] != flags["spellAbsorptionFlags"]:
        raise RuntimeError("native HP or absorption differs from class replay")
    equipment = []
    for stage, items in spec.equipment_stages:
        eligible, removed = [], {}
        for name, item in items:
            facts = inspect_item(item, career=flags)
            if facts["placements"]:
                eligible.append(name)
            else:
                removed[name] = facts["reasons"]
        equipment.append({"stage": stage, "eligible": eligible, "excluded": removed})
    if screen["eligible_stage_items"] != [len(s["eligible"]) for s in equipment]:
        raise RuntimeError("native equipment screening differs from physical item replay")
    names = {s["id"]: s["name"] for s in rules["skills"]}
    cast_bits = flags["abilityFlagsAndSpellPointsBitfield"]
    return {
        **screen,
        "race": race_row["name"],
        "paired_births": rolls,
        "magicka_multiplier": check["magicka_multiplier"],
        "advancement_multiplier": check["advancement_multiplier"],
        "casting_restrictions": [
            p["secondary"]
            for p in doc["disadvantages"]
            if p["primary"] in ("lightPoweredMagery", "darknessPoweredMagery")
        ],
        "unrestricted_day_and_night": not bool(cast_bits & 0x3C0),
        "spell_absorption": {0: "none", 1: "inLight", 2: "inDarkness", 4: "general"}.get(
            flags["spellAbsorptionFlags"]
        ),
        "save_elements": ["fire", "frost", "poison", "shock", "magic"],
        "race_defense_flags": race_row["flags"],
        "class_save_flags": {
            k: flags[k]
            for k in ("resistanceFlags", "criticalWeaknessFlags", "lowToleranceFlags", "immunityFlags")
        },
        "equipment_class_compatibility": equipment,
        "required_masteries": [names[k] for k in spec.required_masteries],
        "mastery_slots": quotas,
        "eligible_mastery_groups": doc["skills"],
        "potential_arcane_paths": [
            p["id"]
            for p in law["paths"]
            if p["family"] == "arcane" and mastery_eligible(draft.skills, p["skills"], quotas)
        ],
        "training_skill_multipliers": {names[i]: law["skill_multipliers"][i] for i in draft.skills},
        "conditional_effects": [
            {
                "trait": p["primary"],
                "condition": p.get("secondary"),
                "consequence": {
                    "regenerateHealth": "Periodic healing depends on the magic-round clock and environment.",
                    "damage": "Environmental HP loss depends on exposure and the magic-round clock.",
                    "rapidHealing": "Faster recovery depends on its active condition.",
                    "phobia": "Group-specific attack penalty applies to the physical attack channel.",
                    "inabilityToRegen": "Spell-point recovery for this disadvantage is unverified.",
                }[p["primary"]],
            }
            for p in (*doc["advantages"], *doc["disadvantages"])
            if p["primary"] in ("regenerateHealth", "damage", "rapidHealing", "phobia", "inabilityToRegen")
        ],
        "limits": "Birth uses the common allocation rule. Mastery and path eligibility require earned skills. "
        "Equipment compatibility precedes acquisition, spending and loadout selection.",
    }

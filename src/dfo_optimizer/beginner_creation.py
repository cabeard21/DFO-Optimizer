"""Pinned creation equipment probes and independent replay for the beginner profile."""

import json
import re
from copy import deepcopy
from functools import lru_cache
from hashlib import sha256
from importlib.resources import files

from .beginner_progression import _birth
from .class_document import parse_document
from .classes import disallowed_trait, validate_class_snapshot
from .discovery_features import _item_masks, mastery_eligible
from .equipment import _catalog, inspect_item
from .ruleset import _service_rules

MELEE = frozenset((28, 29, 31, 32))
CREATION_DIGEST = "8eff390c2b1291dc453c296b255cfb18d1bc220169ccca985fdca88601579704"


def _read(name):
    return files("dfo_optimizer").joinpath("data", name).read_bytes().replace(b"\r\n", b"\n")


@lru_cache(maxsize=1)
def creation():
    raw = _read("beginner-creation-v1.json")
    if sha256(raw).hexdigest() != CREATION_DIGEST:
        raise ValueError("Beginner creation mechanics differ from verified source probes")
    facts = json.loads(raw)
    for name, expected in facts["input_sha256"].items():
        if sha256(_read(name)).hexdigest() != expected:
            raise ValueError(f"Beginner creation input differs from qualified fixture: {name}")
    return facts


def exclusion(primary, secondary):
    if primary == "forbiddenArmorType" and secondary == "plate":
        return "plate_forbidden"
    if primary == "lowTolerance" and secondary != "toDisease":
        return "class_save_vulnerability"
    return disallowed_trait(primary, secondary)


def sampling_preference(primary, secondary):
    if primary == "phobia":
        return "beginner preference against group-specific physical attack penalties"
    if primary == "lowTolerance" and secondary == "toDisease":
        return "beginner preference against disease vulnerability outside the scored encounters"
    return None


def _item_fact(item):
    return creation()["items"][f"{item['templateIndex']}/{item.get('material', 'none')}"]


def _equipment_part(items):
    weight, weapons = 0, []
    for item in items:
        fact = _item_fact(item)
        weight += fact["unit_weight"] * item.get("stackCount", 1)
        if fact["skill"] in MELEE:
            masks = _item_masks(item)
            if masks is not None:
                weapons.append((fact["skill"], *masks))
    return weight, weapons


@lru_cache(maxsize=1)
def starter_tables():
    law = _service_rules(None)["progression_rules"]["creation"]
    parts = []
    for steel in (0, 1):
        for chain in (0, 1):
            ids = law["skill_kits"][f"male/{steel}/{chain}"]
            parts.extend(_equipment_part(law["kit_rows"][i]) for i in ids)
            parts.append(_equipment_part(law["common_kit"]["male"]))
    facts = creation()
    kits = facts["kit_sensitivity"]
    unique = []
    for p in kits["parts"]:
        weapons = []
        for index, metal, skill, condition in p["weapons"]:
            masks = _item_masks(
                {
                    "templateIndex": index,
                    "material": metal,
                    "currentCondition": condition,
                }
            )
            if masks is not None:
                weapons.append((skill, *masks))
        unique.append((p["units"], weapons))
    probes = [
        unique[k]
        for decile in (1, 5, 9)
        for gender in ("male", "female")
        for steel in (0, 1)
        for chain in (0, 1)
        for k in kits["variants"][f"{decile}/{gender}/{steel}/{chain}"]
    ]
    spells = facts["starter_damage"]
    if set(spells) != {"22/primary", "22/major"}:
        raise ValueError("Starter damage placement differs from the native school slots")
    return {
        "parts": parts,
        "probes": probes,
        "attack_costs": [
            min(record["costs"][skill] for record in spells["22/" + group])
            for group in ("primary", "major")
            for skill in range(41)
        ],
        "plate_weights": [r["units"] for r in facts["cuirasses"]],
        "capacity": facts["capacity"],
    }


@lru_cache(maxsize=1)
def _catalog_forms():
    """One static item per reviewed wearable template and legal base material encoding."""
    cat = _catalog()
    pools = {"weapons": [], "armor": [], "other": []}
    for key, template in cat["templates"].items():
        group = template["group"]
        if not template["slots"]:
            continue
        if group == "Weapons":
            family, materials = "weapons", range(10)
        elif group == "Armor":
            family, materials = (
                "armor",
                sorted(m for m in cat["armor_materials"].values() if m >= 0),
            )
        else:
            family, materials = "other", (None,)
        for material in materials:
            item = {"templateIndex": int(key)}
            if material is not None:
                item["material"] = material
            mask = _item_masks(item)
            if mask is not None:
                pools[family].append((template["name"], group, int(key), material, mask))
    return pools


@lru_cache(maxsize=1)
def catalog_masks():
    return {k: [mask for _, _, _, _, mask in v] for k, v in _catalog_forms().items()}


@lru_cache(maxsize=256)
def _catalog_counts(materials, gear):
    total = {}
    by_type = {}
    for family, entries in _catalog_forms().items():
        count = 0
        for name, group, index, material, (metal_bits, gear_bits) in entries:
            key = group + "/" + name
            if key in by_type and by_type[key]["template_index"] != index:
                key = f"{key}/{index}"
            row = by_type.setdefault(
                key,
                {
                    "template_index": index,
                    "eligible_materials": [],
                    "excluded_materials": [],
                },
            )
            allowed = not (materials & metal_bits or gear & gear_bits)
            row["eligible_materials" if allowed else "excluded_materials"].append(material)
            count += int(allowed)
        total[family] = {
            "eligible": count,
            "reviewed": len(entries),
            "excluded": len(entries) - count,
        }
    return {
        "by_family": total,
        "by_type": by_type,
        "material_names": {
            "Weapons": {str(p["material"] - 512): p["name"] for p in creation()["cuirasses"]},
            "Armor": {str(v): k for k, v in _catalog()["armor_materials"].items() if v >= 0},
        },
        "scope": "Class eligibility of ordinary unenchanted forms, before actor-specific wear, items, "
        "availability and purchase. Encodings are weapon metal or armor material codes.",
    }


def _pretty(word):
    return re.sub(r"(?<=[a-z])(?=[A-Z])", " ", word).capitalize()


def _display(pick):
    return " ".join(_pretty(v) for v in (pick["primary"], pick.get("secondary")) if v)


def _starting_attacks(born):
    from .progression_practice import release_cost
    from .progression_replay import _cast_price

    attacks = []
    for record in born["spell_records"]:
        cost = release_cost(record, 22)
        if cost is None:
            continue
        price = _cast_price(born, {"skill": 22, **cost})
        if price <= born["sp"]:
            attacks.append(
                {
                    "index": record["index"],
                    "name": record["name"],
                    "cost_sp": price,
                    "range_type": record["rangeType"],
                }
            )
    return attacks


def _gear_births(document, race, seeds, rules):
    facts = creation()
    law = {s["id"]: s["name"] for s in rules["skills"]}
    births, backups, plate, joint = [], [], None, []
    for seed in seeds:
        start = {
            "type": "new_character",
            "profile": "custom",
            "class": document,
            "race_id": race,
            "roll_seed": seed,
        }
        submitted, born = _birth(start, rules)
        career = born["career"]
        if not births:
            plates = [
                p
                for p in facts["cuirasses"]
                if inspect_item({"templateIndex": 102, "material": p["material"]}, career=career)[
                    "placements"
                ]
            ]
            if plates:
                best = min(plates, key=lambda p: p["units"])
                plate = {
                    "name": best["name"] + " Cuirass",
                    "material": best["name"],
                    "weight_kg": best["units"] / 400,
                    "allowed_materials": [p["name"] for p in plates],
                    "assumption": "Lightest equippable plain cuirass, hypothetical carry test only.",
                }
            trained = set(born["primary"] + born["major"] + born["minor"])
            for copy in born["inventory"]:
                item = copy["item"]
                skill = _item_fact(item)["skill"]
                if skill not in MELEE or skill not in trained:
                    continue
                check = inspect_item(item, career=career, gender=born["gender"])
                if check["placements"]:
                    metal = facts["cuirasses"][item["material"]]["name"]
                    backups.append(
                        {
                            "instance_id": copy["instance_id"],
                            "name": check["name"],
                            "skill": law[skill],
                            "skill_id": skill,
                            "material": metal,
                            "template_index": item["templateIndex"],
                        }
                    )
            joint = [
                p["name"]
                for p in plates
                if any(
                    inspect_item(
                        {
                            "templateIndex": w["template_index"],
                            "material": p["material"] - 512,
                        },
                        career=career,
                    )["placements"]
                    for w in backups
                )
            ]
        load = born["gold"] * facts["gold_unit_weight"] + sum(
            _item_fact(c["item"])["unit_weight"] * c["item"].get("stackCount", 1) for c in born["inventory"]
        )
        strength = born["attributes"][0]
        cap = facts["capacity"][strength]
        births.append(
            {
                "seed": seed,
                "hp": born["max_hp"],
                "sp": born["max_sp"],
                "affordable_starting_damage_spells": _starting_attacks(born),
                "owned_starting_spell_names": [s["name"] for s in born["spell_records"]],
                "unresolved_starting_spell_indices": sorted(
                    set(born["known"]) - {s["index"] for s in born["spell_records"]}
                ),
                "strength": strength,
                "attributes": born["attributes"],
                "attribute_allocation": submitted["attribute_allocation"],
                "capacity_kg": cap / 400,
                "kit_weight_kg": load / 400,
                "headroom_kg": (cap - load) / 400 - plate["weight_kg"] if plate else None,
            }
        )
    return births, backups, plate, joint


def _kit_robustness(draft, flags, births, plate):
    if not births:
        return []
    creation_kits = creation()["kit_sensitivity"]
    materials, armor = (
        flags["forbiddenMaterialsFlags"],
        flags["weaponArmorShieldsBitfield"] >> 6,
    )
    luck = draft.attributes[-1]
    tests = []
    for decile in (1, 5, 9):
        upgrade = 1 + 10 * decile <= (luck // 2 if luck < 56 else luck)
        steel = int(bool(materials & 1 or upgrade and not materials & 2))
        chain = int(bool(armor & 1 or upgrade and not armor & 2))
        gold = 5 + (luck - 5) * decile // 10
        if 14 in draft.skills[:6]:
            gold += luck + (3 * luck) * decile // 10
        for gender in ("male", "female"):
            idx = creation_kits["variants"][f"{decile}/{gender}/{steel}/{chain}"]
            parts = [creation_kits["parts"][idx[i]] for i in (*draft.skills[:6], 35)]
            usable = {}
            for part in parts:
                for index, metal, skill, condition in part["weapons"]:
                    state = {
                        "templateIndex": index,
                        "material": metal,
                        "currentCondition": condition,
                    }
                    facts = inspect_item(state, career=flags, gender=gender)
                    if skill in draft.skills and facts["placements"]:
                        usable[index] = facts["name"]
            weight = (gold + sum(p["units"] for p in parts)) / 400
            room = min(b["capacity_kg"] for b in births) - weight - plate["weight_kg"] if plate else None
            tests.append(
                {
                    "gender": gender,
                    "constant_kit_roll": decile / 10,
                    "backup_names": list(usable.values()),
                    "kit_weight_kg": weight,
                    "minimum_headroom_kg": room,
                    "passed": bool(usable and room is not None and room >= 0),
                }
            )
    return tests


def _seeds(values):
    if (
        not isinstance(values, (tuple, list))
        or not 1 <= len(values) <= 128
        or any(type(v) is not int or not 0 <= v < 2**32 for v in values)
        or len(set(values)) != len(values)
    ):
        raise ValueError("roll_seeds must contain 1..128 distinct uint32 values")
    return values


def compliance(document, race_id, rules, seeds):
    check = validate_class_snapshot(document, ruleset=rules, race=race_id, profile="custom")
    failures = [
        *check["errors"],
        *check["create_errors"],
        *(f for f in check["profile_errors"] if f != "difficulty_lock"),
    ]
    if not check["parsed"] or check["race_id"] is None:
        return {
            "passed": False,
            "failures": list(dict.fromkeys(failures or ["unknown_race"])),
        }
    doc = check["normalized"]
    draft, _ = parse_document(doc, rules)
    schools = {r["id"] for r in rules["skills"] if r["magic"]}
    school_names = {r["name"] for r in rules["skills"] if r["magic"]}
    quotas = rules["progression_rules"]["limits"]["mastery_slots"]
    if not mastery_eligible(draft.skills, schools, quotas):
        failures.append("six_mastery_slots")
    traits = {side: [_display(p) for p in doc[side]] for side in ("advantages", "disadvantages")}
    for p in (*doc["advantages"], *doc["disadvantages"]):
        if reason := exclusion(p["primary"], p.get("secondary", "")):
            failures.append(reason)
    births, backups, plate, joint = [], [], None, []
    if check["create_legal"] and not check["skipped"]:
        births, backups, plate, joint = _gear_births(doc, check["race_id"], seeds, rules)
        if not plate:
            failures.append("plate_forbidden")
        if not backups:
            failures.append("no_equippable_trained_starting_melee_weapon")
        if plate and any(b["headroom_kg"] < 0 for b in births):
            failures.append("insufficient_carry")
    race = next(r for r in rules["races"] if r["id"] == check["race_id"])
    sensitivity = _kit_robustness(draft, check["effective_flags"], births, plate)
    if any(not kit["passed"] for kit in sensitivity):
        failures.append("sampled_kit_without_usable_backup_or_carry")
    if any(not b["affordable_starting_damage_spells"] for b in births):
        failures.append("no_affordable_starting_damage_spell")
    return {
        "passed": not failures,
        "failures": list(dict.fromkeys(failures)),
        "race": race["name"],
        "difficulty_points": check["difficulty_points"],
        "advancement_multiplier": check["advancement_multiplier"],
        "magicka_multiplier": check["magicka_multiplier"],
        "effective_flags": check["effective_flags"],
        "mastery_groups": {k: [s for s in names if s in school_names] for k, names in doc["skills"].items()},
        "backup_weapons": backups,
        "plate": plate,
        "births": births,
        "traits": traits,
        "plate_weapon_materials": len(joint),
        "plate_weapon_material_names": joint,
        "restrictions": [_display(p) for p in doc["disadvantages"]],
        "kit_sensitivity": sensitivity,
        "kit_scope": "Independent source-kit probes at constant low, medium and high rolls for both genders. "
        "Does not enumerate mixed random streams, biography gifts or live-game drops.",
        "catalog_eligibility": deepcopy(
            _catalog_counts(
                check["effective_flags"]["forbiddenMaterialsFlags"],
                check["effective_flags"]["weaponArmorShieldsBitfield"],
            )
        ),
        "carry_assumption": "Unbuffed male birth with a common 0.5 kit tape, starting gold and all owned items. "
        "Allocate up to four points to Endurance, then prioritize Intelligence and Speed.",
    }

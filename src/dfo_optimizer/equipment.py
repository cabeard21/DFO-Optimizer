"""Pinned equipment data and equip-window eligibility for one physical copy."""
from copy import deepcopy
from functools import lru_cache
import hashlib
import json
import math

from .ruleset import DATA, SOURCE_SHA
from .equipment_effects import item_modifiers

EQUIPMENT_HASH = "2d8d9a7e5b631682880df93cbdb40c6587927af9123ac8b1646867e5407f0a85"


@lru_cache(maxsize=1)
def _catalog():
    raw = (DATA / "equipment.json").read_bytes()
    if hashlib.sha256(raw.rstrip(b"\r\n")).hexdigest() != EQUIPMENT_HASH:
        raise ValueError("Equipment catalog content hash mismatch")
    data = json.loads(raw)
    if data["source_sha"] != SOURCE_SHA:
        raise ValueError("Equipment catalog source revision mismatch")
    return data


def equipment_catalog():
    """Return a detached copy so imports and searches cannot alter the catalog."""
    return deepcopy(_catalog())


def _integer(value, name, maximum=2**31 - 1):
    if type(value) is not int or not 0 <= value <= maximum:
        raise ValueError(f"{name} must be a nonnegative integer up to {maximum}")
    return value


def career_masks(career):
    if not isinstance(career, dict):
        raise ValueError("Expected career object")
    return (_integer(career.get("weaponArmorShieldsBitfield", 0), "career weapon/armor flags", 2**32-1),
            _integer(career.get("forbiddenMaterialsFlags", 0), "career material flags", 2**32-1))


def _placements(template, catalog, switch):
    slots, hands = catalog["slots"], catalog["hands"]
    right, left = slots["RightHand"], slots["LeftHand"]
    selected = template["switch_hands"] if switch else template["hands"]
    choices = template["slots"]
    if template["group"] == "Weapons":
        if selected == hands["Both"]:
            return [{"slot": right, "mask": (1 << left) | (1 << right)}]
        choices = {hands["LeftOnly"]: [left], hands["RightOnly"]: [right],
                   hands["Either"]: [right, left]}.get(selected, [])
    return [{"slot": slot, "mask": 1 << slot} for slot in choices]


def _career_gate(catalog, template, index, material, career):
    group = template["group"]
    if group not in {"Weapons", "Armor"}:
        return None
    if career is None:
        return "unknown_career"
    flags, metals = career_masks(career)
    if group == "Weapons":
        if flags & 63 & template["weapon_mask"]:
            return "class_restriction"
        if material is None:
            return "unknown_material" if metals else None
        return "class_restriction" if metals & (1 << material) else None
    shield = template["hands"] == catalog["hands"]["LeftOnly"]
    if shield and (flags >> 9) & (1 << (index - 109)):
        return "class_restriction"
    if material is None:
        return "unknown_material" if (metals or (not shield and flags & (7 << 6))) else None
    if not shield and (flags >> 6) & (1 << (material >> 8)):
        return "class_restriction"
    if material >> 8 == 2 and metals & (1 << (material & 255)):
        return "class_restriction"
    return None


def inspect_item(item, *, career, bow_left_hand=False, worn_slot=None, gender=None):
    """Evaluate static legality; a retained restricted copy may only keep its slot."""
    if not isinstance(item, dict) or not isinstance(career, (dict, type(None))):
        raise ValueError("Expected game item and career objects")
    if type(bow_left_hand) is not bool:
        raise ValueError("bow_left_hand must be boolean")
    if worn_slot is not None:
        _integer(worn_slot, "worn_slot", 26)
    index = _integer(item.get("templateIndex"), "templateIndex")
    catalog = _catalog()
    template = catalog["templates"].get(str(index))
    result = {"template_index": index, "name": "", "placements": [], "modifiers": {},
              "reasons": [], "equip_refusals": [], "unsupported": [], "keep_only": False,
              "legendary_id": None, "worn_slot": worn_slot}
    if template is None:
        return {**result, "unsupported": ["unreviewed_template"], "reasons": ["unreviewed_template"]}
    group = template["group"]
    if item.get("group", group) != group:
        return {**result, "reasons": ["template_group_mismatch"]}
    material = item.get("material")
    if material is not None:
        _integer(material, "material")
        legal = range(10) if group == "Weapons" else catalog["armor_materials"].values() if group == "Armor" else None
        if legal is not None and material not in legal:
            return {**result, "reasons": ["invalid_material"]}
    placements = _placements(template, catalog, bow_left_hand)
    unsupported, mods = item_modifiers(item, template, catalog)
    if worn_slot is not None and not any(x["slot"] == worn_slot for x in placements):
        return {**result, "reasons": ["invalid_worn_slot"], "unsupported": unsupported}
    gate = _career_gate(catalog, template, index, material, career)
    condition = item.get("currentCondition")
    if condition is not None and (type(condition) not in (int, float) or abs(condition) > 2**53 - 1
                                  or not math.isfinite(condition)):
        raise ValueError("currentCondition must be finite")
    refusals = [reason for reason in (gate, "broken" if condition is not None and condition < 1 else None) if reason]
    if refusals:
        placements = [p for p in placements if p["slot"] == worn_slot]
    return {**result, "name": str(item.get("name") or template["name"]), "placements": placements,
            "reasons": [] if placements else refusals or ["not_wearable"], "equip_refusals": refusals,
            "unsupported": unsupported, "modifiers": mods, "keep_only": bool(placements and refusals),
            "legendary_id": item.get("legendary") if item.get("rarity") == "legendary" else None}


def gear_catalog_scope(theoretical):
    if theoretical:
        return ("Theoretical domain of source-minted weapons, armor and jewelry plus maximum-band caster lines from the classic magic and rare "
                "equipment pools. Limited to listed templates, representative materials and proc choices.")
    return ("Source-minted weapon, armor and jewelry rolls from a tier 6 pile, level 45, luck 50. "
            "Requires confirmed access to the declared loot profile. Each paired-slot copy needs a separate drop.")


def legal_catalog_items(character, *, theoretical, template_indices=None, access=()):
    """Declare a finite sample/constructed roll domain and identify each physical copy."""
    from .equipment_candidates import catalog_rows
    return catalog_rows(_catalog(), character, theoretical, template_indices, access)

"""Portable immutable-by-value character observations and DFO v1 save import."""
from copy import deepcopy
import hashlib
import json
import re

from .character_files import read_input

CONTAINERS = {"items": "pack", "wagonItems": "wagon", "bagItems": "bag",
              "otherItems": "repair", "furnishings": "furnishings"}
MODIFIERS = ("power_pct", "pierce", "cast_speed_pct", "focus_pct")
BASE_FIELDS = ("level", "destruction_trained", "destruction_mastered", "current_sp",
               "max_sp", "gold", "has_spellbook")
CASTER_FIELDS = {"speed", "destruction_live", *BASE_FIELDS, *MODIFIERS}
_LIMIT = 2**53 - 1   # Largest exact integer in a JS save.


def _obj(value, name):
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be an object")
    return value


def _list(value, name):
    if not isinstance(value, list):
        raise ValueError(f"{name} must be a list")
    return value


def _int(value, name, lower=0, upper=_LIMIT):
    if value is not None and (type(value) is not int or not lower <= value <= upper):
        raise ValueError(f"{name} must be an integer between {lower} and {upper}")
    return value


def _hash(obj):
    try:
        raw = json.dumps(obj, sort_keys=True, allow_nan=False, ensure_ascii=True, separators=(",", ":"))
    except (TypeError, RecursionError, OverflowError) as exc:
        raise ValueError("Character contains invalid JSON") from exc
    return hashlib.sha256(raw.encode()).hexdigest()


def _inventory(save):
    rows = []
    identities = set()
    for field, container in CONTAINERS.items():
        for index, item in enumerate(_list(save.get(field, []), field)):
            _obj(item, "item")
            uid = item.get("uid")
            # Only itemLaw.js ITEM_UID_RE identifies a persistent UID. Other observed
            # references stay on the record; its position identifies this frozen copy.
            if type(uid) is int:
                _int(uid, "legacy numeric uid")
                uid = None
            if uid is not None and (not isinstance(uid, str) or not uid):
                raise ValueError("A game item uid must be a nonempty string")
            key = f"uid:{uid}" if uid and re.fullmatch("[0-9a-f]{16}", uid) else f"save:{container}:{index}"
            if key in identities:
                raise ValueError(f"Duplicate physical item {key}")
            identities.add(key)
            rows.append({"instance_id": key, "container": container, "item": deepcopy(item)})
    return rows


def _spells(save):
    records, unresolved = [], []
    for spell in _list(save.get("spells", []), "spells"):
        if type(spell) is int:
            unresolved.append(spell)
        else:
            records.append(deepcopy(_obj(spell, "saved spell")))
    return {"records": records, "unresolved_indices": unresolved}


def _skill(save):
    skills = save.get("skills")
    if isinstance(skills, list):
        for skill in skills:
            _int(skill, "earned skill", 0, 200)
        trained = skills[22] if len(skills) > 22 else None
    else:
        trained = _int(skills, "earned skill", 0, 200)
    mastered = save.get("masteredSkills")
    if mastered is not None:
        if any(_int(i, "mastery", 0, 34) is None for i in _list(mastered, "masteredSkills")):
            raise ValueError("Invalid mastery")
        if len(set(mastered)) != len(mastered):
            raise ValueError("Duplicate mastered skill")
    mastered_destruction = 22 in mastered if mastered is not None else None
    if trained is None or trained <= 100:
        return trained, mastered_destruction, trained
    if mastered_destruction is not True:
        return trained, mastered_destruction, 100 if mastered_destruction is False else None
    milestones = ((125, 2), (150, 3), (175, 4), (200, 6))
    bonus = sum(v for threshold, v in milestones if threshold <= trained)
    return trained, True, 100 + (trained - 100) // 4 + bonus


def _resources(save):
    resources = {}
    for name in ("health", "maxHealth", "magicka", "maxMagicka"):
        value = save.get(name)
        if value is not None and (type(value) not in (int, float) or not 0 <= value <= _LIMIT):
            raise ValueError(f"Invalid saved resource {name}")
        resources[name] = value
    return resources


def _as_worn(save, pack, base):
    worn = [it for it in pack if it.get("equipSlot") is not None]
    if not worn:
        return dict(base), []
    from .equipment import inspect_item
    from .gear_replay import fold_worn_modifiers
    occupied = 0
    rows, problems = [], []
    for it in worn:
        slot = _int(it["equipSlot"], "worn slot", 0, 26)
        review = inspect_item(it, career=save.get("career"), gender=save.get("gender"), worn_slot=slot)
        problems.extend(f"slot {slot}: {r}" for r in (*review["reasons"], *review["unsupported"]))
        mask = next((p["mask"] for p in review["placements"] if p["slot"] == slot), 0)
        if not mask or mask & occupied:
            problems.append(f"slot {slot}: uncertain equipment placement")
        occupied |= mask
        rows.append((slot, review["legendary_id"], review["modifiers"]))
    if problems:
        return {**base, **dict.fromkeys(("speed", "destruction_live", *MODIFIERS))}, problems
    # Only evaluated fields are projected back. Unknown base inputs stay unknown.
    ctx = {"speed": base["speed"] or 0, "live_skill": base["destruction_live"] or 0, **dict.fromkeys(MODIFIERS, 0)}
    folded, _ = fold_worn_modifiers(((key, mods) for _, key, mods in sorted(rows, key=lambda r: r[0])), ctx)
    return {**base, **{k: folded[k] for k in MODIFIERS},
            "speed": folded["speed"] if base["speed"] is not None else None,
            "destruction_live": folded["live_skill"] if base["destruction_live"] is not None else None}, []


def _caster(save, gear):
    speed = _int(_obj(save.get("stats", {}), "stats").get("speed"), "speed", 0, 255)
    trained, mastered, skill = _skill(save)
    coins = _int(save.get("goldPieces"), "goldPieces")
    cash = coins
    pack = [r["item"] for r in gear if r["container"] == "pack"]
    if coins is not None:
        credit = (_int(it.get("value", 0), "letter value") for it in pack if it.get("templateIndex") == 275)
        cash = coins + sum(v or 0 for v in credit)
    base = {"level": _int(save.get("level"), "level", 1), "speed": min(100, speed) if speed is not None else None,
            "destruction_trained": trained, "destruction_mastered": mastered, "destruction_live": skill,
            "current_sp": None, "max_sp": None, "gold": cash,
            "has_spellbook": any(it.get("group") == "MiscItems" and it.get("templateIndex") == 132
                                 for it in pack) if "items" in save else None,
            **dict.fromkeys(MODIFIERS, 0)}
    # A save has permanent stats and the items, rather than the live equipment fold.
    as_worn, problems = _as_worn(save, pack, base)
    return base, as_worn, problems


def _unknown(save, career):
    effects = _list(save.get("activeEffects", []), "activeEffects")
    result = {f"active_effect:{a.get('kind', 'unidentified')}" for a in effects
              if not _obj(a, "active effect").get("ended")}
    for key in ("arcanePath", "martialPath"):
        if save.get(key):
            result.add(f"{key}:{save[key]}")
    if career is not None:
        flags = _int(career.get("abilityFlagsAndSpellPointsBitfield", 0),
                     "abilityFlagsAndSpellPointsBitfield", 0, 2**32-1)
        if flags and flags & 0x3C0:
            result.add("environmental_magery")
    return sorted(result)


def _save_snapshot(save, card):
    if type(save.get("v")) is not int or save["v"] != 1:
        raise ValueError("Unsupported v1 SaveData version")
    if card.get("save_version") is not None and card["save_version"] != save["v"]:
        raise ValueError("Slot card and save versions disagree")
    if card.get("character_id") is not None and save.get("characterId") not in (None, card["character_id"]):
        raise ValueError("Slot card and save character IDs disagree")
    career = save.get("career")
    if career is not None:
        _obj(career, "career")
    gear = _inventory(save)
    base, caster, problems = _caster(save, gear)
    # Keep absent fields absent. Several pre-progression portable exports omitted
    # these counters even when the game had already banked a full skill point.
    from .progression_inputs import capture_progression
    return {
        "kind": "character", "schema_version": 2, "caster": caster,
        "progression": capture_progression(save),
        "gear": {"items": gear, "base_caster": base, "career": deepcopy(career),
                 "race_id": _int(save.get("raceId"), "raceId"), "gender": save.get("gender")},
        "observations": {
            "character_id": save.get("characterId"), "name": save.get("name"), "stats": deepcopy(save.get("stats")),
            "trained_skills": deepcopy(save.get("skills")), "mastered_skills": deepcopy(save.get("masteredSkills")),
            "resources": _resources(save), "spells": _spells(save), "gold_pieces": save.get("goldPieces"),
            "active_effects": deepcopy(save.get("activeEffects", [])),
            "arcane_path": save.get("arcanePath"), "martial_path": save.get("martialPath"),
            "worn_equipment_issues": problems,
        },
        "provenance": {"format": "dfo_save_v1", "observation_sha256": _hash(save), **card,
                       "realm_copy": bool(save.get("realmCopy")),
                       "resource_scope": "saved_without_online_bonuses",
                       "base_caster_scope": "solo_online_snapshot_without_equipment_or_temporary_effects"},
        "unknown_mechanics": _unknown(save, career), "live_observations": {},
    }


def _validate_caster(caster):
    _obj(caster, "caster")
    unknown = set(caster) - CASTER_FIELDS
    if unknown:
        raise ValueError(f"Unknown caster fields: {sorted(unknown)}")
    for field, value in caster.items():
        if value is None:
            continue
        if field in ("has_spellbook", "destruction_mastered"):
            if type(value) is not bool:
                raise ValueError(f"{field} must be boolean")
        else:
            _int(value, field, -_LIMIT if field in MODIFIERS else int(field == "level"))
    if caster.get("current_sp") is not None and caster.get("max_sp") is not None:
        if caster["current_sp"] > caster["max_sp"]:
            raise ValueError("Observed current SP exceeds maximum SP")


def _apply_observations(result):
    live = _obj(result.get("live_observations", {}), "live_observations")
    for key, observation in live.items():
        _obj(observation, "live observation")
        if key not in CASTER_FIELDS and key != "max_fatigue":
            raise ValueError(f"Unsupported live observation {key!r}")
        if not isinstance(observation.get("source"), str) or not observation["source"].strip():
            raise ValueError("Every live observation requires its source")
        if _int(observation.get("observed_at_ms"), "observed_at_ms") is None or "value" not in observation:
            raise ValueError("Live observations require a timestamp and value")
        if key == "max_fatigue":
            _int(observation["value"], "max_fatigue")
            continue
        result["caster"][key] = observation["value"]
        # Live stat and skill modifiers can already include worn gear.
        if key in ("current_sp", "gold", "has_spellbook") and "base_caster" in result["gear"]:
            result["gear"]["base_caster"][key] = observation["value"]


def _portable(document):
    if type(document.get("schema_version")) is not int or document["schema_version"] not in (1, 2):
        raise ValueError("Unsupported portable character schema")
    result = deepcopy(document)
    supplied = result.pop("snapshot_hash", None)
    if supplied is not None and supplied != _hash(result):
        raise ValueError("Character snapshot hash mismatch")
    if result["schema_version"] == 2:
        from .progression_inputs import validate_capture
        validate_capture(result.get("progression"))
    _obj(result.setdefault("observations", {}), "observations")
    _obj(result.setdefault("provenance", {"format": "portable"}), "provenance")
    gear = _obj(result.setdefault("gear", {}), "gear")
    ids = set()
    for row in _list(gear.get("items", []), "items"):
        _obj(row, "item copy")
        identity = row.get("instance_id")
        if not isinstance(identity, str) or not identity or identity in ids:
            raise ValueError("Expected a unique physical item ID")
        ids.add(identity)
        if row.get("container") not in CONTAINERS.values():
            raise ValueError("Unknown inventory container")
        _obj(row.get("item"), "item")
    if any(not isinstance(x, str) for x in _list(result.get("unknown_mechanics", []), "unknown_mechanics")):
        raise ValueError("Invalid unknown mechanics")
    _obj(result.get("caster"), "caster")
    if "base_caster" in gear:
        _obj(gear["base_caster"], "base_caster")
    _apply_observations(result)
    _validate_caster(result["caster"])
    if "base_caster" in gear:
        _validate_caster(gear["base_caster"])
    return {**result, "snapshot_hash": _hash(result)}


def normalize_character(document, *, card=None):
    """Detach and fingerprint a saved or manually observed character, preserving unknown values."""
    value = _obj(document, "character")
    if value.get("kind") == "character":
        return _portable(value)
    return _portable(_save_snapshot(value, card or {}))


def apply_request_observations(request):
    """Create a new attributed character for this request and keep the source snapshot intact."""
    if not isinstance(request, dict) or "live_observations" not in request:
        return request
    if "character" not in request or "caster" in request:
        raise ValueError("A live observation overlay requires an imported character")
    old = normalize_character(request["character"])
    observations = _obj(request["live_observations"], "live_observations")
    changed = {k: v for k, v in old.items() if k != "snapshot_hash"}
    changed["provenance"] = {**old["provenance"], "parent_snapshot_hash": old["snapshot_hash"]}
    changed["live_observations"] = {**old.get("live_observations", {}), **observations}
    result = {k: v for k, v in request.items() if k != "live_observations"}
    return {**result, "character": normalize_character(changed)}


def import_character(path, *, slot=None):
    data, card = read_input(path, slot)
    return normalize_character(data, card=card)


def list_character_slots(path):
    return read_input(path, list_only=True)

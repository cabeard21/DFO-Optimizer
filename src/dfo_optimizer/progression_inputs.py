"""Freeze the progression state at an online save load or a legal character birth."""
from copy import deepcopy
import math
import re

from .character import _hash, normalize_character
from .class_document import ATTRIBUTES

# Preserve source spelling inside this capture so a new reader can distinguish
# a null game value from a field the portable format never exported.
SAVE_FIELDS = {"classicMinutes", "lastSkillCheckTime", "timeOfLastSkillTraining", "restNightAt",
               "reflexes", "startingLevelUpSkillSum", "currentLevelUpSkillSum", "readyToLevelUp",
               "pendingLevel", "pendingBonusPool", "chargenDone", "levelingSystem", "levelProgress",
               "skillUses", "skillUseFrac", "skillProgress", "fatigue", "arcanePath", "martialPath",
               "masteredSkills", "bankAccounts", "spells"}
LIMIT = 2**53 - 1


def capture_progression(save):
    return {"version": 1, "fields": {k: deepcopy(save[k]) for k in SAVE_FIELDS if k in save},
            "boundary": "after_save_load"}


def validate_capture(capture):
    if (not isinstance(capture, dict) or type(capture.get("version")) is not int or capture["version"] != 1
            or capture.get("boundary") != "after_save_load" or not isinstance(capture.get("fields"), dict)
            or not capture["fields"].keys() <= SAVE_FIELDS):
        raise ValueError("Invalid versioned progression capture")


def number(value, key, lo=0, hi=LIMIT, *, integer=True):
    if value is None:
        return None
    if (type(value) not in ((int,) if integer else (int, float))
            or not lo <= value <= hi or not math.isfinite(value)):
        raise ValueError(f"Invalid progression {key}")
    return value


def vector(value, key, count, lo=0, hi=LIMIT, *, integer=True, partial=False):
    if value is None:
        return None
    if not isinstance(value, list) or len(value) > count or (not partial and len(value) != count):
        raise ValueError(f"Invalid progression {key} length")
    values = [number(x, key, lo, hi, integer=integer) for x in value]
    if len(values) != count or None in values:
        if partial:
            return None
        raise ValueError(f"Incomplete progression {key}")
    return values


def _array(fields, key, name, *, fractional=False):
    if key not in fields:
        return None
    value = fields[key]
    if value is None and key in ("skillUseFrac", "skillProgress"):
        return [0.] * 35  # The save writes null for the game's lazy zero-filled banks.
    values = vector(value, name, 35, integer=not fractional, partial=True)
    if key == "skillUseFrac" and values is not None and any(v >= 1 for v in values):
        raise ValueError("Invalid progression fractions")
    return values


def _supplied(additions):
    if isinstance(additions, dict):
        for key, fact in additions.items():
            if not isinstance(fact, dict) or not isinstance(fact.get("record"), dict):
                raise ValueError("Invalid supplemental spell observation")
            row = fact["record"]
            if (str(row.get("index")) != key or _hash(row) != fact.get("record_sha256")
                    or not isinstance(fact.get("source_sha256"), str)
                    or not re.fullmatch("[0-9a-f]{64}", fact["source_sha256"])):
                raise ValueError("Supplemental record index or hash mismatch")
            yield row, {k: v for k,v in fact.items() if k != "record"}
    else:
        for row in additions:
            yield row, {"source_format":"supplied_record","record_sha256":_hash(row)}


def _known(data, additions):
    if not isinstance(additions, (dict,list)) or not isinstance(data, dict):
        raise ValueError("Spell records must be a list of game records")
    rows = data.get("records", [])
    indices = data.get("unresolved_indices", [])
    if not isinstance(rows, list) or not isinstance(indices, list):
        raise ValueError("Invalid known spell observations")
    known = set()
    records = {}
    for i in indices:
        if number(i, "spell index", -2**31, 2**31-1) is None:
            raise ValueError("Invalid spell index")
        known.add(i)
    for record in rows:
        if not isinstance(record, dict):
            raise ValueError("Invalid owned spell record")
        i = number(record.get("index"), "spell index", -2**31, 2**31-1)
        if i is None:
            continue
        if i in records and record != records[i]:
            raise ValueError("Conflicting owned spell records")
        known.add(i)
        records[i] = deepcopy(record)
    evidence = {}
    for record, provenance in _supplied(additions):
        if not isinstance(record, dict) or type(record.get("index")) is not int:
            raise ValueError("Supplemental spell records require an integer index")
        i = record["index"]
        if i not in known:
            continue
        if i in records and record != records[i]:
            raise ValueError("Supplemental record conflicts with owned spell")
        records[i] = deepcopy(record)
        evidence[str(i)] = provenance
    ordered = [records[i] for i in sorted(records)]
    return {"known": sorted(known), "spell_records": ordered, "unresolved_indices": sorted(known - records.keys()),
            "spell_records_hash": _hash(ordered), "spell_record_evidence": evidence}


def _bank_gold(accounts):
    if accounts is None:
        return None
    if not isinstance(accounts, list):
        raise ValueError("Invalid bank accounts")
    if any(row is not None and not isinstance(row, dict) for row in accounts):
        raise ValueError("Invalid bank account")
    # world.js calls foldEmpireAccounts on the save before restorePlayer pads
    # the table. A pre-Empire short table therefore has no payable Empire gold.
    if len(accounts) <= 17 or accounts[17] is None:
        return 0
    total = sum(number(row.get("accountGold"), "bank", -LIMIT) or 0 for row in accounts if row)
    return number(max(0, total), "bank")


def _current(start):
    snap = normalize_character(start.get("character"))
    obs, gear, caster = snap["observations"], snap["gear"], snap["caster"]
    career = gear.get("career")
    if career is not None and not isinstance(career, dict):
        raise ValueError("Invalid portable progression career")
    career = career or {}
    documented = snap.get("schema_version") == 2
    fields = snap.get("progression", {}).get("fields", {}) if documented else {}
    if fields.get("levelingSystem") not in (None, "classic"):
        raise ValueError("Online progression requires the converted classic character")
    chargen_done = fields.get("chargenDone")
    if chargen_done is not None and type(chargen_done) is not bool:
        raise ValueError("Invalid chargenDone flag")
    stats = obs.get("stats")
    if stats is not None and not isinstance(stats, dict):
        raise ValueError("Invalid portable progression attributes")
    attrs = [stats.get(k) for k in ATTRIBUTES] if isinstance(stats, dict) else None
    group_ids = {k: vector(career.get(k+"Skills"), k, n, hi=34, partial=True)
                 for k, n in (("primary", 3), ("major", 3), ("minor", 6))}
    selected = [s for ids in group_ids.values() if ids for s in ids]
    if len(set(selected)) != len(selected):
        raise ValueError("Duplicate progression career skills")
    mastered = obs.get("mastered_skills")
    if mastered is not None:
        if not isinstance(mastered, list) or len(mastered) > 6:
            raise ValueError("Invalid mastered skill slots")
        if any(number(i, "mastery", 0, 34) is None for i in mastered) or len(set(mastered)) != len(mastered):
            raise ValueError("Invalid mastered skill IDs")
        for k, quota in (("primary", 3), ("major", 2), ("minor", 1)):
            if group_ids[k] and len(set(group_ids[k]) & set(mastered)) > quota:
                raise ValueError("Exceeded mastery quota")
        if all(group_ids.values()) and set(mastered) - set(selected):
            raise ValueError("Miscellaneous skills cannot be mastered")
    available = number(caster.get("gold"), "gold")
    bank = _bank_gold(fields.get("bankAccounts"))
    ready = fields.get("readyToLevelUp")
    if ready is not None and type(ready) is not bool:
        raise ValueError("Invalid pending level latch")
    if ready is False:
        pending_level = pending_pool = -1
    elif ready is True:
        pending_level = number(fields.get("pendingLevel"), "pending level", 1)
        pending_pool = number(fields.get("pendingBonusPool"), "pending pool", 0, 30)
        if pending_pool is None:
            pending_pool = -1  # sheet has not opened, draw at the level-up door
    else:
        pending_level = pending_pool = None
    paths = {}
    for public, field in (("arcane_path", "arcanePath"), ("martial_path", "martialPath")):
        path = obs.get(public)
        if path is not None and (not isinstance(path, str) or not path):
            raise ValueError("Invalid specialization ID")
        # Older source builds can restore a path from the career mirror or a signature.
        paths[public] = path if path is not None else (-1 if field in fields else None)
    minutes = number(fields.get("classicMinutes"), "clock", integer=False)
    if minutes is not None and minutes >= 2**31:
        minutes = None  # restorePlayer substitutes the world's clock, unknown offline.
    fatigue = number(fields.get("fatigue"), "fatigue", integer=False)
    resources = obs.get("resources", {})
    if not isinstance(resources, dict):
        raise ValueError("Invalid portable progression resources")
    trained = obs.get("trained_skills")
    if type(trained) is int:
        number(trained, "legacy destruction", 0, 200)
        trained = None  # Older readers could capture only the Destruction value.
    spells = _known(obs.get("spells", {}), start.get("spell_records", []))
    if "spells" not in (fields if documented else obs):
        spells["known"] = None
    state = {**group_ids, **paths, "skills": vector(trained, "skills", 35, hi=200, partial=True),
            "attributes": vector(attrs, "attributes", 8, hi=255, partial=True), "mastered": deepcopy(mastered),
            "uses": _array(fields, "skillUses", "uses"), "fractions": _array(fields, "skillUseFrac", "fractions", fractional=True),
            "progress": _array(fields, "skillProgress", "progress", fractional=True),
            "level": number(caster.get("level"), "level", 1), "minutes": math.floor(minutes) if minutes is not None else None,
            "last_check": number(fields.get("lastSkillCheckTime"), "last check"),
            "last_training": number(fields.get("timeOfLastSkillTraining"), "last training"),
            "last_rest": number(fields.get("restNightAt"), "last rest") if fields.get("restNightAt") is not None else (-1 if documented else None),
            "reflexes": number(fields.get("reflexes"), "reflexes", 0, 4), "pending_level": pending_level, "pending_pool": pending_pool,
            "starting_sum": number(fields.get("startingLevelUpSkillSum"), "starting sum"),
            "current_sum": number(fields.get("currentLevelUpSkillSum"), "highest sum"),
            "advancement_multiplier": number(career.get("advancementMultiplier"), "advancement", 0.01, 10, integer=False),
            "gold": available, "bank_gold": bank, "observed_fatigue": fatigue,
            "fatigue": math.floor(fatigue) if fatigue is not None else None,
            "max_fatigue": snap.get("live_observations", {}).get("max_fatigue", {}).get("value"),
            "hp_setting": number(career.get("hitPointsPerLevel"), "HP setting", 1, 255),
            "hp": resources.get("health"), "max_hp": resources.get("maxHealth"), "sp": caster.get("current_sp"),
            "max_sp": caster.get("max_sp"), "has_spellbook": caster.get("has_spellbook"),
            "race_id": gear.get("race_id"), "gender": gear.get("gender"), "inventory": deepcopy(gear.get("items", [])),
            "career": deepcopy(gear.get("career")), "snapshot_hash": snap["snapshot_hash"],
            "real_ms": 0, "boundary": "after_save_load", "chargen_done": chargen_done, **spells}
    # levelCap.js preserves genuinely grandfathered levels. Keep the observations
    # intact while suppressing actions that require a value outside native scope.
    outside = {k: state[k] for k, hi in (("level", 45), ("pending_level", 45), ("starting_sum", 840),
                                          ("current_sum", 840)) if state[k] is not None and state[k] > hi}
    if state["attributes"] is not None and max(state["attributes"]) > 100:
        outside["attributes"] = state["attributes"]
    return {**state, **dict.fromkeys(outside), "unsupported_legacy_values": outside}


def resolve_start(start, *, rules=None):
    """Resolve a request start and list its missing observations by canonical name."""
    if not isinstance(start, dict):
        raise ValueError("A progression start must be an object")
    if start.get("type") == "current_character":
        state = _current(start)
    elif start.get("type") == "new_character":
        from .progression_birth import birth_state
        state = birth_state(start, rules)
    else:
        raise ValueError("Unknown progression start type")
    return state, sorted(k for k, v in state.items() if v is None)


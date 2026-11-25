"""Snapshot v1 custom-class document reader and writer (English skill names)."""

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
import json
import unicodedata


FORMAT = "daggerfall-enhanced/custom-class"
GROUPS = (("primary", 3), ("major", 3), ("minor", 6))
ATTRIBUTES = ("strength", "intelligence", "willpower", "agility",
              "endurance", "personality", "speed", "luck")
REPUTATIONS = ("merchants", "peasants", "scholars", "nobility", "underworld")
SIDES = (("advantages", "advantage"), ("disadvantages", "disadvantage"))
# WhiteSpace and LineTerminator code points consumed by ECMAScript String.trim.
JS_SPACE = "\u0009\u000a\u000b\u000c\u000d\u0020\u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u2028\u2029\u202f\u205f\u3000\ufeff"


@dataclass(frozen=True)
class ClassDraft:
    name: str
    hp: int
    skills: tuple[int | None, ...]
    attributes: tuple[int, ...]
    reputations: tuple[int, ...]
    advantages: tuple[int, ...]
    disadvantages: tuple[int, ...]


def _mapping(value):
    return value if isinstance(value, Mapping) else {}


def _integer(value):
    return type(value) is int or (type(value) is float and value.is_integer())


def _in_range(value, label, minimum, maximum):
    if not _integer(value) or not minimum <= value <= maximum:
        raise ValueError(f"{label} must be a whole number from {minimum} to {maximum}")
    return int(value)


def _imported_name(value):
    if not isinstance(value, str):
        return ""
    clean = "".join(c for c in value if unicodedata.category(c) not in ("Cc", "Cf"))
    # ChargenFlow.customImport uses String.slice(0, 31), measured in UTF-16 units.
    units = clean.strip(JS_SPACE).encode("utf-16-le", "surrogatepass")
    return units[:62].decode("utf-16-le", "surrogatepass")


def _read_skills(value, catalog):
    names = {s["name"].lower(): s["id"] for s in catalog}
    valid_ids = set(names.values())
    picked = []
    for group, count in GROUPS:
        row = _mapping(value).get(group)
        if not isinstance(row, list) or len(row) != count:
            raise ValueError(f"expected {count} {group} skills")
        for slot in row:
            if slot is None:
                picked.append(None)
            elif _integer(slot) and slot in valid_ids:
                picked.append(int(slot))
            elif isinstance(slot, str) and slot.strip(JS_SPACE).lower() in names:
                picked.append(names[slot.strip(JS_SPACE).lower()])
            else:
                raise ValueError(f"unknown skill in {group}")
    chosen = [s for s in picked if s is not None]
    if len(set(chosen)) != len(chosen):
        raise ValueError("a skill may only be selected once")
    return tuple(picked)


def _read_traits(doc, rules):
    catalog = {(t["side"], t["primary"], t["secondary"]): t for t in rules["traits"]}
    accepted_ids = set()
    skipped = []
    sides = []
    for field, side in SIDES:
        picks = []
        unique_groups = set()
        entries = doc.get(field)
        for entry in entries if isinstance(entries, list) else ():
            pick = _mapping(entry)
            primary = pick.get("primary")
            secondary = pick.get("secondary")
            key = secondary if isinstance(secondary, str) else ""
            trait = catalog.get((side, primary, key)) if isinstance(primary, str) else None
            if (trait is None or len(picks) >= rules["limits"]["max_picks"]
                    or primary in unique_groups or trait["id"] in accepted_ids
                    or not accepted_ids.isdisjoint(trait["conflicts"])):
                skipped.append(deepcopy(entry))
                continue
            accepted_ids.add(trait["id"])
            picks.append(trait["id"])
            if trait["only_one"]:
                unique_groups.add(primary)
        sides.append(tuple(picks))
    return sides[0], sides[1], skipped


def _reject_constant(value):
    raise ValueError(f"{value} is invalid JSON")


def parse_document(document, rules):
    if isinstance(document, str):
        document = json.loads(document, parse_constant=_reject_constant)
    doc = _mapping(document)
    if doc.get("format") != FORMAT:
        raise ValueError(f"expected class format {FORMAT}")
    version = doc.get("version")
    if not _integer(version) or version != 1:
        raise ValueError("supported class file version is 1")
    limits = rules["limits"]
    hp = _in_range(doc.get("hitPointsPerLevel"), "HP setting", limits["hp_min"], limits["hp_max"])
    skills = _read_skills(doc.get("skills"), rules["skills"])
    stats = _mapping(doc.get("attributes"))
    attributes = tuple(_in_range(stats.get(k), k, limits["stat_min"], limits["stat_max"])
                       for k in ATTRIBUTES)
    rep = _mapping(doc.get("reputations"))
    rep_max = limits["rep_max"]
    reputations = tuple(_in_range(rep[k] if rep.get(k) is not None else 0, k, -rep_max, rep_max)
                        for k in REPUTATIONS)
    advantages, disadvantages, skipped = _read_traits(doc, rules)
    draft = ClassDraft(_imported_name(doc.get("name")), hp, skills, attributes, reputations,
                       advantages, disadvantages)
    return draft, skipped


def export_document(draft, rules):
    names = {skill["id"]: skill["name"] for skill in rules["skills"]}
    traits = {trait["id"]: trait for trait in rules["traits"]}
    skill_names = iter(names.get(i) for i in draft.skills)
    grouped = {group: [next(skill_names) for _ in range(size)] for group, size in GROUPS}

    def picks(ids):
        return [{"primary": traits[i]["primary"],
                 **({"secondary": traits[i]["secondary"]} if traits[i]["secondary"] else {})}
                for i in ids]

    return {"format": FORMAT, "version": 1, "name": draft.name, "hitPointsPerLevel": draft.hp,
            "skills": grouped, "attributes": dict(zip(ATTRIBUTES, draft.attributes, strict=True)),
            "advantages": picks(draft.advantages), "disadvantages": picks(draft.disadvantages),
            "reputations": dict(zip(REPUTATIONS, draft.reputations, strict=True))}

"""Turn one recommended game document and its replayed development route into a player checklist."""
from functools import lru_cache
import re

from .class_document import ATTRIBUTES
from .ruleset import load_ruleset


@lru_cache(maxsize=1)
def _skill_names():
    return {row["id"]:row["name"] for row in load_ruleset()["skills"]}


def _label(value):
    return re.sub(r"(?<=[a-z])(?=[A-Z])", " ", str(value)).replace("_", " ").strip().capitalize()


def _trait(pick):
    return " · ".join(_label(s) for s in (pick["primary"], pick.get("secondary")) if s)


def _consequence(pick):
    kind, detail = pick["primary"], pick.get("secondary", "")
    words = _label(detail).lower()
    if kind == "forbiddenMaterial":
        return f"You cannot equip items made of {words}. Check the material before buying an upgrade."
    if kind == "forbiddenArmorType":
        return f"You cannot wear {words} armor."
    if kind == "forbiddenShieldTypes":
        return f"You cannot equip the {words} shield type."
    if kind == "forbiddenWeaponry":
        return f"The {words} weapon category is restricted. Use a permitted backup weapon."
    if kind in ("criticalWeakness", "lowTolerance"):
        effect = words.removeprefix("to ")
        return f"Your class lowers saves against {effect} by {50 if kind == 'criticalWeakness' else 25} points before the final save calculation."
    if kind == "phobia":
        return f"Physical attacks against the {words} group take a hit penalty."
    if kind == "inabilityToRegen":
        return "Spell-point recovery is uncertain under this disadvantage. Reliable free recovery has not been established."
    if kind == "damage":
        return f"You can lose health {words}. Exposure and the passive magic-round clock govern damage."
    if kind in ("darknessPoweredMagery", "lightPoweredMagery"):
        light = "daylight" if kind == "darknessPoweredMagery" else "darkness"
        return f"You cannot cast in {light}." if detail.startswith("unable") else f"Your spell-point capacity falls in {light}."
    return "Its practical effect is unreported for this scenario."


def _names(values):
    return [str(v.get("name") or v.get("id")) if isinstance(v, dict) else str(v) for v in values]


def _choices(title, names, unavailable):
    return title + ", ".join(names) + "." if names else unavailable


def _checkpoints(progression):
    rolls = progression.get("rolls", [])
    representative = next((r for r in rolls if r["seed"] == progression.get("representative_seed")), rolls[0] if rolls else {})
    stages = representative.get("stages", progression.get("checkpoints", []))
    return {s["stage"]:s for s in stages}


def _birth_bonus(policy, skills):
    order = [_label(v) for v in policy.get("birth_attribute_order", [])]
    birth_rule = policy.get("birth")
    birth_tips = [birth_rule or _choices("Spend your available birth bonus in this order. ", order,
                                        "Birth bonus allocation is unreported for this family.")]
    skill_bonus = policy.get("birth_skill_allocation")
    if isinstance(skill_bonus, str):
        birth_tips.append(skill_bonus)
    allocation = policy.get("birth_allocation")
    if isinstance(allocation, list) and len(allocation) == len(ATTRIBUTES):
        earned = [f"{_label(k)} +{v}" for k,v in zip(ATTRIBUTES, allocation, strict=True) if v]
        if earned:
            birth_tips.append("The replay used " + ", ".join(earned) + ".")
    for group, bonuses in policy.get("realized_birth_skill_allocation", {}).items():
        invested = [f"{name} +{n}" for name,n in zip(skills[group], bonuses, strict=True) if n]
        if invested:
            birth_tips.append(f"The {group} bonus on this example roll went to " + ", ".join(invested) + ".")
    return birth_tips


def _opening_spells(policy, birth, certified):
    spells = _names(birth.get("spells", []))
    if policy.get("starter_spells"):
        starter_names = policy["starter_spells"]
    else:
        starter_names = spells
    spell_tips = [_choices("Your starting spellbook contains ", starter_names,
                           "The replay did not report a funded opening spell.")]
    if certified:
        spell_tips.append(f"The example birth has {certified['sp']} SP available before the opening fight.")
        for spell in certified.get("affordable_starting_damage_spells", []):
            spell_tips.append(f"{spell['name']} costs {spell['cost_sp']} SP per cast on this roll.")
    for spell in birth.get("spells", []):
        if not isinstance(spell, dict):
            continue
        effects = {e["effect_id"] for e in spell.get("effects", [])}
        name = spell.get("name") or spell.get("id")
        if "10,8" in effects:
            spell_tips.append(f"Use {name} to restore health. The scenario policy checks healing below 60% health.")
        if "35,255" in effects:
            spell_tips.append(f"Cast {name} when your damage shield is depleted and you have the spell points.")
        if effects.intersection({"4,0", "5,255"}):
            reach = {1:"within touch range", 2:"at range", 3:"among nearby targets", 4:"at a group in range"}.get(spell.get("range_type"),"when a target is in reach")
            spell_tips.append(f"Use {name} {reach} for offense.")
    return spell_tips


def _equipment(permanent, birth, mid):
    gear = birth.get("loadout_details") or birth.get("loadout") or []
    if isinstance(gear, dict):
        inventory = {r["instance_id"]:r["item"].get("name", r["instance_id"]) for r in birth.get("inventory", [])}
        gear = [f"{_label(slot)} — {inventory.get(v, v)}" for slot,v in gear.items()]
    elif birth.get("loadout_details"):
        gear = [f"{_label(it['slot'])} — {it['name']}" for it in gear]
    equipment = [_choices("Equip the starting copies used in the replay. ", _names(gear),
                          "Opening loadout is unreported. Keep your owned starting equipment until a replacement is available.")]
    backups = [f"{v.get('material','')} {v['name']} ({v['skill']})".strip() for v in permanent.get("backup_weapons", [])]
    if backups:
        equipment.append("When spell points run low, use a proficient backup from the starting kit. The checked copies include " + ", ".join(backups) + ".")
    plate = permanent.get("plate")
    if plate:
        equipment.append(f"The carry test uses a hypothetical {plate['name']}. It weighs {plate['weight_kg']:g} kg.")
        if permanent.get("births"):
            headroom = min(b["headroom_kg"] for b in permanent["births"])
            equipment.append(f"The starting kit plus that cuirass leaves at least {headroom:.1f} kg free across the tested births.")
    if mid and mid.get("acquisitions"):
        equipment.extend(f"The level-{mid['level']} replay acquired {a['name']} for {a['gold']} gold under the declared offer."
                         for a in mid["acquisitions"] if a.get("kind") == "gear")
    return equipment


def _first_levels(policy, mid, refined=False):
    levels = [_choices("At level-up, allocate attributes in this order. ",
                       [_label(k) for k in policy.get("level_attribute_order", [])],
                       "Level-up allocation is unreported for this family.")]
    priorities = policy.get("mastery_priority", [])
    if priorities:
        levels.append("Practice the skills on the route, starting with " + ", ".join(str(p) for p in priorities[:3]) + ".")
    first = policy.get("first_earned_level")
    if first:
        gains = [f"{_label(k)} +{v}" for k,v in zip(ATTRIBUTES, first["attribute_gains"], strict=True) if v]
        levels.append(f"At the first earned level ({first['level']}), the replay gained " + ", ".join(gains) + ".")
    if refined:
        return [*levels,
                "Use your starting spells and backup weapon first. At a Spell Maker, look for an affordable ranged attack and healing or shielding you can use regularly.",
                "Use the tested recipes in the workbench when you have access and enough gold. Upgrade the backup weapon and armor as compatible pieces become available."]
    if mid:
        levels.append(f"The next encounter checkpoint was level {mid['level']}.")
        if "minutes" in mid.get("effort", {}):
            levels.append(f"On this roll the checkpoint required {mid['effort']['minutes']:,} in-game minutes under the supplied opportunities.")
    if policy.get("spell_access"):
        levels.append(policy["spell_access"])
    training = policy.get("training")
    if isinstance(training, str):
        assumptions = policy.get("assumptions") or {}
        if assumptions.get("cadence_ms"):
            levels.append(f"The replay assumes one qualifying action every {assumptions['cadence_ms']/1000:g} seconds and access to full bed rests.")
    return levels


def _masteries(permanent, policy, mastered):
    planned = [_skill_names().get(v, str(v)) for v in policy.get("mastery_priority", [])]
    masteries = [_choices("Prioritize mastery in this order. ", planned,
                          "No mastery order was reported. Check the skill threshold and group quota before committing.")]
    if mastered:
        masteries.append("Mastered at the final checkpoint — " + ", ".join(_skill_names().get(v, str(v)) for v in mastered) + ".")
    groups = permanent.get("mastery_groups") or {}
    for group, names in groups.items():
        if names:
            masteries.append(f"{_label(group)} school choices include " + ", ".join(names) + ".")
    return masteries


@lru_cache(maxsize=1)
def _arcane_paths():
    return tuple(p for p in load_ruleset()["encounter_paths"] if p.get("id") and p.get("schools"))


def _earned_paths(mastered):
    return [{"path":_label(p["id"]), "masteries":[_skill_names()[skill] for skill in p["schools"]],
             "signature":p["name"]} for p in _arcane_paths() if set(p["schools"]).issubset(mastered)]


def _challenge(rows, case):
    trials = [r for r in rows if r.get("status") == "replayed" and r["scenario"] == case and r.get("max_hp")]
    if not trials:
        return ""
    low = min(trials, key=lambda t: t["minimum_hp"] / t["max_hp"])
    name = "melee-pressure" if case == "physical" else "enemy-spellcaster"
    return f" Health fell as low as {low['minimum_hp']/low['max_hp']:.0%} in the tested {name} fights."


def _specialization(cap, paths, outcomes):
    path = cap.get("state", {}).get("arcane_path")
    if path:
        chosen = next(r for r in paths if r["path"] == _label(path))
        return [f"The final replay chose {chosen['path']} with {' and '.join(chosen['masteries'])} mastered.",
                f"Acquire {chosen['signature']} separately when you have access and spell points to cast it."]
    tips = ["Leave the path open at first. The replay measured this build before choosing a specialization."]
    eligible = {r["path"]:r for r in paths}
    if "Battlemage" in eligible:
        pair = " and ".join(eligible["Battlemage"]["masteries"])
        tips.append(f"If melee enemies repeatedly reach you and drain your health, choose Battlemage after mastering {pair}. "
                    "When Aegis Bolt deals damage in ordinary PvE, it raises a shield worth twice the landed damage, "
                    "up to 20% of your maximum HP." + _challenge(outcomes, "physical"))
    if "Spellbreaker" in eligible:
        pair = " and ".join(eligible["Spellbreaker"]["masteries"])
        tips.append(f"If enemy spellcasters keep landing spells, choose Spellbreaker after mastering {pair}. "
                    "Unravel deals damage and rolls separately for Silence. A damaging hit returns one third of "
                    "the spell points paid, subject to your pool limit." + _challenge(outcomes, "enemy_caster"))
    if paths:
        tips.append("Unlocking a path and acquiring its signature spell are separate steps. Buy the spell only when a funded opportunity is available.")
    else:
        tips.append("The recorded route has no earned mastery pair for an arcane path.")
    return tips


def _refined_specialization(arcane, paths):
    name = arcane.get("selected", "none")
    if name == "none":
        return ["Keep the arcane path open while learning the game. The capped comparison selected the build without an active path."]
    path = "battlemage" if name == "battlemage_aegis" else name
    chosen = next(r for r in paths if r["path"] == _label(path))
    pair = " and ".join(chosen["masteries"])
    steps = [f"Work toward {chosen['path']} by mastering {pair}. Select it after earning both masteries."]
    if path == "soulbinder":
        steps.append("Soulbinder restores magicka after eligible kills. The tested benefit does not need Soul Lance.")
    elif name == "battlemage_aegis":
        steps.append("Acquire Aegis Bolt separately when it appears on the Buy Spells shelf. It raises a shield after landing damage.")
    elif path == "battlemage":
        steps.append("Keep a damage shield active to benefit from Battlemage's spell power. Aegis Bolt is a separate purchase.")
    return steps


def _refined_gear(birth, mid):
    from .equipment import equipment_catalog

    slots = {"RightHand", "ChestArmor"}
    equipped = {(item["slot"], item["name"], item.get("material")) for item in birth.get("loadout_details", [])}
    labels = {value: key for key, value in equipment_catalog()["armor_materials"].items()}
    upgrades = []
    for item in mid.get("loadout_details", []):
        slot, name, material = item["slot"], item["name"], item.get("material")
        if slot not in slots or (slot, name, material) in equipped:
            continue
        code = material + 512 if slot == "RightHand" and isinstance(material, int) else material
        metal = labels.get(code)
        upgrades.append(f"{metal} {name}" if metal and not name.casefold().startswith(metal.casefold()) else name)
    return ["Look for these usable upgrade options when available. " + ", ".join(upgrades) + "."] if upgrades else []


def _traits(doc, permanent):
    labels = permanent.get("traits", {})
    advantages = labels.get("advantages") or [_trait(p) for p in doc["advantages"]]
    disadvantages = labels.get("disadvantages") or [_trait(p) for p in doc["disadvantages"]]
    rows = ["Advantages — " + (", ".join(advantages) or "None") + ".",
            "Disadvantages — " + (", ".join(disadvantages) or "None") + "."]
    if permanent.get("magicka_multiplier"):
        rows.append(f"Magery gives this class {permanent['magicka_multiplier']:g} spell points per point of Intelligence before other modifiers.")
    return rows


def build_guide(row):
    """Use the editor values verbatim, with separate conditional guidance from the representative roll."""
    doc, permanent = row["class"], row.get("permanent") or {}
    progression = row.get("progression") or {}
    policy = progression.get("policy") or {}
    stages = _checkpoints(progression)
    birth, mid, cap = (stages.get(k) or {} for k in ("birth", "midgame", "cap"))
    mastered = cap.get("state", {}).get("mastered", []) or []
    paths = _earned_paths(mastered)
    seed = progression.get("representative_seed")
    certified = next((b for b in permanent.get("births", []) if b["seed"] == seed), None)
    refined = row.get("refinement")
    gear = _equipment(permanent, birth, mid)
    specialization = (_refined_specialization(refined["arcane"], paths) if refined else
                      _specialization(cap, paths, row.get("outcomes") or []))
    if refined:
        gear += _refined_gear(birth, mid)
    effects = [f"{_trait(p)}. {_consequence(p)}" for p in doc["disadvantages"]]
    groups = [f"{group.title()} skills in order — " + " → ".join(doc["skills"][group]) for group in ("primary","major","minor")]
    race = [f"Select {row['race']} in character creation. Race is a separate choice when importing the class file.",
            "The online creator goes directly from class to name."]
    if birth.get("state", {}).get("reflexes") == 2:
        race.append("Select Average reflexes to match the tested character.")
    rows = [
        ("race", "Choose your race", race),
        ("attributes", "Set your class attributes", [", ".join(f"{_label(k)} {doc['attributes'][k]}" for k in ATTRIBUTES) + ".",
                                                    f"Set class health to {doc['hitPointsPerLevel']} HP per level. Birth rolls and bonuses determine your starting sheet."]),
        ("skills", "Enter the ordered skill groups", groups),
        ("traits", "Select advantages and disadvantages", _traits(doc, permanent)),
        ("birth_bonus", "Spend your birth bonus", _birth_bonus(policy,doc["skills"])),
        ("restrictions", "Play around each disadvantage", effects or ["This class has no selected disadvantages."]),
        ("spells", "Choose your opening spells", _opening_spells(policy,birth,certified)),
        ("equipment", "Equip your first loadout", gear),
        ("training", "Plan your first levels", _first_levels(policy,mid,bool(refined))),
        ("masteries", "Plan your masteries", _masteries(permanent,policy,mastered)),
        ("specialization", "Choose an arcane specialization", specialization),
        ("later", "Decisions you can postpone", ["Keep your mastery and specialization slots open while practicing the required skills.",
          "Wait to buy an upgrade or a Spell Maker recipe until you have access and enough gold."]),
    ]
    sections = [{"id":key, "title":title, "items":items} for key,title,items in rows]
    basis = f"\nThe development example uses paired birth seed {seed}." if seed is not None else ""
    text = f"{doc['name']} · {row['race']}\nCharacter creation and development checklist{basis}\n"
    for section in sections:
        text += "\n[ ] " + section["title"] + "\n" + "".join("    " + v + "\n" for v in section["items"])
    return {"sections":sections, "text":text, "specialization_reference":paths}

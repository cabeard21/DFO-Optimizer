"""One legal ordinary online custom-character birth, detached from any actual save."""
from copy import deepcopy

from .character import _hash
from .class_document import ATTRIBUTES, parse_document
from .classes import validate_class_snapshot
from .progression_inputs import _known, number, vector
from .ruleset import load_ruleset


def _rolls(start):
    if ("rolls" in start) == ("roll_seed" in start):
        raise ValueError("Supply exactly one birth roll_seed or realized rolls")
    if "roll_seed" in start:
        # A reproducible tape for the source's roll parameters, not a prediction
        # of the browser RNG. All class candidates consume the same 56 draws.
        seed = number(start["roll_seed"], "roll_seed", 0, 2**32-1)
        if seed is None:
            raise ValueError("Missing roll seed")
        def draw(span):
            nonlocal seed
            seed = (1664525 * seed + 1013904223) & 0xffffffff
            return (seed * span) >> 32
        return {"attribute_bonus": [draw(11) for _ in range(8)], "attribute_pool": 6+draw(9),
                "misc_bonus": [draw(4) for _ in range(35)], "career_bonus": [draw(4) for _ in range(12)]}
    r = start["rolls"]
    if not isinstance(r, dict) or set(r) != {"attribute_bonus", "attribute_pool", "misc_bonus", "career_bonus"}:
        raise ValueError("Incomplete birth rolls")
    values = {"attribute_bonus": vector(r["attribute_bonus"], "attribute rolls", 8, hi=10),
              "attribute_pool": number(r["attribute_pool"], "attribute pool", 6, 14),
              "misc_bonus": vector(r["misc_bonus"], "misc rolls", 35, hi=3),
              "career_bonus": vector(r["career_bonus"], "career rolls", 12, hi=3)}
    if any(value is None for value in values.values()):
        raise ValueError("Missing birth roll")
    return values


def _spend(values, budget, allocation):
    if allocation is not None:
        extra = vector(allocation, "birth allocation", len(values), hi=budget)
        if sum(extra) != budget:
            raise ValueError("Birth allocation must spend its full source pool")
        return [v+e for v,e in zip(values,extra,strict=True)]
    out = values.copy()
    for _ in range(budget):
        i = min(range(len(out)), key=out.__getitem__)
        out[i] += 1
    return out


def _birth_stats(start, draft, rolls):
    before = [b+r for b,r in zip(draft.attributes, rolls["attribute_bonus"], strict=True)]
    attrs = _spend(before, rolls["attribute_pool"], start.get("attribute_allocation"))
    if max(attrs) > 100:
        raise ValueError("An allocated attribute exceeds 100")
    skills = [v+3 for v in rolls["misc_bonus"]]
    bonus = rolls["career_bonus"]
    allocation = vector(start.get("skill_allocation"), "skill allocation", 12, hi=6)
    for first,last,base in ((0,3,28),(3,6,18),(6,12,13)):
        values = _spend([base+r for r in bonus[first:last]], 6, allocation[first:last] if allocation else None)
        for skill, value in zip(draft.skills[first:last], values, strict=True):
            skills[skill] = value
    return attrs, skills


def _kit(facts, draft, report, gender):
    # A common, declared kit-roll tape of 0.5. Every skill's generated item rows
    # come from assignSkillItems; the basic kit from assignSkillEquipment.
    flags = report["effective_flags"]
    luck = draft.attributes[-1]
    upgrade = 51 <= (luck//2 if luck < 56 else luck)
    metals = flags["forbiddenMaterialsFlags"]
    armor = flags["weaponArmorShieldsBitfield"] >> 6
    steel = bool(metals & facts["iron_mask"]) or (upgrade and not metals & facts["steel_mask"])
    chain = bool(armor & 1) or (upgrade and not armor & 2)
    lookup = facts["skill_kits"][f"{gender}/{int(steel)}/{int(chain)}"]
    rows = [row for skill in draft.skills[:6] for row in facts["kit_rows"][lookup[skill]]]
    rows.extend(facts["common_kit"][gender])
    copies, stacks = [], {}
    for raw in rows:
        row = deepcopy(raw)
        family = row.pop("stack_family", None)
        if family in stacks:
            old = stacks[family]
            old["stackCount"] = old.get("stackCount", 1) + row.get("stackCount", 1)
        else:
            copies.append({"instance_id":f"birth:pack:{len(copies)}","container":"pack","item":row})
            if family is not None:
                stacks[family] = row
    gold = 5 + (luck-5)//2
    if facts["mercantile"] in draft.skills[:6]:
        gold += luck + (3*luck)//2
    return copies, gold


def birth_state(start, rules):
    rules = load_ruleset() if rules is None else rules
    if "progression_rules" not in rules:
        raise ValueError("New characters require a ruleset with progression mechanics")
    f = rules["progression_rules"]["creation"]
    profile = start.get("profile", "dhargo_pve")
    report = validate_class_snapshot(start.get("class"), ruleset=rules, race=start.get("race_id"), profile=profile)
    if (not report["create_legal"] or report["skipped"] or report["race_id"] is None
            or (profile == "dhargo_pve" and not report["profile_legal"])):
        reasons = report["errors"] + report["create_errors"] + report["profile_errors"]
        raise ValueError("Invalid progression birth class/race/profile " + ", ".join(reasons))
    gender = start.get("gender","male")
    if gender not in ("male", "female"):
        raise ValueError("Invalid birth gender")
    reflexes = number(start.get("reflexes", 2), "reflexes", 0, 4)
    if reflexes is None:
        raise ValueError("A birth requires reflexes")
    draft, _ = parse_document(report["normalized"], rules)
    rolls = _rolls(start)
    attrs, skills = _birth_stats(start,draft,rolls)
    groups = {"primary":list(draft.skills[:3]),"major":list(draft.skills[3:6]),"minor":list(draft.skills[6:])}
    anchor = sum(skills[i] for i in groups["primary"]) + sum(sorted(skills[i] for i in groups["major"])[-2:])
    anchor += max(skills[i] for i in groups["minor"])
    inventory, gold = _kit(f,draft,report,gender)
    indices = {i for group in ("primary","major") for skill in groups[group]
               for i in f["starting_spells"].get(str(skill), {}).get(group, [])}
    source = [r for r in f["generated_records"] if r["index"] in indices]
    observations = {"unresolved_indices": sorted(indices), "records": source}
    spells = _known(observations, start.get("spell_records", []))
    hp, sp = 25 + draft.hp, int(attrs[1] * report["magicka_multiplier"])
    career = {**dict(zip(ATTRIBUTES,draft.attributes,strict=True)), **report["effective_flags"],
              "hitPointsPerLevel":draft.hp,"advancementMultiplier":report["advancement_multiplier"],
              **{k+"Skills":v for k,v in groups.items()}}
    state = {**groups, "skills":skills,"attributes":attrs,"uses":[0]*35,"progress":[0.]*35,
             "fractions":[0.]*35,"mastered":[],"level":1,"starting_sum":anchor,"current_sum":anchor,
             "reflexes":reflexes,"advancement_multiplier":report["advancement_multiplier"],
             "minutes":f["start_minutes"],"last_check":f["start_minutes"],"last_training":0,"last_rest":-1,
             "pending_level":-1,"pending_pool":-1,"gold":gold,"bank_gold":0,"sp":sp,"max_sp":sp,
             "hp":hp,"max_hp":hp,"hp_setting":draft.hp,"fatigue":(attrs[0]+attrs[4])*f["fatigue_multiplier"],
             "has_spellbook":True,"arcane_path":-1,"martial_path":-1,"race_id":report["race_id"],
             "gender":gender,"career":career,"inventory":inventory,**spells,"real_ms":0,"boundary":"creation",
             "birth_rolls":rolls,"kit_roll":0.5,"chargen_done":True,"ruleset_hash":rules["content_hash"]}
    state = {**state, "max_fatigue": state["fatigue"]}
    return {**state,"snapshot_hash":_hash(state)}


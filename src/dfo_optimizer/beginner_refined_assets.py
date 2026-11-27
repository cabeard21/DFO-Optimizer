"""Conditional equipment access and verified Spell Maker books for beginner v2."""

from functools import lru_cache
from hashlib import sha256
import json

from .beginner_equipment import bind_physical_player
from .equipment import _catalog, career_masks, inspect_item
from .physical_encounter import laws
from .ruleset import DATA, SOURCE_SHA
from .spell_request import SpellCaster
from .spells import optimize_spells

POOL_LIMITS = {"early": 1, "middle": 7, "cap": 8}
ASSET_LAW_HASH = "22b8c9a8a1d3c59e1c56b4d824cb78e9e9b92bf5ec425b49573b9d928ec21829"
CAP_MAKER_ASSUMPTION = "The theoretical ceiling assumes access to the selected Spell Maker purchases."
MAKER_ASSUMPTION = "Conditional Spell Maker visit, using source prices at chapter multiplier 1.0."
POOL_ASSUMPTION = (
    "Conditional access to full-condition mundane copies offered at this checkpoint. "
    "The equipped copies fit beside the existing pack. Acquisition and drop rates are unspecified."
)
LEGACY_AREA = -910001


@lru_cache(maxsize=1)
def asset_law():
    contents = (DATA / "beginner-assets-v2.json").read_bytes().rstrip(b"\r\n")
    digest = sha256(contents).hexdigest()
    table = json.loads(contents)
    if digest != ASSET_LAW_HASH or table["source_sha"] != SOURCE_SHA:
        raise ValueError("Beginner assets require the pinned equipment and Spell Maker snapshot")
    return table, digest


@lru_cache(maxsize=16)
def _pool(limit, flags, forbidden, gender):
    catalog = _catalog()
    career = {"weaponArmorShieldsBitfield": flags, "forbiddenMaterialsFlags": forbidden}
    items = []
    for key, (condition, weight) in asset_law()[0]["items"].items():
        index, material = (int(v) for v in key.split("/"))
        if (material & 255) > limit:
            continue
        template = catalog["templates"][str(index)]
        item = {"templateIndex": index, "material": material, "name": template["name"],
                "group": template["group"], "currentCondition": condition, "maxCondition": condition}
        facts = inspect_item(item, career=career, gender=gender)
        if facts["placements"] and not facts["unsupported"]:
            items.append((f"assumed:{key}", item, weight, facts["placements"]))
    return tuple(items)


def _for_slot(items, slot):
    return [(identity, item, weight, flag["mask"]) for identity, item, weight, placements in items
            for flag in placements if flag["slot"] == slot]


def _body_score(item):
    shield = item["templateIndex"] >= 109
    tier = laws()["materials"][str(item["material"])][int(shield)]
    coverage = len(laws()["armor_parts"][str(item["templateIndex"])])
    return tier, coverage


def _layout(stage, inventories, access, *, hands, order):
    slots = _catalog()["slots"]
    current = stage["loadout"]
    active = dict(current)
    added, occupied, carried = [], 0, round(stage["carry"]["carried_kg"] * 400)
    limit = round(stage["carry"]["capacity_kg"] * 400)
    if hands is not None:
        ident, item, weight, mask = hands
        if carried + weight <= limit:
            active.update(RightHand=ident)
            active.pop("LeftHand", None)
            added.append((ident, item))
            carried += weight
            occupied |= mask
    if not added:
        existing = next((row["item"] for row in stage["inventory"]
                         if row["instance_id"] == current.get("RightHand")), None)
        if existing is not None:
            options = inspect_item(existing, career=stage["career"], gender=stage["state"].get("gender"))
            occupied = next(p["mask"] for p in options["placements"] if p["slot"] == slots["RightHand"])
    for slot in order:
        options = sorted((r for r in _for_slot(inventories, slots[slot]) if r[1]["group"] == "Armor"),
                         key=lambda r: (*(-v for v in _body_score(r[1])), r[2], r[0]))
        for ident, item, weight, mask in options:
            if not occupied & mask and carried + weight <= limit:
                active[slot] = ident
                added.append((ident, item))
                carried += weight
                occupied |= mask
                break
    carry = {**stage["carry"], "carried_kg": carried / 400, "headroom_kg": (limit - carried) / 400}
    view = {**stage, "inventory": [*stage["inventory"], *(
        {"instance_id": identity, "container": "pack", "item": dict(item)} for identity, item in added
    )], "loadout": active, "carry": carry, "asset_access": {**access, "assumed_copies": len(added)}}
    player = bind_physical_player(view)
    return {**view, "physical_player": {**player, "evidence": POOL_ASSUMPTION}}


def equipment_options(stage, mode):
    """Offer finite legal alternatives for selection on a separate tuning panel."""
    if mode not in ("owned", "representative", "theoretical"):
        raise ValueError("Unknown beginner equipment assumption")
    if mode == "owned":
        view = stage.get("variants", {}).get("owned_only", stage)
        return [{**view, "physical_player": bind_physical_player(view), "spell_policy": "steady",
                 "asset_access": {"mode": "owned", "assumed_copies": 0}}]
    checkpoint = "cap" if stage["level"] == 45 else "middle" if stage["level"] >= 15 else "early"
    upper = 9 if mode == "theoretical" else POOL_LIMITS[checkpoint]
    items = _pool(upper, *career_masks(stage["career"]), stage["state"].get("gender"))
    catalog = _catalog()
    weapons = laws()["weapons"]
    skill = stage["state"]["skills"]
    left = catalog["slots"]["LeftHand"]
    # Use the actual names for the source slots. Body and shield do not conflict.
    occupied_slots = {p["slot"] for _, item, _, placements in items if item["group"] == "Armor"
                      for p in placements}
    slots = (name for name, slot in catalog["slots"].items() if slot in occupied_slots and slot != left)
    access = {"mode": mode, "assumption": POOL_ASSUMPTION, "maximum_metal_index": upper,
              "eligible_weapon_metals": sorted({i["material"] for _, i, _, _ in items if i["group"] == "Weapons"}),
              "eligible_plate_metals": sorted({i["material"] - 512 for _, i, _, _ in items
                                               if 102 <= i["templateIndex"] <= 108 and i["material"] >= 512})}
    options = sorted(_for_slot(items, catalog["slots"]["RightHand"]), key=lambda r: (
        -skill[weapons[str(r[1]["templateIndex"])]["skill"]], -r[1]["material"],
        -sum(weapons[str(r[1]["templateIndex"])]["span"]), r[2], r[0]))
    light = next((r for r in options if not r[3] & (1 << left)), None)
    heavy = options[0] if options else None
    armor = tuple(sorted(slots, key=lambda s: (s != "ChestArmor", s)))
    # The owned weapon, a shield-compatible weapon, and the highest screened melee option
    # are separate candidates. Encounter replay decides which of these proposals to use.
    layouts = [_layout(stage, items, access, hands=weapon, order=order)
               for weapon, order in ((light, ("LeftHand", *armor)), (heavy, armor), (None, armor))]
    return list({tuple(sorted(row["loadout"].items())): row for row in layouts}.values())


def _spell_request(stage, funds, reach, objective, budget, hypothetical):
    actor = stage["actor"]
    caster = {k: actor[k] for k in SpellCaster.__dataclass_fields__ if k in actor}
    caster.update(gold=funds, current_sp=actor["max_sp"])
    domain = {"base_low": [1, 3, 6, 12], "base_high": [1, 3, 6, 12, 18],
              "plus_low": [1, 2, 5, 8], "plus_high": [1, 2, 5, 8], "per_level": [1, 2, 4]}
    if not hypothetical:
        # Add a deliberately cheap frontier. A larger spell judged affordable in SP
        # can still be outside the checkpoint's purchase budget.
        domain = {"base_low": [1, 2], "base_high": [1, 2, 3],
                  "plus_low": [1, 2, 3], "plus_high": [1, 2, 3], "per_level": [2, 3, 4, 5]}
    return {"caster": caster, "price_factor": 1,
            "target": {"id": "Spell drafting, varied saves", "hp": 140, "willpower": 65,
                       "resist_mods": [15, 0, 0, 0, 0]},
            "domain": {**domain, "element": [0, 1, 2, 3, 4], "range_type": [reach]},
            "search": {"objective": objective, "top_k": 12, "max_nodes": min(3000, budget.remaining()),
                       "wall_seconds": budget.seconds(), "memory_bytes": max(1, budget.memory // 8)}}


def _offense(stage, reach, objective, budget, rules, funds, hypothetical):
    if not budget.remaining() or not budget.seconds() or (budget.token and budget.token.cancelled()):
        return []
    query = _spell_request(stage, funds, reach, objective, budget, hypothetical)
    # Shared spell rules, budgeted native candidate generation, independent finalist validation.
    result = optimize_spells(query, ruleset=rules, cancel=getattr(budget.token, "spell", None))
    budget.used["spell_nodes"] += result["counters"]["nodes"]
    budget.used["spell_searches"] += 1
    role = {1: "Touch", 2: "Ranged", 3: "Close area"}[reach]
    choices = []
    for row in result["candidates"]:
        recipe = row["spell"]
        choices.append({"id": f"{role} {objective} {row['spell_id'][:10]}", "element": recipe["element"],
                        "range_type": reach, "effects": [{k: v for k, v in recipe.items()
                                                         if k not in ("element", "range_type")}],
                        "evidence": MAKER_ASSUMPTION, "gold": row["metrics"]["purchase_gold"]})
    return choices


def _defense(effect_id):
    return [{"id": row["name"], "effects": [row["effect"]], "element": 4, "range_type": 0,
             "gold": row["gold"], "evidence": MAKER_ASSUMPTION}
            for row in reversed(asset_law()[0]["defense"]) if row["effect"]["effect_id"] == effect_id]


def _book(stage, mode, rules, budget):
    hypothetical = mode == "theoretical"
    funds = stage["state"]["gold"]
    selected = []
    phases = ((1, "damage_per_sp"), (2, "damage_per_sp"), (3, "damage_per_sp"))
    offensive = [_offense(stage, reach, objective, budget, rules, funds, hypothetical) for reach, objective in phases]
    defensive = [_defense(effect) for effect in ("10,8", "35,255", "18,255")]
    burst = [_offense(stage, reach, "dps", budget, rules, funds, hypothetical) for reach in (1, 2, 3)]
    # Cycle through the roles so one costly recipe does not spend all of the practical budget.
    for lane in [*offensive, *defensive, *burst]:
        choice = next((row for row in lane if (hypothetical or row["gold"] <= funds)
                       and not any((row["effects"], row["range_type"], row["element"])
                                   == (s["effects"], s["range_type"], s["element"])
                                   for s in [*stage["spells"], *selected])), None)
        if choice:
            selected.append(choice)
            if not hypothetical:
                funds -= choice["gold"]
    if hypothetical:
        return {**stage, "spells": [*(dict(s, evidence=CAP_MAKER_ASSUMPTION) for s in selected), *stage["spells"]],
                "theoretical_spells": [{"id": s["id"], "quote_gold": s["gold"]} for s in selected]}
    receipts = [{"kind": "optimized_spell", "id": s["id"], "name": s["id"], "gold": s["gold"],
                 "evidence": s["evidence"]} for s in selected]
    paid = stage["state"]["gold"] - funds
    carry = stage["carry"]
    # One gold piece is 1/400 kg in the verified inventory law.
    return {**stage, "spells": [*selected, *stage["spells"]],
            "actor": {**stage["actor"], "gold": funds}, "state": {**stage["state"], "gold": funds},
            "carry": {**carry, "carried_kg": carry["carried_kg"] - paid / 400,
                      "headroom_kg": carry["headroom_kg"] + paid / 400},
            "acquisitions": [*stage["acquisitions"], *receipts],
            "transactions": [*stage["transactions"], *({**a, "delta_gold": -a["gold"]} for a in receipts)],
            "effort": {**stage["effort"], "spent": stage["effort"]["spent"] + paid}}


def _starting_inventory(stage):
    """Use the actual birth kit and funded training, before optional legacy offers."""
    base = stage.get("variants", {}).get("owned_only", stage)
    legacy = next((a["gold"] for a in base["acquisitions"] if a["id"] == LEGACY_AREA), 0)
    if not legacy:
        return base
    carry = base["carry"]
    return {**base, "state": {**base["state"], "gold": base["state"]["gold"] + legacy,
                               "known": [i for i in base["state"]["known"] if i != LEGACY_AREA]},
            "actor": {**base["actor"], "gold": base["actor"]["gold"] + legacy},
            "acquisitions": [a for a in base["acquisitions"] if a["id"] != LEGACY_AREA],
            "transactions": [a for a in base["transactions"] if a["id"] != LEGACY_AREA],
            "spells": [s for s in base["spells"] if s["id"] != "Close circle (paid recipe)"],
            "effort": {**base["effort"], "spent": base["effort"]["spent"] - legacy},
            "carry": {**carry, "carried_kg": carry["carried_kg"] + legacy / 400,
                      "headroom_kg": carry["headroom_kg"] - legacy / 400}}


def hold_book(stage, book_stage):
    """Keep a frozen spellbook and its associated spell purchases across a gear-only fork."""
    carry = stage["carry"]
    cash_shift = book_stage["state"]["gold"] - stage["state"]["gold"]
    return {**stage, "spells": book_stage["spells"], "spell_policy": book_stage.get("spell_policy", "steady"),
            "actor": {**stage["actor"], "gold": book_stage["state"]["gold"]},
            "state": {**stage["state"], "gold": book_stage["state"]["gold"]},
            "carry": {**carry, "carried_kg": carry["carried_kg"] + cash_shift / 400,
                      "headroom_kg": carry["headroom_kg"] - cash_shift / 400},
            **{k: book_stage[k] for k in ("acquisitions", "transactions", "effort", "theoretical_spells")
               if k in book_stage}}


def prepare_options(stage, mode, rules, budget):
    """Draft one book for the legal gear proposals on this checkpoint."""
    stage = _starting_inventory(stage)
    options = equipment_options(stage, "owned" if stage["level"] == 1 else mode)
    if mode == "owned" or stage["level"] == 1:
        return options
    book = _book(options[0], mode, rules, budget)
    return [book, *(hold_book(option, book) for option in options[1:])]


def prepare(stage, mode, rules, budget):
    return prepare_options(stage, mode, rules, budget)[0]


_POLICIES = ("steady", "heal_early", "conserve", "burst")


def casting_plan(book, multiple, profile):
    """Apply the same chosen rules to the spellbook and geometry of each draw."""
    from .beginner_scenario_trials import casting_policy

    if profile not in _POLICIES:
        raise ValueError("Unknown beginner casting plan")
    if profile == "burst":
        book = sorted(book, key=lambda s: " dps " not in s["id"])
    base = casting_policy(book, multiple)
    rules = base["rules"]
    if profile == "heal_early":
        rules = [{**row, "hp_below_pct": 75} if "hp_below_pct" in row else row for row in rules]
    elif profile == "conserve":
        rules = [{**row, "hp_below_pct": 45} if "hp_below_pct" in row else row for row in rules
                 if "shield_below" not in row]
    return {"id": "beginner-" + profile, "rules": rules}


def tune(stage, case, rules, budget):
    """Select a finite casting plan on one separate tuning draw with native encounter search."""
    from .beginner_scenario_trials import ScenarioGap, make_request
    from .encounter import optimize_encounter

    if stage["level"] == 1 or not budget.remaining() or not budget.seconds():
        return stage
    try:
        query = make_request(stage, case, "baseline", (701,))
    except ScenarioGap:
        return stage
    unique = {}
    for profile in _POLICIES:
        policy = casting_plan(stage["spells"], case["id"] == "multiple", profile)
        identity = json.dumps(policy["rules"], sort_keys=True)
        unique.setdefault(identity, policy)
    if len(unique) < 2:
        return stage
    query.update(policies=list(unique.values()), search={
        "objective": "pareto", "max_events": min(4096, budget.remaining()),
        "wall_seconds": budget.seconds(), "memory_bytes": max(1, budget.memory // 4),
    })
    result = optimize_encounter(query, ruleset=rules, cancel=getattr(budget.token, "encounter", None))
    budget.used["encounter_events"] += result["counters"]["events"]
    budget.used["encounter_batches"] += 1
    budget.used["replayed_trials"] += sum(q["metrics"]["trials"] for q in result["frontier"])
    if not result["frontier"]:
        return stage

    def score(row):
        m = row["metrics"]
        return (m["clear_probability"], m["survival_probability"], m["mean_minimum_hp"],
                -m["censored_mean_clear_us"], m["mean_damage"], -m["mean_sp_spent"],
                -row["policy_index"])

    winner = max(result["frontier"], key=score)
    return {**stage, "spell_policy": winner["policy_id"].removeprefix("beginner-"),
            "policy_tuning": {"seed": 701, "case": case["id"], "status": result["termination"],
                              "policies_evaluated": result["counters"]["policies_completed"]}}

"""Bind shared prospective training and acquisition policies to a realized class."""

import math
from copy import deepcopy

from .progression_domain import fields, integer, require

# Practice casts in each school use actual generated spell records from the pinned kit.
_PRACTICE = {22: 991, 23: 995, 24: 993, 25: 992, 26: 997, 27: 998}
_ACTIVITIES = {
    1: "polite_conversation",
    2: "blunt_conversation",
    13: "lockpick_attempt",
    14: "completed_trade",
    15: "pickpocket_attempt",
    16: "stealth_check",
    20: "missed_melee_attack",
    **dict.fromkeys(range(4, 13), "failed_pacification"),
}
_SUPPORTED = set(_PRACTICE) | set(_ACTIVITIES) | {0}


def _training_skills(groups, spec, rules):
    from .discovery_request import resolve_ids

    by_name = {skill["name"].casefold(): skill["id"] for skill in rules["skills"]}
    resolve_ids(spec.get("mastery_priority", []), by_name, "mastery_priority")
    # resolve_ids canonicalizes domains. Here, declared preference order matters.
    priority = [by_name[v.casefold()] if isinstance(v, str) else v for v in spec.get("mastery_priority", [])]
    order = {v: i for i, v in enumerate(priority)}

    def rank(skill):
        return order.get(skill, len(order) + (skill not in _PRACTICE))

    return [
        i
        for group, quota in zip(groups, (3, 2, 1), strict=True)
        for i in sorted((i for i in group if i in _SUPPORTED), key=rank)[:quota]
    ]


def _allocation_window(spec):
    extra = spec.get("alternate_allocation_orders", [])
    require(isinstance(extra, list) and len(extra) <= 3, "up to three alternate allocation orders")
    policies = [spec["allocation_order"], *extra]
    for order in policies:
        require(
            isinstance(order, list)
            and len(order) == 8
            and all(type(i) is int for i in order)
            and set(order) == set(range(8)),
            "allocation_order must permute all eight attributes",
        )
    require(len(set(map(tuple, policies))) == len(policies), "allocation orders must be distinct")
    return [
        {
            "kind": "level",
            "if_due": True,
            "allocation_order": list(order),
            **({"allocation_policy": i} if extra else {}),
        }
        for i, order in enumerate(policies)
    ]


def _specialization(spec, rules, repeats):
    row = fields(spec, {"path", "after_circuit", "signature_offer"}, "specialization opportunity")
    law = next(
        (
            r
            for r in rules["progression_rules"]["paths"]
            if r["family"] == "arcane" and r["id"] == row.get("path")
        ),
        None,
    )
    require(law is not None, "unrecognized arcane specialization")
    after = integer(row.get("after_circuit"), "specialization access circuit", 1, repeats)
    choose = {"kind": "choose", "family": "arcane", "path": law["id"]}
    goal = {"arcane_path": law["id"]}
    stages = [[choose]]
    if "signature_offer" in row:
        offer = fields(row["signature_offer"], {"record", "gold_cost", "evidence"}, "signature offer")
        source = next(r for r in rules["encounter_paths"] if r["id"] == law["id"])
        blank = next(
            e
            for r in rules["progression_rules"]["creation"]["generated_records"]
            for e in r["effects"]
            if e["type"] < 0
        )
        # Mirror buildCustomSpell's three slots and one-valued spinner defaults.
        # The authenticated encounter catalog carries every mechanical field.
        effects = [
            {**dict.fromkeys(blank, 1), "type": s["type"], "subType": s["subType"], **s["settings"]}
            for s in source["slots"]
        ]
        effects.extend(deepcopy(blank) for _ in range(3 - len(effects)))
        record = {
            "index": source["index"],
            "name": source["name"],
            "path": source["id"],
            "custom": True,
            "element": source["element"],
            "rangeType": source["range_type"],
            "cost": 0,
            "effects": effects,
        }
        submitted = offer.get("record", record)
        require(
            isinstance(submitted, dict) and {k: v for k, v in submitted.items() if k != "icon"} == record,
            "signature offer requires the matching source spell record",
        )
        require(
            isinstance(offer.get("evidence"), str) and offer["evidence"].strip(),
            "signature quote needs evidence",
        )
        integer(offer.get("gold_cost"), "signature gold quote")
        stages.append(
            [{**choose, "kind": "buy", "spell": law["signature"], **deepcopy(offer), "record": record}]
        )
        goal["known"] = [law["signature"]]
    return after, stages, goal


def _lesson(school, template, index, factor):
    # The RRI spell supplies its source effect kind and a legal casting target.
    # Buy a newly inscribed custom recipe when that starter is absent.
    from .progression_practice import release_cost

    row = deepcopy(template["effects"][0])
    for component in ("duration", "chance"):
        if row[component + "PerLevel"]:
            row.update({component + "Base": 1, component + "Mod": 1, component + "PerLevel": 2})
    if row["magnitudePerLevel"]:
        row.update(
            magnitudeBaseLow=1,
            magnitudeBaseHigh=1,
            magnitudeLevelBase=1,
            magnitudeLevelHigh=1,
            magnitudePerLevel=2,
        )
    recipe = {
        "index": index,
        "custom": True,
        "name": f"Practice {template['name']}",
        "icon": template["icon"],
        "cost": 0,
        "rangeType": template["rangeType"],
        "element": template["element"],
        "effects": [row],
    }
    price = release_cost(recipe, school)
    gold = price["component_gold"] * price["range_multiplier_twice"] // 2
    return recipe, max(1, math.floor(gold * factor + 0.5))


def _circuit(spec, note, chosen, practices, cadence, challenge):
    arrival = {
        "kind": "check",
        "minutes": 120,
        "fare_gold": 0,
        "trigger": "fast_travel_arrival",
        "evidence": "Hypothetical zero-fare arrival after two personal hours before the next full night.",
    }
    bed = {
        "kind": "rest",
        "site": "bed",
        "recovery": "full_bed",
        "evidence": "Conditional uninterrupted access to a full-recovery bed, with lodging already covered. "
        + note,
    }
    windows = [[arrival], [bed]]
    for skill in chosen:
        if skill == 0:
            continue  # Each full night already tallies Medical eight times.
        action = {
            "kind": "practice",
            "skill": skill,
            "cadence_ms": cadence,
            "until_skill": 200,
            "evidence": note,
        }
        if skill in _PRACTICE:
            action.update(spell=practices[skill], count=64, until_spent=True, challenge_level=challenge)
        else:
            action.update(
                activity=_ACTIVITIES[skill], count=384, challenge_level=challenge if skill == 20 else 0
            )
            if skill == 20:
                action["evidence"] = "Hypothetical connected melee attacks that roll zero damage. " + note
        windows.append([action])
        windows.extend([[arrival], [bed]])
    windows.extend([[{"kind": "master", "skill": i, "if_eligible": True}] for i in chosen])
    windows.append(_allocation_window(spec))
    return windows


def bind_itinerary(progression, start, rules):
    """Expand the common opportunity policy after the family and roll are fixed."""
    spec = fields(
        progression["itinerary"],
        {
            "version",
            "cycles",
            "cadence_ms",
            "challenge_level",
            "maker_price_factor",
            "cache_gold",
            "allocation_order",
            "alternate_allocation_orders",
            "mastery_priority",
            "specialization",
            "evidence",
        },
        "prospective itinerary",
    )
    require(
        not set(progression).intersection({"activities", "cycles", "stages"}),
        "choose one progression itinerary",
    )
    integer(spec.get("version"), "itinerary version", 1, 1)
    repeats = integer(spec.get("cycles"), "training circuits", 1, 4000)
    cadence = integer(spec.get("cadence_ms"), "itinerary cadence", 1400, 1_000_000)
    challenge = integer(spec.get("challenge_level"), "practice challenge", 0, 2000)
    factor = spec.get("maker_price_factor")
    require(
        type(factor) in (float, int) and math.isfinite(factor) and 0.01 <= factor <= 100,
        "maker_price_factor must be finite and in [0.01, 100]",
    )
    coins = integer(spec.get("cache_gold"), "hypothetical gold cache", 0, 2**31 - 1)
    note = spec.get("evidence")
    require(isinstance(note, str) and 0 < len(note.strip()) <= 1500, "itinerary requires attributed evidence")
    from .progression_inputs import resolve_start

    source, _ = resolve_start(start, rules=rules)
    chosen = _training_skills([source[k] for k in ("primary", "major", "minor")], spec, rules)
    records = {r["index"]: r for r in rules["progression_rules"]["creation"]["generated_records"]}
    cycles = []
    practices = dict(_PRACTICE)
    lessons = []
    if coins:
        lessons.append(
            [
                {
                    "kind": "collect_gold",
                    "copy": "itinerary-coin-purse",
                    "amount": coins,
                    "evidence": "One physical stack of the stated gold amount is available after the birth checkpoint. Contents and access are hypothetical.",
                }
            ]
        )
    missing = (
        s for s in dict.fromkeys([22, *chosen]) if s in practices and practices[s] not in source["known"]
    )
    for offset, school in enumerate(missing, start=1):
        record, price = _lesson(school, records[practices[school]], -offset, factor)
        practices[school] = record["index"]
        lessons.append(
            [
                {
                    "kind": "buy",
                    "spell": record["index"],
                    "gold_cost": price,
                    "record": record,
                    "evidence": f"Hypothetical Spell Maker service with price factor {factor:g}; the candidate buys this exact single-effect recipe using available gold.",
                }
            ]
        )
    if lessons:
        cycles.append({"windows": lessons})
    windows = _circuit(spec, note, chosen, practices, cadence, challenge)
    goal = progression["goal"]
    if "specialization" in spec:
        after, opportunity, path_goal = _specialization(spec["specialization"], rules, repeats)
        require(
            goal.get("arcane_path", path_goal["arcane_path"]) == path_goal["arcane_path"],
            "specialization conflicts with the requested arcane goal",
        )
        goal = {
            **goal,
            **path_goal,
            **(
                {"known": sorted(set(goal.get("known", ())) | set(path_goal["known"]))}
                if "known" in path_goal
                else {}
            ),
        }
        cycles.extend([{"repeat": after, "windows": windows}, {"windows": opportunity}])
        if repeats > after:
            cycles.append({"repeat": repeats - after, "windows": windows})
    else:
        cycles.append({"repeat": repeats, "windows": windows})
    return {
        **{k: v for k, v in progression.items() if k != "itinerary"},
        "goal": goal,
        "cycles": cycles,
        "project_creation_vitals": True,
        "search": {"memory_bytes": 256 << 20, **progression.get("search", {}), "final_stage_only": False},
    }

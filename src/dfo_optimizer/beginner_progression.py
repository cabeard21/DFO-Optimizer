"""One prospective progression policy per family and birth, shared across scenario forks."""

import json
from collections import OrderedDict
from copy import deepcopy
from time import perf_counter

from .beginner_stage_assets import StageAssets
from .class_document import ATTRIBUTES, parse_document
from .discovery_itinerary import bind_itinerary
from .discovery_presets import discovery_preset
from .progression import digest, plan_progression
from .progression_batches import interrupted_report, stop_reason
from .progression_birth import _rolls, birth_state
from .progression_domain import fields, integer, require
from .progression_replay import initial_effort
from .ruleset import _progression_service_rules
from .search import class_identity

_ORDER = (4, 1, 6, 2, 0, 3, 5, 7)
_STAGES = {1: "birth", 15: "midgame", 45: "cap"}
_STATE = (
    "level",
    "attributes",
    "skills",
    "known",
    "mastered",
    "hp",
    "max_hp",
    "sp",
    "max_sp",
    "fatigue",
    "max_fatigue",
    "gold",
    "minutes",
    "pending_level",
    "pending_pool",
    "current_sum",
    "arcane_path",
    "martial_path",
)


def _birth(start, rules):
    require(
        isinstance(start, dict) and start.get("type") == "new_character",
        "beginner checkpoints require an ordinary new character",
    )
    integer(start.get("roll_seed"), "paired birth roll_seed", 0, 2**32 - 1)
    start = {"profile": "custom", **start}
    rolls = _rolls(start)
    allocation = start.get("attribute_allocation")
    if allocation is None:
        draft, _ = parse_document(start.get("class"), rules)
        headroom = [
            100 - value - n for value, n in zip(draft.attributes, rolls["attribute_bonus"], strict=True)
        ]
        remaining = rolls["attribute_pool"]
        allocation = [0] * 8
        for attr, maximum in [(4, 4), *((i, 100) for i in (1, 6, 2, 4, 0, 3, 5, 7))]:
            extra = min(remaining, maximum, max(0, headroom[attr] - allocation[attr]))
            allocation[attr] += extra
            remaining -= extra
        require(remaining == 0, "birth allocation exceeds attribute ceilings")
        start = {**start, "attribute_allocation": allocation}
    return start, birth_state(start, rules)


def _policy(start, source, query, rules, route):
    spec = query.get("itinerary", {})
    primary_order = spec.get("allocation_order", [])
    from .discovery_itinerary import _training_skills

    skills = {r["id"]: r["name"] for r in rules["skills"]}
    priority = (
        _training_skills([source[k] for k in ("primary", "major", "minor")], spec, rules) if spec else []
    )
    first_level = next((p for p in (route or {}).get("checkpoints", []) if p["state"]["level"] == 2), None)
    allocation = {}
    career_rolls = iter(source["birth_rolls"]["career_bonus"])
    for group, base in (("primary", 28), ("major", 18), ("minor", 13)):
        allocation[group] = [source["skills"][skill] - base - next(career_rolls) for skill in source[group]]
    return {
        "name": "beginner-reachable-checkpoints-v1",
        "birth_attribute_order": [ATTRIBUTES[k] for k in (4, 1, 6, 2, 4, 0, 3, 5, 7)],
        "birth_allocation": start["attribute_allocation"],
        "birth_attribute_pool": source["birth_rolls"]["attribute_pool"],
        "birth_skill_allocation": start.get(
            "skill_allocation", "Spend all six points per group on its lowest rolled skills."
        ),
        "realized_birth_skill_allocation": allocation,
        "first_earned_level": None
        if first_level is None
        else {
            "level": 2,
            "attribute_gains": [
                a - b for a, b in zip(first_level["state"]["attributes"], source["attributes"], strict=True)
            ],
            **first_level["effort"],
        },
        "level_attribute_order": [ATTRIBUTES[k] for k in primary_order],
        "mastery_priority": [skills[k] for k in priority],
        "starter_spells": [r["name"] for r in source["spell_records"]],
        "birth": "Allocate up to four points to Endurance, then Intelligence, Speed and Willpower within legal caps. Explicit allocations override that rule.",
        "training": spec.get("evidence", "Explicit finite progression opportunities."),
        "level_ups": "Follow one declared attribute order at every level. Choose eligible masteries in the itinerary's fixed order.",
        "gear_access": "Equip one proficient owned melee weapon in the right hand, a compatible shield if available and eligible clothing/armor. At the first scored earned level buy an affordable legal iron plate cuirass (30 gold), steel plate (35), or chain (20), in that order, when it upgrades the chest slot. All three quotes and access are hypothetical. Wear the chosen loadout for the encounter forks.",
        "spell_access": "Start with the actual birth spellbook. Pay for missing practice recipes during training. At the first scored earned level, buy the stated area-touch recipe at the ordinary Spell Maker price if affordable after armor and obligatory training.",
        "assumptions": spec,
        "alternate_access": "Each scenario starts from a fresh copy of the checkpoint. Gear and optional combat spells persist across earned checkpoints. No optional combat purchases or encounter damage alter the training route.",
    }


def _initial(source):
    state = {k: source[k] for k in _STATE}
    for key in ("arcane_path", "martial_path"):
        if state[key] == -1:
            state[key] = None
    return {"stage": 0, "state": state, "effort": initial_effort()}


def _stages(start, source, levels, route, family, rules):
    records = {r["index"]: r for r in source["spell_records"]}
    points = {1: _initial(source)}
    actions = route["actions"] if route else []
    checks = route["checkpoints"] if route else []
    for checkpoint in checks:
        level = checkpoint["state"]["level"]
        if level in levels and level not in points:
            points[level] = checkpoint
    for action in actions:
        if "record" in action:
            records[action["spell"]] = action["record"]
    assets = StageAssets(source, rules)
    receipts = []
    for index, action in enumerate(actions, start=1):
        if action["kind"] == "collect_gold":
            receipts.append(
                {
                    "window": index,
                    "kind": "gold_cache",
                    "id": action["copy"],
                    "delta_gold": action["amount"],
                    "evidence": action["evidence"],
                }
            )
        elif action["kind"] == "buy":
            receipts.append(
                {
                    "window": index,
                    "kind": "training_spell",
                    "id": action["spell"],
                    "delta_gold": -action["gold_cost"],
                    "name": records[action["spell"]]["name"],
                    "evidence": action["evidence"],
                }
            )
    result, purchases = [], None
    for level, point in points.items():
        if level > 1 and purchases is None:
            # The fixed ordinary itinerary collects gold and buys all training lessons before
            # its first circuit. Later full-bed and travel opportunities have no additional fee.
            funds = point["state"]["gold"]
            purchases = {
                name: assets.decide(
                    funds,
                    records,
                    point["state"],
                    gear=name != "owned_only",
                    spell=name != "no_spell_purchase",
                )
                for name in ("baseline", "owned_only", "no_spell_purchase")
            }
        ledger = [r for r in receipts if r["window"] <= point["stage"]]
        common = {
            "stage": _STAGES.get(level, f"level-{level}"),
            "level": level,
            "family": family,
            "roll_seed": start["roll_seed"],
            "race_id": source["race_id"],
            "route_window": point["stage"],
        }
        view = {**common, **assets.view(point, records, (purchases or {}).get("baseline", []), ledger)}
        variants = {
            name: {**common, **assets.view(point, records, (purchases or {}).get(name, []), ledger)}
            for name in ("owned_only", "no_spell_purchase")
        }
        result.append({**view, "variants": variants})
    return result


class CheckpointCache:
    """Job-local cache. Only completed states are retained and callers receive detached JSON."""

    def __init__(self, rules=None, *, cache_bytes=8 << 20):
        self.rules = _progression_service_rules(rules)
        self.cache_bytes = integer(cache_bytes, "checkpoint cache bytes", 0, 256 << 20)
        self._entries = OrderedDict()
        self._bytes = 0
        default = discovery_preset("creation_to_cap")["progression"]
        self.default = {
            **default,
            "itinerary": {
                **default["itinerary"],
                "cycles": 7000,
                "allocation_order": list(_ORDER),
                "alternate_allocation_orders": [],
            },
        }

    def project(
        self,
        start,
        progression=None,
        *,
        levels=(1, 15, 45),
        family=None,
        max_nodes=200_000,
        wall_seconds=30,
        memory_bytes=256 << 20,
        cancel=None,
    ):
        before = perf_counter()
        require(
            isinstance(levels, (list, tuple))
            and len(levels) > 0
            and levels[0] == 1
            and all(type(n) is int and 1 <= n <= 45 for n in levels)
            and list(levels) == sorted(set(levels)),
            "levels must begin at birth and increase to at most 45",
        )
        query = deepcopy(self.default if progression is None else progression)
        fields(query, {"goal", "itinerary", "require_starting_damage"}, "beginner progression")
        require(
            isinstance(query.get("itinerary"), dict)
            and not query["itinerary"].get("alternate_allocation_orders"),
            "beginner progression requires one committed itinerary allocation policy",
        )
        require(not set(query.get("goal", {})) - {"level"}, "beginner milestones require a level goal")
        require(
            "specialization" not in query["itinerary"],
            "beginner itinerary supports school masteries without a path selection",
        )
        require(
            all(type(v) is int and v > 0 for v in (max_nodes, memory_bytes)),
            "beginner progression requires positive node and memory budgets",
        )
        require(
            type(wall_seconds) in (int, float) and 0 < wall_seconds <= 86400,
            "invalid beginner progression time budget",
        )
        start, source = _birth(start, self.rules)
        family = family or class_identity(self.rules["content_hash"], source["race_id"], start["class"])
        query = {**query, "goal": {"level": levels[-1]}}
        key = digest([self.rules["content_hash"], family, start, query, list(levels)])
        deadline = before + wall_seconds
        reason = stop_reason(cancel, deadline)
        if not reason and key in self._entries:
            answer = json.loads(self._entries[key])
            self._entries.move_to_end(key)
            return {
                **answer,
                "cache_hit": True,
                "work_seconds": perf_counter() - before,
                "counters": {"nodes": 0, "leaves": 0, "pruned": 0, "cache_hits": 0, "work_bytes": 0},
            }
        plan = {"routes": [], "first_gap": None, "termination": "exhausted", "counters": {"nodes": 0}}
        if reason:
            plan = interrupted_report(reason, {}, "before_search", 0, 1, levels[-1])
        elif levels[-1] > 1:
            bound = bind_itinerary(query, start, self.rules, max_cycles=7000)
            request = {
                **bound,
                "start": start,
                "checkpoints": sorted({2, *levels}),
                "search": {
                    "max_nodes": max_nodes,
                    "memory_bytes": memory_bytes,
                    "wall_seconds": wall_seconds,
                    "final_stage_only": False,
                    "retain_states": False,
                },
            }
            plan = plan_progression(
                request,
                ruleset=self.rules,
                cancel=cancel,
                _lifecycle=True,
                _checkpoint_prefix=True,
                _deadline=deadline,
            )
        route = plan["routes"][0] if plan["routes"] else plan.get("verified_prefix")
        stages = _stages(start, source, levels, route, family, self.rules)
        complete = len(stages) == len(levels) and plan["termination"] == "exhausted"
        result = {
            "status": "complete" if complete else plan["status"],
            "termination": plan["termination"],
            "first_gap": plan["first_gap"],
            "cache_hit": False,
            "checkpoints": stages,
            "policy": _policy(start, source, query, self.rules, route),
            "counters": {"nodes": 0, **plan["counters"]},
            "work_seconds": perf_counter() - before,
        }
        encoded = json.dumps(result, separators=(",", ":"), allow_nan=False).encode()
        if complete and len(encoded) <= self.cache_bytes:
            while self._entries and self._bytes + len(encoded) > self.cache_bytes:
                _, old = self._entries.popitem(last=False)
                self._bytes -= len(old)
            self._entries[key] = encoded
            self._bytes += len(encoded)
        # Each scenario receives a detached nested state, even when its base fields
        # and the cheaper sensitivity branch happened to be mechanically identical.
        return json.loads(encoded)

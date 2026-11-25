"""Joint, native search of legal equipment and single-effect spell settings."""
from copy import deepcopy
from dataclasses import astuple, replace
import hashlib
import json
from time import perf_counter

from . import equipment
from .gear_capacity import capacity
from .gear_replay import PAIRS, replay
from .gear_request import mapping, prepare_inventory
from .ruleset import _installed_combat_rules, validate_combat_ruleset
from .spell_request import parse_spell_request

SPELL_FIELDS = {"schema_version", "ruleset_hash", "caster", "target", "spell", "domain", "price_factor"}
GEAR_FIELDS = {"character", "live_observations", "mode", "inventory", "offers", "budget", "locks",
              "exclusions", "catalog", "catalog_templates", "catalog_access", "career", "available_containers",
              "bow_left_hand", "search", "marginals", "loadout","capacity"}
SEARCH_FIELDS = {"exact", "max_nodes", "wall_seconds", "memory_bytes", "max_spells_per_loadout",
                 "workers", "objective", "top_k"}


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=True, allow_nan=False).encode()).hexdigest()


def _int(value, label, low, high):
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f"{label} must be an integer between {low} and {high}")
    return value


def _limits(request):
    import math
    raw = mapping(request.get("search", {}), "gear search")
    if set(raw)-SEARCH_FIELDS:
        raise ValueError("unknown gear search setting")
    if raw.get("objective", "pareto") != "pareto":
        raise ValueError("gear objective must be pareto")
    if "top_k" in raw:
        raise ValueError("gear returns the full discovered Pareto frontier; omit top_k")
    _int(raw.get("workers", 1), "gear workers", 1, 1)
    exact = raw.get("exact", False)
    if type(exact) is not bool:
        raise ValueError("exact must be boolean")
    per = _int(raw.get("max_spells_per_loadout", 0 if exact else 128),
               "max_spells_per_loadout", 0, 10_000_000)
    if exact and per:
        raise ValueError("exact search requires max_spells_per_loadout=0")
    wall = raw.get("wall_seconds", 0 if exact else 10)
    if type(wall) not in (int, float) or not math.isfinite(wall) or wall < 0:
        raise ValueError("wall_seconds must be a finite nonnegative number")
    return {"per_state": per, "max_nodes": _int(raw.get("max_nodes", 0 if exact else 250_000),
            "max_nodes", 0, 2**63-1), "memory_bytes": _int(raw.get("memory_bytes", 64 << 20),
            "memory_bytes", 1, 2**63-1), "wall_seconds": float(wall)}


def _normalize(request, rules):
    mapping(request, "gear request")
    if set(request)-GEAR_FIELDS-SPELL_FIELDS:
        raise ValueError("unknown gear request fields: " + ", ".join(sorted(set(request)-GEAR_FIELDS-SPELL_FIELDS)))
    from .character import apply_request_observations, normalize_character
    request = apply_request_observations(deepcopy(dict(request)))
    spell = {k: request[k] for k in SPELL_FIELDS if k in request}
    if ("spell" in spell) == ("domain" in spell):
        raise ValueError("provide exactly one fixed spell or automatic spell domain")
    blockers = []
    if "character" in request:
        if "caster" in request or "career" in request:
            raise ValueError("a character supplies both caster and career")
        char = normalize_character(request["character"])
        if char.get("ruleset_hash", rules["content_hash"]) != rules["content_hash"]:
            raise ValueError("character ruleset_hash differs from selected ruleset")
        request["character"] = char
        blockers.extend(char.get("unknown_mechanics", ()))
        spell["caster"] = char["gear"].get("base_caster", {})
        if not spell["caster"]:
            blockers.append("unknown unequipped caster stats")
    spec = parse_spell_request(spell, rules, auto="domain" in spell)
    if spec.caster.current_sp is None:
        blockers.append("unknown caster.current_sp")
    if type(request.get("marginals", True)) is not bool:
        raise ValueError("marginals must be boolean")
    return request, spec, sorted(set(blockers).union(spec.blockers))


def _packed(domain, extra_excluded=()):
    items = domain.items
    ids = {item.identity: i for i, item in enumerate(items)}
    legends = {s: n for n, s in enumerate(sorted({i.legendary for i in items if i.legendary}))}
    budget = dict(domain.budget) if domain.mode == "owned_plus_budget" else {}
    locks = dict(domain.locks)
    all_slots = [[] for _ in range(27)]
    copies = []
    for index, item in enumerate(items):
        prices = dict(item.price or ())
        copies.append((item.modifiers, tuple(prices.get(k, 0) for k in budget),
                       legends.get(item.legendary, -1), -1 if item.worn is None else item.worn, item.owned))
        if item.identity not in extra_excluded:
            for slot, mask in item.placements:
                all_slots[slot].append((index, mask))
    preferred = {domain.slots[second]: domain.slots[first] for second, first in PAIRS.items()}
    slots = []
    for n, entries in enumerate(all_slots):
        # Start with currently worn or high caster contributions to find strong feasible incumbents early.
        entries.sort(key=lambda p: (items[p[0]].worn != n, -sum(items[p[0]].modifiers), p[0]))
        lock = -2 if n not in locks else -1 if locks[n] is None else ids.get(locks[n], len(items))
        current = ids.get(domain.current[n], len(items)) if n in domain.current else -1
        slots.append((lock, current, preferred.get(n, -1), entries))
    return copies, slots, tuple(budget.values())


def _run(domain, spec, limits, token, removed=()):
    from . import _gear
    tic = perf_counter()
    packed = _packed(domain,removed)
    setup_seconds = perf_counter() - tic
    remaining = max(1e-12,limits["wall_seconds"]-setup_seconds) if limits["wall_seconds"] else 0
    native = _gear.traverse(spec.native_context(), spec.domains, *packed,
                            **{**limits, "wall_seconds": remaining}, cancel=token,
                            capacity=astuple(domain.policy),empty_mask=domain.empty_mask)
    if native["first_feasible_seconds"] is not None:
        native["first_feasible_native_seconds"] = native["first_feasible_seconds"]
        native["first_feasible_seconds"] += setup_seconds
    validated = [replay(row, domain, spec,domain.policy,domain.empty_mask) for row in native.pop("results")]
    validated.sort(key=lambda r: (-r["metrics"]["dps"], -(r["metrics"]["damage_per_sp"] or 0),
                                  tuple(r["spell"].values()), tuple(r["loadout"].values())))
    return native, validated


def _marginals(domain, spec, limits, token, selected, work, deadline):
    item_ids = sorted({key for r in selected for key in r["loadout"].values() if key is not None})
    locked = {identity for _, identity in domain.locks}
    report = {}
    for key in item_ids:
        if key in locked:
            report[key] = {"status": "locked"}
            continue
        remaining_nodes = limits["max_nodes"] - work["nodes"] if limits["max_nodes"] else 0
        seconds = max(0.0, deadline - perf_counter()) if deadline is not None else 0.0
        if (deadline is not None and seconds <= 0) or (limits["max_nodes"] and remaining_nodes <= 0):
            report[key] = {"status": "budget_exhausted"}
            continue
        stats, choices = _run(domain, spec, {**limits, "max_nodes": remaining_nodes,
                             "wall_seconds": seconds}, token, (key,))
        work["nodes"] += stats["nodes"]
        dps = max((r["metrics"]["dps"] for r in choices), default=None)
        eff = max((r["metrics"]["damage_per_sp"] for r in choices
                   if r["metrics"]["damage_per_sp"] is not None), default=None)
        report[key] = {"status": _status(stats, choices), "termination": stats["termination"], "exact": _exact(stats),
            "best_dps_without": dps, "best_damage_per_sp_without": eff, "nodes": stats["nodes"],
            "delta_best_dps": max(r["metrics"]["dps"] for r in selected)-dps if dps is not None else None,
            "delta_best_damage_per_sp": max(r["metrics"]["damage_per_sp"] for r in selected
                if r["metrics"]["damage_per_sp"] is not None)-eff if eff is not None else None}
    return report


def _exact(stats):
    return stats["termination"] == "exhausted" and not (stats["sampled_spells"] or stats["uncertain_sp_recipes"])


def _status(stats, rows):
    if stats["termination"] == "cancelled":
        return "cancelled"
    if _exact(stats):
        return "optimal_proven" if rows else "infeasible_proven"
    return "best_found_bounded" if rows else "no_feasible_found"


class GearService:
    def optimize(self, request, *, ruleset=None, cancel=None):
        return self._query(request, ruleset, cancel, fixed=False)

    def evaluate(self, request, *, ruleset=None, cancel=None):
        return self._query(request, ruleset, cancel, fixed=True)

    def _query(self, raw, rules, token, fixed):
        if isinstance(raw, dict) and "encounter" in raw:
            from .loadout_encounter import single_checkpoint
            return single_checkpoint(raw, equipment_search=True, fixed=fixed, ruleset=rules, cancel=token)
        start = perf_counter()
        rules = _installed_combat_rules() if rules is None else validate_combat_ruleset(rules)
        if rules["equipment_hash"] != equipment.EQUIPMENT_HASH:
            raise ValueError("Gear data differs from the pinned ruleset")
        request, spec, blockers = _normalize(raw, rules)
        limits = _limits(request)
        empty_locks = [name for name,key in mapping(request.get("locks",{}),"locks").items() if key is None]
        if fixed:
            from .gear_request import _source
            _, entries = _source(request)
            current = {e["item"]["equipSlot"]: e["instance_id"] for e in entries
                       if e["item"].get("equipSlot") is not None}
            slots = {k:v for k,v in equipment.equipment_catalog()["slots"].items() if 0 <= v < 27}
            selected = request.get("loadout", {k: current[n] for k,n in slots.items() if n in current})
            mapping(selected, "loadout")
            loaded = {**dict.fromkeys(slots), **selected}
            if any(loaded.get(k) != v for k,v in mapping(request.get("locks", {}), "locks").items()):
                raise ValueError("fixed loadout conflicts with requested locks")
            request = {**request, "locks": loaded}
        elif "loadout" in request:
            raise ValueError("use gear evaluate for a fixed loadout, or locks for optimization")
        domain = prepare_inventory(request)
        policy = capacity(request,domain)
        domain = replace(domain,policy=policy,empty_mask=sum(1<<domain.slots[name] for name in empty_locks))
        if domain.mode == "owned_plus_budget" and spec.caster.gold is not None and dict(domain.budget).get("gold",0)>spec.caster.gold:
            raise ValueError("gold budget exceeds caster's available gold")
        constrained = {k for _, k in domain.locks if k is not None}
        for key in sorted(constrained.intersection(domain.filtered)):
            reasons = domain.filtered[key]
            if key in domain.unsupported or any("unknown" in r for r in reasons):
                blockers.append(f"{key}: " + ", ".join(reasons))
        base = {"schema_version": 1, "engine": "native-cython-cpp17", "source_sha": rules["source_sha"],
                "ruleset_hash": rules["content_hash"], "input_hash": _hash(request), "mode": domain.mode,
                "filtered": dict(domain.filtered), "unscored_items":dict(domain.unsupported),
                "unsupported_mechanics": blockers,
                "candidate_count": len(domain.items), "generated_candidates": domain.generated,
                "catalog_scope": equipment.gear_catalog_scope(domain.mode == "theoretical_bis")
                     if domain.generated else "explicit physical candidates",
                "proof_scope": "Nondominated DPS and damage/SP among visited supported loadouts and affordable spells. Equal metrics share a representative.",
                "resource_policy": "hypothetical fixed post-swap SP" if policy.explicit>=0 else
                    "observed current SP clipped to supported post-removal capacity; unresolved swaps counted separately",
                "assumptions": ["one ordinary PvE target, one landed cast per recovery cycle",
                                "caster supplies the unequipped baseline",
                                "gear purchase budget excludes Spell Maker acquisition and travel",
                                "loadout records item anchors; occupancy includes both hands of a two-handed item"]}
        if blockers:
            return {**base, "candidates": [], "counters": {}, "termination": "unsupported",
                    "status": "unsupported", "exact": False, "marginals": {}}
        prepared_at = perf_counter()
        seconds = max(1e-12,limits["wall_seconds"]-(prepared_at-start)) if limits["wall_seconds"] else 0
        stats, rows = _run(domain, spec, {**limits, "wall_seconds": seconds}, token)
        if stats["first_feasible_seconds"] is not None:
            # Native first time is reported by the traversal. Preparation and replay
            # are included in the total service time separately.
            stats["first_feasible_seconds"] += prepared_at-start
        marginal_work = {"nodes": stats["nodes"]}
        deadline = start + limits["wall_seconds"] if limits["wall_seconds"] else None
        marginals = _marginals(domain, spec, limits, token, rows, marginal_work, deadline) if (
            not fixed and request.get("marginals", True) and stats["termination"] != "cancelled") else {}
        exact = _exact(stats)
        status = _status(stats, rows)
        termination = stats["termination"]
        if termination == "exhausted" and stats["sampled_spells"]:
            termination = "spell_sample_limit"
        if termination == "exhausted" and stats["uncertain_sp_recipes"]:
            termination = "unknown_swap_capacity"
        if any(r["status"]=="cancelled" for r in marginals.values()):
            termination = "cancelled"
            status = "cancelled"
        counters = {k:v for k,v in stats.items() if k != "termination"}
        return {**base, "counters": counters, "status": status, "termination": termination,
                "exact": exact, "validation": {"finalists_checked":len(rows)},
                "result_hash": _hash({"input": base["input_hash"], "rules": rules["content_hash"],
                                      "status":status,"termination":termination,"candidates":rows,"marginals":marginals}),
                "candidates": rows, "marginals": marginals, "total_nodes": marginal_work["nodes"],
                "elapsed_seconds": perf_counter()-start}


def optimize_gear(request, *, ruleset=None, cancel=None):
    return GearService().optimize(request, ruleset=ruleset, cancel=cancel)


def evaluate_gear(request, *, ruleset=None, cancel=None):
    return GearService().evaluate(request, ruleset=ruleset, cancel=cancel)

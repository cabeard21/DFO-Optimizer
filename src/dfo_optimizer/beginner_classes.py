"""Permanently committed beginner classes, screened before any lifecycle fork."""

import json
from copy import deepcopy
from time import perf_counter

from .beginner_creation import (
    _read,
    _seeds,
    catalog_masks,
    compliance,
    creation,
    exclusion,
    sampling_preference,
    starter_tables,
)
from .class_document import parse_document
from .discovery_request import resolve_ids
from .native import require_native
from .ruleset import _service_rules
from .search import _compile, _game_doc, class_identity
from .search_request import parse_request

# Cost slices are disjoint. Each bounded profile spends a share on the fast-advancement
# end and on successively less restrictive budgets for advantageous permanent choices.
_QUICK = (-12, -11, -8, 0, 16)
_STANDARD = (*_QUICK, -10, -9, -7, -6, -5, -4, -2, 4, 8, 12, 20, 24, 28, 32, 36, 40)
_THOROUGH = (*_STANDARD, *(i for i in range(-12, 41) if i not in _STANDARD))
_LANE_NODES = 18000
_SLICES = {
    "quick": (_QUICK, 4),
    "standard": (_STANDARD, 24),
    "thorough": (_THOROUGH, 100),
}
_REFINED_SIZES = {"quick": (2048, 32), "standard": (8192, 96), "thorough": (32768, 384)}
_FIELDS = {
    "race_ids",
    "hp_values",
    "attribute_domains",
    "skill_domains",
    "difficulty_values",
    "trait_ids",
    "required_trait_ids",
    "top_k",
}


def beginner_compliance(document, race_id, *, ruleset=None, roll_seeds=(42, 43)):
    """Certify an imported class against creation, mastery and real starting inventory."""
    return compliance(document, race_id, _service_rules(ruleset), _seeds(roll_seeds))


def _family(doc, race, origin, rules, seeds):
    return {
        "id": class_identity(rules["content_hash"], race, doc),
        "origin": origin,
        "start": {
            "type": "new_character",
            "profile": "custom",
            "race_id": race,
            "class": deepcopy(doc),
        },
        "compliance": compliance(doc, race, rules, seeds),
    }


def _manual(rules, seeds):
    source = creation()
    if source["source_sha"] != rules["source_sha"]:
        raise ValueError("Beginner templates require the verified creation snapshot")
    families = []
    for entry, oracle in zip(json.loads(_read("beginner-manual.json")), source["templates"], strict=True):
        doc, race = entry["class"], entry["race_id"]
        family = _family(doc, race, "manual", rules, seeds)
        verdict = family["compliance"]
        if (
            not verdict["passed"]
            or doc["name"] != oracle["name"]
            or race != oracle["race_id"]
            or verdict["advancement_multiplier"] != oracle["multiplier"]
            or verdict["magicka_multiplier"] != oracle["magery"]
            or verdict["difficulty_points"] != oracle["difficulty"]
        ):
            raise RuntimeError("Manual beginner template differs from pinned creator verification")
        families.append(family)
    return families


def manual_classes(*, ruleset=None, roll_seeds=(42, 43)):
    return _manual(_service_rules(ruleset), _seeds(roll_seeds))


def _counterfactuals(reference, rules, seeds):
    start = reference["start"]
    doc = start["class"]
    swapped = [
        {**p, "secondary": "ebony"}
        if p == {"primary": "forbiddenMaterial", "secondary": "adamantium"}
        else dict(p)
        for p in doc["disadvantages"]
    ]
    probes = []
    for origin, race, variant, changed, before, after in (
        ("race_comparison", 5, doc, "race_id", start["race_id"], 5),
        (
            "material_comparison",
            start["race_id"],
            {**doc, "disadvantages": swapped},
            "forbiddenMaterial",
            "adamantium",
            "ebony",
        ),
    ):
        family = _family(variant, race, origin, rules, seeds)
        if (
            not family["compliance"]["passed"]
            or family["compliance"]["difficulty_points"] != reference["compliance"]["difficulty_points"]
        ):
            raise RuntimeError("Controlled beginner counterfactual failed independent compliance")
        probes.append(
            {
                **family,
                "counterfactual": {
                    "reference_id": reference["id"],
                    "changed_field": changed,
                    "from": before,
                    "to": after,
                },
            }
        )
    return probes


def _compile_domain(domain, target, top, exact, rules, seeds, max_nodes, memory, seconds):
    forbidden = [
        r["id"]
        for r in rules["traits"]
        if exclusion(r["primary"], r["secondary"])
        or ("trait_ids" not in domain and sampling_preference(r["primary"], r["secondary"]))
    ]
    request = {k: v for k, v in domain.items() if k not in ("difficulty_values", "top_k")}
    # Five schools in primary and major leave one equipped-backup proficiency in
    # the first two groups. Slots inside each group remain ordered and free.
    if "skill_domains" not in request:
        schools = [s["id"] for s in rules["skills"] if s["magic"]]
        major = [*schools, 28, 29, 31, 32]
        request["skill_domains"] = [schools] * 3 + [major] * 3 + [list(range(35))] * 6
    spec = parse_request(
        {
            **request,
            "profile": "spellcaster_discovery_v1",
            "top_k": top,
            "objective": "exhaustive" if exact else "diverse",
            "difficulty_points": target,
            "excluded_traits": forbidden,
            "roll_seeds": seeds,
            "discovery_seed": target + 93,
            "max_nodes": max_nodes,
            "memory_bytes": memory,
            "wall_seconds": seconds,
        },
        rules,
    )
    args, _, _, reason = _compile(spec, rules)
    args["discovery"].update(beginner=starter_tables(), stage_items=list(catalog_masks().values()))
    return args, reason


def _selection(rows, capacity, exact, previous=(), *, cancel=None, deadline=None, refined=False):
    if exact:
        return rows[:capacity]
    if not rows:
        return []
    indices = {id(raw): i for i, (_, raw) in enumerate(rows)}
    prior = [indices[id(raw)] for _, raw in previous]
    seconds = max(1e-12, deadline - perf_counter()) if deadline else 0
    native = require_native()
    indices = native.beginner_panel(rows, prior, capacity, cancel, seconds, refined=True) if refined else (
        native.beginner_panel(rows, prior, capacity, cancel, seconds)
    )
    return [rows[i] for i in indices]


def _options(thoroughness, domain, exact, max_nodes):
    if not isinstance(thoroughness, str) or thoroughness not in _SLICES or type(exact) is not bool:
        raise ValueError("Invalid beginner thoroughness or exhaustive switch")
    if not isinstance(domain, dict) or set(domain) - _FIELDS:
        raise ValueError("Unknown beginner class domain field")
    if "hp_values" in domain and domain["hp_values"] != [30]:
        raise ValueError("The beginner class profile requires 30 class HP")
    targets, quota = _SLICES[thoroughness]
    targets = domain.get("difficulty_values", targets)
    if (
        not isinstance(targets, (list, tuple))
        or not targets
        or any(type(i) is not int or not -12 <= i <= 40 for i in targets)
        or len(set(targets)) != len(targets)
    ):
        raise ValueError("difficulty_values must be distinct legal target costs between -12 and 40")
    top = domain.get("top_k", 100 if exact else quota)
    if type(top) is not int or not 1 <= top <= 10000:
        raise ValueError("top_k requires 1..10000")
    return targets, top, len(targets) * _LANE_NODES if max_nodes is None else max_nodes


def _material_cost_bound(rules):
    """Optimistic costs ignore conflicts and all additional beginner kit gates."""
    allowed = [t for t in rules["traits"] if not (
        exclusion(t["primary"], t["secondary"]) or sampling_preference(t["primary"], t["secondary"])
    )]
    magery = next(t for t in allowed if (t["primary"], t["secondary"]) == (
        "increasedMagery", "intInSpellPoints3"
    ))
    # All other advantages at the pin cost at least zero. Include negative
    # ones if ever supplied to keep the estimate optimistic.
    mandatory = 30 - 8 + magery["cost"] + sum(
        min(0, t["cost"]) for t in allowed if t["side"] == "advantage" and t != magery
    )
    metals = {t["secondary"]: t["cost"] for t in allowed if t["primary"] == "forbiddenMaterial"}
    other = [t["cost"] for t in allowed if t["side"] == "disadvantage" and t["primary"] != "forbiddenMaterial"]
    picks = rules["limits"]["max_picks"]

    def lowest(costs):
        return mandatory + sum(sorted([c for c in [*costs, *other] if c < 0])[:picks])

    cheapest = sorted(metals.values())
    required = next((n for n in range(len(metals) + 1)
                     if lowest(cheapest[:n]) <= rules["limits"]["difficulty_min"]), None)
    retained = {"elven": {"elven"}, "steel": {"steel"}, "steel_and_elven": {"steel", "elven"}}
    return {"maximum_metals_at_floor": None if required is None else len(metals) - required,
            "lowest_cost_by_retained_materials": {
                label: lowest([cost for metal, cost in metals.items() if metal not in keep])
                for label, keep in retained.items()
            },
            "scope": "Optimistic bound for the sampled beginner trait policy, ignoring compatibility and kit gates."}


def _lanes(targets, packed_traits, trait_rows, material_bound):
    """Keep material-sensitive samples disjoint from ordinary difficulty slices."""
    protected_ids = {t["secondary"]: t["id"] for t in trait_rows
                     if t["primary"] == "forbiddenMaterial" and t["secondary"] in ("steel", "elven")}
    thresholds = material_bound["lowest_cost_by_retained_materials"]
    for target in targets:
        for kept in ((), ("elven",), ("steel",), ("steel", "elven")):
            name = "_and_".join(kept)
            if kept and target < thresholds[name]:
                continue
            excluded = {protected_ids[metal] for metal in kept}
            required = set(protected_ids.values()) - excluded
            traits = [(*trait[:4], trait[4] or trait[0] in required, trait[5])
                      for trait in packed_traits if trait[0] not in excluded]
            yield target, name or None, traits


def _single_edits(manual, domain, args, targets, rules):
    """Each proposed edit has a concrete, independently certified witness."""
    names = {
        "/".join(filter(None, (t["primary"], t["secondary"]))).casefold(): t["id"] for t in rules["traits"]
    }
    required = resolve_ids(domain.get("required_trait_ids", []), names, "required_trait_ids")
    eligible = {r[0] for r in args["traits"]}
    edits = []
    for family in manual:
        doc = family["start"]["class"]
        draft, _ = parse_document(doc, rules)
        picks = set(draft.advantages + draft.disadvantages)
        if (
            family["start"]["race_id"] not in args["races"]
            or family["compliance"]["difficulty_points"] not in targets
            or not picks <= eligible
            or not all(v in d for v, d in zip(draft.attributes, args["attributes"], strict=True))
            or not all(v in d for v, d in zip(draft.skills, args["skills"], strict=True))
        ):
            continue
        missing = set(required) - picks
        if len(missing) == 1:
            trait = next(iter(missing))
            edits.append(
                {
                    "field": "required_trait_ids",
                    "remove_id": trait,
                    "witness": family["id"],
                    "restores_eligibility": True,
                    "edit_count": 1,
                    "message": f"Remove the requirement for {next(k for k, v in names.items() if v == trait)} "
                    f"to permit {doc['name']}.",
                }
            )
    return edits


def beginner_roster(
    thoroughness="standard",
    *,
    ruleset=None,
    cancel=None,
    roll_seeds=(42, 43),
    max_nodes=None,
    wall_seconds=0,
    memory_bytes=64 << 20,
    domain=None,
    exhaustive=False,
    _refined_wave=None,
):
    """Admit classes for a shared lifecycle evaluation; references are always listed separately."""
    started = perf_counter()
    domain = {} if domain is None else domain
    targets, capacity, nodes = _options(thoroughness, domain, exhaustive, max_nodes)
    refined = _refined_wave is not None
    rules, seeds = _service_rules(ruleset), _seeds(roll_seeds)
    samples = []
    # Validate limits and the full caller domain even when a pre-cancelled token is supplied.
    first_args, first_reason = _compile_domain(
        domain,
        targets[0],
        capacity,
        exhaustive,
        rules,
        seeds,
        nodes,
        memory_bytes,
        wall_seconds,
    )
    deadline = started + wall_seconds if wall_seconds else None

    def interrupted():
        return (
            "cancelled"
            if cancel is not None and cancel.cancelled()
            else "time_limit"
            if deadline and perf_counter() >= deadline
            else None
        )

    counts = {
        "nodes": 0,
        "legal": 0,
        "screened": 0,
        "leaf_visits": 0,
        "native_retained": 0,
    }
    slices, candidates, protected = [], [], []
    traits = {r["id"]: r for r in rules["traits"]}
    skills = {r["id"]: r for r in rules["skills"]}
    native = require_native()
    material_bound = _material_cost_bound(rules) if refined else None
    lanes = (list(_lanes(targets, first_args["traits"], traits.values(), material_bound))
             if refined and tuple(targets) != (-12,) else [(cost, None, first_args["traits"]) for cost in targets])
    for i, (target, retained_metal, lane_traits) in enumerate(lanes):
        if interrupted() or (nodes and counts["nodes"] >= nodes):
            break
        args = {
            **first_args,
            "target": target,
            "traits": lane_traits,
            "discovery": {**first_args["discovery"], "seed": target + 93},
        }
        if refined:
            base_attempts, _ = _REFINED_SIZES[thoroughness]
            wave_scale = 1 << min(_refined_wave, 3) if thoroughness == "thorough" else 1
            share, remainder = divmod(base_attempts * wave_scale, len(lanes))
            attempts = max(1, share + int(i < remainder))
            args["discovery"].update(
                seed=(target + 93 + 1_000_003 * _refined_wave + (65537 * (i + 1) if retained_metal else 0)) % (1 << 32),
                sample_attempts=attempts,
            )
        args["top_k"] = capacity if exhaustive or domain else 24
        if refined and len(lanes) > 1:
            args["top_k"] = min(capacity, max(8, (2 * capacity + len(lanes) - 1) // len(lanes)))
        if nodes:
            remaining = nodes - counts["nodes"]
            args["max_nodes"] = (
                remaining
                if exhaustive
                else max(1, remaining // (len(lanes) - i))
                if domain
                else min(_LANE_NODES, remaining)
            )
        elif not exhaustive and not domain:
            args["max_nodes"] = _LANE_NODES
        if deadline:
            args["wall_seconds"] = max(1e-12, deadline - perf_counter())
        if first_reason:
            slices.append(
                {
                    "difficulty": target,
                    "termination": "constraint_conflict",
                    "reason": first_reason,
                }
            )
            continue
        result = native.search_classes(**args, cancel=cancel)
        counts["nodes"] += result["nodes"]
        counts["legal"] += result["beginner_admissible"]
        counts["screened"] += result["unique_screened"]
        counts["leaf_visits"] += result["leaves"]
        counts["native_retained"] += len(result["results"])
        slices.append(
            {
                "difficulty": target,
                "termination": result["termination"],
                "screened": result["unique_screened"],
                "passed": result["beginner_admissible"],
                "nodes": result["nodes"],
                "kit_rejections_by_mask": result["beginner_rejections"],
                "work_bytes": result["work_bytes"],
                **({"seed": args["discovery"]["seed"], "sample_attempts": result["attempts"],
                    "sample_attempt_limit": attempts, "retained_metal": retained_metal} if refined else {}),
            }
        )
        rows = result["results"][: max(0, capacity - len(samples))] if exhaustive else result["results"]
        tagged = [(target, r) for r in rows]
        samples.extend(tagged)
        if retained_metal and tagged:
            protected.extend(_selection(tagged, 1, False, cancel=cancel, deadline=deadline, refined=True))
    selected = []
    if exhaustive or domain:
        selected = _selection(samples, capacity, exhaustive, protected[:capacity], cancel=cancel,
                              deadline=deadline, refined=refined)
    else:
        for slice_targets, tier_limit in _SLICES.values():
            pool = [r for r in samples if r[0] in slice_targets]
            selected = _selection(
                pool, min(capacity, tier_limit), False, selected, cancel=cancel, deadline=deadline
            )
            if tier_limit >= capacity:
                break
    for target, row in selected:
        if interrupted():
            break
        doc = _game_doc(row, traits, skills)
        family = _family(doc, row["race"], "discovered", rules, seeds)
        verdict, screen = family["compliance"], row["screen"]
        backups = {w["skill_id"] for w in verdict["backup_weapons"]}
        eligible = [r["eligible"] for r in verdict["catalog_eligibility"]["by_family"].values()]
        sp = sum(b["sp"] for b in verdict["births"]) / len(seeds)
        if (
            not verdict["passed"]
            or verdict["difficulty_points"] != target
            or sp != screen["mean_birth_sp"]
            or round(400 * min(b["headroom_kg"] for b in verdict["births"]))
            != screen["minimum_headroom_units"]
            or sum(1 << k for k in backups) != screen["usable_backup_skill_mask"]
            or eligible != screen["eligible_stage_items"]
        ):
            raise RuntimeError("Beginner native screen disagrees with independent creation replay")
        candidates.append({**family, "native_screen": screen})
    manual = [] if interrupted() else _manual(rules, seeds)
    if refined:
        manual = [f for f in manual if f["compliance"]["difficulty_points"] in targets]
    probes = _counterfactuals(manual[0], rules, seeds) if manual and not domain else []
    counts.update(admitted=len(candidates), manual=len(manual), controlled_comparisons=len(probes))
    enumerated = len(slices) == len(targets) and all(
        s["termination"] == "constraint_conflict" or exhaustive and s["termination"] == "exhausted"
        for s in slices
    )
    admitted = enumerated and len(candidates) == counts["legal"]
    conflicts = [s["reason"] for s in slices if s["termination"] == "constraint_conflict"]
    edits = (
        _single_edits(manual, domain, first_args, targets, rules)
        if enumerated and not counts["legal"]
        else []
    )
    scope = {
        "enumeration_complete": enumerated,
        "admission_complete": admitted,
        "difficulty_values": list(targets),
        "slices": slices,
        "termination": interrupted() or ("exhausted" if enumerated else "bounded"),
        "conflicts": list(dict.fromkeys(conflicts)),
        "claim": "Within the declared class domain and ordinary birth assumptions only.",
        "suggested_edits": (
            [
                "Submit a new request with the conflicting required trait removed or an eligible domain supplied."
            ]
            if conflicts
            else []
        ),
        "verified_minimal_edits": edits,
        "kit_rejection_bits": {
            "1": "no plate",
            "2": "insufficient carry",
            "4": "no owned trained melee",
            "8": "no affordable owned direct-damage spell at birth",
        },
        "excluded_traits": {
            str(t["id"]): reason
            for t in rules["traits"]
            if (
                reason := exclusion(t["primary"], t["secondary"])
                or ("trait_ids" not in domain and sampling_preference(t["primary"], t["secondary"]))
            )
        },
        "domain_policy": {
            "hp": 30,
            "magicka": 3,
            "required_masteries": list(range(22, 28)),
            "race_ids": first_args["races"],
            "attribute_domains": first_args["attributes"],
            "ordered_skill_domains": first_args["skills"],
            "trait_ids": [r[0] for r in first_args["traits"]],
            "required_trait_ids": [r[0] for r in first_args["traits"] if r[4]],
            "advancement": "Every enumerated cost slice is reported in difficulty_values.",
        },
        "catalog_scope": {k: len(v) for k, v in catalog_masks().items()},
        "eligibility_only": "Reviewed mundane template/material combinations do not imply ownership or access.",
        **({"material_cost_bound": material_bound} if refined else {}),
    }
    return {
        "families": [*manual, *probes, *candidates],
        "reference_ids": [f["id"] for f in manual],
        "counts": counts,
        "proof_scope": scope,
    }


def refined_roster(mode, *, ruleset=None, roll_seeds=(42, 43), max_nodes=0,
                   memory_bytes=64 << 20, wall_seconds=0, cancel=None, wave=0, slower=False):
    """One deterministic, bounded mechanics sample for the revised beginner profile."""
    if not isinstance(mode, str) or mode not in _REFINED_SIZES:
        raise ValueError("Invalid beginner thoroughness")
    if type(wave) is not int or not 0 <= wave <= 2**32-1 or type(slower) is not bool:
        raise ValueError("Invalid beginner wave or advancement lane")
    _, capacity = _REFINED_SIZES[mode]
    costs = [-11, -10, -9, -8] if slower else [-12]
    return beginner_roster(mode, ruleset=ruleset, roll_seeds=roll_seeds, max_nodes=max_nodes,
                           memory_bytes=memory_bytes, wall_seconds=wall_seconds, cancel=cancel,
                           domain={"difficulty_values": costs, "top_k": capacity}, _refined_wave=wave)

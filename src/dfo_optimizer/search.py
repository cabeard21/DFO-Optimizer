"""M1 offline class search. Enumerate in native code and certify only finalists in Python."""

import hashlib
import json
from copy import deepcopy

from .class_document import FORMAT, REPUTATIONS
from .classes import disallowed_trait, validate_class_snapshot
from .native import require_native
from .ruleset import load_ruleset, validate_ruleset
from .search_request import ATTRIBUTES, MAGERY_KEYS, parse_request

ORDER_SENSITIVE = {"rapidHealing": 1, "regenerateHealth": 2, "spellAbsorption": 3}
ENGINE = "m1-class-search-v1"


def _digest(value):
    encoded = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"),
                         allow_nan=False).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()


def class_identity(ruleset_hash, race_id, class_doc):
    """Identify the actual external race and ordered game document under one ruleset."""
    return _digest([ruleset_hash, race_id, class_doc])


def _policy(request):
    return {
        "allow_high_risk": request.allow_high_risk_disadvantages,
        "require_day_and_night_casting": request.require_day_and_night_casting,
        "allow_unverified_advantageous_behavior": request.allow_unverified_advantageous_behavior,
    }


def _traits(request, rules):
    by_id = {r["id"]: r for r in rules["traits"]}
    required = set(request.required_trait_ids)
    multiplier = request.magicka_multiplier
    if multiplier is not None and MAGERY_KEYS[multiplier] is not None:
        required.add(next(r["id"] for r in rules["traits"] if r["primary"] == "increasedMagery"
                          and r["secondary"] == MAGERY_KEYS[multiplier]))

    allowed, excluded = [], []
    for i in request.trait_ids:
        row = by_id[i]
        reason = disallowed_trait(row["primary"], row["secondary"], **_policy(request))
        if row["primary"] == "increasedMagery" and multiplier is not None:
            if row["secondary"] != MAGERY_KEYS[multiplier]:
                reason = "magicka_multiplier_lock"
        if reason:
            excluded.append({"id": i, "reason": reason})
        else:
            allowed.append(row)

    # Material bans establish feasible examples early. This order removes no legal completion.
    def order(r):
        return (r["id"] not in required, r["primary"] != "forbiddenMaterial",
                r["side"] != "disadvantage", r["cost"] if r["primary"] == "forbiddenMaterial" else 0,
                r["id"])

    rows = [(r["id"], int(r["side"] == "disadvantage"), r["cost"], tuple(r["conflicts"]),
             r["id"] in required, ORDER_SENSITIVE.get(r["primary"], 0))
            for r in sorted(allowed, key=order)]
    return rows, required, excluded


def _compile(request, rules):
    rows, required, excluded = _traits(request, rules)
    missing = required.difference(row[0] for row in rows)
    reason = f"required trait IDs outside eligible domain: {sorted(missing)}" if missing else None
    domains = (request.race_ids, request.hp_values, *request.attribute_domains, *request.skill_domains)
    if any(not d for d in domains):
        reason = "an explicit race, HP, attribute or skill slot domain is empty"
    kwargs = {
        "traits": rows, "hp_values": request.hp_values, "races": request.race_ids,
        "attributes": request.attribute_domains, "skills": request.skill_domains,
        "target": request.difficulty_points, "top_k": request.top_k, "max_nodes": request.max_nodes,
        "wall_seconds": request.wall_seconds, "memory_bytes": request.memory_bytes,
        "objective": request.objective, "stop_after_top": request.objective == "examples" and not request.exact,
        "require_magic": request.require_magic_school,
        "magic_skills": tuple(r["id"] for r in rules["skills"] if r["magic"]),
    }
    return kwargs, required, excluded, reason


def _game_doc(candidate, traits, skills):
    picks = {"advantage": [], "disadvantage": []}
    for i in candidate["traits"]:
        row = traits[i]
        pick = {"primary": row["primary"]}
        if row["secondary"]:
            pick["secondary"] = row["secondary"]
        picks[row["side"]].append(pick)
    names = [skills[i]["name"] for i in candidate["skills"]]
    return {
        "format": FORMAT, "version": 1, "name": "DFO class",
        "hitPointsPerLevel": candidate["hp"],
        "skills": {"primary": names[:3], "major": names[3:6], "minor": names[6:]},
        "attributes": dict(zip(ATTRIBUTES, candidate["attributes"], strict=True)),
        "advantages": picks["advantage"], "disadvantages": picks["disadvantage"],
        "reputations": dict.fromkeys(REPUTATIONS, 0),
    }


def _domain_check(row, req, eligible, required):
    return (
        row["race"] in req.race_ids and row["hp"] in req.hp_values
        and required <= set(row["traits"]) <= eligible
        and all(v in d for v, d in zip(row["attributes"], req.attribute_domains, strict=True))
        and all(v in d for v, d in zip(row["skills"], req.skill_domains, strict=True))
    )


def _finalists(rows, request, rules, native_request, required):
    traits = {r["id"]: r for r in rules["traits"]}
    skills = {r["id"]: r for r in rules["skills"]}
    eligible = {r[0] for r in native_request["traits"]}
    found = []
    seen = set()
    for row in rows:
        if not _domain_check(row, request, eligible, required):
            raise RuntimeError("Native finalist failed independent candidate-domain validation")
        doc = _game_doc(row, traits, skills)
        check = validate_class_snapshot(
            doc, ruleset=rules, race=row["race"], profile=request.profile,
            hp_lock=None, magery_lock=request.magicka_multiplier,
            require_magic_school=request.require_magic_school,
            difficulty_target=request.difficulty_points, **_policy(request),
        )
        if (not check["profile_legal"] or check["skipped"]
                or (request.require_magic_school and check["starting_spell_set_index"] is None)):
            raise RuntimeError(f"Native finalist failed independent class validation: {check}")
        identity = class_identity(rules["content_hash"], row["race"], doc)
        if identity in seen:
            raise RuntimeError("Native search returned a duplicate finalist")
        seen.add(identity)
        found.append({
            "class_id": identity, "race_id": row["race"], "class_doc": doc,
            "difficulty_points": check["difficulty_points"], "advancement_multiplier": check["advancement_multiplier"],
            "effective_flags": check["effective_flags"], "starting_spell_set_index": check["starting_spell_set_index"],
            "objective_value": doc["attributes"]["intelligence"] if request.objective == "max_intelligence" else None,
            "warnings": check["warnings"], "unsupported_mechanics": check["unsupported_mechanics"],
        })
    return found


def _status(termination, has_candidates):
    if termination == "cancelled":
        return "cancelled"
    if termination in ("exhausted", "constraint_conflict"):
        return "optimal_proven" if has_candidates else "infeasible_proven"
    return "best_found_bounded" if has_candidates else "no_feasible_found"


def optimize_classes(request=None, *, ruleset=None, cancel=None):
    """Run an explicit finite-domain search under the pinned online snapshot."""
    engine = require_native()
    rules = load_ruleset() if ruleset is None else validate_ruleset(deepcopy(ruleset))
    spec = parse_request(request, rules)
    native_request, required, excluded, conflict = _compile(spec, rules)
    if conflict:
        raw = {"results": [], "termination": "constraint_conflict", "nodes": 0, "pruned": 0,
               "leaves": 0, "work_bytes": 0, "first_feasible_seconds": None}
    else:
        raw = engine.search_classes(**native_request, cancel=cancel)
    candidates = _finalists(raw["results"], spec, rules, native_request, required)
    scope = {
        **spec.snapshot(), "eligible_trait_ids": sorted(row[0] for row in native_request["traits"]),
        "effective_required_trait_ids": sorted(required), "excluded_traits": excluded,
        "constraint_conflict": conflict, "attribute_order": list(ATTRIBUTES),
        "class_universe": "creator-legal classes in the supplied domains, with distinct effective trait orders",
        "ordering": "stable native traversal for equal objective values",
        "claim": "class construction at the pinned snapshot",
    }
    status = _status(raw["termination"], bool(candidates))
    input_hash = _digest([ENGINE, rules["content_hash"], spec.snapshot()])
    return {
        "schema_version": 1, "engine": ENGINE, "source_sha": rules["source_sha"],
        "ruleset_hash": rules["content_hash"], "input_hash": input_hash,
        "result_hash": _digest([input_hash, status, raw["termination"], candidates]),
        "proof_scope": scope, "status": status, "termination": raw["termination"], "candidates": candidates,
        "counters": {k: v for k, v in raw.items() if k not in ("termination", "results")},
        "validation": {"finalists_checked": len(candidates), "checker": "independent class and domain replay"},
        "unsupported_mechanics": ["starting practical damage", "training route feasibility",
                                  "combat and progression ranking", "live-server equivalence"],
    }

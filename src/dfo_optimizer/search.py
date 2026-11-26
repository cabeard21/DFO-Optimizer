"""M1 offline class search. Enumerate in native code and certify only finalists in Python."""

import hashlib
import json
from time import perf_counter

from .class_document import FORMAT, REPUTATIONS
from .discovery_request import DiscoveryRequest
from .classes import disallowed_trait, validate_class_snapshot
from .native import require_native
from .ruleset import _service_rules
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
            for r in sorted(allowed, key=(lambda r: r["id"]) if isinstance(request, DiscoveryRequest) else order)]
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
    if isinstance(request, DiscoveryRequest):
        from .discovery_features import packed_features
        config = packed_features(request, rules)
        kwargs.update(discovery=config, objective="examples", stop_after_top=False)
        if not config["exhaustive"]:
            kwargs["attributes"] = request.coarse_attributes
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


def _finalists(rows, request, rules, native_request, required, stop_reason=None):
    traits = {r["id"]: r for r in rules["traits"]}
    skills = {r["id"]: r for r in rules["skills"]}
    eligible = {r[0] for r in native_request["traits"]}
    found = []
    seen = set()
    for row in rows:
        if stop_reason and stop_reason():
            break
        if not _domain_check(row, request, eligible, required):
            raise RuntimeError("Native finalist failed independent candidate-domain validation")
        doc = _game_doc(row, traits, skills)
        check = validate_class_snapshot(
            doc, ruleset=rules, race=row["race"], profile="custom" if isinstance(request, DiscoveryRequest) else request.profile,
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
        if isinstance(request, DiscoveryRequest):
            from .discovery_features import certified_features
            found[-1]["screening_features"] = certified_features(
                doc, row["race"], check, row["screen"], request, rules)
            found[-1]["unsupported_mechanics"] = [
                k for k in check["unsupported_mechanics"] if k not in
                ("pve.spell_damage", "progression.training", "gear.eligibility")]
    return found


def validate_discovery_document(query, doc, race, rules):
    """Recheck an archived admission without rerunning the heuristic generator."""
    from .class_document import parse_document
    from .discovery_features import mastery_eligible
    spec = parse_request(query, rules)
    if not isinstance(spec, DiscoveryRequest):
        raise ValueError("expected a discovery profile")
    draft, skipped = parse_document(doc,rules)
    rows, required, _ = _traits(spec,rules)
    packed = {"hp":draft.hp, "race":race, "skills":draft.skills, "attributes":draft.attributes,
              "traits":draft.advantages + draft.disadvantages}
    report = validate_class_snapshot(doc,ruleset=rules,race=race,profile="custom",hp_lock=None,
        magery_lock=spec.magicka_multiplier,require_magic_school=spec.require_magic_school,
        difficulty_target=spec.difficulty_points,**_policy(spec))
    if (skipped or not report["profile_legal"] or not _domain_check(packed,spec,{r[0] for r in rows},required)
            or not set(spec.required_skills) <= set(draft.skills)
            or not mastery_eligible(draft.skills,spec.required_masteries,rules["progression_rules"]["limits"]["mastery_slots"])):
        raise ValueError("class violates frozen discovery domain")
    return report


def _status(termination, has_candidates):
    if termination == "cancelled":
        return "cancelled"
    if termination in ("exhausted", "constraint_conflict"):
        return "optimal_proven" if has_candidates else "infeasible_proven"
    return "best_found_bounded" if has_candidates else "no_feasible_found"


def optimize_classes(request=None, *, ruleset=None, cancel=None):
    """Run an explicit finite-domain search under the pinned online snapshot."""
    started = perf_counter()
    engine = require_native()
    rules = _service_rules(ruleset)
    spec = parse_request(request, rules)
    native_request, required, excluded, conflict = _compile(spec, rules)
    practical = isinstance(spec, DiscoveryRequest)
    deadline = started + spec.wall_seconds if practical and spec.wall_seconds else None

    def interrupted():
        if cancel is not None and cancel.cancelled():
            return "cancelled"
        return "time_limit" if deadline and perf_counter() >= deadline else None

    stop = interrupted() if practical else None
    if deadline:
        native_request["wall_seconds"] = max(1e-12, deadline-perf_counter())
    if conflict or stop:
        raw = {"results": [], "termination": stop or "constraint_conflict", "nodes": 0, "pruned": 0,
               "leaves": 0, "work_bytes": 0, "first_feasible_seconds": None}
    else:
        raw = engine.search_classes(**native_request, cancel=cancel)
    candidates = _finalists(raw["results"], spec, rules, native_request, required,
                            interrupted if practical else None)
    fully_enumerated = raw["termination"] in ("constraint_conflict","exhausted")
    if practical and len(candidates) < len(raw["results"]):
        raw["termination"] = interrupted() or "time_limit"
    scope = {
        **spec.snapshot(), "eligible_trait_ids": sorted(row[0] for row in native_request["traits"]),
        "effective_required_trait_ids": sorted(required), "excluded_traits": excluded,
        "constraint_conflict": conflict, "attribute_order": list(ATTRIBUTES),
        "class_universe": "creator-legal classes in the supplied domains, with distinct effective trait orders",
        "ordering": "stable native traversal for equal objective values",
        "claim": "class construction at the pinned snapshot",
    }
    status = _status(raw["termination"], bool(candidates))
    engine_name = ENGINE
    unsupported = ["starting practical damage", "training route feasibility",
                   "combat and progression ranking", "live-server equivalence"]
    if isinstance(spec, DiscoveryRequest):
        from .discovery_features import discovery_evidence
        engine_name = "spellcaster-discovery-v1"
        raw.setdefault("unique_screened", 0)
        enumerated = bool(raw["termination"] == "constraint_conflict"
                          or native_request["discovery"]["exhaustive"] and fully_enumerated)
        admitted = enumerated and raw["leaves"] == len(candidates) and not (
            raw["termination"] in ("time_limit","cancelled"))
        scope.update(enumeration_complete=enumerated, admission_complete=admitted,
                     mechanics_evidence=discovery_evidence(rules),
                     ordering="native deterministic screening panel",
                     screening_frontier="Race-partitioned Pareto representatives and diversity slots. "
                         "Screening considers paired birth SP, speed, Destruction, HP, absorption eligibility "
                         "and class compatibility for each submitted gear pool. Truncation affects admission.",
                     claim="Creator eligibility and paired birth screening on the stated finite domain. "
                           "Lifecycle performance requires independent progression and combat replay.")
        if not admitted and status == "optimal_proven":
            status = "best_found_bounded"
        if not enumerated and status == "infeasible_proven":
            status = "no_feasible_found"
        unsupported = ["live-server equivalence"]
    input_hash = _digest([engine_name, rules["content_hash"], spec.snapshot()])
    return {
        "schema_version": 1, "engine": engine_name, "source_sha": rules["source_sha"],
        "ruleset_hash": rules["content_hash"], "input_hash": input_hash,
        "result_hash": _digest([input_hash, status, raw["termination"], candidates]),
        "proof_scope": scope, "status": status, "termination": raw["termination"], "candidates": candidates,
        "counters": {k: v for k, v in raw.items() if k not in ("termination", "results")},
        "validation": {"finalists_checked": len(candidates), "checker": "independent class and domain replay"},
        "unsupported_mechanics": unsupported,
    }

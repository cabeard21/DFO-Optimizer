"""Budgeted native class admission for prospective lifecycle comparisons."""
from time import perf_counter

from .class_document import ATTRIBUTES, parse_document
from .progression import digest
from .progression_replay import require


PROFILE = "spellcaster_discovery_v1"
STRATEGIES = ("exhaustive", "examples", "diverse", "adaptive")


def diagnostic_panel(raw, rules, token):
    from .search import optimize_classes

    if "class_search" not in raw:
        return raw
    query = raw["class_search"]
    require(isinstance(query, dict), "class_search must be an object")
    result = optimize_classes({**query, "objective": "examples"}, ruleset=rules, cancel=token.class_token)
    bounded = result["status"] not in ("optimal_proven", "infeasible_proven") or result["counters"].get(
        "leaves", 0
    ) > len(result["candidates"])
    admitted = [
        {"id": c["class_id"], "start": {"type": "new_character", "class": c["class_doc"], "race_id": c["race_id"]}}
        for c in result["candidates"]
    ]
    return {
        **raw,
        "class_admission": {
            "families": admitted,
            "bounded": bounded,
            "status": result["status"],
            "termination": result["termination"],
            "result_hash": result["result_hash"],
            "limits": {
                k: result["proof_scope"][k]
                for k in ("max_nodes", "memory_bytes", "wall_seconds", "top_k", "exact")
            },
            "counters": {k: result["counters"][k] for k in ("nodes", "pruned", "leaves")},
        },
    }


def strategy(raw):
    name = raw.get("class_admission_strategy")
    query = raw.get("class_search")
    if "class_admission_strategy" in raw:
        require(isinstance(query, dict), "an admission strategy requires class_search")
        require(name in STRATEGIES, "unknown class admission strategy")
        return name
    if isinstance(query, dict) and query.get("profile") == PROFILE:
        return "adaptive"
    return None


def _limit(total, ceiling):
    """Zero denotes an uncapped native budget."""
    return min(total, ceiling) if total and ceiling else total or ceiling


class ClassAdmission:
    def __init__(self, raw, rules, token, limits, started):
        from .search_request import parse_request
        self.strategy = strategy(raw)
        self.raw, self.rules, self.token = raw, rules, token
        self.limits, self.started = limits, started
        self.nodes = self.work_bytes = 0
        self.class_seconds = 0.0
        self.families = {}
        self.features = {}
        self.runs = []
        self.scope = {}
        self.query = dict(raw["class_search"])
        if self.strategy in ("adaptive", "diverse"):
            self.query.setdefault("profile", PROFILE)
            require(self.query["profile"] == PROFILE, "guided admission requires the spellcaster discovery profile")
        if self.query.get("profile") == PROFILE:
            from .discovery_features import screening_equipment

            self.query["roll_seeds"] = raw.get("roll_seeds", list(range(42, 50)))
            self.query["screen_equipment"] = screening_equipment(raw.get("equipment", {}))
        parse_request(self.query, rules)

    def generate(self, query, allowance, *, center=None, phase="initial", capacity=None):
        from .search import optimize_classes

        cap = self.limits
        wall = cap["wall_seconds"]
        class_wall = self.query.get("wall_seconds", 0)
        class_nodes = self.query.get("max_nodes", 0)
        if class_nodes and self.nodes >= class_nodes:
            self.runs.append({"phase": phase, "termination": "node_limit", "nodes": 0, "generated_legal": 0, "screened": 0})
            return []
        if wall and perf_counter() - self.started >= wall or class_wall and self.class_seconds >= class_wall:
            self.runs.append({"termination": "time_limit", "nodes": 0, "generated_legal": 0, "screened": 0})
            return []
        if cap["max_nodes"] and allowance < 1:
            return []
        mode = "exhaustive" if phase == "exact_completion" else self.strategy
        if phase == "exact_completion" and not allowance:
            # A statistical hint that sampling is repeating cannot justify an
            # unlimited full-domain audit even when lifecycle nodes are uncapped.
            allowance = query.get("max_nodes") or 1_000_000
        practical = query.get("profile") == PROFILE
        # M1's exact example visitor enumerates the diagnostic finite domain.
        objective = ("diverse" if mode in ("adaptive", "diverse") else
                     "exhaustive" if mode == "exhaustive" and practical else "examples")
        max_families = 10000 - len(self.raw.get("families", []))
        room = max_families - len(self.families)
        if capacity is not None:
            # This global pass can rediscover already-admitted families.
            room = min(10000 - len(self.raw.get("families", [])), capacity + len(self.families))
        if room < 1:
            self.runs.append({"termination": "admission_capacity", "nodes": 0, "generated_legal": 0, "screened": 0})
            return []
        run = {**query, "objective": objective, "exact": mode == "exhaustive",
               "max_nodes": _limit(class_nodes - self.nodes if class_nodes else 0, allowance),
               "memory_bytes": min(cap["memory_bytes"], query.get("memory_bytes", cap["memory_bytes"])),
               "wall_seconds": _limit(class_wall-self.class_seconds if class_wall else 0,
                                      max(1e-12, wall - (perf_counter() - self.started)) if wall else 0)}
        run["top_k"] = room if mode == "exhaustive" else min(query.get("top_k", 20), room)
        start = perf_counter()
        result = optimize_classes(run, ruleset=self.rules, cancel=self.token.class_token)
        while (mode == "exhaustive" and run["top_k"] > 1 and result["termination"] == "memory_limit"
               and not result["counters"]["nodes"] and not self.token.cancelled()):
            if run["wall_seconds"] and perf_counter() - start >= run["wall_seconds"]:
                break
            run["top_k"] //= 2
            retry_wall = max(1e-12, run["wall_seconds"] - (perf_counter()-start)) if run["wall_seconds"] else 0
            result = optimize_classes({**run,"wall_seconds":retry_wall}, ruleset=self.rules, cancel=self.token.class_token)
        self.class_seconds += perf_counter()-start
        counters, scope = result["counters"], result["proof_scope"]
        used = counters["nodes"]
        if run["max_nodes"] and used > run["max_nodes"]:
            raise RuntimeError("Native class search exceeded its allocation")
        self.nodes += used
        self.work_bytes = max(self.work_bytes, counters.get("work_bytes", 0))
        candidates = result["candidates"]
        complete = scope.get("enumeration_complete", result["termination"] in ("exhausted", "constraint_conflict"))
        legal = counters.get("generated_legal", counters["leaves"])
        admitted_all = scope.get("admission_complete", complete and legal == len(candidates))
        stop = "admission_capacity" if mode == "exhaustive" and complete and not admitted_all else result["termination"]
        log = {"center": center, "phase": phase, "termination": stop, "nodes": used,
               "generated_legal": legal, "screened": counters.get("unique_screened", legal),
               "enumeration_complete": complete, "admission_complete": admitted_all,
               "node_allowance": run["max_nodes"], "top_k": scope["top_k"]}
        self.runs.append(log)
        if phase == "initial":
            self.scope = scope
        new = []
        for c in candidates:
            key = c["class_id"]
            if key in self.families:
                continue
            if len(self.families) == max_families:
                log.update(termination="admission_capacity", admission_complete=False)
                break
            family = {"id": key, "start": {"type": "new_character", "class": c["class_doc"],
                                           "race_id": c["race_id"], "profile": "custom"}}
            self.families[key] = family
            self.features[key] = c.get("screening_features", {})
            new.append(family)
        return new

    def initial(self):
        cap = self.limits["max_nodes"]
        self.generate(self.query, max(1, cap // 4) if cap else 0)

    def audit_worthwhile(self, capacity):
        # Small input domains and frequent repeated legal visits are scheduling
        # signals only. Exhausting the native full-resolution visitor supplies proof.
        from math import prod
        if not self.scope:
            return False
        scope = self.scope
        shape = prod(len(d) for d in scope["attribute_domains"].values()) * prod(map(len, scope["skill_domains"]))
        optional = len(scope["eligible_trait_ids"]) - len(scope["effective_required_trait_ids"])
        small = shape * (1 << max(0, optional)) * len(scope["race_ids"]) <= 64 * capacity
        first = self.runs[0]
        repeated = first["screened"] <= capacity and 2 * first["screened"] < first["generated_legal"]
        return small or repeated

    def widen(self, allowance, capacity, iteration):
        if not capacity:
            return []
        if iteration == 1 and self.audit_worthwhile(capacity):
            return self.generate(self.query, allowance, phase="exact_completion", capacity=capacity)
        desired = min(10000, len(self.families) + capacity, self.query.get("top_k", 20) * 2**iteration)
        query = {**self.query, "top_k": desired,
                 "discovery_seed": (self.query.get("discovery_seed", 0) + iteration) % 2**32}
        return self.generate(query, allowance, phase="widen")

    def full_coverage(self):
        return any(r.get("admission_complete") and (
            self.strategy == "exhaustive" or r.get("phase") == "exact_completion") for r in self.runs)

    def neighbors(self, family, allowance):
        start = family[1]
        if start.get("type") != "new_character" or family[0] not in self.families:
            return []
        doc = start["class"]
        draft, _ = parse_document(doc, self.rules)
        domains = self.scope["attribute_domains"]
        attrs = {}
        for name, value in zip(ATTRIBUTES, draft.attributes, strict=True):
            allowed = sorted(domains[name])
            index = allowed.index(value)
            attrs[name] = allowed[max(0, index-1):index+2]
        if all(len(v) == 1 for v in attrs.values()):
            return []
        picks = list(draft.advantages + draft.disadvantages)
        local = {**self.query, "attribute_grid_step": 1, "attribute_domains": attrs,
                 "coarse_attribute_domains": attrs,
                 "race_ids": [start["race_id"]], "hp_values": [draft.hp],
                 "skill_domains": [[i] for i in draft.skills], "trait_ids": picks,
                 "required_trait_ids": picks}
        return self.generate(local, allowance, center=family[0], phase="neighborhood")

    def freeze(self):
        first = self.runs[0]
        enumeration = first.get("enumeration_complete", False) or any(
            r.get("enumeration_complete") for r in self.runs if r.get("phase") == "exact_completion")
        complete = self.full_coverage()
        counts = {"nodes": self.nodes, "work_bytes": self.work_bytes,
                  "generated_legal": sum(r["generated_legal"] for r in self.runs),
                  "screened": sum(r["screened"] for r in self.runs)}
        return {**self.raw, "class_admission": {
            "strategy": self.strategy, "bounded": not (enumeration and complete),
            "families": list(self.families.values()), "screening_features": dict(self.features),
            "enumeration_complete": enumeration, "admission_complete": complete, "counters": counts,
            "passes": list(self.runs), "limits": dict(self.limits),
            "snapshot_id": digest(list(self.families)),
        }}


def annotate(plan, admission, trials, history):
    from .lifecycle import _id

    frozen = plan["frozen_request"]["class_admission"]
    evaluated = {t.family[0] for t in trials if t.visited}
    checked = {t.family[0] for t in trials if t.witnesses}
    downstream = all(t.visited and not t.stopping_reasons for t in trials)
    discovered = set(admission.families)
    centers = {r["center"] for r in admission.runs if r.get("center")}
    deeper = {r["family"] for r in history if r["phase"] == "refine"}
    stats = {"strategy": admission.strategy, "enumeration_complete": frozen["enumeration_complete"],
             "admission_complete": frozen["admission_complete"], "downstream_complete": downstream,
             "generated_legal": frozen["counters"]["generated_legal"], "screened": frozen["counters"]["screened"],
             "admitted": len(discovered), "evaluated": len(discovered & evaluated),
             "validated": len(discovered & checked),
             "refined": len((deeper | centers) & discovered), "neighborhood_centers": len(centers),
             "neighbor_families_evaluated": len({r["family"] for r in history if r["phase"] == "neighbor_probe"}),
             "evaluated_pairs": sum(t.visited for t in trials), "declared_pairs": len(trials),
             "class_nodes": admission.nodes, "lifecycle_nodes": plan["counters"]["nodes"] - admission.nodes}
    plan["class_admission"] = stats
    from .lifecycle_comparisons import family_comparisons
    plan.update(family_comparisons(plan, trials))
    plan["proof_scope"] = ("Class enumeration and admission have separate completeness flags. Downstream completeness "
                           "covers the admitted class and declared birth, activity, equipment, recipe, policy and "
                           "checkpoint domains on the frozen scenarios. Paired family rankings use the reported "
                           "conditional policy representatives and equal-weight seed panel.")
    plan["budget_scope"] = ("One node budget and deadline cover native class generation, screening, progression and joint combat. "
                            "Generated counts legal visits. Screened sums distinct classes per pass and includes overlap between passes. "
                            "Admitted counts distinct generated family IDs. Memory measures native working sets.")
    plan["result_hash"] = _id(plan)
    return plan


def verify_admissions(plan, rules):
    from .search import class_identity, validate_discovery_document

    raw = plan["frozen_request"]
    raw_admission = raw.get("class_admission", {})
    if "strategy" not in raw_admission:
        require("class_admission" not in plan, "missing archived admission evidence")
        return
    stats = plan.get("class_admission", {})
    by_id = {f["id"]: f["start"] for f in raw_admission["families"]}
    complete = stats.get("enumeration_complete") and stats.get("admission_complete")
    require(stats.get("strategy") == strategy(raw) == raw_admission["strategy"]
            and stats.get("enumeration_complete") == raw_admission["enumeration_complete"]
            and stats.get("admission_complete") == raw_admission["admission_complete"]
            and (not stats.get("admission_complete") or stats["strategy"] == "exhaustive" or any(
                r.get("phase") == "exact_completion" and r.get("enumeration_complete") and r.get("admission_complete")
                for r in raw_admission["passes"]))
            and (not plan["exact"] or complete and stats.get("downstream_complete"))
            and len(by_id) == len(raw_admission["families"]) == stats.get("admitted")
            and stats.get("class_nodes") == raw_admission["counters"]["nodes"]
            and stats["class_nodes"] + stats.get("lifecycle_nodes", -1) == plan["counters"]["nodes"],
            "inconsistent archived class admission")
    query = raw["class_search"]
    practical = query.get("profile") == PROFILE or stats["strategy"] in ("adaptive", "diverse")
    if not practical:
        from .classes import validate_class_snapshot
        from .search import _domain_check, _policy, _traits
        from .search_request import parse_request
        spec = parse_request(query, rules)
        traits, required, _ = _traits(spec, rules)
        eligible = {row[0] for row in traits}
    for key, start in by_id.items():
        require(key == class_identity(rules["content_hash"], start["race_id"], start["class"]),
                "archived class admission identity differs from game document")
        if practical:
            validate_discovery_document({**query, "profile": PROFILE}, start["class"], start["race_id"], rules)
        else:
            draft, skipped = parse_document(start["class"], rules)
            packed = {"hp": draft.hp, "race": start["race_id"], "skills": draft.skills,
                      "attributes": draft.attributes, "traits": draft.advantages + draft.disadvantages}
            check = validate_class_snapshot(start["class"], ruleset=rules, race=start["race_id"],
                hp_lock=None, magery_lock=spec.magicka_multiplier, difficulty_target=spec.difficulty_points,
                require_magic_school=spec.require_magic_school, **_policy(spec))
            require(not skipped and check["profile_legal"] and _domain_check(packed,spec,eligible,required),
                    "class violates frozen diagnostic admission domain")

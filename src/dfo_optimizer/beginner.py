"""One-click beginner recommendation using the existing native class, progression and encounter services."""
from collections import Counter
from math import isfinite
from time import perf_counter

from .beginner_report import (
    ASSUMPTIONS,
    LIMITATIONS,
    METRICS,
    PanelArchive,
    retained_size,
    checked_metrics,
    compact_stage,
    publish,
    result_identity,
)
from .character import _hash
from .progression_domain import fields, integer, require
from .ruleset import _progression_service_rules

PROFILE = "first_spellcaster_v1"
MODES = {"quick": (30, 8_000_000), "standard": (120, 40_000_000), "thorough": (600, 200_000_000)}
BIRTH_SEEDS = (42, 43)
COMBAT_SEEDS = (101, 202)


class CancelToken:
    def __init__(self):
        from . import _encounter, _lifecycle

        self.lifecycle = _lifecycle.CancelToken()
        self.encounter = _encounter.CancelToken()

    def cancel(self):
        self.lifecycle.cancel()
        self.encounter.cancel()

    def cancelled(self):
        return self.lifecycle.cancelled()


def parse_request(raw):
    fields(raw, {"schema_version", "thoroughness", "search", "require_fast_advancement"}, "beginner recommendation")
    integer(raw.get("schema_version", 1), "beginner request version", 1, 1)
    mode = raw.get("thoroughness", "standard")
    require(isinstance(mode, str) and mode in MODES, "Choose quick, standard or thorough")
    wall, nodes = MODES[mode]
    budget = fields(raw.get("search", {}), {"max_nodes", "wall_seconds", "memory_bytes"}, "beginner search budget")
    seconds = budget.get("wall_seconds", wall)
    require(type(seconds) in (int, float) and isfinite(seconds) and 0 <= seconds <= 86400,
            "Wall budget must be finite and between 0 and 86400 seconds")
    maximum = integer(budget.get("max_nodes", nodes), "max_nodes", 0, 2**53-1)
    require(maximum or seconds, "Supply a work limit or a time limit")
    memory = integer(budget.get("memory_bytes", 256 << 20), "memory_bytes", 1, 2**53-1)
    fast = raw.get("require_fast_advancement", False)
    require(type(fast) is bool, "require_fast_advancement must be a boolean")
    return {"schema_version": 1, "thoroughness": mode, "search": {
        "max_nodes": maximum, "wall_seconds": seconds, "memory_bytes": memory},
        **({"require_fast_advancement": True} if fast else {})}


class _Budget:
    def __init__(self, limits, token):
        self.start = perf_counter()
        self.limits = limits
        self.token = token
        self.used = Counter()
        self.memory = limits["memory_bytes"]

    @property
    def nodes(self):
        return sum(self.used[k] for k in ("class_nodes", "progression_nodes", "encounter_events"))

    def remaining(self):
        return max(0, self.limits["max_nodes"] - self.nodes) if self.limits["max_nodes"] else 2**53-1

    def seconds(self):
        limit = self.limits["wall_seconds"]
        return max(0., limit - (perf_counter() - self.start)) if limit else 86400.

    def stop(self):
        if self.token.cancelled():
            return "cancelled"
        if not self.remaining():
            return "node_limit"
        if not self.seconds():
            return "time_limit"
        if self.memory <= 0:
            return "memory_limit"
        return None


def _settings(rules, roll_seeds, combat_seeds, cases, variants):
    from .beginner_creation import CREATION_DIGEST
    from .beginner_scenarios import CASE_IDS, VARIANTS, scenario_matrix
    from .physical_encounter import CORE, LAW_HASH

    for seeds in (roll_seeds, combat_seeds):
        require(isinstance(seeds, (tuple, list)) and 1 <= len(seeds) <= 128 and
                all(type(s) is int and 0 <= s < 2**32 for s in seeds) and len(set(seeds)) == len(seeds),
                "Use distinct uint32 seeds for the paired panel")
    catalog = {c["id"]: c for c in scenario_matrix()}
    selected = list(CASE_IDS if cases is None else cases)
    require(0 < len(selected) <= len(catalog) and all(isinstance(c, str) and c in catalog for c in selected)
            and len(set(selected)) == len(selected), "Unknown or repeated recommendation scenario")
    variants = list(VARIANTS if variants is None else variants)
    require(0 < len(variants) <= len(VARIANTS) and all(isinstance(v, str) and v in VARIANTS for v in variants)
            and len(set(variants)) == len(variants), "Unknown or repeated assumption variant")
    return {"profile": PROFILE, "ruleset_hash": rules["content_hash"], "roll_seeds": list(roll_seeds),
            "combat_seeds": list(combat_seeds), "cases": list(CASE_IDS if cases is None else cases),
            "variants": variants, "creation_law_hash": CREATION_DIGEST,
            "scenarios": [catalog[c] for c in selected], "physical_core": CORE, "physical_law_hash": LAW_HASH}


def _project(family, cache, settings, budget):
    checkpoints, rolls, policy = [], [], {}
    for seed in settings["roll_seeds"]:
        if reason := budget.stop():
            return checkpoints, rolls, policy, reason
        result = cache.project({**family["start"], "roll_seed": seed}, family=family["id"],
                               max_nodes=budget.remaining(), memory_bytes=max(1, budget.memory // 2),
                               wall_seconds=budget.seconds(), cancel=budget.token.lifecycle.progression_token)
        budget.used["progression_nodes"] += result["counters"]["nodes"]
        budget.used["checkpoint_cache_hits"] += int(result["cache_hit"])
        policy = policy or result["policy"]
        stages = result["checkpoints"]
        checkpoints.extend(stages)
        rolls.append({"seed": seed, "status": result["status"], "first_gap": result["first_gap"],
                      "reached_level": result.get("reached_level", stages[-1]["level"] if stages else None),
                      "birth_allocation": result["policy"]["birth_allocation"],
                      "stages": [compact_stage(s) for s in stages]})
        if result["status"] != "complete":
            return checkpoints, rolls, policy, result["termination"]
    return checkpoints, rolls, policy, None


def _evaluate(family, cache, settings, rules, budget):
    from .beginner_scenarios import evaluate_matrix

    start, permanent = family["start"], family["compliance"]
    base = {"id": family["id"], "origin": family["origin"], "race_id": start["race_id"],
            "race": permanent["race"], "class": start["class"], "permanent": permanent}
    if not permanent["passed"]:
        return {**base, "status": "profile_excluded", "reason": ", ".join(permanent["failures"])}
    stages, rolls, policy, gap = _project(family, cache, settings, budget)
    progress = {"policy": policy, "rolls": rolls, "representative_seed": settings["roll_seeds"][0]}
    base = {**base, "progression": progress}
    if gap or budget.stop():
        reason = next((r["first_gap"] for r in rolls if r["first_gap"]), None)
        return {**base, "status": "incomplete", "termination": gap or budget.stop(), "reason": str(reason or gap or budget.stop())}
    matrix = evaluate_matrix(stages, settings["cases"], settings["combat_seeds"], variants=settings["variants"],
                             max_events=budget.remaining(), wall_seconds=budget.seconds(),
                             memory_bytes=max(1, budget.memory // 2),
                             cancel=budget.token.encounter, ruleset=rules)
    work = matrix["counters"]
    budget.used["encounter_events"] += work["events"]
    budget.used["encounter_batches"] += work["encounter_batches"]
    budget.used["replayed_trials"] += work["replayed_trials"]
    budget.used["identical_encounter_batches_reused"] += work.get("reused_batches", 0)
    budget.used["checkpoint_forks"] += matrix["coverage"]["required"]
    cov = matrix["coverage"]
    base = {**base, "coverage": cov, "outcomes": matrix["rows"], "outcomes_hash": matrix["outcomes_hash"]}
    if not cov["required"] or cov["replayed"] != cov["required"]:
        reasons = sorted({r["reason"] for r in matrix["rows"] if r["status"] != "replayed"})
        return {**base, "status": "incomplete", "termination": matrix["termination"], "reason": "; ".join(reasons) or "Incomplete scenario panel"}
    return {**base, "status": "replayed", "metrics": checked_metrics(permanent, rolls, matrix["rows"])}


def _document(req, settings, rules, budget, admission, archive, stop, first, *, full=False):
    from .beginner_sensitivity import interpretation, matched_decisions
    winner, alternatives, changes = publish(archive)
    rows = [archive.expand(r) for r in archive.rows] if full else list(archive.rows)
    matched = matched_decisions(rows)
    summary, notes = interpretation(winner, changes, matched, rows)
    return_value = {"schema_version": 1, "kind": "beginner_recommendation", "profile": PROFILE,
                    "ruleset_hash": rules["content_hash"], "source_sha": rules["source_sha"],
                    "frozen_request": req, "evaluation": settings, "comparison_hash": _hash(settings),
                    "recommendation": winner, "alternatives": alternatives, "comparisons": rows,
                    "status": "cancelled" if stop == "cancelled" else "best_found_bounded" if winner else "incomplete",
                    "termination": stop, "exact": False, "sensitivity": changes,
                    "summary": summary, "sensitivity_notes": notes, "matched_decisions": matched,
                    "assumptions": list(ASSUMPTIONS), "limitations": list(LIMITATIONS), "metric_definitions": dict(METRICS),
                    "diagnostics": {"admission": admission, "fully_evaluated": sum(r["status"] == "replayed" for r in rows),
                                    "retained_bytes": archive.bytes,
                                    **budget.used, "nodes": budget.nodes},
                    "timings": {"elapsed_seconds": perf_counter() - budget.start,
                                "first_validated_seconds": first}}
    return {**return_value, "result_hash": result_identity(return_value)}


def _run(req, *, rules, token, families=None, roll_seeds=BIRTH_SEEDS, combat_seeds=COMBAT_SEEDS,
         cases=None, variants=None, on_incumbent=None, full=False):
    from .beginner_progression import CheckpointCache

    budget = _Budget(req["search"], token)
    settings = _settings(rules, roll_seeds, combat_seeds, cases, variants)
    budget.memory -= retained_size(settings, set())
    admission = {}
    if families is None and not budget.stop():
        from .beginner_classes import beginner_roster

        allowance = min(budget.remaining(), max(1, budget.remaining() // 6), 4000000)
        roster = beginner_roster(req["thoroughness"], ruleset=rules, roll_seeds=roll_seeds,
                                 max_nodes=allowance, wall_seconds=budget.seconds(),
                                 memory_bytes=max(1, budget.memory // 2), cancel=token.lifecycle.class_token,
                                 domain={"difficulty_values": [-12]} if req.get("require_fast_advancement") else None)
        budget.used["class_nodes"] = roster["counts"]["nodes"]
        families = roster["families"]
        admission = {k: v for k, v in roster.items() if k != "families"}
    cache = CheckpointCache(rules, cache_bytes=max(0, min(8 << 20, budget.memory // 16)))
    archive, first = PanelArchive(), None
    stop = None
    for family in families or ():
        if budget.stop():
            break
        if req.get("require_fast_advancement") and family["compliance"]["difficulty_points"] != -12:
            continue
        row = _evaluate(family, cache, settings, rules, budget)
        if not archive.append(row, budget.memory // 3):
            stop = "memory_limit"
            break
        if row["status"] == "replayed" and first is None:
            first = perf_counter() - budget.start
            if on_incumbent:
                on_incumbent(_document(req, settings, rules, budget, admission, archive,
                                       "checked_preview", first))
    gaps = [r for r in archive.rows if r["status"] == "incomplete"]
    stops = {r.get("termination") for r in gaps}
    reason = next((s for s in ("cancelled", "time_limit", "memory_limit", "node_limit", "event_limit") if s in stops), None)
    return _document(req, settings, rules, budget, admission, archive,
                     stop or budget.stop() or reason or ("panel_partial" if gaps else "panel_complete"), first, full=full)


def recommend_build(request, ruleset=None, *, cancel=None, on_incumbent=None):
    rules = _progression_service_rules(ruleset)
    return _run(parse_request(request), rules=rules, token=cancel or CancelToken(), on_incumbent=on_incumbent)


def evaluate_roster(families, *, ruleset=None, roll_seeds=BIRTH_SEEDS, combat_seeds=COMBAT_SEEDS,
                    cases=None, variants=None, search=None, cancel=None):
    """Evaluate a declared finite roster for paired qualification without re-running admission."""
    from .beginner_classes import beginner_compliance
    from .search import class_identity
    rules = _progression_service_rules(ruleset)
    require(isinstance(families, (list, tuple)) and len(families) <= 256, "Invalid finite class roster")
    identities = set()
    for f in families:
        start = fields(f["start"], {"type", "race_id", "class", "profile"}, "fixed beginner class")
        require(start.get("type") == "new_character" and start.get("profile", "custom") == "custom",
                "Use an ordinary fixed new character for the comparison")
        identity = class_identity(rules["content_hash"], start["race_id"], start["class"])
        require(f["id"] == identity and identity not in identities, "Invalid or duplicate class identity")
        identities.add(identity)
        permanent = beginner_compliance(start["class"], start["race_id"], ruleset=rules, roll_seeds=roll_seeds)
        require(f["compliance"] == permanent, "Submitted permanent class properties differ from the paired birth replay")
    return _run(parse_request({"search": {} if search is None else search}), families=families, full=True,
                rules=rules, token=cancel or CancelToken(),
                roll_seeds=roll_seeds, combat_seeds=combat_seeds, cases=cases, variants=variants)


def replay_recommendation(result, *, ruleset=None, cancel=None):
    rules = _progression_service_rules(ruleset)
    require(result.get("kind") == "beginner_recommendation" and result.get("profile") == PROFILE
            and result.get("source_sha") == rules["source_sha"] and result.get("ruleset_hash") == rules["content_hash"]
            and result.get("result_hash") == result_identity(result),
            "Beginner recommendation identity mismatch")
    from .beginner_classes import beginner_compliance
    from .search import class_identity

    settings = result["evaluation"]
    params = {k: settings[k] for k in ("roll_seeds", "combat_seeds", "cases", "variants")}
    require(result["comparison_hash"] == _hash(settings) and settings == _settings(rules, **params),
            "Beginner scenario panel differs from the installed snapshot")
    require(result.get("exact") is False and result.get("schema_version") == 1 and
            parse_request(result["frozen_request"]) == result["frozen_request"], "Invalid frozen beginner request")
    rows = [r for r in result["comparisons"] if r["status"] == "replayed"]
    require(len(rows) <= 256 and len({r["id"] for r in rows}) == len(rows), "Invalid recommendation roster")
    require(all(r["id"] == class_identity(rules["content_hash"], r["race_id"], r["class"]) for r in rows),
            "Beginner class identity mismatch")
    token = cancel or CancelToken()
    families = []
    for r in rows:
        if token.cancelled():
            break
        families.append({"id": r["id"], "origin": r["origin"],
                         "start": {"type": "new_character", "profile": "custom", "class": r["class"], "race_id": r["race_id"]},
                         "compliance": beginner_compliance(r["class"], r["race_id"], ruleset=rules, roll_seeds=settings["roll_seeds"])})
    checked = _run(parse_request({"search":{"wall_seconds":0, "max_nodes":200_000_000},
                                  "require_fast_advancement": result["frozen_request"].get("require_fast_advancement", False)}),
                   families=families, **params, rules=rules, token=token)
    if token.cancelled():
        return {"verified":False, "status":"cancelled", "termination":"cancelled", "result_hash":result["result_hash"]}
    summaries = [{k:v for k,v in row.items() if k != "outcomes"} for row in rows]
    from .beginner_sensitivity import interpretation
    prose = interpretation(checked["recommendation"], checked["sensitivity"], checked["matched_decisions"], result["comparisons"])
    require((result["summary"],result["sensitivity_notes"]) == prose and
            all("outcomes" not in r or _hash(r["outcomes"]) == r["outcomes_hash"] for r in rows)
            and checked["comparisons"] == summaries and all(checked[k] == result[k] for k in
            ("recommendation", "alternatives", "sensitivity", "matched_decisions", "assumptions", "limitations",
             "metric_definitions")), "Independent beginner recommendation replay differs")
    return {"verified": True, "result_hash": result["result_hash"], "families_checked": len(rows),
            "scope": "Published winners, paired outcomes and selection among fully covered classes. Partial trials and class enumeration are outside this replay.",
            "outcomes_checked": sum(r["coverage"]["replayed"] for r in rows)}

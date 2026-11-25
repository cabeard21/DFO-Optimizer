"""Pinned online-snapshot spell services. Python validates only the retained finalists."""
import hashlib
import json
from copy import deepcopy
from functools import lru_cache
from importlib import import_module
from math import isclose
from time import perf_counter

from .ruleset import load_ruleset
from .spell_reference import evaluate_reference
from .spell_request import AXES, parse_spell_request

ENGINE = "m2-direct-damage-v1"
MECHANICS = ("spell.maker", "spell.cast_cost", "spell.purchase", "spell.ready_charge",
             "spell.cadence", "spell.potency", "spell.saves", "pve.spell_damage")
ASSUMPTIONS = (
    "A player casts one instant Damage Health effect at one stationary, non-player PvE target.",
    "The designed spell is available to ready for this calculation. The caster can cast in the environment.",
    "One confirmed hit per cast, including area targeting. The caster uses the classic release clock.",
    "DPS uses the continuous click-to-click interval while SP is available. Each hit starts at the stated target HP.",
    "Stats and resources are stable between ready and charge. The scenario excludes interruptions, travel time and mentoring.",
    "The target has no shield, absorption, reflection or boss modifiers. All included resistance and equipment modifiers are explicit.",
)
OUT_OF_SCOPE = ("multi-effect spells and spellbooks", "damage over time", "conditional powers and procs",
                "encounter resource recovery", "live-server equivalence")


def _digest(value):
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
    return hashlib.sha256(raw.encode()).hexdigest()


@lru_cache(maxsize=1)
def _installed_rules():
    from .ruleset import validate_combat_ruleset
    return validate_combat_ruleset(load_ruleset())


def _engine():
    try:
        return import_module("._spells", __package__)
    except ImportError as exc:
        raise RuntimeError("Install a dfo-optimizer wheel with the native spell extension") from exc


def _admitted(row, spec):
    return (len(row) == len(AXES)
            and all(type(v) is int and v in d for v, d in zip(row, spec.native_domain(), strict=True))
            and row[2] <= row[3] and row[4] <= row[5])


def _missing_timing(spec):
    return {f"unknown caster.{k}" for k in ("speed", "cast_speed_pct") if getattr(spec.caster, k) is None}


def _scoring_context(spec):
    ctx = spec.native_context()
    # Timing is constant across recipes for a fixed caster. The native efficiency
    # comparator uses only the exact damage/SP ratio. Mask this unused channel in output.
    if ctx["speed"] is None:
        ctx["speed"] = 50
    if ctx["cast_speed_pct"] is None:
        ctx["cast_speed_pct"] = 0
    return ctx


def _metrics(recipe, spec, native):
    ctx = _scoring_context(spec)
    metrics = native.evaluate(ctx, recipe)
    for name, expected in evaluate_reference(ctx, recipe).items():
        got = metrics[name]
        equal = isclose(got, expected, abs_tol=1e-12, rel_tol=1e-12) if type(expected) is float else got == expected
        if not equal:
            raise RuntimeError(f"Native spell finalist failed independent replay of {name}: {got} versus {expected}")
    if spec.auto and not metrics["affordable"]:
        raise RuntimeError("Native spell search returned an unaffordable spell")
    metrics = dict(metrics)
    if spec.price_factor is None:
        metrics["purchase_gold"] = None
    quote = metrics["purchase_gold"]
    gold, book = spec.caster.gold, spec.caster.has_spellbook
    metrics["purchase_affordable"] = gold >= quote if gold is not None and quote is not None else None
    metrics["has_spellbook"] = book
    metrics["spell_known"] = True if recipe in spec.known_recipes else None
    metrics["maker_access"] = None
    if spec.caster.current_sp is None:
        metrics["affordable"] = None
    # The host refuses a ready above current SP and spends nothing on the refusal.
    ready = metrics["affordable"]
    metrics["actual_sp_charged"] = None if ready is None else (metrics["cost_sp"] if ready else 0)
    metrics["damage_per_sp_if_cast"] = metrics["damage_per_sp"]
    if ready is not True:
        metrics["damage_per_sp"] = None
    if _missing_timing(spec):
        metrics.update(dict.fromkeys(("cast_rate", "release_seconds", "recovery_seconds", "dps")))
    return metrics


def _finalists(rows, multiplicities, spec, native, rules):
    candidates, seen = [], set()
    for raw, count in zip(rows, multiplicities, strict=True):
        row = tuple(raw)
        if not _admitted(row, spec) or row in seen or type(count) is not int or count < 1:
            raise RuntimeError("Native spell finalist failed domain or identity validation")
        seen.add(row)
        spell = {"effect_id": spec.effect_id, **dict(zip(AXES, row, strict=True))}
        candidates.append({"spell_id": _digest([rules["content_hash"], spell]), "spell": spell,
                           "metrics": _metrics(row, spec, native), "multiplicity": count})
    return candidates


def _status(end, found):
    if end in ("evaluated", "evaluated_partial"):
        return end
    if end in ("unsupported", "cancelled"):
        return end
    if end == "exhausted":
        return "optimal_proven" if found else "infeasible_proven"
    return "best_found_bounded" if found else "no_feasible_found"


def _find(spec, native, cancel, started):
    optional = _missing_timing(spec) if not spec.auto or spec.search.objective == "damage_per_sp" else set()
    if set(spec.blockers) - optional:
        return "unsupported", [], [], {"nodes": 0, "leaves": 0, "pruned": 0, "work_bytes": 0}
    if not spec.auto:
        end = "evaluated_partial" if optional else "evaluated"
        return end, [spec.recipe()], [1], {"nodes": 1, "leaves": 1, "pruned": 0}
    if not spec.domain_size:
        return "exhausted", [], [], {"nodes": 0, "leaves": 0, "pruned": 0, "work_bytes": 0}
    budget = spec.search
    # Zero disables the native deadline. A spent service deadline must therefore
    # stay strictly positive when entering the native cancellation/time gate.
    remaining = max(1e-12, budget.wall_seconds - (perf_counter() - started)) if budget.wall_seconds else 0
    raw = native.search(_scoring_context(spec), spec.native_domain(), objective=budget.objective,
                        top_k=budget.top_k, max_nodes=budget.max_nodes, wall_seconds=remaining,
                        memory_bytes=budget.memory_bytes, token=cancel)
    counters = {k: v for k, v in raw.items() if k not in ("end", "rows", "multiplicities")}
    return raw["end"], raw["rows"], raw["multiplicities"], counters


def _run(request, ruleset, cancel, auto):
    started = perf_counter()
    from .ruleset import validate_combat_ruleset
    rules = _installed_rules() if ruleset is None else validate_combat_ruleset(deepcopy(ruleset))
    spec = parse_spell_request(request, rules, auto=auto)
    native = _engine()
    prepared = perf_counter()
    end, rows, counts, counters = _find(spec, native, cancel, started)
    candidates = _finalists(rows, counts, spec, native, rules)
    status = _status(end, bool(candidates))
    input_hash = _digest([ENGINE, rules["content_hash"], spec.snapshot()])
    result = {"schema_version": 1, "engine": ENGINE, "source_sha": rules["source_sha"],
            "ruleset_hash": rules["content_hash"], "input_hash": input_hash,
            "result_hash": _digest([input_hash, status, end, candidates]),
            "status": status, "termination": end, "candidates": candidates, "counters": counters,
            "proof_scope": {"mode": "online_snapshot", "kind": "auto_spell" if auto else "fixed_spell",
                            "effect_id": spec.effect_id, "domain": dict(zip(AXES, spec.domains, strict=True)),
                            "legal_recipes": spec.domain_size, "objective": spec.search.objective if auto else None,
                            "frontier_complete": auto and spec.search.objective == "pareto" and end == "exhausted",
                            "ranking": {"pareto": "expected HP loss per recast second and per actual SP",
                                        "dps": "expected HP loss per recast second",
                                        "damage_per_sp": "expected HP loss per actual SP"}[spec.search.objective] if auto else None,
                            "bounded_tie_policy": "multiplicities count recipes visited under this search budget",
                            "caster_snapshot_hash": spec.snapshot_hash, "request": spec.snapshot()},
            "mechanic_ids": MECHANICS, "assumptions": ASSUMPTIONS, "unsupported_mechanics": list(spec.blockers),
            "unmodeled": OUT_OF_SCOPE,
            "validation": {"finalists_checked": len(candidates), "checker": "independent scalar distribution replay"}}
    counters.update(preparation_seconds=prepared - started, service_seconds=perf_counter() - started)
    return result


def evaluate_spell(request, *, ruleset=None, cancel=None):
    """Measure a provided spell under its frozen caster and target assumptions."""
    return _run(request, ruleset, cancel, False)


def optimize_spells(request, *, ruleset=None, cancel=None):
    """Search the supplied subset of legal single-effect Damage Health recipes."""
    return _run(request, ruleset, cancel, True)

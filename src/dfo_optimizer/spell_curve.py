"""Measure a fixed recipe across explicit hypothetical caster inputs."""
from dataclasses import replace
from copy import deepcopy

from .ruleset import _installed_combat_rules, validate_combat_ruleset
from .spell_request import _int, _object, parse_spell_request
from .spells import ASSUMPTIONS, _checked_metrics, _digest, _engine, _missing_timing, _scoring_context


AXES = {"level": (1, 45), "destruction_live": (0, 10000), "destruction_trained": (0, 200)}


def evaluate_spell_curve(request, *, ruleset=None, cancel=None):
    if not isinstance(request, dict):
        raise ValueError("Expected a fixed spell request with curve settings")
    settings = _object(request.get("curve", {"axis":"level", "values":[1, 5, 10, 15, 20, 25, 30, 35, 40, 45]}),
                       "curve", ("axis", "values"))
    axis, values = settings.get("axis"), settings.get("values")
    if not isinstance(axis, str) or axis not in AXES:
        raise ValueError("Choose level, destruction_live or destruction_trained")
    if not isinstance(values, list) or not 1 <= len(values) <= 64:
        raise ValueError("Supply 1 to 64 curve points")
    values = [_int(v, axis, *AXES[axis]) for v in values]
    if sorted(set(values)) != values:
        raise ValueError("Curve values must be unique and increasing")
    rules = _installed_combat_rules() if ruleset is None else validate_combat_ruleset(ruleset)
    fixed = parse_spell_request({k:v for k,v in request.items() if k != "curve"}, rules, auto=False)
    series = [replace(fixed, caster=replace(fixed.caster, **{axis:v})) for v in values]
    # One explicit axis can supply an unknown base observation. Earned climb still
    # requires a known mastery for a trained value above 100.
    projected = {"level":"level", "destruction_live":"destruction_live", "destruction_trained":"climb"}[axis]
    allowed = _missing_timing(fixed)
    if all(getattr(point.caster, projected) is not None for point in series):
        allowed.add(f"unknown caster.{projected}")
    gaps = sorted(set(fixed.blockers) - allowed)
    if any(point.caster.climb is None for point in series):
        gaps = sorted(set([*gaps, "unknown caster.climb"]))
    rows = []
    if gaps:
        status = "unsupported"
    else:
        contexts = [_scoring_context(point) for point in series]
        recipe = fixed.recipe()
        scores = _engine().evaluate_contexts(contexts, recipe, cancel)
        for i, score in enumerate(scores):
            rows.append({axis:values[i], "metrics":_checked_metrics(recipe, series[i], contexts[i], score)})
        status = "cancelled" if len(rows) < len(series) else "evaluated_partial" if _missing_timing(fixed) else "evaluated"
    identity = _digest([rules["content_hash"], fixed.snapshot(), axis, values])
    return {"kind":"spell_curve", "schema_version":1, "status":status, "termination":status, "axis":axis,
            "source_sha":rules["source_sha"], "ruleset_hash":rules["content_hash"], "input_hash":identity,
            "result_hash":_digest([identity, rows, gaps, status]), "candidates":rows, "points_checked":len(rows),
            "assumptions":[*ASSUMPTIONS, "Only the selected caster field varies. Each point is a hypothetical fixed cast."],
            "blockers":gaps, "frozen_request":deepcopy(request)}

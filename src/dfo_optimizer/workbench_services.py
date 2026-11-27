"""Map reviewed desktop actions to the same domain services the CLI uses."""
from copy import deepcopy
from importlib import import_module

from .character_files import MAX_SAVE_BYTES, read_json
from .project_data import shared_data
from .ruleset import coverage, load_ruleset


# A name from an HTTP request can only select an entry in this fixed registry.
SEARCH = {
    "class optimize": ("search", "optimize_classes", "_native"),
    "evaluate": ("spells", "evaluate_spell", "_spells"),
    "spell evaluate": ("spells", "evaluate_spell", "_spells"),
    "spell curve": ("spell_curve", "evaluate_spell_curve", "_spells"),
    "spell optimize": ("spells", "optimize_spells", "_spells"),
    "gear evaluate": ("gear", "evaluate_gear", "_gear"),
    "gear optimize": ("gear", "optimize_gear", "_gear"),
    "progression plan": ("progression", "plan_progression", "_progression"),
    "build optimize": ("lifecycle", "optimize_build", "_lifecycle"),
    "build recommend": ("beginner", "recommend_build", "beginner"),
    "build replan": ("lifecycle", "replan_build", "_lifecycle"),
    "spellbook evaluate": ("spellbook", "evaluate_spellbook", "_spellbook"),
    "spellbook optimize": ("spellbook", "optimize_spellbook", "_spellbook"),
    "encounter evaluate": ("encounter", "evaluate_encounter", "_encounter"),
    "encounter optimize": ("encounter", "optimize_encounter", "_encounter"),
}
REPLAY = {"build replay": ("lifecycle", "replay_build"), "progression replay": ("progression", "replay_progression"),
          "encounter replay": ("encounter", "replay_encounter")}
ACTIONS = (*SEARCH, *REPLAY, "class validate", "class export", "build compare", "ruleset coverage", "build baselines")
MODES = {"request": {}, "quick": {"max_nodes":10_000, "wall_seconds":1},
         "balanced":{"max_nodes":100_000, "wall_seconds":5},
         "exhaustive":{"max_nodes":1_000_000, "wall_seconds":30},
         "research":{"max_nodes":5_000_000, "wall_seconds":60}}


def module(name):
    return import_module("." + name, __package__)


def search_token(action, request):
    if (action == "build replay" and request.get("kind") == "beginner_recommendation" or
            action == "build compare" and isinstance(request.get("plans"), list) and any(
                isinstance(p, dict) and p.get("kind") == "beginner_recommendation" for p in request["plans"])):
        return module("beginner").CancelToken()
    if action.split()[0] in ("gear","spellbook") and "encounter" in request:
        return module("_lifecycle").CancelToken()
    return module(SEARCH[action][2]).CancelToken() if action in SEARCH else None


def is_discovery(action, request):
    return action == "build recommend" or action == "build optimize" and (
        "class_admission_strategy" in request
        or isinstance(request.get("class_search"), dict)
        and request["class_search"].get("profile") == "spellcaster_discovery_v1"
    )


def execute(action, request, token, *, on_incumbent=None):
    if action in SEARCH:
        source, function, _ = SEARCH[action]
        if on_incumbent is not None and is_discovery(action, request):
            return getattr(module(source), function)(request, cancel=token, on_incumbent=on_incumbent)
        return getattr(module(source), function)(request, cancel=token)
    if action in REPLAY:
        source, function = REPLAY[action]
        if action == "build replay" and request.get("kind") == "beginner_recommendation":
            return module(source).replay_build(request, cancel=token)
        return getattr(module(source), function)(request)
    if action == "class validate":
        return module("classes").validate_class(request.get("document", request), race=request.get("race"))
    if action == "class export":
        return module("classes").export_class(request.get("document", request))
    if action == "build compare":
        return module("lifecycle").compare_builds(request.get("plans"), cancel=token)
    if action == "build baselines":
        return module("build_baselines").baseline_catalog(load_ruleset())
    if action == "ruleset coverage":
        return coverage(load_ruleset())
    raise ValueError("Unknown workbench action")


def inline_only(value):
    stack = [value]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            if node.keys() & {"character_file", "progression_file"}:
                raise ValueError("Upload the referenced input and include its contents in this request.")
            stack.extend(node.values())
        elif isinstance(node, list):
            stack.extend(node)


def read_example(name):
    if name.startswith("discovery-"):
        from .discovery_presets import discovery_preset, preset_catalog
        key = name.removeprefix("discovery-")
        if key not in {row["id"] for row in preset_catalog()}:
            raise KeyError("Unknown discovery preset")
        value = discovery_preset(key)
        inline_only(value)
        return value
    directory = shared_data("examples")
    examples = {p.stem: p for p in directory.glob("*.json")}
    if name not in examples:
        raise KeyError("Unknown packaged example")
    with examples[name].open("rb") as stream:
        value = read_json(stream, MAX_SAVE_BYTES, "packaged example")
    # Only shipped examples enter the CLI's relative-file resolution. Their
    # references are expanded before the browser receives an editable request.
    if name.startswith("build-"):
        from .lifecycle import _freeze
        value = _freeze(value, load_ruleset(), directory, name.startswith("build-replan"))
    elif name.startswith("progression-") and "character_file" in value.get("start", {}):
        from .character import import_character
        start = value["start"].copy()
        start["character"] = import_character(directory / start.pop("character_file"), slot=start.pop("slot", None))
        value = {**value, "start":start}
    inline_only(value)
    return value


def metadata():
    from .build_baselines import baseline_catalog, resolve_family_baseline
    from .discovery_presets import preset_catalog
    from .lifecycle_objectives import OBJECTIVES
    from .equipment import equipment_catalog
    rules = load_ruleset()
    baselines = baseline_catalog(rules)["baselines"]
    slots = {key:value for key,value in equipment_catalog()["slots"].items() if 0 <= value <= 26}
    return {"ruleset_hash": rules["content_hash"], "source_sha":rules["source_sha"], "mode":rules["mode"],
            "engine":rules["engine_version"], "actions":list(ACTIONS),
            "examples":sorted(p.stem for p in shared_data("examples").glob("*.json")),
            "discovery_presets":preset_catalog(), "modes":MODES,
            "catalog":{"slots":slots,**{k:rules[k] for k in ("races","skills","traits","limits")},
                       "objective_definitions":OBJECTIVES,
                       "caster_races":{r["id"]:r["race_id"] for r in baselines
                                       if r["id"] in ("m1-breton-caster","comparison-high-elf-caster")},
                       "caster_classes":{key:resolve_family_baseline(key,rules)["class"] for key in
                                         ("m1-breton-caster","comparison-high-elf-caster")}},
            "baselines":baselines, "coverage":coverage(rules)}


def limited_request(action, request, caps):
    result = deepcopy(request)
    if not caps or not searchable(action):
        return result
    limits = result if action == "class optimize" else result.setdefault("search", {})
    if not isinstance(limits, dict):
        raise ValueError("search must be a JSON object")
    for key, ceiling in caps.items():
        if action.startswith("encounter ") and key == "max_nodes":
            key = "max_events"
        current = limits.get(key)
        if current is None or (type(current) in (int, float) and (current == 0 or current > ceiling)):
            limits[key] = ceiling
    return result


def searchable(action):
    return action.endswith("optimize") or action in ("progression plan", "build replan", "build recommend")

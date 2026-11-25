"""Adapt gear and spellbook requests to a single access-checked native encounter."""
from .character import normalize_character
from .equipment import equipment_catalog
from .progression_domain import fields, integer
from .progression_replay import require
from .spell_request import SpellTarget


def single_checkpoint(request, *, equipment_search, fixed, ruleset, cancel):
    from .lifecycle import replan_build

    raw = fields(request, {"schema_version", "ruleset_hash", "description", "character",
                           "live_observations", "encounter", "firmament", "spellbook", "mode", "offers",
                           "budget", "locks", "exclusions", "available_containers", "loadout",
                           "search"}, "encounter loadout request")
    character = normalize_character(raw.get("character"))
    control = raw.get("encounter")
    require(isinstance(control, dict) and control.get("at", "terminal") == "terminal",
            "gear and spellbook require a single terminal encounter")
    scene = control.get("scenario")
    require(isinstance(scene, dict) and isinstance(scene.get("enemies"), list) and scene["enemies"]
            and isinstance(scene["enemies"][0], dict), "encounter requires at least one target")
    equipment = {k:raw[k] for k in ("offers", "locks", "exclusions", "available_containers") if k in raw}
    mode = raw.get("mode", "owned_only")
    require(mode in ("owned_only", "owned_plus_budget"), "encounter gear requires physical copies or priced offers")
    require(mode != "owned_only" or not raw.get("offers"), "owned_only excludes equipment offers")
    if fixed or not equipment_search:
        worn = {r["item"]["equipSlot"]:r["instance_id"] for r in character["gear"]["items"]
                if r["item"].get("equipSlot") is not None}
        slots = equipment_catalog()["slots"]
        current = {name:worn[index] for name,index in slots.items() if index in worn and 0 <= index < 27}
        equipment["loadouts"] = [raw.get("loadout", current)]
    else:
        require("loadout" not in raw, "use gear evaluate for a fixed encounter loadout")
    book = raw.get("spellbook", {})
    require(isinstance(book, dict), "spellbook must be an object")
    if fixed and not equipment_search:
        require(len(book.get("policies", [])) == 1, "fixed spellbook requires one explicit priority policy")
        book = {**book, "mode":"fixed_spellbook"}
    start = {"type":"current_character", "character":character}
    if "firmament" in raw:
        start["firmament"] = raw["firmament"]
    if "live_observations" in raw:
        start["live_observations"] = raw["live_observations"]
    family = {"id":"Current character", "start":start}
    target = {k:v for k,v in scene["enemies"][0].items() if k in SpellTarget.__dataclass_fields__}
    frozen = {**{k:raw[k] for k in ("schema_version", "ruleset_hash", "description", "search") if k in raw},
              "families":[family], "equipment":equipment, "spellbook":book, "encounter":control,
              "target":target, "progression":{"stages":[], "goal":{"level":1},
                                             "require_starting_damage":False,"search":{"exact":True}}}
    if "budget" in raw:
        budget = fields(raw["budget"], {"gold"}, "encounter purchase budget")
        frozen["budget_gold"] = integer(budget.get("gold"), "available budget in gold", 0, 2**53-1)
    return replan_build(frozen, ruleset=ruleset, cancel=cancel)

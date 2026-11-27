"""Validate and search hypothetical online Firmament allocations locally."""

from copy import deepcopy
from functools import lru_cache
from hashlib import sha256
import json
from math import isfinite

from .character import normalize_character
from .firmament_projection import (
    CHANNEL_NAMES, maximum_sp_reference, project_reference, projection_basis, tree_vectors,
)
from .ruleset import DATA, SOURCE_SHA, load_ruleset
from .spell_reference import evaluate_reference
from .spell_request import AXES, parse_spell_request


def _digest(value):
    return sha256(json.dumps(value, sort_keys=True, ensure_ascii=True, allow_nan=False,
                            separators=(",", ":")).encode()).hexdigest()


@lru_cache(maxsize=1)
def _catalog():
    data = (DATA / "firmament-rules.json").read_bytes()
    catalog = json.loads(data)
    if catalog["source_sha"] != SOURCE_SHA:
        raise RuntimeError("Firmament catalog does not match the pinned DFO source")
    return {**catalog, "content_hash": sha256(data).hexdigest()}


def firmament_catalog():
    return deepcopy(_catalog())


def _integer(value, name, maximum):
    if type(value) is not int or not 0 <= value <= maximum:
        raise ValueError(f"{name} must be an integer between 0 and {maximum}")
    return value


def validate_allocation(tree, stars, craft):
    """Check budgets and connectivity, without changing the submitted tree."""
    catalog = _catalog()
    stars = _integer(stars, "Stars", catalog["stars_max"])
    craft = _integer(craft, "Craft points", catalog["craft_max"])
    if not isinstance(tree, dict) or set(tree) != {"start", "keys"}:
        raise ValueError("Firmament tree must contain a start and keys")
    start, keys = tree["start"], tree["keys"]
    starts, nodes = catalog["starts"], catalog["nodes"]
    if start is not None and (not isinstance(start, str) or start not in starts):
        raise ValueError("Unknown Firmament starting sign")
    if (not isinstance(keys, list) or any(not isinstance(key, str) or key not in nodes
                                         or key in starts for key in keys)
            or len(keys) != len(set(keys))):
        raise ValueError("Invalid or duplicate Firmament node")
    if keys and start is None:
        raise ValueError("Choose a starting sign before allocating a Firmament node")
    held = set(keys)
    reachable = set()
    frontier = [start] if start else []
    while frontier:
        key = frontier.pop()
        if nodes[key]["kind"] != "keystone":
            for adjacent in nodes[key]["adjacent"]:
                if adjacent in held and adjacent not in reachable:
                    reachable.add(adjacent)
                    frontier.append(adjacent)
    if held != reachable:
        raise ValueError("Firmament nodes must be connected to the sign through allocated nodes")
    life = sum(nodes[key]["ring"] == "life" for key in held)
    craft_spent = min(craft, life)
    stars_spent = len(held) - craft_spent
    if stars_spent > stars:
        raise ValueError("The Firmament allocation exceeds its Star and Craft budgets")
    return {"tree": {"start": start, "keys": sorted(held)},
            "stars_left": stars - stars_spent, "craft_left": craft - craft_spent}


def fixed_projection(payload, character, rules):
    """Bind a funded, immutable Gear projection to one imported character."""
    allowed = {"tree", "stars", "craft", "profile_id", "revision", "snapshot_hash",
               "ruleset_hash", "catalog_hash"}
    if not isinstance(payload, dict) or set(payload) - allowed or not {"tree", "stars", "craft"} <= payload.keys():
        raise ValueError("Firmament requires a tracked tree and both point budgets")
    catalog = _catalog()
    if payload.get("ruleset_hash", rules["content_hash"]) != rules["content_hash"]:
        raise ValueError("Firmament ruleset does not match this request")
    if payload.get("catalog_hash", catalog["content_hash"]) != catalog["content_hash"]:
        raise ValueError("Firmament catalog changed since this request was saved")
    if "snapshot_hash" in payload:
        snapshot_hash = payload["snapshot_hash"]
        accepted_hashes = (character["snapshot_hash"], character["provenance"].get("parent_snapshot_hash"))
        if not isinstance(snapshot_hash, str) or not snapshot_hash or snapshot_hash not in accepted_hashes:
            raise ValueError("The tracked Firmament tree belongs to a different character snapshot")
    allocation = validate_allocation(payload["tree"], payload["stars"], payload["craft"])
    basis = projection_basis(character, payload["stars"], catalog)
    return (basis, *tree_vectors(allocation["tree"], catalog))


def _limits(raw):
    if not isinstance(raw, dict) or set(raw) - {"max_nodes", "wall_seconds", "memory_bytes", "exact"}:
        raise ValueError("Unknown Firmament search setting")
    exact = raw.get("exact", False)
    if type(exact) is not bool:
        raise ValueError("Firmament exact setting must be a boolean")
    seconds = raw.get("wall_seconds", 0 if exact else 5)
    if type(seconds) not in (int, float) or not isfinite(seconds) or seconds < 0:
        raise ValueError("Firmament wall time must be finite and nonnegative")
    memory = _integer(raw.get("memory_bytes", 128 << 20), "Firmament memory bytes", 2**63 - 1)
    if not memory:
        raise ValueError("Firmament memory limit must be positive")
    return {"max_nodes": _integer(raw.get("max_nodes", 0 if exact else 100_000), "Firmament nodes", 2**63 - 1),
            "wall_seconds": seconds, "memory_bytes": memory}


def _spell(request, character):
    if ("spell" in request) == ("spell_index" in request):
        raise ValueError("Select one supported saved spell or submit one damage spell recipe")
    if "spell" in request:
        return request["spell"]
    spellbook = character["observations"].get("spells")
    records = spellbook.get("records", []) if isinstance(spellbook, dict) else []
    if not isinstance(records, list) or not records:
        raise ValueError("No saved spells were available to score")
    index = _integer(request["spell_index"], "Saved spell index", len(records) - 1)
    record = records[index]
    effects = record.get("effects") if isinstance(record, dict) else None
    if not isinstance(effects, list) or any(not isinstance(e, dict) for e in effects):
        raise ValueError("The selected saved spell has invalid effects")
    effects = [e for e in effects if e.get("type") != -1]
    if len(effects) != 1 or (effects[0].get("type"), effects[0].get("subType")) != (4, 0):
        raise ValueError("Select a single-effect Damage Health spell")
    source = ("magnitudeBaseLow", "magnitudeBaseHigh", "magnitudeLevelBase",
              "magnitudeLevelHigh", "magnitudePerLevel")
    return {"effect_id": "4,0", "element": record.get("element"), "range_type": record.get("rangeType"),
            **{key: effects[0].get(k) for key, k in zip(AXES[2:], source, strict=True)}}


def _checked_row(row, ids, base, recipe, basis, request, catalog, original):
    start = ids[row["start"]] if row["start"] >= 0 else None
    tree = {"start": start, "keys": [ids[i] for i in row["keys"]]}
    stars, craft = request["stars"], request["craft"]
    allocation = validate_allocation(tree, stars, craft)
    additions = [ids[i] for i in row["additions"]]
    current = {"start": original["start"], "keys": list(original["keys"])}
    for key in additions:
        if key in catalog["starts"]:
            if current["start"] is not None:
                raise RuntimeError("Firmament replay changed the starting sign")
            current["start"] = key
        else:
            current["keys"].append(key)
        validate_allocation(current, stars, craft)
    if current["start"] != start or sorted(current["keys"]) != allocation["tree"]["keys"]:
        raise RuntimeError("Firmament purchase order does not produce the selected allocation")
    gains, prices = tree_vectors(tree, catalog)
    context = project_reference(base, basis, gains, prices)
    context["available_sp"] = maximum_sp_reference(basis, gains, prices, basis[3])
    score = evaluate_reference(context, recipe)
    if (score["cost_sp"] != row["cost_sp"] or score["outcomes"] != row["outcomes"]
            or score["health_loss_sum"] != row["health_loss_sum"]
            or round(score["cast_rate"] * 200) != row["rate_200"]
            or context["available_sp"] != row["available_sp"]):
        raise RuntimeError("Native Firmament score disagrees with independent replay")
    return {**allocation, "additions": additions, "cost_sp": score["cost_sp"],
            "available_sp": context["available_sp"], "affordable": score["affordable"],
            "damage_per_second": score["dps"], "damage_per_sp": score["damage_per_sp"]}


def optimize_firmament(request, *, ruleset=None, cancel=None):
    """Search complete allocations using a single fixed Damage Health spell."""
    from . import _firmament

    required = {"character", "tree", "stars", "craft", "target"}
    optional = {"spell", "spell_index", "search", "profile_id", "revision", "ruleset_hash", "catalog_hash"}
    if (not isinstance(request, dict) or not required <= request.keys()
            or request.keys() - required - optional):
        raise ValueError("Invalid Firmament search request")
    rules, catalog = ruleset or load_ruleset(), _catalog()
    if request.get("ruleset_hash", rules["content_hash"]) != rules["content_hash"]:
        raise ValueError("Firmament request uses a different ruleset")
    if request.get("catalog_hash", catalog["content_hash"]) != catalog["content_hash"]:
        raise ValueError("Firmament request uses a different tree catalog")
    character = normalize_character(request["character"])
    stars, craft = request["stars"], request["craft"]
    tree = validate_allocation(request["tree"], stars, craft)["tree"]
    basis = projection_basis(character, stars, catalog)
    status_effects = [v for v in character.get("unknown_mechanics", []) if v.startswith("active_effect:")]
    blockers = [v for v in character.get("unknown_mechanics", []) if v not in status_effects]
    spec = parse_spell_request({"caster": character["caster"], "target": request["target"],
                               "spell": _spell(request, character)}, rules)
    blockers.extend(spec.blockers)
    if blockers:
        raise ValueError("Firmament scoring is unavailable: " + ", ".join(sorted(set(blockers))))
    ids = tuple(sorted(catalog["nodes"]))
    index = {key: i for i, key in enumerate(ids)}
    nodes = []
    for key in ids:
        node = catalog["nodes"][key]
        stats = node["stats"]
        values = tuple(stats.get(channel, 0) for channel in CHANNEL_NAMES)
        nodes.append((node["kind"] == "start", node["ring"] == "life", node["kind"] == "keystone",
                      tuple(index[k] for k in node["adjacent"]),
                      tuple(max(0, n) for n in values), tuple(min(0, n) for n in values)))
    base, recipe = spec.native_context(), spec.recipe()
    limits = _limits(request.get("search", {}))
    result = _firmament.traverse(base, recipe, nodes, index.get(tree["start"], -1),
                                 tuple(index[key] for key in tree["keys"]), stars, craft, basis,
                                 **limits, cancel=cancel)
    baseline = _checked_row(result["baseline"], ids, base, recipe, basis, request, catalog, tree)
    candidates = [_checked_row(row, ids, base, recipe, basis, request, catalog, tree)
                  for row in result["candidates"]]
    exact = result["termination"] == "exhausted"
    return {**result, "schema_version": 1, "engine": "native-cython-cpp17", "exact": exact,
            "status": "exact" if exact else "best_found", "baseline": baseline, "candidates": candidates,
            "counters": {"nodes": result["nodes"], "work_bytes": result["work_bytes"]},
            "limits": limits, "source_sha": SOURCE_SHA, "ruleset_hash": rules["content_hash"],
            "catalog_hash": catalog["content_hash"], "input_hash": _digest(request),
            "advisories": [*(f"Ignored unmodeled status effect {v.removeprefix('active_effect:')}"
                             for v in status_effects),
                           "Assumed full projected SP with the selected tree and worn gear.",
                           "Single damage spell in ordinary unmentored PvE. Incoming damage, recovery, "
                           "weapon damage and crafting benefits are outside the score."]}

"""Native finite spellbook evaluation and per-stage acquisition planning."""
from importlib import import_module
from math import isclose

from .character import normalize_character
from .spell_request import _float, _int, _object, _bool, parse_spell_request
from .spells import _digest, _status

SHAPE = ("base_low", "base_high", "plus_low", "plus_high", "per_level")
CHANCE = ("chance_base", "chance_increment", "chance_per_level")
RANGES = ("element", "range_type", "effects")
SCENE = ("schema_version", "ruleset_hash", "caster", "target", "character", "price_factor",
         "live_observations")


def _number(value, name, lo, hi):
    return _int(value.get(name), name, lo, hi)


def _effect(item):
    if not isinstance(item, dict) or "effect_id" not in item:
        raise ValueError("Effects require an observed Spellmaker effect_id")
    code = item["effect_id"]
    if code == "5,255":
        _object(item, "Disintegrate", ("effect_id", *CHANCE))
        return (1, _number(item, CHANCE[0], 1, 100), _number(item, CHANCE[1], 1, 100),
                0, 0, _number(item, CHANCE[2], 1, 20))
    if code != "4,0":
        raise ValueError(f"unsupported spell effect {code}")
    _object(item, "Damage Health", ("effect_id", *SHAPE))
    low = _number(item, SHAPE[0], 1, 100)
    bonus = _number(item, SHAPE[2], 1, 100)
    return (0, low, _number(item, SHAPE[1], low, 100), bonus,
            _number(item, SHAPE[3], bonus, 100), _number(item, SHAPE[4], 1, 20))


def pack_spell(recipe):
    """Shared read-only payload for the native per-target search."""
    _object(recipe, "spell", RANGES)
    explicit = recipe.get("effects")
    if not isinstance(explicit, (list, tuple)) or not 1 <= len(explicit) <= 3:
        raise ValueError("A fixed spell must have between one and three effects")
    return (_number(recipe, "element", 0, 4), _number(recipe, "range_type", 1, 4),
            tuple(_effect(slot) for slot in explicit))


def _native():
    try:
        return import_module("._spellbook", __package__)
    except ImportError as exc:
        raise RuntimeError("A complete native Damage Health / Disintegrate spellbook backend is required") from exc


def evaluate_loadout(context, spells):
    """Price and evaluate the supplied access-confirmed recipes against one resolved loadout."""
    return _native().evaluate_many(context, [pack_spell(s) for s in spells])


def replay_spell(context, recipe):
    """Independently recompute a selected result at this point in the plan."""
    from .spellbook_reference import replay
    return replay(context, pack_spell(recipe))


def _prepare_context(query, rules):
    prefix = {k: query[k] for k in SCENE if k in query}
    # Spellmaker casts and spellbooks share a user-input schema for the player, target and live skill.
    pending = parse_spell_request({**prefix, "domain": {"element": [0], "range_type": [1],
        **{k: [1] for k in SHAPE}}}, rules, auto=True)
    return pending, pending.native_context()


def _known_recipes(query):
    if "character" not in query:
        return None
    observed = normalize_character(query["character"])["observations"]["spells"]
    return {s for x in observed.get("records", []) if (s := _packet_for(x)) is not None}


def _packet_for(example):
    if not isinstance(example, dict) or example.get("custom") is not True:
        return None
    seen = []
    for piece in example.get("effects") or []:
        if not isinstance(piece, dict):
            return None
        if piece.get("type") == -1:
            continue
        if (piece.get("type"), piece.get("subType")) == (4, 0):
            saved = ("magnitudeBaseLow", "magnitudeBaseHigh", "magnitudeLevelBase",
                     "magnitudeLevelHigh", "magnitudePerLevel")
            effect = {"effect_id": "4,0", **dict(zip(SHAPE, (piece.get(k) for k in saved), strict=True))}
        elif piece.get("type") == 5 and piece.get("subType") in (-1, 255):
            saved = ("chanceBase", "chanceMod", "chancePerLevel")
            effect = {"effect_id": "5,255", **dict(zip(CHANCE, (piece.get(k) for k in saved), strict=True))}
        else:
            return None
        seen.append(effect)
    try:
        return pack_spell({"element": example.get("element"), "range_type":example.get("rangeType"),
                           "effects": seen})
    except ValueError:
        return None


def _routes(query, scene, access):
    variants = query.get("spells", [])
    if not isinstance(variants, list) or not variants or len(variants) > 3000:
        raise ValueError("A loadout needs 1 to 3000 spell offers")
    met_price = scene.price_factor is not None and scene.caster.gold is not None
    labels, values, claims, packed = [], [], {}, {}
    notes = set()
    known = _known_recipes(query)
    for row in variants:
        _object(row, "spell offer", ("id", "route", "spell"))
        label = row.get("id")
        if not isinstance(label, str) or not label or len(label) > 256 or label in claims:
            raise ValueError("Every spell name must link to one distinct purchase")
        control = row.get("route")
        if control not in ("known", "maker"):
            raise ValueError("The spell route must be known or maker")
        s = pack_spell(row.get("spell"))
        if s in packed:
            raise ValueError("Duplicate spell recipes require a single readied acquisition record")
        if control == "known":
            val = 0 if known is None or s in known else -1
            if val < 0:
                notes.add(f"{label}: no matching learned spell in the supplied save")
        else:
            val = 1 if access and scene.caster.has_spellbook and met_price else -1
            if val < 0 and (access is None or scene.caster.has_spellbook is None or not met_price):
                notes.add(f"{label}: incomplete maker pricing, book or access evidence")
        packed[s] = label
        claims[label] = (val, row["spell"])
        labels.append(label)
        values.append((s, val))
    return labels, values, claims, notes


def _check(points, labels, curves, context, corresponding):
    merged = {}
    result = []
    for evidence in points:
        purchases = set()
        cast_orders = [labels[i] for i in evidence["paid_casts"]]
        consumption = treasure = 0
        gain = 0.0
        elapsed = last_release = 0.0
        for name in cast_orders:
            mode, recipe = curves[name]
            if name not in merged:
                merged[name] = replay_spell(context, recipe)
            q = merged[name]
            if mode not in (0, 1):
                raise RuntimeError("Ineligible spell requested by cached policy")
            if name not in purchases and mode == 1:
                treasure += q["purchase_gold"]
                purchases.add(name)
            consumption += q["cost_sp"]
            gain += q["expected_health_loss"]
            last_release = elapsed + q["release_seconds"]
            elapsed += q["recovery_seconds"]
        if (consumption > context["available_sp"] or treasure > corresponding
                or consumption != evidence["sp_spent"] or treasure != evidence["gold_spent"]
                or not isclose(gain, evidence["expected_damage"], abs_tol=1e-10, rel_tol=1e-12)):
            raise RuntimeError("Native action policy failed an exact target/damage/SP/gold replay")
        result.append({"policy": cast_orders, "purchases": sorted(purchases), "expected_damage": gain,
                       "sp_spent": consumption, "gold_spent": treasure,
                       "damage_per_sp": gain/consumption if consumption else None,
                       "last_release_seconds": last_release, "ready_again_seconds": elapsed})
    return sorted(result, key=lambda r: (-r["expected_damage"], r["sp_spent"], r["gold_spent"], r["policy"]))


def _run(request, ruleset, token, alternate):
    from .ruleset import validate_progression_ruleset, load_ruleset
    rules = validate_progression_ruleset(load_ruleset() if ruleset is None else ruleset)
    raw = _object(request, "effect policy", (*SCENE, "max_casts", "policy", "spells", "exact",
                                            "maker_access", "search"))
    kind = "native_spellbook_v1"
    scene, context = _prepare_context(raw, rules)
    access = _bool(raw.get("maker_access"), "maker_access")
    labels, actual, shapes, extra = _routes(raw, scene, access)
    keep = raw.get("policy")
    if alternate and keep is not None:
        raise ValueError("For fixed settings choose a spellbook policy evaluation")
    if not alternate and (not isinstance(keep, list) or not keep):
        raise ValueError("A fixed stage policy requires at least one staged spell")
    if not alternate and any(type(i) is not str or i not in shapes for i in keep):
        raise ValueError("Policy refers to an unknown spell")
    default = len(keep) if keep else 1
    horizon = _int(raw.get("max_casts", default) if alternate else default, "spellbook cast horizon", 1, 64)
    scope = _object(raw.get("search", {}), "user stages", ("max_nodes", "wall_seconds", "memory_bytes"))
    exact = _bool(raw.get("exact", False), "exact")
    n = _int(scope.get("max_nodes", 0 if exact else 100_000), "max_nodes", 0, 2**63-1)
    t = _float(scope.get("wall_seconds", 0), "wall_seconds", 0, 86400)
    memory = _int(scope.get("memory_bytes", 64 << 20), "memory_bytes", 1, 2**63-1)
    pool = scene.caster.gold or 0
    if scene.blockers:
        packet = {"termination":"unsupported","policies":[], "native":None}
    else:
        paths = {label: i for i, label in enumerate(labels)}
        packet = _native().search_book(context, actual, [paths[x] for x in keep or []],
                     casts=horizon, gold=pool, max_nodes=n, wall_seconds=t,
                     memory_bytes=memory, token=token)
    quotation = packet.get("policies", [])
    status = _status(packet["termination"], bool(quotation))
    routes = _check(quotation, labels, shapes, context, pool)
    incoming = _digest([raw, rules["content_hash"], kind])
    out = {"schema_version":1, "engine":kind, "mode":"finite_spellbook", "input_hash":incoming,
           "result_hash": _digest([incoming, status, routes, tuple(sorted(extra))]),
           "search_exact": packet["termination"]=="exhausted" and not extra,
           "search_depth":horizon, "status":status, "source_sha":rules["source_sha"],
           "ruleset_hash":rules["content_hash"], "termination":packet["termination"], "candidates":routes,
           "mechanic_ids": ["spell.maker", "spell.cast_cost", "spell.saves", "spell.cadence",
                            "pve.spell_damage", "spell.disintegrate", "spell.multi_effect", "spell.native_spellbook"],
           "unsupported_mechanics": sorted(set(scene.blockers) | extra),
           "scenario": "Each cast has one confirmed hit on a fresh stationary target at the displayed HP. The pool and native modifier values are fixed for this step.",
           "counters": {k: v for k,v in packet.items() if k not in ("policies", "termination")}}
    if extra and status in ("optimal_proven", "infeasible_proven"):
        out["status"] = "supported_subset" if routes else "unsupported"
        out["result_hash"] = _digest([incoming, out["status"], tuple(sorted(extra)), routes])
    return out


def evaluate_spellbook(request, *, ruleset=None, cancel=None):
    return _run(request, ruleset, cancel, False)


def optimize_spellbook(request, *, ruleset=None, cancel=None):
    return _run(request, ruleset, cancel, True)

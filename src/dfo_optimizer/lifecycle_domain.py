"""Freeze class, physical-copy, spell and opportunity identities before native expansion."""

from dataclasses import dataclass
import math

from .classes import validate_class_snapshot
from .gear import _packed
from .gear_request import prepare_inventory
from .gear_capacity import capacity
from .progression_domain import fields, require
from .spell_request import _target, MASKS, CHANNELS


def catalog(families, rules):
    from .build_baselines import resolve_family_baseline

    require(isinstance(families, list) and 0 < len(families) <= 10000, "families must be a nonempty list")
    seen = set()
    for family in families:
        fields(family, {"id", "start", "baseline_id"}, "family")
        name = family.get("id")
        require(isinstance(name, str) and name.strip() and name not in seen, "invalid or duplicate family id")
        seen.add(name)
        require(("start" in family) != ("baseline_id" in family), "family needs one start or baseline_id")
        start = (
            resolve_family_baseline(family["baseline_id"], rules) if "baseline_id" in family else family["start"]
        )
        require(isinstance(start, dict), "family start must be an object")
        reason = None
        if start.get("type") == "new_character":
            profile = start.get("profile", "dhargo_pve")
            facts = validate_class_snapshot(
                start.get("class"), race=start.get("race_id"), ruleset=rules, profile=profile
            )
            if not facts["create_legal"] or facts["skipped"] or facts.get("race_id") is None:
                issues = [*facts["errors"], *facts["create_errors"]]
                if facts["skipped"]:
                    issues.append("skipped class traits")
                if facts.get("race_id") is None:
                    issues.append("unknown race")
                reason = "Class creation constraints: " + ", ".join(issues)
            elif profile == "dhargo_pve" and not facts["profile_legal"]:
                reason = "dhargo_pve class constraints: " + ", ".join(facts["profile_errors"])
        yield name, start, family.get("baseline_id"), reason


def rows_at(value, name):
    if value is None:
        return None
    require(
        isinstance(value, list)
        and all(type(x) is int and 0 <= x <= 100000 for x in value)
        and len(set(value)) == len(value),
        f"{name} must list distinct checkpoint indices",
    )
    return set(value)


def record_recipe(record):
    require(
        isinstance(record, dict)
        and isinstance(record.get("effects", []), list)
        and all(isinstance(e, dict) for e in record.get("effects", [])),
        "invalid saved spell effects",
    )
    if record.get("minimumCastingCost") or record.get("pvpKitCost"):
        return None
    if record.get("path"):
        return None
    effects = []
    for row in record.get("effects", []):
        kind = row.get("type"), row.get("subType")
        if kind[0] == -1:
            continue
        if kind == (4, 0):
            recipe = {
                "effect_id": "4,0",
                **dict(
                    zip(
                        ("base_low", "base_high", "plus_low", "plus_high", "per_level"),
                        [
                            row.get(k)
                            for k in (
                                "magnitudeBaseLow",
                                "magnitudeBaseHigh",
                                "magnitudeLevelBase",
                                "magnitudeLevelHigh",
                                "magnitudePerLevel",
                            )
                        ],
                        strict=True,
                    )
                ),
            }
        elif kind in ((5, 255), (5, -1)):
            recipe = {
                "effect_id": "5,255",
                "chance_base": row.get("chanceBase"),
                "chance_increment": row.get("chanceMod"),
                "chance_per_level": row.get("chancePerLevel"),
            }
        else:
            return None
        effects.append(recipe)
    if not effects or record.get("rangeType") not in (1, 2, 3, 4):
        return None
    return {"effects": effects, "element": record.get("element"), "range_type": record["rangeType"]}


def book_domain(config, source, actions):
    from .spellbook import pack_spell

    config = fields(config, {"spells", "policies", "mode", "maker", "include_known", "allow_unarmed_start"}, "spellbook")
    require(type(config.get("allow_unarmed_start", False)) is bool, "allow_unarmed_start must be boolean")
    include = config.get("include_known", True)
    require(type(include) is bool, "include_known must be boolean")
    found = {}
    omitted = [str(i) for i in source.get("unresolved_indices", []) if include]
    records = [*source.get("spell_records", []), *(a["record"] for a in actions if a.get("record"))]
    if include:
        for record in records:
            identifier = record["index"]
            recipe = record_recipe(record)
            if recipe is None:
                omitted.append(str(identifier))
                continue
            try:
                pack_spell(recipe)
            except ValueError:
                omitted.append(str(identifier))
                continue
            key = "known/" + str(identifier)
            if key in found and found[key][1] != recipe:
                raise ValueError("conflicting indexed spell records")
            found[key] = (identifier, recipe)
    recipes = config.get("spells", [])
    require(isinstance(recipes, list) and len(recipes) <= 63, "spells must list up to 63 candidates")
    for entry in recipes:
        fields(entry, {"id", "recipe"}, "spell candidate")
        key = entry.get("id")
        require(
            isinstance(key, str) and key.strip() and not key.startswith("known/") and key not in found,
            "invalid or duplicate recipe identity",
        )
        pack_spell(entry.get("recipe"))
        found[key] = (None, entry["recipe"])
    ids = sorted(found)
    mode = config.get("mode", "auto_spellbook")
    require(mode in ("auto_spellbook", "fixed_spellbook"), "invalid spellbook mode")
    scripts = config.get("policies", [[k] for k in ids])
    require(isinstance(scripts, list) and len(scripts) <= 65536, "invalid policies")
    if mode == "fixed_spellbook":
        require(len(scripts) == 1, "fixed_spellbook needs one explicit ordered policy")
    for p in scripts:
        require(
            isinstance(p, list) and 1 <= len(p) <= 128 and all(k in found for k in p),
            "unknown spell in casting policy",
        )
    require(len(set(map(tuple, scripts))) == len(scripts), "duplicate casting policy")
    maker = config.get("maker")
    if maker is not None:
        fields(maker, {"source", "price_factor", "stages"}, "Spell Maker opportunity")
        require(
            isinstance(maker.get("source"), str) and maker["source"].strip(), "Spell Maker access needs evidence"
        )
        f = maker.get("price_factor")
        require(type(f) in (int, float) and 0 < f <= 1000 and math.isfinite(f), "unknown Spell Maker price factor")
        rows_at(maker.get("stages"), "maker stages")
    return ids, [found[k] for k in ids], scripts, maker, sorted(set(omitted))


def _offer_stages(offers):
    require(isinstance(offers, list), "invalid physical offers")
    windows = {}
    for offer in offers:
        require(isinstance(offer, dict) and isinstance(offer.get("instance_id"), str), "invalid physical offer")
        acq = offer.get("acquisition")
        require(
            isinstance(acq, dict) and isinstance(acq.get("source"), str) and acq["source"].strip(),
            "physical offers need attributed acquisition evidence",
        )
        windows[offer["instance_id"]] = rows_at(offer.get("stages"), "offer stages")
    return windows


def gear_domain(config, source):
    fields(config, {"offers", "loadouts", "locks", "available_containers", "exclusions"}, "equipment")
    offers = config.get("offers", [])
    windows = _offer_stages(offers)
    req = {k: v for k, v in config.items() if k not in ("loadouts", "offers")}
    req.update(
        mode="owned_plus_budget",
        budget={"gold": 2**53 - 1},
        inventory=source.get("inventory", []),
        offers=offers,
        career=source.get("career"),
        character={"gear": {"gender": source.get("gender")}},
    )
    # Registries contain books and other nonwearables too. M3 retains exclusion reasons.
    domain = prepare_inventory(req)
    declared = config.get("loadouts")
    packed = None
    if declared is not None:
        require(isinstance(declared, list) and len(declared) <= 10000, "invalid loadout list")
        keys = {item.identity: i for i, item in enumerate(domain.items)}
        packed = []
        for row in declared:
            fields(row, domain.slots, "loadout")
            if any(v is not None and v not in keys for v in row.values()):
                continue
            selected = [-1] * 27
            for slot, identity in row.items():
                if identity is not None:
                    selected[domain.slots[slot]] = keys[identity]
            if selected not in packed:
                packed.append(selected)
    copies, slots, _ = _packed(domain)
    locks = config.get("locks", {})
    empty = sum(1 << domain.slots[k] for k, v in locks.items() if v is None)
    slots = [
        (lock, current, preferred, [(i, m) for i, m in places if not m & empty])
        for lock, current, preferred, places in slots
    ]
    return domain, copies, slots, packed, windows, capacity(req, domain)


def context(st, target):
    from .progression_replay import effective

    for k in ("attributes", "skills", "mastered", "sp", "level"):
        require(st.get(k) is not None, f"missing checkpoint observation {k}")
    n = st["skills"][22]
    require(type(n) is int and type(st["attributes"][6]) is int, "missing caster skill or speed")
    climb = effective(n if 22 in st["mastered"] else min(100, n))
    t = _target(target)
    return {
        "level": st["level"],
        "live_skill": climb,
        "climb": climb,
        "speed": min(st["attributes"][6], 100),
        "available_sp": st["sp"],
        "target_hp": t.hp,
        "willpower": t.willpower,
        **{k: getattr(t, k) for k in (*MASKS, *CHANNELS)},
        "pierce": 0,
        "focus_pct": 0,
        "cast_speed_pct": 0,
        "power_pct": 0,
    }


def maker_price(row, factor):
    from .spellbook import pack_spell

    _, target, slots = pack_spell(row)
    gold = sum(
        20 * ((a + b) // 2) + 28 * (((c + d) // 2) // gap) if kind == 0 else 80 * a + 140 * (b // gap)
        for kind, a, b, c, d, gap in slots
    )
    return max(1, math.floor((gold * (target + 1) // 2) * factor + 0.5))


@dataclass
class Domain:
    source: dict
    states: list
    indices: list
    stages: list
    book: list
    names: list
    scripts: list
    domain: object
    copies: list
    slots: list
    declared: list | None
    owned: int
    names_all: list
    omitted: list
    actions: list
    encounters: list | None = None
    firmament: list | None = None
    objective: str = "legacy"
    encounter_gaps: tuple = ()


def compile_route(raw, source, route, rules=None, start=None):
    from .spellbook import pack_spell

    states = [row["state"] for row in route["checkpoints"]]
    wanted = raw.get("checkpoints")
    if raw.get("encounter",{}).get("at","terminal") == "terminal" and "encounter" in raw:
        indices = [len(states)-1]
    elif wanted is None:
        indices = [0]
        for i in range(1, len(states)):
            if states[i]["level"] != states[i - 1]["level"] and states[i]["level"] % 5 == 0:
                indices.append(i)
        if indices[-1] != len(states) - 1:
            indices.append(len(states) - 1)
    else:
        indices = sorted(rows_at(wanted, "checkpoints"))
        require(
            indices and indices[0] == 0 and indices[-1] == len(states) - 1,
            "checkpoints must include the actual start and final progression stage",
        )
    names, book, policies, maker, omitted = book_domain(raw.get("spellbook", {}), source, route["actions"])
    if (raw.get("spellbook", {}).get("allow_unarmed_start") and source.get("boundary") == "creation"
            and len(indices) > 1 and indices[0] == 0 and "encounter" not in raw):
        policies = [*policies, []]
    domain, copies, slots, declared, windows, cap = gear_domain(raw.get("equipment", {}), source)
    owned = sum(1 << i for i, it in enumerate(domain.items) if it.owned)
    starting_known = {
        pack_spell(recipe) for identifier, recipe in book if identifier in (source.get("known") or [])
    }
    for j, (identifier, recipe) in enumerate(book, len(copies)):
        if (
            identifier in (source.get("known") or [])
            if identifier is not None
            else pack_spell(recipe) in starting_known
        ):
            owned |= 1 << j
    stages = []
    firmament = []
    for ordinal, i in enumerate(indices):
        state = states[i]
        target = raw.get("targets", {}).get(str(i), raw["target"])
        ctx = context(state, target)
        if "encounter" in raw:
            from .firmament_combat import modifiers
            sky = modifiers(raw["encounter"], states[0], state, rules["permanent_rules"], start)
            ctx = {**ctx, **{k:ctx[k]+v for k,v in sky.items()}}
            firmament.append(sky)
        if "encounter" in raw and state.get("martial_path") == "windrunner":
            # The M4 state has permanent attributes before the live martial and equipment fold.
            ctx["speed"] = min(100, ctx["speed"] + 10)
        next_i = indices[ordinal + 1] if ordinal + 1 < len(indices) else i
        # Leaving funds for every intervening action includes the next checkpoint's
        # training, and covers costs paid between two reported checkpoints.
        funds = [s["gold"] for s in states[i : next_i + 1]]
        require(all(type(v) is int and v >= 0 for v in funds), "missing checkpoint spendable gold")
        ceiling = min(*funds, raw.get("budget_gold", 2**53 - 1) - route["effort"]["spent"])
        prices = []
        for item in domain.items:
            window = windows.get(item.identity)
            prices.append(
                -1
                if item.owned or item.price is None or window is not None and i not in window
                else dict(item.price).get("gold", 0)
            )
        known = state.get("known") or []
        known_recipes = {pack_spell(recipe) for identifier, recipe in book if identifier in known}
        for identifier, recipe in book:
            if identifier is not None:
                prices.append(0 if identifier in known else -1)
            else:
                open_maker = (
                    maker
                    and source.get("has_spellbook") is True
                    and ("stages" not in maker or i in maker["stages"])
                )
                prices.append(
                    0
                    if pack_spell(recipe) in known_recipes
                    else maker_price(recipe, maker["price_factor"])
                    if open_maker
                    else -1
                )
        sp_floor = state["sp"]
        debt_cap = 2**53 - 1
        for j in range(i + 1, next_i + 1):
            action = route["actions"][j - 1]
            if action["kind"] == "rest" and action.get("recovery") == "full_bed":
                debt_cap = 0
            if action["kind"] == "rest" and action.get("refill_sp") is not None:
                floor = action["refill_sp"]
                maximum = source["max_sp"]
                require(
                    maximum is not None
                    and 0 <= floor <= min(maximum, 8 * max(1, maximum // 8))
                    and not source["career"].get("abilityFlagsAndSpellPointsBitfield", 0) & 8,
                    "unverified online rest recovery",
                )
                # Relative to the unmodified practice route, the outstanding
                # extra SP spend shrinks to the gap above the guaranteed floor.
                debt_cap = min(debt_cap, states[j]["sp"] - floor)
            if debt_cap > states[j]["sp"]:
                sp_floor = min(sp_floor, states[j]["sp"])
        stages.append(
            (
                ctx,
                ceiling,
                prices,
                min(state["attributes"][1], 100),
                cap.quarters,
                cap.current_int,
                cap.uncertain_worn,
                sp_floor,
                debt_cap,
            )
        )
    asset_ids = [it.identity for it in domain.items] + names
    require(len(set(asset_ids)) == len(asset_ids), "physical and spell identities collide")
    encounters = None
    encounter_gaps = ()
    if "encounter" in raw:
        from .lifecycle_encounter import bind
        encounters, slots, declared, policies, encounter_gaps = bind(
            raw["encounter"], states, indices, stages, route["actions"], book, names, policies,
            source, domain, slots, declared, rules)
    return Domain(
        source,
        states,
        indices,
        stages,
        book,
        names,
        policies,
        domain,
        copies,
        slots,
        declared,
        owned,
        asset_ids,
        omitted,
        route["actions"],
        encounters,
        firmament,
        raw.get("objective", "legacy"), tuple(encounter_gaps),
    )

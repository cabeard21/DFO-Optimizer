"""Bind the observed checkpoint to a frozen encounter and replay only emitted decisions."""
from .encounter_request import _scenario
from .progression_domain import evidence, fields, integer
from .progression_replay import require


class EncounterGap(ValueError):
    """A checkpoint lacks the evidence needed to enter or leave combat."""


def _powers(state, path_rows, chained, observation):
    from . import encounter_advanced_reference as powers
    active = {}
    for family, ids, key in (("arcane", powers.PATH_IDS, "path_id"),
                             ("martial", powers.MARTIAL_IDS, "martial_id")):
        name = state.get(family + "_path")
        if not name:
            continue
        law = next((r for r in path_rows if r["id"] == name and r["family"] == family), None)
        if not law or name not in ids or not set(law["skills"]) <= set(state["mastered"]):
            raise EncounterGap("path requires the verified permanent mastery pair and an encounter implementation")
        if observation is None:
            raise EncounterGap("active paths require an attributed ordinary online PvE context")
        if name == "trickster":
            raise EncounterGap("Trickster panic requires an enemy AI response")
        if name in {"shadowcaster","seer","elementalist","hierophant","necromancer","soulbinder",
                    "bladedancer","juggernaut","bloodletter","brawler","vanguard"}:
            if chained:
                raise EncounterGap("this path requires fresh verified effects, timers and combat state at one encounter")
        active[key] = ids[name]
    return active


def _passive_round(career, scene, environment):
    # passiveSpecialsMagicRound gates on the absolute magic-round number % 4.
    # The event clock carries the next round time, without the game world's
    # absolute phase, prison/temple/swimming flags or the worn hood state.
    if scene["first_round_us"] > scene["horizon_us"]:
        return
    flags = career.get("abilityFlagsAndSpellPointsBitfield", 0)
    if flags & 16 and environment != "darkness":
        raise EncounterGap("Damage from Sunlight requires the passive round phase, exposure and hood state")
    if flags & 32:
        raise EncounterGap("Damage from Holy Places requires the passive round phase and temple exposure")
    if career.get("regeneration") and (scene["incoming"] or scene["hp"] < scene["max_hp"]):
        raise EncounterGap("Regenerate Health requires the passive round phase and career-specific conditions")


def hostile_catalog(control, names):
    from .encounter_request import _slot, array, label
    from .spellbook import pack_spell

    ids, recipes, shapes = [], [], []
    for row in array(control.get("hostile_spells", []), "hostile spell catalog", 0, 128):
        fields(row, {"id", "recipe", "evidence"}, "hostile spell")
        key = label(row.get("id"), "hostile spell id")
        require(key not in ids and key not in names, "duplicate player or hostile spell id")
        evidence(row.get("evidence"))
        recipe = row.get("recipe")
        pack_spell(recipe)
        ids.append(key)
        recipes.append(recipe)
        shapes.append({"range_type":recipe["range_type"], "effects":[_slot(e, [])[0] for e in recipe["effects"]]})
    return ids, recipes, shapes


def _item_gap(item, incoming, bundles):
    affixes = item.get("affixes", [])
    if "blow" in incoming and any(a.get("id") == "thorns" for a in affixes):
        return "incoming blows require joint replay of the physical Thorns roll"
    if bundles and (item.get("legendary") or item.get("enchantments") or
            any(a.get("id") not in ("castSpeed","focus","potency","skill","stat") or
                a.get("id") == "stat" and a.get("param") not in ("speed","personality","luck") for a in affixes)):
        return "hostile spells require verified equipped defenses and SP capacity"
    if "spell" in incoming and item.get("enchantments"):
        from .equipment import equipment_catalog
        absorbs = equipment_catalog()["enchantment_types"]["AbsorbsSpells"]
        if any(e.get("type") == absorbs for e in item["enchantments"]):
            return "equipped spell absorption requires a resolved hostile spell"
    return None


def _supported_options(gear, slots, declared, policies, names, book, incoming, bundles, chained):
    available = {j for lock,_,_,places in slots for j,_ in places if lock == -2 or lock == j}
    if declared is not None:
        available.intersection_update(j for row in declared for j in row if j >= 0)
    blocked = {}
    for j in sorted(available):
        reason = _item_gap(gear.items[j].item, incoming, bundles)
        if reason:
            blocked[j] = f"{gear.items[j].identity}: {reason}"
    filtered_slots = [(lock,cur,pref,[(j,m) for j,m in places if j not in blocked])
                      for lock,cur,pref,places in slots] if blocked else slots
    filtered_layouts = [row for row in declared if blocked.keys().isdisjoint(row)] if declared is not None and blocked else declared
    restricted = {}
    requested = {k for script in policies for k in script}
    for k, (_, recipe) in zip(names, book, strict=True):
        if k not in requested:
            continue
        if recipe["range_type"] == 4:
            restricted[k] = f"{k}: Area at range needs actor self-blast defense at every checkpoint"
        elif chained and recipe["range_type"] != 1:
            restricted[k] = f"{k}: chained encounters require touch policies"
    scripts = [row for row in policies if restricted.keys().isdisjoint(row)] if restricted else policies
    return filtered_slots, filtered_layouts, scripts, [*blocked.values(), *restricted.values()]


def bind(raw, states, indices, stages, actions, book, names, policies, source, gear, slots, declared, rules):
    control = fields(raw, {"at", "seed", "scenario", "idle_us", "evidence",
                           "path_evidence", "firmament_evidence", "environment", "hostile_spells"}, "build encounter")
    require(control.get("at", "terminal") in ("terminal", "checkpoints"), "invalid encounter checkpoint mode")
    seed = integer(control.get("seed"), "encounter seed", 0, 2**32-1)
    observation = control.get("path_evidence")
    if observation is not None:
        fields(observation, {"source","observed_at_ms","context","initial_state"}, "path evidence")
        evidence(observation.get("source"))
        integer(observation.get("observed_at_ms"), "observed path time", 0, 2**53-1)
        if observation.get("context") != "ordinary_online_pve" or observation.get("initial_state") != "fresh":
            raise EncounterGap("active paths require a fresh ordinary online PvE encounter observation")
    evidence(control.get("evidence"))
    scene_input = control.get("scenario")
    require(isinstance(scene_input, dict), "encounter scenario must be an object")
    incoming = scene_input.get("incoming", [])
    require(isinstance(incoming, list), "incoming events must be a list")
    has_bundles = any(isinstance(row, dict) and row.get("kind") == "bundle" for row in incoming)
    environment = control.get("environment")
    require(environment in (None,"darkness","daylight"), "unknown encounter environment")
    ids, hostile, shapes = hostile_catalog(control, names)
    if has_bundles and not hostile:
        raise EncounterGap("hostile spell bundles require an attributed hostile catalog and checkpoint defenses")
    if has_bundles:
        if source.get("boundary") != "creation" or source.get("birth_rolls") is None:
            raise EncounterGap("hostile spells require a verified checkpoint race, biography and active defenses")
        if environment is None and source["career"].get("spellAbsorptionFlags") in (1, 2):
            raise EncounterGap("conditional career absorption needs a declared encounter environment")
        unknown_ids = {e.get("spell") for e in incoming if e.get("kind") == "bundle"} - set(ids)
        require(not unknown_ids, "incoming spell absent from hostile catalog")
    incoming_kinds = {row.get("kind") for row in incoming if isinstance(row, dict) and isinstance(row.get("kind"), str)}
    if "spell" in incoming_kinds and source["career"].get("spellAbsorptionFlags"):
        raise EncounterGap("career spell absorption requires a resolved hostile spell and verified environment")
    options = _supported_options(gear, slots, declared, policies, names, book,
                                 incoming_kinds, has_bundles, len(indices) > 1)
    if len(indices)>1:
        idle = integer(control.get("idle_us", 0), "inter-encounter downtime in microseconds", 0, 2**31-1)
        if idle < 1_400_000:
            raise EncounterGap("chained encounters require touch policies and at least 1.4 seconds of verified safe downtime")
        if any(a["kind"] not in ("skip","buy","master","practice","train") for a in actions):
            raise EncounterGap("intervening activity changes HP/SP or effects without an exact transition")
    panel = []
    for idx, stage in zip(indices, stages, strict=True):
        state = states[idx]
        if any(type(state.get(k)) is not int for k in ("hp","max_hp","max_sp")) or state["hp"] <= 0:
            raise EncounterGap("missing live HP, HP capacity, or SP capacity at encounter entry")
        active = _powers(state, rules["progression_rules"]["paths"], len(indices) > 1, observation)
        actor = {"caster":stage[0], **active, **{k:state[k] for k in ("hp","max_hp","max_sp")}}
        reasons = []
        if has_bundles:
            from .lifecycle_defenses import career_absorption, player_save_channels
            race = next(r for r in rules["races"] if r["id"] == source["race_id"])
            defense = player_save_channels(race["flags"], source["career"], state["attributes"][2])
            defense.pop("pierce")  # Player offensive pierce is applied only on outgoing NPC hits.
            actor["caster"] = {**stage[0], **defense}
            actor["player_defense"] = defense
            actor["wards"] = {"career_absorbs":career_absorption(source["career"], environment)}
            actor["hostile_recipes"] = hostile
        scene = _scenario(scene_input, actor, reasons, ids, shapes)
        # Incoming and player spells share a read-only kernel catalog. Policies
        # and asset masks address only the player's book.
        for event in scene["incoming"]:
            if event["kind"] == "bundle":
                event["spell"] += len(book)
        if any(e["wards"].get("reflect_chance") for e in scene["enemies"]):
            raise EncounterGap("reflected player spells require the player's actual checkpoint defenses")
        if reasons:
            raise EncounterGap(", ".join(reasons))
        _passive_round(source["career"], scene, environment)
        if scene["recovery"] or any("rest_hp" in room for room in scene.get("rooms", [])):
            raise EncounterGap("encounter consumables and recovery require tracked cross-stage provenance")
        panel.append((scene, seed))
    return (panel, *options)


def replay_point(panel, context, book, names, available_hp, available_sp, wellspring):
    from .encounter_reference import simulate_trial
    from .encounter_request import _slot
    from .spellbook import pack_spell
    from .spellbook_reference import _state, _tally
    scene, seed = panel
    actual = {**scene, "caster":{**context,**scene.get("player_defense", {}),"available_sp":available_sp}, "hp":available_hp,
              "wellspring_pct":wellspring}
    spells = []
    if scene.get("hostile_recipes"):
        catalog = list(book.values()) + scene["hostile_recipes"]
        indices = [list(book).index(name) for name in names]
    else:
        catalog = [book[name] for name in names]
        indices = range(len(names))
    for recipe in catalog:
        cost, _, _ = _tally(_state(context), pack_spell(recipe))
        slots = [_slot(e, [])[0] for e in recipe["effects"]]
        spells.append({"effects":slots, "range_type":recipe["range_type"], "element":recipe["element"],
                       "cost_sp":cost, "climb":context["climb"]})
    trial = simulate_trial(actual, spells, [{"spell":i} for i in indices], seed)
    score = trial["damage"]*1_000_000/scene["horizon_us"]
    return score, trial

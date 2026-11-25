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


def bind(raw, states, indices, stages, actions, book, names, policies, source, gear, declared, paths):
    control = fields(raw, {"at", "seed", "scenario", "idle_us", "evidence",
                           "path_evidence", "firmament_evidence"}, "build encounter")
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
    if any(isinstance(row, dict) and row.get("kind") == "bundle" for row in incoming):
        raise EncounterGap("hostile spell bundles require a verified hostile catalog and checkpoint defenses")
    incoming_kinds = {row.get("kind") for row in incoming if isinstance(row, dict) and isinstance(row.get("kind"), str)}
    if "spell" in incoming_kinds and source["career"].get("spellAbsorptionFlags"):
        raise EncounterGap("career spell absorption requires a resolved hostile spell and verified environment")
    possible = {k for row in declared for k in row if k >= 0} if declared is not None else range(len(gear.items))
    for index in possible:
        it = gear.items[index]
        if "blow" in incoming_kinds and any(line.get("id") == "thorns" for line in it.item.get("affixes", [])):
            raise EncounterGap("incoming blows require joint replay of the physical Thorns roll")
        if "spell" in incoming_kinds and it.item.get("enchantments"):
            from .equipment import equipment_catalog
            absorbs = equipment_catalog()["enchantment_types"]["AbsorbsSpells"]
            if any(e.get("type") == absorbs for e in it.item["enchantments"]):
                raise EncounterGap("equipped spell absorption requires a resolved hostile spell")
    requested = {k for script in policies for k in script}
    ranges = {recipe["range_type"] for k, (_,recipe) in zip(names, book, strict=True) if k in requested}
    if 4 in ranges:
        raise EncounterGap("Area at range needs actor self-blast defense at every checkpoint")
    if len(indices)>1:
        idle = integer(control.get("idle_us", 0), "inter-encounter downtime in microseconds", 0, 2**31-1)
        if idle < 1_400_000 or ranges != {1}:
            raise EncounterGap("chained encounters require touch policies and at least 1.4 seconds of verified safe downtime")
        if any(a["kind"] not in ("skip","buy","master","practice","train") for a in actions):
            raise EncounterGap("intervening activity changes HP/SP or effects without an exact transition")
    panel = []
    for idx, stage in zip(indices, stages, strict=True):
        state = states[idx]
        if any(type(state.get(k)) is not int for k in ("hp","max_hp","max_sp")) or state["hp"] <= 0:
            raise EncounterGap("missing live HP, HP capacity, or SP capacity at encounter entry")
        active = _powers(state, paths, len(indices) > 1, observation)
        actor = {"caster":stage[0], **active, **{k:state[k] for k in ("hp","max_hp","max_sp")}}
        reasons = []
        scene = _scenario(scene_input, actor, reasons, [], [])
        if any(e["wards"].get("reflect_chance") for e in scene["enemies"]):
            raise EncounterGap("reflected player spells require the player's actual checkpoint defenses")
        if reasons:
            raise EncounterGap(", ".join(reasons))
        if scene["recovery"] or any("rest_hp" in room for room in scene.get("rooms", [])):
            raise EncounterGap("encounter consumables and recovery require tracked cross-stage provenance")
        panel.append((scene, seed))
    return panel


def replay_point(panel, context, book, names, available_hp, available_sp, wellspring):
    from .encounter_reference import simulate_trial
    from .encounter_request import _slot
    from .spellbook import pack_spell
    from .spellbook_reference import _state, _tally
    scene, seed = panel
    actual = {**scene, "caster":{**context,"available_sp":available_sp}, "hp":available_hp,
              "wellspring_pct":wellspring}
    spells = []
    for name in names:
        recipe = book[name]
        cost, _, _ = _tally(_state(context), pack_spell(recipe))
        slots = [_slot(e, [])[0] for e in recipe["effects"]]
        spells.append({"effects":slots, "range_type":recipe["range_type"], "element":recipe["element"],
                       "cost_sp":cost, "climb":context["climb"]})
    trial = simulate_trial(actual, spells, [{"spell":i} for i in range(len(names))], seed)
    score = trial["damage"]*1_000_000/scene["horizon_us"]
    return score, trial

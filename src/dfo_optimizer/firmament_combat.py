"""Project reviewed static Firmament channels from an authenticated, funded tree."""
from collections import Counter

from .lifecycle_encounter import EncounterGap
from .progression_domain import evidence, fields, integer


# firmamentLaw.js STAT_DEFS and SKILL_DEF. Gear and the Firmament cap independently.
CASTER_CHANNELS = {"spellPower":("power_pct",30), "spellPierce":("pierce",10),
                   "castSpeed":("cast_speed_pct",15), "skill.Destruction":("live_skill",15)}
CAPACITY = {"intelligence", "pct.intelligence", "mp", "mpPct"}
LIFE = {"carry", "warmth", "coldDegrees", "heatDegrees", "dry", "fatigueLess", "fallLess", "standing"}


def _totals(tree, nodes):
    totals = Counter()
    if not tree or not tree["start"]:
        return totals
    for key in [tree["start"], *tree["keys"]]:
        node = nodes[key]
        if node["kind"] == "keystone":
            raise EncounterGap("Firmament keystone prices require verified joint effect ordering")
        totals.update(node["stats"])
    return totals


def modifiers(control, initial_state, state, law, start):
    tree = (state.get("firmament") or {}).get("tree")
    if not tree or not tree["start"]:
        return {}
    observation = control.get("firmament_evidence")
    if not isinstance(observation, dict):
        raise EncounterGap("active Firmament requires observed online, unmentored PvE conditions")
    fields(observation, {"source", "observed_at_ms", "context", "in_force", "mentor_scale", "sp_capacity_basis"},
           "Firmament combat observation")
    evidence(observation.get("source"))
    stamp = integer(observation.get("observed_at_ms"), "Firmament combat timestamp", 0, 2**53-1)
    if (observation.get("context") != "ordinary_online_pve" or observation.get("in_force") is not True
            or type(observation.get("mentor_scale")) not in (int, float) or observation["mentor_scale"] != 1):
        raise EncounterGap("Firmament requires an active, unmentored ordinary online PvE encounter")
    totals = _totals(tree, law["nodes"])
    unknown = set(totals).difference(CASTER_CHANNELS, CAPACITY, LIFE)
    if unknown:
        raise EncounterGap("unsupported active Firmament channels " + ", ".join(sorted(unknown)))
    original = _totals((initial_state.get("firmament") or {}).get("tree"), law["nodes"])
    if CAPACITY.intersection(totals) or CAPACITY.intersection(original):
        observed = (start.get("character") or {}).get("live_observations", {})
        if (observation.get("sp_capacity_basis") != "observed_with_tree" or
                any(original[k] != totals[k] for k in CAPACITY) or
                (start.get("firmament") or {}).get("observed_at_ms") != stamp or
                any(observed.get(k, {}).get("observed_at_ms") != stamp for k in ("current_sp","max_sp"))):
            raise EncounterGap("Firmament pool changes require current and maximum SP observed with the same active tree")
    return {channel:min(cap,totals[key]) for key,(channel,cap) in CASTER_CHANNELS.items() if totals[key]}

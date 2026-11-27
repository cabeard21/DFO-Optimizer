"""Replayed cap path decisions for the beginner's ordinary PvE hypotheses."""

from .beginner_stage_assets import _FIELDS
from .encounter_advanced_reference import PATH_IDS
from .encounter_request import HYPOTHETICAL_ARCANE_PATHS, MAGNITUDE, _spellbook
from .progression_replay import effective, transition

_PATH_EVIDENCE = {
    "basis": "hypothetical",
    "source": "Replayed cap mastery choice. Conditional fresh ordinary online PvE; "
              "no previously running path cooldown, effect, stack or fractional credit.",
    "context": "ordinary_online_pve",
    "initial_state": "fresh",
}
_SHELF = ("Conditional awake Battlemage guild shelf outside Witches Festival; "
          "building quality 10 and chapter factor 1.0. Source: signatureSpells.js, "
          "spellbookWindow.js and shopStock.js.")


def _aegis_spell(rules):
    row = next(r for r in rules["encounter_paths"] if r["id"] == "battlemage")
    effect, = row["slots"]
    return {
        "id": row["name"], "signature": row["index"], "range_type": row["range_type"],
        "element": row["element"], "evidence": _SHELF,
        "effects": [{"effect_id": f"{effect['type']},{effect['subType']}",
                     **{key: effect["settings"][_FIELDS[key]] for key in MAGNITUDE}}],
    }


def _aegis_quote(stage, spell, rules):
    actor = stage["actor"]
    state = stage["state"]
    blockers = []
    _, spells = _spellbook(
        [spell], {"path_id": PATH_IDS["battlemage"], "caster": actor},
        {"destruction": actor["destruction_live"]},
        {"destruction": effective(state["skills"][22])}, {}, blockers,
        rules["encounter_paths"], {spell["signature"]},
    )
    if blockers:
        raise RuntimeError("The authenticated Aegis Bolt record failed its shelf check")
    # spellbookWindow.presentedCost and calculateTradePrice at shop quality 10.
    mercantile = min(100, effective(min(state["skills"][14], 100)))
    personality = min(100, state["attributes"][5])
    merchant = (50 << 8) // 200 + 128
    skill = (merchant * (((100 - mercantile) << 8) // 200 + 128)) >> 8
    attribute = (merchant * (((100 - personality) << 8) // 200 + 128)) >> 8
    return (((192 * skill) >> 8) + (attribute >> 2)) * spells[0]["cost_sp"] * 4 // 256


def _replay(stage, action, path_index):
    start = stage["state"]
    # The checkpoint projection omits the private wall clock. These terminal
    # edges have no elapsed time, so use a local zero and preserve the projection.
    state, effort = transition({"real_ms": 0, **start, "arcane_path": path_index},
                               action, stage["effort"])
    if "real_ms" not in start:
        del state["real_ms"]
    return state, effort


def _aegis_purchase(stage, path_index, rules):
    spell = _aegis_spell(rules)
    gold = _aegis_quote(stage, spell, rules)
    state = stage["state"]
    if gold > state["gold"] or spell["signature"] in state["known"]:
        return None
    state, effort = _replay(
        stage,
        {"kind": "buy", "spell": spell["signature"], "family": "arcane",
         "path": path_index, "gold_cost": gold},
        path_index,
    )
    receipt = {"kind": "signature_spell", "id": spell["signature"], "name": spell["id"],
               "gold": gold, "evidence": _SHELF}
    return {**stage, "state": {**state, "arcane_path": "battlemage"}, "effort": effort,
            "actor": {**stage["actor"], "gold": state["gold"], "known_signature_indices": [spell["signature"]]},
            "spells": [*stage["spells"], spell],
            "acquisitions": [*stage["acquisitions"], receipt],
            "transactions": [*stage["transactions"], {**receipt, "delta_gold": -gold}]}


def variants(stage, rules):
    """Fork an attained cap once per eligible path without mutating progression."""
    if stage["stage"] != "cap" or stage.get("status") != "attained":
        return {"none": stage}
    base = {**stage, "refined_entry": True}
    options = {"none": base}
    state = stage["state"]
    if state.get("arcane_path") not in (None, -1) or state.get("martial_path") not in (None, -1):
        return options
    earned = set(state["mastered"])
    rows = {r["id"]: (i, r["skills"]) for i, r in enumerate(rules["progression_rules"]["paths"])
            if r["family"] == "arcane"}
    for name in HYPOTHETICAL_ARCANE_PATHS:
        index, skills = rows[name]
        if not earned.issuperset(skills):
            continue
        selected, effort = _replay(
            stage,
            {"kind": "choose", "family": "arcane", "path": index, "pair": skills},
            -1,
        )
        branch = {**base, "state": {**selected, "arcane_path": name}, "effort": effort,
                  "actor": {**stage["actor"], "path": name, "path_evidence": dict(_PATH_EVIDENCE)}}
        options[name] = branch
        if name == "battlemage" and (aegis := _aegis_purchase(branch, index, rules)):
            options["battlemage_aegis"] = aegis
    return options

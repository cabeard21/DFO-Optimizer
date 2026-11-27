"""Bind one reachable, owned loadout to the ordinary physical encounter actor."""
from .class_document import ATTRIBUTES
from .equipment import _catalog, inspect_item
from .physical_encounter import PhysicalGap
from .progression_replay import effective


def _verified_layout(checkpoint, layout):
    inventory = checkpoint["inventory"]
    copies = {r["instance_id"]: r["item"] for r in inventory}
    if len(copies) != len(inventory):
        raise ValueError("Ambiguous duplicate physical copy in checkpoint")
    catalog = _catalog()
    occupied = 0
    used = set()
    for slot, identity in sorted(layout.items()):
        if slot not in catalog["slots"] or identity not in copies or identity in used:
            raise ValueError("Loadout requires a distinct owned copy and a known slot")
        item = copies[identity]
        state = checkpoint["state"]
        facts = inspect_item(item, career=state["career"], gender=state.get("gender"))
        place = next((p for p in facts["placements"] if p["slot"] == catalog["slots"][slot]), None)
        if place is None or place["mask"] & occupied:
            raise ValueError(f"{identity} cannot occupy {slot} in this loadout")
        if facts["unsupported"] or item.get("legendary") or item.get("enchantments"):
            raise PhysicalGap(f"{identity} has an unresolved physical combat effect")
        used.add(identity)
        occupied |= place["mask"]
        yield slot, item, catalog["templates"][str(item["templateIndex"])]["group"]


def bind_physical_player(checkpoint, loadout=None):
    """Derive an actor from physical item IDs. The caller supplies the fight and target."""
    state = checkpoint["state"]
    arcane = state.get("arcane_path")
    actor = checkpoint.get("actor", {})
    modeled = checkpoint.get("refined_entry") and actor.get("path") == arcane and (
        actor.get("path_evidence", {}).get("basis") == "hypothetical"
    )
    if (arcane not in (None, -1) and not modeled) or state.get("martial_path", -1) not in (None, -1):
        raise PhysicalGap("Physical combat projection needs verified active path state")
    attrs = list(state["attributes"])
    mastered = set(state.get("mastered", ()))
    skills = [effective(v if i in mastered else min(v, 100)) for i, v in enumerate(state["skills"])]
    weapon, armor = None, []
    layout = checkpoint["loadout"] if loadout is None else loadout
    for slot, item, group in _verified_layout(checkpoint, layout):
        for line in item.get("affixes", ()):
            if line.get("gem") is not None:
                raise PhysicalGap("Socketed physical modifiers require a verified live skill fold")
            if line["id"] == "skill":
                skills[line["param"]] += line["value"]
            elif line["id"] == "stat" and line.get("param") in ATTRIBUTES:
                attrs[ATTRIBUTES.index(line["param"])] += line["value"]
            elif line["id"] not in ("castSpeed", "potency", "focus"):
                raise PhysicalGap("Unresolved equipped physical effect")
        if group not in ("Weapons", "Armor") and slot != "Feet":
            continue
        if not all(type(item.get(k)) is int and item[k] > 0 for k in ("currentCondition", "maxCondition")):
            raise PhysicalGap("Physical equipment requires verified positive condition")
        if group == "Weapons":
            if slot != "RightHand":
                raise PhysicalGap("The ordinary beginner attack uses the right-hand weapon")
            weapon = dict(item)
        else:
            armor.append(dict(item))
    return {"level": state["level"], "race_id": state["race_id"], "career": state["career"],
            "fatigue": state["fatigue"],
            "attributes": [min(100, v) for v in attrs], "skills": skills, "weapon": weapon, "armor": armor,
            "evidence": "Replayed checkpoint, owned physical copies, selected slots and recorded item condition."}

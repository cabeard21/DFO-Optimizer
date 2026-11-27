"""Construct legal caster rolls over a declared, finite hypothetical domain."""
from copy import deepcopy

from .equipment import career_masks

LOOT_PROFILE = "tier6_pile_level45_luck50"


def _max_line(data, kind, tier, param=None):
    return {"id": kind, "value": data["affixes"][kind]["range"][tier][1],
            **({"param": param} if param is not None else {})}


def _materials(data, group, forbidden):
    if group not in ("Weapons", "Armor"):
        return [None]
    metals = [n for n in range(10) if not forbidden & (1 << n)]
    if group == "Armor":
        # Retain representatives of all three armor families for career eligibility.
        return [0, 256] + [data["armor_materials"]["Iron"] + m for m in metals[:1]]
    return metals[:1]


def _extremes(index, template, data, forbidden):
    group = template["group"]
    # Reviewed RRI pieces can be read from a save. Their loot pools depend on mod settings.
    if (not template["slots"] or "native_armor_families" in template
            or group not in ("Weapons", "Armor", "Jewellery", "MensClothing", "WomensClothing")):
        return
    procs = [k for k in ["castSpeed", "potency", "focus"] if group in data["affixes"][k]["groups"]]
    for tier in ("magic", "rare"):
        # The first two independently rollable numbers are different kinds.
        # Clothing's stat is restricted to Personality; use the allowed school alone for Magic.
        lines = [_max_line(data, "skill", tier, data["destruction_id"])]
        if not group.endswith("Clothing"):
            lines.append(_max_line(data, "stat", tier, "speed"))
        if tier == "rare":
            if group.endswith("Clothing"):
                lines.extend([_max_line(data, "stat", tier, "personality"), _max_line(data, "dry", tier)])
            else:
                lines.append(_max_line(data, "stat", tier, "intelligence"))
        for material in _materials(data, group, forbidden):
            for proc in [None, *procs]:
                item = {"templateIndex": index, "group": group, "rarity": tier, "affixes": lines +
                        ([_max_line(data, proc, tier)] if proc else [])}
                if material is not None:
                    item["material"] = material
                if tier == "rare":
                    # Choose an actual flavor with no outgoing spell effect.
                    good = {data["enchantment_types"][k] for k in ("GoodRepWith", "IncreasedWeightAllowance", "PotentVs")}
                    flavour = next((row for row in data["rare_flavours"].get(group, []) if row["type"] in good), None)
                    if not flavour:
                        continue
                    item["enchantments"] = [flavour]
                yield f"ideal-{index}-{material}-{tier}-{proc or 'base'}", item


def _copies(identifier, item, template, *, obtainable, source):
    count = 2 if len(template["slots"]) == 2 else 1
    for copy in range(count):
        yield {"instance_id": f"catalog-{identifier}-{copy + 1}", "item": deepcopy(item), "container": "catalog",
               "acquisition": {"owned": False, "obtainable": obtainable, "hypothetical": obtainable is None,
                               "price": None, "source": source}}


def catalog_rows(data, character, theoretical, template_indices, access):
    if not isinstance(character, dict) or type(theoretical) is not bool:
        raise ValueError("Expected character object and theoretical mode")
    gear = character.get("gear", {})
    if not isinstance(gear, dict):
        raise ValueError("Expected character.gear object")
    career = gear.get("career")
    _, forbidden = career_masks(career) if career is not None else (0, 0)
    if not isinstance(access, (list, tuple, set, frozenset)) or any(s != LOOT_PROFILE for s in access):
        raise ValueError(f"Catalog access must list supported loot profiles such as {LOOT_PROFILE}")
    if template_indices is not None and (
        not isinstance(template_indices, (list, tuple, set, frozenset))
        or any(type(t) is not int or str(t) not in data["templates"] for t in template_indices)
    ):
        raise ValueError("catalog_templates must contain reviewed equipment template indices")
    selected = {int(t) for t in data["templates"]} if template_indices is None else set(template_indices)
    if not theoretical and LOOT_PROFILE not in access:
        return
    for row in data["minted"]:
        item = row["item"]
        index = item["templateIndex"]
        if index not in selected or (not theoretical and row["kind"] != "witness"):
            continue
        source = f"{LOOT_PROFILE}; base factory and rollLootRarity seed {row['seed']}"
        yield from _copies(f"loot-{index}-{row['seed']}", item, data["templates"][str(index)],
                           obtainable=None if theoretical else True, source=source)
    if theoretical:
        for index in sorted(selected):
            template = data["templates"][str(index)]
            for identifier, item in _extremes(index, template, data, forbidden):
                yield from _copies(identifier, item, template, obtainable=None, source="hypothetical caster roll")

"""Equip owned copies and bind funded spell records for a fixed prospective role."""

from copy import deepcopy

from .encounter_request import CHANCE, DURATION, MAGNITUDE, SCHOOLS
from .gear_request import prepare_inventory
from .lifecycle_defenses import player_save_channels
from .lifecycle_domain import maker_price
from .progression_replay import effective

_SCHOOLS = ("destruction", "restoration", "illusion", "alteration", "thaumaturgy", "mysticism")
_FIELDS = dict(
    zip(
        (*MAGNITUDE, *CHANCE, *DURATION),
        (
            "magnitudeBaseLow",
            "magnitudeBaseHigh",
            "magnitudeLevelBase",
            "magnitudeLevelHigh",
            "magnitudePerLevel",
            "chanceBase",
            "chanceMod",
            "chancePerLevel",
            "durationBase",
            "durationMod",
            "durationPerLevel",
        ),
        strict=True,
    )
)
_AREA = {
    "effects": [
        {"effect_id": "4,0", "base_low": 1, "base_high": 1, "plus_low": 1, "plus_high": 1, "per_level": 2}
    ],
    "range_type": 3,
    "element": 2,
}
_SPELL_OFFER = {
    "id": "Close circle (paid recipe)",
    **_AREA,
    "evidence": "Conditional Spell Maker at the first earned checkpoint. Source-price multiplier 1.0.",
}
_COMBAT_ID = -910001


def _spell(record):
    """Retain the entire supported spell, including the exact earned heal magnitude."""
    if record.get("minimumCastingCost") or record.get("pvpKitCost") or record.get("path"):
        return None
    effects = []
    for row in record["effects"]:
        if row["type"] < 0:
            continue
        pair = f"{row['type']},{row['subType'] & 255}"
        if pair not in SCHOOLS or pair == "19,255":
            return None
        fields = CHANCE if pair == "5,255" else MAGNITUDE
        if pair in ("18,255", "35,255"):
            fields = (*fields, *DURATION)
        effects.append({"effect_id": pair, **{k: row[_FIELDS[k]] for k in fields}})
    if not effects:
        return None
    return {
        "id": f"{record['name']} [{record['index']}]",
        "element": record["element"],
        "range_type": record["rangeType"],
        "effects": effects,
        "evidence": f"Owned game record {record['index']} from the replayed birth or funded itinerary.",
    }


def _gear(inventory, source, preferred=None):
    from .physical_encounter import laws

    domain = prepare_inventory(
        {
            "inventory": inventory,
            "career": source["career"],
            "character": {"gear": {"gender": source["gender"]}},
        }
    )
    labels = {i: k for k, i in domain.slots.items()}
    indexed = {row["instance_id"]: i for i, row in enumerate(inventory)}
    weapons = laws()["weapons"]
    melee = [
        v
        for v in domain.items
        if str(v.item["templateIndex"]) in weapons
        and any(slot == domain.slots["RightHand"] for slot, _ in v.placements)
    ]
    proficiency = set(source["primary"] + source["major"] + source["minor"])

    def skill_order(option):
        skill = weapons[str(option.item["templateIndex"])]["skill"]
        return skill not in proficiency, -source["skills"][skill], indexed[option.identity]

    primary = min(melee, key=skill_order).identity if melee else None
    selected, occupied = {}, 0
    for item in sorted(
        domain.items, key=lambda v: (v.identity != primary, v.identity != preferred, indexed[v.identity])
    ):
        for slot, mask in item.placements:
            if item.item["group"] == "Weapons" and (item.identity != primary or labels[slot] != "RightHand"):
                continue
            if labels[slot] == "LeftHand" and item.item["templateIndex"] not in range(109, 113):
                continue
            if not (mask & occupied):
                selected[labels[slot]] = item.identity
                occupied |= mask
                break
    return selected


def _actor(state, source, rules):
    skills = state["skills"]
    achieved = {
        s: effective(skills[i] if i in state["mastered"] else min(100, skills[i]))
        for i, s in enumerate(_SCHOOLS, start=22)
    }
    race = next(r for r in rules["races"] if r["id"] == source["race_id"])
    defense = player_save_channels(race["flags"], source["career"], state["attributes"][2])
    return {
        "level": state["level"],
        "speed": min(100, state["attributes"][6]),
        "destruction_live": achieved["destruction"],
        "destruction_trained": skills[22],
        "destruction_mastered": 22 in state["mastered"],
        "current_sp": state["sp"],
        "max_sp": state["max_sp"],
        "gold": state["gold"],
        "hp": state["hp"],
        "max_hp": state["max_hp"],
        "has_spellbook": source["has_spellbook"],
        "school_live": {k: v for k, v in achieved.items() if k != "destruction"},
        "school_climb": {k: v for k, v in achieved.items() if k != "destruction"},
        "school_trained": {"restoration": skills[23], "mysticism": skills[27]},
        "defense": {k: v for k, v in defense.items() if k != "pierce"},
        "mastered": state["mastered"],
        "path": state["arcane_path"] or "none",
        "martial_path": state["martial_path"] or "none",
        "power_pct": 0,
        "pierce": 0,
        "focus_pct": 0,
        "cast_speed_pct": 0,
    }


class StageAssets:
    def __init__(self, source, rules):
        from .beginner_creation import creation as creation_weights

        self.source = source
        self.rules = rules
        self.weights = creation_weights()
        self.kit_weight = sum(
            self._weight(copy["item"]) * copy["item"].get("stackCount", 1) for copy in source["inventory"]
        )
        creation = rules["progression_rules"]["creation"]
        cuirass = next(
            item
            for bundle in creation["kit_rows"]
            for item in bundle
            if item["templateIndex"] == 102 and item.get("material") == 256
        )
        self.baseline = _gear(source["inventory"], source)
        # Source mintCondition({group:'Armor', templateIndex:102, material:512/513})
        # sets these pools. Full condition and the one-copy shop quotes are scenario inputs.
        self.offers = []
        for name, price, item in (
            (
                "Iron plate cuirass",
                30,
                {
                    "name": "Cuirass",
                    "group": "Armor",
                    "templateIndex": 102,
                    "material": 512,
                    "currentCondition": 4096,
                    "maxCondition": 4096,
                },
            ),
            (
                "Steel plate cuirass",
                35,
                {
                    "name": "Cuirass",
                    "group": "Armor",
                    "templateIndex": 102,
                    "material": 513,
                    "currentCondition": 6144,
                    "maxCondition": 6144,
                },
            ),
            ("Chain cuirass", 20, dict(cuirass)),
        ):
            identity = "beginner:cuirass:" + str(item["material"])
            offer = {"instance_id": identity, "container": "pack", "item": item}
            layout = _gear([*source["inventory"], offer], source, preferred=identity)
            if layout.get("ChestArmor") == identity:
                self.offers.append((name, price, offer, layout))

    def _weight(self, item):
        index, material = item["templateIndex"], item.get("material", "none")
        if index == 102 and isinstance(material, int) and 512 <= material <= 521:
            return self.weights["cuirasses"][material - 512]["units"]
        return self.weights["items"][f"{index}/{material}"]["unit_weight"]

    def _carry(self, state, gold, extra=None):
        limit = self.weights["capacity"][state["attributes"][0]]
        held = self.kit_weight + gold * self.weights["gold_unit_weight"]
        if extra:
            held += self._weight(extra)
        return {"carried_kg": held / 400, "capacity_kg": limit / 400, "headroom_kg": (limit - held) / 400}

    def decide(self, funds, records, state, *, gear=True, spell=True):
        buy = []
        worn = self.baseline.get("ChestArmor")
        worn_item = next((r["item"] for r in self.source["inventory"] if r["instance_id"] == worn), {})
        if gear:
            for name, price, offer, _ in self.offers:
                if (
                    worn_item.get("material", -1) < offer["item"]["material"]
                    and funds >= price
                    and self._carry(state, funds - price, offer["item"])["headroom_kg"] >= 0
                ):
                    buy.append(
                        {
                            "kind": "gear",
                            "id": offer["instance_id"],
                            "name": name,
                            "gold": price,
                            "evidence": "One hypothetical shop copy at the stated gold quote. Plate uses pinned itemTemplates.js mintCondition at full durability. Chain uses the exact pinned creation kit record.",
                        }
                    )
                    funds -= price
                    break
        recipes = [_spell(records[i]) for i in state["known"] if i in records]
        price = maker_price(_AREA, 1.0)
        if (
            spell
            and funds >= price
            and not any(r and all(r[k] == v for k, v in _AREA.items()) for r in recipes)
        ):
            buy.append(
                {
                    "kind": "combat_spell",
                    "id": _COMBAT_ID,
                    "name": _SPELL_OFFER["id"],
                    "gold": price,
                    "evidence": _SPELL_OFFER["evidence"],
                }
            )
        return buy

    def view(self, point, records, acquisitions, receipts):
        state, effort = point["state"], point["effort"]
        bought = {a["kind"] for a in acquisitions}
        paid = sum(a["gold"] for a in acquisitions)
        state = {
            **state,
            "gold": state["gold"] - paid,
            "race_id": self.source["race_id"],
            "career": self.source["career"],
            "gender": self.source["gender"],
            "reflexes": self.source["reflexes"],
        }
        spells, unsupported = [], []
        for i in state["known"]:
            spell = _spell(records[i]) if i in records else None
            if spell:
                spells.append(spell)
            else:
                unsupported.append(
                    {
                        "index": i,
                        "name": records.get(i, {}).get("name"),
                        "reason": "Owned record unresolved or outside the reviewed encounter effect set.",
                    }
                )
        if "combat_spell" in bought:
            spells.append(deepcopy(_SPELL_OFFER))
            state = {**state, "known": [*state["known"], _COMBAT_ID]}
        inventory, layout, extra = self.source["inventory"], self.baseline, None
        if "gear" in bought:
            selected = next(a["id"] for a in acquisitions if a["kind"] == "gear")
            offer, layout = next(
                (offer, layout) for _, _, offer, layout in self.offers if offer["instance_id"] == selected
            )
            inventory = [*inventory, offer]
            extra = offer["item"]
        carry = self._carry(state, state["gold"], extra)
        ledger = [*receipts, *({**a, "delta_gold": -a["gold"]} for a in acquisitions)]
        if self.source["gold"] + sum(r["delta_gold"] for r in ledger) != state["gold"]:
            raise RuntimeError("Beginner resource ledger differs from the independently replayed gold pool")
        return {
            "state": state,
            "actor": _actor(state, self.source, self.rules),
            "spells": spells,
            "unsupported_spells": unsupported,
            "acquisitions": acquisitions,
            "effort": {**effort, "spent": effort["spent"] + paid},
            "career": self.source["career"],
            "transactions": ledger,
            "inventory": inventory,
            "loadout": layout,
            "carry": carry,
            **(
                {
                    "status": "unsupported",
                    "reason": "Held checkpoint inventory exceeds verified carry capacity.",
                }
                if carry["headroom_kg"] < 0
                else {"status": "attained"}
            ),
        }

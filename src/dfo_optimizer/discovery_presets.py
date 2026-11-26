"""Editable, conditional prospective itineraries for the shared lifecycle optimizer."""

import json
from copy import deepcopy

from .discovery_itinerary import bind_itinerary
from .equipment import equipment_catalog, legal_catalog_items
from .project_data import shared_data

__all__ = ["bind_itinerary", "discovery_preset", "preset_catalog"]

_SCENARIOS = {
    "early": (
        "Early caster development",
        "Compare ordinary creation rolls and the first earned level gains.",
    ),
    "midgame": ("Midgame caster progression", "Develop the six contributing skills toward level 15."),
    "endgame": (
        "Endgame direct damage",
        "Compare affordable damage at level 45 on one ordinary stationary foe.",
    ),
    "dungeon": (
        "Sustained dungeon clearing",
        "Fight an Orc and an Orc Shaman in consecutive rooms with carried HP and SP.",
    ),
    "enemy_caster": (
        "Enemy spellcaster",
        "Face a level-13 Orc Shaman with an explicit incoming spell recipe and schedule.",
    ),
    "high_resistance": (
        "High-resistance opponent",
        "Face a hypothetical opponent with an active resistance ward.",
    ),
    "multiple_targets": (
        "Multiple targets",
        "Compare legal casting policies in the same three-enemy encounter.",
    ),
    "creation_to_cap": (
        "Creation to level 45",
        "Compare the birth, intermediate and final checkpoints of a common practice itinerary.",
    ),
    "theoretical_endgame": (
        "Theoretical endgame equipment",
        "Compare level-45 builds with cost-free access to the declared finite theoretical item panel.",
    ),
}
_OFFER_IDS = ((133, 39, 10, "Amulet0"), (113, 44, 12, "RightHand"), (103, 226, 15, "Gloves"))
_IDEAL_COPIES = {
    "catalog-ideal-133-None-rare-castSpeed-1": "Amulet0",
    "catalog-ideal-113-0-rare-potency-1": "RightHand",
    "catalog-ideal-103-0-rare-base-1": "Gloves",
    "catalog-ideal-135-None-rare-focus-1": "Ring0",
}


def preset_catalog():
    return [{"id": key, "label": title, "description": desc} for key, (title, desc) in _SCENARIOS.items()]


def _equipment(ideal):
    if ideal:
        items = legal_catalog_items({}, theoretical=True, template_indices=[133, 113, 103, 135])
        rows = [
            (
                it["instance_id"],
                it["item"],
                0,
                _IDEAL_COPIES[it["instance_id"]],
                "Hypothetical cost-free access to a constructed high-end roll from the pinned theoretical gear catalog.",
            )
            for it in items
            if it["instance_id"] in _IDEAL_COPIES
        ]
    else:
        rows = _quoted_items()
    offers, layouts = [], [{}]
    for identifier, item, price, slot, provenance in rows:
        offers.append(
            {
                "instance_id": identifier,
                "item": deepcopy(item),
                "acquisition": {
                    "owned": False,
                    "obtainable": True,
                    "price": {"gold": price},
                    "source": provenance,
                },
            }
        )
        layouts += [{**layout, slot: identifier} for layout in layouts]
    return {"offers": offers, "loadouts": layouts}


def _quoted_items():
    minted = {(row["item"]["templateIndex"], row["seed"]): row for row in equipment_catalog()["minted"]}
    return [
        (
            f"offer-{index}-{seed}",
            minted[index, seed]["item"],
            price,
            slot,
            f"Hypothetical availability and gold quote. Pinned tier6_pile_level45_luck50 template {index}, seed {seed}.",
        )
        for index, seed, price, slot in _OFFER_IDS
    ]


def _spellbook():
    def spell(name, base, step, interval, range_type, element):
        return {
            "id": name,
            "recipe": {
                "range_type": range_type,
                "element": element,
                "effects": [
                    {
                        "effect_id": "4,0",
                        "base_low": base,
                        "base_high": base,
                        "plus_low": step,
                        "plus_high": step,
                        "per_level": interval,
                    }
                ],
            },
        }

    return {
        "include_known": True,
        "mode": "auto_spellbook",
        "spells": [
            spell("Apprentice touch", 1, 1, 1, 1, 4),
            spell("Scaling flame", 1, 2, 1, 2, 0),
            spell("Close circle", 1, 1, 2, 3, 2),
        ],
        "maker": {
            "source": "Hypothetical access to an ordinary Spell Maker at every scored checkpoint. The price factor is explicit and purchases use actual gold.",
            "price_factor": 1.0,
        },
    }


def _scene(name):
    exemplar = {
        "dungeon": "dungeon",
        "enemy_caster": "dungeon",
        "multiple_targets": "pack",
        "high_resistance": "rat",
    }[name]
    scene = json.loads((shared_data("examples") / f"encounter-{exemplar}.json").read_text())["scenario"]
    encounter = {
        "at": "terminal",
        "seed": 42,
        "scenario": scene,
        "evidence": "Prospective ordinary PvE, fixed stationary positions, authored target rolls, attack schedule and common seed.",
    }
    if name in ("dungeon", "enemy_caster"):
        scene["evidence"] = (
            "Pinned Orc and Orc Shaman base rows with authored HP, Willpower, geometry, incoming spell, and timings. No inter-room healing or consumables."
        )
        scene["rooms"][-1] = {"id": "shaman chamber", "enemies": [1], "delay_us": 6000000}
        shaman = scene["enemies"][-1]
        if name == "enemy_caster":
            scene.pop("rooms")
            scene["enemies"] = [shaman]
            scene["id"] = "shaman duel"
        caster = len(scene["enemies"]) - 1
        scene["incoming"] = [
            r for r in scene["incoming"] if r["kind"] == "blow" and r["source"] == 0 and caster
        ]
        scene["incoming"].append(
            {
                "time_us": 1750000,
                "source": caster,
                "kind": "bundle",
                "spell": "shaman-bolt",
                "evidence": "Authored hostile spell arrival, fixed across prospective classes.",
            }
        )
        encounter.update(
            environment="darkness",
            hostile_spells=[
                {
                    "id": "shaman-bolt",
                    "recipe": _spellbook()["spells"][1]["recipe"],
                    "evidence": "Hypothetical Damage Health bolt. The pinned Orc Shaman career supplies the identity and base level.",
                }
            ],
        )
    elif name == "high_resistance":
        scene["id"] = "warded opponent"
        scene["evidence"] = (
            "Hypothetical warded foe, 80 HP, Willpower 85, stationary in reach for 20 seconds."
        )
        scene.update(horizon_us=20_000_000, incoming=[])
        scene["enemies"] = [
            {
                "id": "warded foe",
                "hp": 80,
                "willpower": 85,
                "x_mm": 900,
                "z_mm": 0,
                "wards": {
                    "resist_chance": 50,
                    "active_through_us": 20_000_000,
                    "evidence": "Hypothetical 50% resist ward active through the full scenario.",
                },
            }
        ]
    return encounter


def discovery_preset(preset_id):
    """Return the whole editable request, including every hypothetical quote and assumption."""
    if preset_id not in _SCENARIOS:
        raise ValueError(f"Unknown spellcaster discovery preset {preset_id!r}")
    level = {"early": 2, "midgame": 15, "endgame": 45, "creation_to_cap": 45, "theoretical_endgame": 45}.get(
        preset_id, 1
    )
    objective = {
        "endgame": "endgame_damage",
        "theoretical_endgame": "endgame_damage",
        "dungeon": "clear_performance",
        "multiple_targets": "clear_performance",
        "enemy_caster": "survivability",
        "high_resistance": "encounter_damage",
    }.get(preset_id, "overall_pve")
    result = {
        "schema_version": 1,
        "description": _SCENARIOS[preset_id][1]
        + " Conditional opportunities and quotes are hypothetical. Gear compares the declared physical copies and layouts. The target and spell access are editable scenario assumptions.",
        "class_admission_strategy": "adaptive",
        "class_search": {
            "profile": "spellcaster_discovery_v1",
            "objective": "diverse",
            "top_k": 4 if level == 45 else 8,
        },
        "objective": objective,
        "roll_seeds": [42, 43] if level == 45 else list(range(42, 50)),
        "target": {"id": "hypothetical ordinary stationary opponent", "hp": 100, "willpower": 50},
        "equipment": _equipment(preset_id == "theoretical_endgame"),
        "spellbook": _spellbook(),
        "search": {
            "max_nodes": 4_000_000 if level == 45 else 1_000_000,
            "wall_seconds": 120,
            "memory_bytes": 256 << 20,
        },
        "progression": {"goal": {"level": level}, "require_starting_damage": False},
    }
    if level == 1:
        result["progression"]["stages"] = []
        result["encounter"] = _scene(preset_id)
    else:
        result["spellbook"]["allow_unarmed_start"] = True
        result["progression"]["itinerary"] = {
            "version": 1,
            "cycles": {2: 12, 15: 350, 45: 1800}[level],
            "cadence_ms": 60_000,
            "challenge_level": 34,
            "maker_price_factor": 1.0,
            "cache_gold": 160,
            "allocation_order": [1, 6, 4, 2, 0, 3, 5, 7],
            "alternate_allocation_orders": [[6, 1, 4, 2, 0, 3, 5, 7]],
            "mastery_priority": [],
            "evidence": "Conditional school practice with repeated eligible targets, successful qualifying actions, safe full nights in beds, and no harm or additional income. Each incoming challenge is authored, not a population estimate. Cadence, Spell Maker access and one identified gold cache are hypothetical. Training uses only funded casts. Select different opportunities to test sensitivity.",
        }
    return result

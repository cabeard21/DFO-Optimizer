"""Common hypothetical opponent panels for attained beginner-build checkpoints."""

from copy import deepcopy

CASE_IDS = (
    "ordinary",
    "physical",
    "enemy_caster",
    "resistant",
    "multiple",
    "low_sp",
    "sustained",
    "defensive",
)
VARIANTS = ("baseline", "owned_only", "no_spell_purchase", "higher_pressure", "protected_recovery")
VARIANT_CASES = {
    "baseline": CASE_IDS,
    "owned_only": CASE_IDS,
    "no_spell_purchase": CASE_IDS,
    "higher_pressure": ("physical", "enemy_caster", "multiple", "low_sp", "sustained", "defensive"),
    "protected_recovery": ("sustained",),
}
GROUND = (
    "Hypothetical dry, dark, non-sacred dungeon with stationary combatants, unobstructed sight, "
    "no swimming, injuries, external buffs or consumables at entry. Common scheduled attacks test "
    "these positions; they are not measured enemy AI, attack frequencies or arrival probabilities."
)
_M = 1_000_000
_BOLT = {
    "id": "hostile/bolt",
    "range_type": 2,
    "element": 0,
    "evidence": "Hypothetical fixed enemy Damage Health recipe.",
    "effects": [
        {"effect_id": "4,0", "base_low": 4, "base_high": 8, "plus_low": 1, "plus_high": 2, "per_level": 2}
    ],
}


def _target(name, hp, level, willpower, x, z=0):
    return {
        "id": name,
        "hp": hp,
        "level": level,
        "willpower": willpower,
        "x_mm": x,
        "z_mm": z,
        "evidence": "Authored living humanoid: HP, permanent level, Willpower, neutral save flags and geometry.",
    }


def _attacks(kind, source, seconds):
    return [
        {
            "kind": kind,
            "source": source,
            "time_us": round(t * _M),
            "evidence": "Authored opportunity for a melee swing."
            if kind == "melee"
            else "Authored instantaneous landing of the declared hostile projectile bundle.",
            **({"spell": "hostile/bolt"} if kind == "bundle" else {}),
        }
        for t in seconds
    ]


def _case(key, targets, incoming, evidence, *, horizon=18, physical=True, rooms=None, skill=35):
    scene = {
        "id": key,
        "horizon_us": horizon * _M,
        "first_round_us": 5 * _M,
        "round_period_us": 5 * _M,
        "evidence": GROUND + " " + evidence,
        "enemies": targets,
        "incoming": incoming,
    }
    if rooms:
        scene["rooms"] = rooms
    bands = {}
    for stage, hp_factor, level, live_skill, weapon, metal, magnitude in (
        ("birth", 1, 5, skill, 113, 0, (4, 8, 1, 2)),
        ("midgame", 2, 14, min(85, skill + 12), 120, 1, (6, 10, 2, 4)),
        ("cap", 6, 26, min(95, skill + 28), 122, 8, (10, 24, 4, 8)),
    ):
        hit_points = [hp_factor * t["hp"] for t in targets]
        levels = [t["level"] if stage == "birth" else max(t["level"], level) for t in targets]
        if key == "enemy_caster":
            hit_points = [{"birth": 50, "midgame": 70, "cap": 170}[stage]]
            levels = [13 if stage != "cap" else 21]
        bands[stage] = {
            "hp": hit_points,
            "level": levels,
            "melee_skill": live_skill,
            "weapon_template": weapon,
            "weapon_material": metal,
            "hostile_magnitude": list(magnitude),
            "evidence": "Authored reproducible opponent and attack inputs conditional on the achieved stage. "
            "Weapon templates and material effects come from the physical catalog. No enemy scaling or loot frequency is inferred.",
        }
    return {
        "id": key,
        "evidence": scene["evidence"],
        "scene": scene,
        "physical": physical,
        "threat_by_stage": bands,
        "enemy_skill": skill,
        "hostile_spells": [deepcopy(_BOLT)] if any(r["kind"] == "bundle" for r in incoming) else [],
        "environment": "darkness",
        "first_absolute_round": 1,
    }


def scenario_matrix():
    """Fresh, JSON-editable scenario definitions. Common difficulty at every stage."""
    room = _target("Corridor opponent", 36, 5, 45, 1100)
    bandit = _target("Raider", 68, 10, 45, 1050)
    shaman = _target("Distant spellcaster", 50, 13, 60, 6400)
    shaman["evidence"] = (
        "Pinned enemyBasics.js Orc Shaman (mobile 21) has level 13, HP 18–74. "
        "This test chooses 50 HP, Willpower 60, neutral save flags and 6.4 m."
    )
    sigil = _target("Warded opponent", 48, 8, 80, 1150)
    sigil["wards"] = {
        "resist_chance": 50,
        "active_through_us": 18 * _M,
        "evidence": "Hypothetical active 50% resist ward.",
    }
    pack = [
        _target(f"Pack member {i + 1}", hp, 5, 45, x, z)
        for i, (hp, x, z) in enumerate(((24, 1100, 0), (24, 1450, 100), (28, 1800, -100)))
    ]
    return [
        _case(
            "ordinary",
            [room],
            _attacks("melee", 0, (1.1, 3.7, 6.3, 8.9, 11.5, 14.1)),
            "Ordinary short-range bout.",
        ),
        _case(
            "physical",
            [bandit],
            _attacks("melee", 0, (0.6, 1.9, 3.2, 4.5, 5.8, 7.1, 8.4, 9.7, 11, 12.3, 13.6, 14.9)),
            "Stronger awake opponent with repeated in-reach attacks.",
            skill=65,
        ),
        _case(
            "enemy_caster",
            [shaman],
            _attacks("bundle", 0, (0.9, 2.8, 4.8, 6.8, 8.8, 10.8, 12.8, 14.8)),
            "Distant spellcaster stays outside melee and touch reach. Movement and enemy mana depletion are outside this schedule.",
            physical=False,
        ),
        _case(
            "resistant",
            [sigil],
            _attacks("melee", 0, (1.5, 4, 6.5, 9, 11.5, 14)),
            "Warded foe remains in weapon reach.",
        ),
        _case(
            "multiple",
            pack,
            [
                hit
                for i in range(3)
                for hit in _attacks(
                    "melee", i, (1 + i * 0.3, 3.5 + i * 0.3, 6 + i * 0.3, 9 + i * 0.3, 12 + i * 0.3)
                )
            ],
            "Three simultaneous targets share an unobstructed, close-range area.",
        ),
        _case(
            "low_sp",
            [deepcopy(room)],
            _attacks("melee", 0, (1.1, 3.7, 6.3, 8.9, 11.5, 14.1)),
            "Enter after a two-minute paid casting drill with no rest or refill. The prelude records each actual payment.",
        ),
        _case(
            "sustained",
            [deepcopy(room), deepcopy(bandit)],
            [
                *_attacks("melee", 0, (0.8, 3.4, 6, 8.6, 11.2, 13.8)),
                *_attacks("melee", 1, (0.6, 2.2, 3.8, 5.4, 7, 8.6, 10.2, 11.8, 13.4, 15)),
            ],
            "Two separate rooms carry remaining HP, SP, effects and timers. The second room opens two seconds after the first clear.",
            rooms=[
                {"id": "entry", "enemies": [0], "delay_us": 0},
                {"id": "inner chamber", "enemies": [1], "delay_us": 2 * _M},
            ],
        ),
        _case(
            "defensive",
            [deepcopy(bandit)],
            [
                *_attacks("melee", 0, (0.2, 1.8, 3.4, 5, 6.6, 8.2, 9.8, 11.4, 13)),
                *_attacks("bundle", 0, (2.6, 6.2, 10, 13.8)),
            ],
            "Close opponent mixes pressure types. A funded shield and emergency heal use the common conditional casting policy.",
            skill=60,
        ),
    ]


def variant_case(case, variant, stage):
    scene = deepcopy(case["scene"])
    band = case["threat_by_stage"][stage["stage"]]
    for target, hp, level in zip(scene["enemies"], band["hp"], band["level"], strict=True):
        target.update(hp=hp, level=level)
        if stage["stage"] != "birth":
            target["evidence"] = band["evidence"]
    if case["id"] == "enemy_caster" and stage["stage"] == "cap":
        scene["enemies"][0].update(
            id="Ancient Lich",
            category="undead",
            evidence="Pinned enemyBasics.js mobile 33 has level 21, HP 30–170; enemyGroups.js places 33 in Undead. "
            "Use 170 HP and the authored Willpower, geometry and offensive spell.",
        )
    if variant == "higher_pressure":
        for hit in scene["incoming"]:
            hit["time_us"] = hit["time_us"] * 3 // 4
        scene["evidence"] += " Sensitivity compresses all scheduled attack times to 75%."
    elif variant == "protected_recovery":
        heal = next(
            (
                s["id"]
                for s in stage["spells"]
                if s["range_type"] == 0 and all(e["effect_id"] == "10,8" for e in s["effects"])
            ),
            None,
        )
        if heal:
            scene["rooms"][1].update(
                heal_spell=heal,
                evidence="Protected opportunity for one known immediate heal in the ordinary two-second transition. "
                "Requires missing HP, enough SP, a ready cast and enough time to release.",
            )
        scene["evidence"] += (
            " One paid self heal may be cast between rooms when owned, warranted and affordable."
        )
    return scene

"""Freeze the reviewed single-target Damage Health input before native work."""
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from math import isfinite

AXES = ("element", "range_type", "base_low", "base_high", "plus_low", "plus_high", "per_level")
EFFECT = "4,0"
MASKS = ("resistant", "immune", "low_tolerance", "critical_weakness")
CHANNELS = ("resist_mods", "elemental_resists")
MODS = ("power_pct", "pierce", "cast_speed_pct", "focus_pct")


def _object(value, name, keys):
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be an object")
    unknown = set(value) - set(keys)
    if unknown:
        raise ValueError(f"unknown {name} fields: {', '.join(sorted(map(str, unknown)))}")
    return value


def _int(v, key, lo, hi):
    if type(v) is not int or not lo <= v <= hi:
        raise ValueError(f"{key} must be an integer in [{lo}, {hi}]")
    return v


def _bool(v, key):
    if v is not None and type(v) is not bool:
        raise ValueError(f"{key} must be a boolean or null")
    return v


def _float(v, key, lo, hi):
    if type(v) not in (float, int) or not lo <= v <= hi or not isfinite(v):
        raise ValueError(f"{key} must be finite and in [{lo}, {hi}]")
    return float(v)


@dataclass(frozen=True)
class SpellCaster:
    level: int | None
    speed: int | None
    destruction_live: int | None
    destruction_trained: int | None
    destruction_mastered: bool | None
    current_sp: int | None
    max_sp: int | None
    gold: int | None
    has_spellbook: bool | None
    power_pct: int | None
    pierce: int | None
    cast_speed_pct: int | None
    focus_pct: int | None

    @property
    def climb(self):
        trained = self.destruction_trained
        if trained is None or (trained > 100 and self.destruction_mastered is None):
            return None
        if trained <= 100 or not self.destruction_mastered:
            return min(100, trained)
        bonuses = ((125, 2), (150, 3), (175, 4), (200, 6))
        return 100 + (trained - 100) // 4 + sum(b for threshold, b in bonuses if trained >= threshold)


def _caster(data):
    data = _object(data, "caster", SpellCaster.__dataclass_fields__)
    ranges = {"level": (1, 45), "speed": (0, 100), "destruction_live": (0, 10_000),
              "destruction_trained": (0, 200), "current_sp": (0, 2**30), "max_sp": (0, 2**30),
              "gold": (0, 2**53 - 1), "power_pct": (-100, 1000), "pierce": (0, 1000),
              "cast_speed_pct": (-100, 1000), "focus_pct": (0, 1000)}
    values = {}
    for key, (lo, hi) in ranges.items():
        v = data.get(key, 0 if key in MODS else None)
        values[key] = _int(v, key, lo, hi) if v is not None else None
    for key in ("has_spellbook", "destruction_mastered"):
        values[key] = _bool(data.get(key), key)
    if values["current_sp"] is not None and values["max_sp"] is not None and values["current_sp"] > values["max_sp"]:
        raise ValueError("current_sp exceeds max_sp")
    return SpellCaster(**values)


@dataclass(frozen=True)
class SpellTarget:
    id: str
    hp: int
    willpower: int
    resistant: int
    immune: int
    low_tolerance: int
    critical_weakness: int
    resist_mods: tuple
    elemental_resists: tuple


def _target(data):
    data = _object(data, "target", SpellTarget.__dataclass_fields__)
    name = data.get("id")
    if not isinstance(name, str) or not name.strip() or len(name) > 256:
        raise ValueError("target.id must be a nonempty label up to 256 characters")
    fields = {key: _int(data.get(key, 0), key, 0, 127) for key in MASKS}
    for key, lo, hi in (("resist_mods", -1000, 1000), ("elemental_resists", 0, 1000)):
        entries = data.get(key, (0,) * 5)
        if not isinstance(entries, (tuple, list)) or len(entries) != 5:
            raise ValueError(f"{key} must have 5 element values")
        fields[key] = tuple(_int(v, key, lo, hi) for v in entries)
    return SpellTarget(name, _int(data.get("hp"), "target.hp", 1, 2**30),
                       _int(data.get("willpower"), "willpower", 0, 100), **fields)


def _domains(raw, auto, law):
    obj = _object(raw, "domain" if auto else "spell", (*AXES, "effect_id"))
    effect = obj.get("effect_id", EFFECT)
    if not isinstance(effect, str) or len(effect) > 64:
        raise ValueError("effect_id must be a string")
    domains = []
    sliders = ("magnitudeBaseLow", "magnitudeBaseHigh", "magnitudeLevelBase",
               "magnitudeLevelHigh", "magnitudePerLevel")
    allowed = [tuple(i for i in range(5) if law[k] & (1 << i)) for k in ("element_mask", "target_mask")]
    allowed += [range(law["spinners"][k][0], law["spinners"][k][1] + 1) for k in sliders]
    for key, choices in zip(AXES, allowed, strict=True):
        values = obj.get(key, choices) if auto else [obj.get(key)]
        if not isinstance(values, (tuple, list, range)) or len(values) > len(choices):
            raise ValueError(f"{key} must contain distinct allowed values")
        if any(type(v) is not int or v not in choices for v in values):
            raise ValueError(f"{key} contains an illegal Spell Maker setting")
        checked = tuple(sorted(values))
        if len(set(checked)) != len(checked):
            raise ValueError(f"{key} contains duplicate values")
        domains.append(checked)
    if not auto and (domains[2][0] > domains[3][0] or domains[4][0] > domains[5][0]):
        raise ValueError("spell magnitude minimum exceeds maximum")
    return effect, tuple(domains)


@dataclass(frozen=True)
class SpellSearch:
    objective: str
    top_k: int
    max_nodes: int
    memory_bytes: int
    wall_seconds: float
    workers: int


def _search(raw):
    raw = _object(raw, "search", SpellSearch.__dataclass_fields__)
    objective = raw.get("objective", "pareto")
    if objective not in ("pareto", "dps", "damage_per_sp"):
        raise ValueError("spell objective must be pareto, dps or damage_per_sp")
    return SpellSearch(
        objective, _int(raw.get("top_k", 10), "top_k", 1, 1000),
        _int(raw.get("max_nodes", 100_000), "max_nodes", 0, 2**63 - 1),
        _int(raw.get("memory_bytes", 64 << 20), "memory_bytes", 1, 2**63 - 1),
        _float(raw.get("wall_seconds", 0), "wall_seconds", 0, 2**31 - 1),
        _int(raw.get("workers", 1), "workers", 1, 1),
    )


def _observed_recipes(character):
    spells = character.get("observations", {}).get("spells")
    if not isinstance(spells, Mapping):
        return ()
    records = spells.get("records", [])
    if not isinstance(records, list):
        raise ValueError("observations.spells.records must be a list")
    fields = ("magnitudeBaseLow", "magnitudeBaseHigh", "magnitudeLevelBase",
              "magnitudeLevelHigh", "magnitudePerLevel")
    known = set()
    for row in records:
        if not isinstance(row, Mapping) or row.get("custom") is not True:
            continue
        entries = row.get("effects")
        if not isinstance(entries, list) or not all(isinstance(e, Mapping) for e in entries):
            continue
        used = [e for e in entries if e.get("type") != -1]
        if len(used) == 1 and (used[0].get("type"), used[0].get("subType")) == (4, 0):
            recipe = (row.get("element"), row.get("rangeType"), *(used[0].get(k) for k in fields))
            if all(type(v) is int for v in recipe):
                known.add(recipe)
    return tuple(sorted(known))


@dataclass(frozen=True)
class SpellRequest:
    caster: SpellCaster
    target: SpellTarget
    search: SpellSearch
    effect_id: str
    domains: tuple
    price_factor: float | None
    blockers: tuple
    snapshot_hash: str | None
    auto: bool
    known_recipes: tuple

    def snapshot(self):
        return asdict(self)

    def recipe(self):
        if self.auto:
            raise ValueError("auto requests have a domain instead of one fixed spell")
        return tuple(axis[0] for axis in self.domains)

    def native_domain(self):
        return self.domains

    @property
    def domain_size(self):
        el, target, blo, bhi, plo, phi, per = self.domains
        return len(el) * len(target) * len(per) * sum(a <= b for a in blo for b in bhi) * sum(a <= b for a in plo for b in phi)

    def native_context(self):
        c = self.caster
        return {"level": c.level, "speed": c.speed, "live_skill": c.destruction_live, "climb": c.climb,
                "available_sp": c.current_sp if c.current_sp is not None else 0,
                "target_hp": self.target.hp, "willpower": self.target.willpower,
                "price_factor": self.price_factor if self.price_factor is not None else 1.0,
                **{k: getattr(self.target, k) for k in (*MASKS, *CHANNELS)},
                **{k: getattr(c, k) for k in MODS}}


def parse_spell_request(raw, rules, *, auto=False):
    if isinstance(raw, Mapping) and "live_observations" in raw:
        from .character import apply_request_observations
        raw = apply_request_observations(raw)
    payload = "domain" if auto else "spell"
    data = _object(raw, "spell request", ("schema_version", "ruleset_hash", "caster", "character",
                                         "target", payload, "search", "price_factor"))
    _int(data.get("schema_version", 1), "schema_version", 1, 1)
    if data.get("ruleset_hash", rules["content_hash"]) != rules["content_hash"]:
        raise ValueError("spell request ruleset_hash differs from the selected ruleset")
    if ("caster" in data) == ("character" in data):
        raise ValueError("provide exactly one of caster or character")
    snapshot_hash = None
    known = ()
    blockers = []
    if "character" in data:
        from .character import normalize_character
        character = normalize_character(data["character"])
        if character.get("ruleset_hash", rules["content_hash"]) != rules["content_hash"]:
            raise ValueError("imported character ruleset_hash differs from the selected ruleset")
        snapshot_hash = character["snapshot_hash"]
        known = _observed_recipes(character)
        blockers.extend(character.get("unknown_mechanics", ()))
        caster = _caster(character["caster"])
    else:
        caster = _caster(data["caster"])
    if "spell_rules" not in rules:
        raise ValueError("Spell requests require a ruleset with combat mechanics")
    effect, domains = _domains(data.get(payload, {}), auto, rules["spell_rules"]["effect"])
    if effect != EFFECT:
        blockers.append(f"unsupported spell effect {effect}")
    wanted = ("level", "speed", "destruction_live", "climb", *MODS, *(("current_sp",) if auto else ()))
    blockers.extend(f"unknown caster.{k}" for k in wanted if getattr(caster, k) is None)
    factor = data.get("price_factor")
    if factor is not None:
        factor = _float(factor, "price_factor", 1e-9, 1000)
    return SpellRequest(caster, _target(data.get("target")), _search(data.get("search", {})),
                        effect, domains, factor, tuple(sorted(set(blockers))), snapshot_hash, auto, known)

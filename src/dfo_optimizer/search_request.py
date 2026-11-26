"""Validate and freeze the M1 finite class domain before native allocation."""

from collections.abc import Mapping
from dataclasses import asdict, dataclass
from math import isfinite
from sys import float_info

from .class_document import ATTRIBUTES
# A reproducible example assignment, editable per slot. These are source skill IDs.
EXAMPLE_SKILLS = (22, 0, 20, 23, 16, 17, 1, 3, 13, 14, 18, 21)
MAGERY_KEYS = {
    0.5: None, 1.0: "intInSpellPoints", 1.5: "intInSpellPoints15",
    1.75: "intInSpellPoints175", 2.0: "intInSpellPoints2", 3.0: "intInSpellPoints3",
}
INPUT_KEYS = frozenset({
    "schema_version", "profile", "objective", "top_k", "max_nodes", "wall_seconds",
    "memory_bytes", "exact", "race_ids", "hp_values", "attribute_domains", "skill_domains",
    "trait_ids", "required_trait_ids", "magicka_multiplier", "allow_high_risk_disadvantages",
    "require_day_and_night_casting", "require_magic_school", "allow_unverified_advantageous_behavior",
    "difficulty_points", "workers",
})


def _integer(value, key, lower, upper):
    if type(value) is not int or not lower <= value <= upper:
        raise ValueError(f"{key} must be an integer from {lower} to {upper}")
    return value


def _boolean(request, key, default):
    value = request.get(key, default)
    if type(value) is not bool:
        raise ValueError(f"{key} must be true or false")
    return value


def _domain(values, key, allowed):
    if not isinstance(values, (list, tuple)) or len(values) > len(allowed):
        raise ValueError(f"{key} must be a list of distinct allowed integers")
    if any(type(v) is not int or v not in allowed for v in values):
        raise ValueError(f"{key} contains an invalid integer")
    if len(set(values)) != len(values):
        raise ValueError(f"{key} contains a duplicate")
    return tuple(sorted(values))


def _stat_domains(request, limits):
    raw = request.get("attribute_domains", {})
    if not isinstance(raw, Mapping) or set(raw).difference(ATTRIBUTES):
        raise ValueError("attribute_domains must map source attribute names to integer lists")
    allowed = range(limits["stat_min"], limits["stat_max"] + 1)
    return tuple(_domain(raw.get(key, [50]), key, allowed) for key in ATTRIBUTES)


def _skill_domains(request, allowed):
    raw = request.get("skill_domains", tuple((v,) for v in EXAMPLE_SKILLS))
    if not isinstance(raw, (list, tuple)) or len(raw) != 12:
        raise ValueError("skill_domains must contain 3 primary, 3 major, and 6 minor slot domains")
    return tuple(_domain(row, f"skill_domains[{i}]", allowed) for i, row in enumerate(raw))


@dataclass(frozen=True)
class SearchRequest:
    profile: str
    objective: str
    top_k: int
    max_nodes: int
    wall_seconds: float
    memory_bytes: int
    exact: bool
    race_ids: tuple
    hp_values: tuple
    attribute_domains: tuple
    skill_domains: tuple
    trait_ids: tuple
    required_trait_ids: tuple
    magicka_multiplier: float | None
    allow_high_risk_disadvantages: bool
    require_day_and_night_casting: bool
    require_magic_school: bool
    allow_unverified_advantageous_behavior: bool
    difficulty_points: int

    def snapshot(self):
        data = asdict(self)
        data["attribute_domains"] = dict(zip(ATTRIBUTES, self.attribute_domains, strict=True))
        return {"schema_version": 1, "workers": 1, **data}


def parse_request(raw, rules):
    request = {} if raw is None else raw
    if not isinstance(request, Mapping):
        raise ValueError("class search request must be a JSON object")
    if request.get("profile") == "spellcaster_discovery_v1":
        from .discovery_request import discovery_request
        return discovery_request(request, rules)
    unknown = set(request).difference(INPUT_KEYS)
    if unknown:
        raise ValueError("unknown class search field(s): " + ", ".join(sorted(map(str, unknown))))
    _integer(request.get("schema_version", 1), "schema_version", 1, 1)
    _integer(request.get("workers", 1), "workers", 1, 1)
    if request.get("profile", "dhargo_pve") != "dhargo_pve":
        raise ValueError("supported M1 profile is dhargo_pve")
    objective = request.get("objective", "examples")
    if objective not in ("examples", "max_intelligence"):
        raise ValueError("supported objectives are examples and max_intelligence")
    magery = request.get("magicka_multiplier", 3.0)
    if magery is not None and (type(magery) not in (int, float) or magery not in MAGERY_KEYS):
        raise ValueError("magicka_multiplier must be a supported source multiplier or null")
    wall = request.get("wall_seconds", 0.0)
    if type(wall) not in (int, float) or not 0 <= wall <= float_info.max or not isfinite(wall):
        raise ValueError("wall_seconds must be finite and nonnegative")
    limits = rules["limits"]
    races = {row["id"] for row in rules["races"]}
    traits = {row["id"] for row in rules["traits"]}
    skills = {row["id"] for row in rules["skills"]}
    return SearchRequest(
        profile="dhargo_pve", objective=objective,
        top_k=_integer(request.get("top_k", 20), "top_k", 1, 10_000),
        max_nodes=_integer(request.get("max_nodes", 1_000_000), "max_nodes", 0, 2**63 - 1),
        wall_seconds=float(wall),
        memory_bytes=_integer(request.get("memory_bytes", 64 << 20), "memory_bytes", 1, 2**63 - 1),
        exact=_boolean(request, "exact", False),
        race_ids=_domain(request.get("race_ids", sorted(races)), "race_ids", races),
        hp_values=_domain(request.get("hp_values", [30]), "hp_values", range(limits["hp_min"], limits["hp_max"] + 1)),
        attribute_domains=_stat_domains(request, limits), skill_domains=_skill_domains(request, skills),
        trait_ids=_domain(request.get("trait_ids", sorted(traits)), "trait_ids", traits),
        required_trait_ids=_domain(request.get("required_trait_ids", []), "required_trait_ids", traits),
        magicka_multiplier=float(magery) if magery is not None else None,
        allow_high_risk_disadvantages=_boolean(request, "allow_high_risk_disadvantages", False),
        require_day_and_night_casting=_boolean(request, "require_day_and_night_casting", True),
        require_magic_school=_boolean(request, "require_magic_school", True),
        allow_unverified_advantageous_behavior=_boolean(request, "allow_unverified_advantageous_behavior", False),
        difficulty_points=_integer(request.get("difficulty_points", -12), "difficulty_points",
                                   limits["difficulty_min"], limits["difficulty_max"]),
    )

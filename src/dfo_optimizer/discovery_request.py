"""Versioned discovery domains. Freeze source identities before entering native search."""

from dataclasses import dataclass
from functools import reduce
from operator import or_

from .class_document import ATTRIBUTES
from .search_request import INPUT_KEYS, SearchRequest, _domain, _integer, parse_request


PROFILE = "spellcaster_discovery_v1"
SLOTS = tuple(
    f"{tier}_{i + 1}" for tier, n in (("primary", 3), ("major", 3), ("minor", 6)) for i in range(n)
)
EXTRA = {
    "attribute_grid_step",
    "skill_locks",
    "required_skills",
    "excluded_skills",
    "required_masteries",
    "required_traits",
    "excluded_traits",
    "roll_seeds",
    "screen_equipment",
    "discovery_seed",
    "coarse_attribute_domains",
}


def resolve_ids(values, names, label):
    if not isinstance(values, (tuple, list)):
        raise ValueError(f"{label} must be a list of catalog names or IDs")
    resolved = []
    for value in values:
        if isinstance(value, str):
            if value.casefold() not in names:
                raise ValueError(f"unknown {label} name: {value}")
            value = names[value.casefold()]
        resolved.append(value)
    return _domain(resolved, label, set(names.values()))


def _balances(domains, total):
    reachable = 1
    for domain in domains:
        reachable = reduce(or_, (reachable << n for n in domain), 0)
    return bool(reachable & (1 << total))


@dataclass(frozen=True)
class DiscoveryRequest(SearchRequest):
    attribute_grid_step: int
    coarse_attributes: tuple
    required_masteries: tuple
    required_skills: tuple
    roll_seeds: tuple
    discovery_seed: int
    equipment_stages: tuple

    def snapshot(self):
        values = super().snapshot()
        values["coarse_attribute_domains"] = dict(
            zip(ATTRIBUTES, values.pop("coarse_attributes"), strict=True)
        )
        values.pop("equipment_stages")
        values["screen_equipment"] = [
            {"stage": stage, "items": [{"instance_id": name, "item": item} for name, item in items]}
            for stage, items in self.equipment_stages
        ]
        return values


def discovery_request(request, rules):
    from .discovery_features import freeze_equipment

    if "progression_rules" not in rules:
        raise ValueError("spellcaster discovery requires an authenticated progression ruleset")
    extra = set(request).difference(INPUT_KEYS | EXTRA)
    if extra:
        raise ValueError(f"unknown discovery fields: {sorted(extra)}")
    objective = request.get("objective", "exhaustive" if request.get("exact") else "diverse")
    if objective not in ("diverse", "exhaustive", "examples"):
        raise ValueError("discovery objective must be diverse, exhaustive or examples")
    skills = {r["name"].casefold(): r["id"] for r in rules["skills"]}
    traits = {
        "/".join(filter(None, (r["primary"], r["secondary"]))).casefold(): r["id"] for r in rules["traits"]
    }
    schools = [r["id"] for r in rules["skills"] if r["magic"]]
    mastery = resolve_ids(request.get("required_masteries", schools), skills, "required_masteries")
    if len(mastery) > sum(rules["progression_rules"]["limits"]["mastery_slots"].values()):
        raise ValueError("required masteries exceed the combined mastery quota")
    required = resolve_ids(request.get("required_skills", []), skills, "required_skills")
    excluded = set(resolve_ids(request.get("excluded_skills", []), skills, "excluded_skills"))
    if excluded.intersection((*mastery, *required)):
        raise ValueError("an excluded skill is required")
    all_skills = sorted(set(skills.values()) - excluded)
    domains = request.get("skill_domains", [all_skills] * 12)
    if not isinstance(domains, (list, tuple)) or len(domains) != 12:
        raise ValueError("expected twelve ordered skill slot domains")
    locks = request.get("skill_locks", {})
    if not isinstance(locks, dict) or set(locks).difference(SLOTS):
        raise ValueError("unknown skill slot lock")
    slot_domains = []
    for key, domain in zip(SLOTS, domains, strict=True):
        values = set(resolve_ids(domain, skills, key)).difference(excluded)
        if key in locks:
            values.intersection_update(resolve_ids([locks[key]], skills, key))
        slot_domains.append(sorted(values))
    banned = resolve_ids(request.get("excluded_traits", []), traits, "excluded_traits")
    available = resolve_ids(request.get("trait_ids", list(traits.values())), traits, "trait_ids")
    required_ids = resolve_ids(request.get("required_trait_ids", []), traits, "required_trait_ids")
    forced = resolve_ids(request.get("required_traits", []), traits, "required_traits")
    limits = rules["limits"]
    full = list(range(limits["stat_min"], limits["stat_max"] + 1))
    override = request.get("attribute_domains", {})
    if not isinstance(override, dict) or set(override).difference(ATTRIBUTES):
        raise ValueError("unknown discovery attribute domain")
    step = _integer(request.get("attribute_grid_step", 10), "attribute_grid_step", 1, len(full))
    grid = sorted({*full[::step], full[-1], 50})
    base = parse_request(
        {
            **{k: v for k, v in request.items() if k in INPUT_KEYS},
            "profile": "dhargo_pve",
            "objective": "examples",
            "skill_domains": slot_domains,
            "trait_ids": sorted(set(available).difference(banned)),
            "required_trait_ids": sorted(set((*forced, *required_ids))),
            "attribute_domains": {k: override.get(k, full) for k in ATTRIBUTES},
        },
        rules,
    )
    seeds = request.get("roll_seeds", list(range(42, 50)))
    if not isinstance(seeds, (tuple, list)) or not 1 <= len(seeds) <= 128:
        raise ValueError("roll_seeds requires 1..128 distinct uint32 seeds")
    seeds = tuple(_integer(v, "roll_seed", 0, 2**32 - 1) for v in seeds)
    if len(set(seeds)) != len(seeds):
        raise ValueError("duplicate roll_seeds")
    coarse = request.get("coarse_attribute_domains", {})
    if not isinstance(coarse, dict) or set(coarse).difference(ATTRIBUTES):
        raise ValueError("unknown coarse attribute domain")
    coarse_values = tuple(
        _domain(coarse.get(k, override.get(k, grid)), k, allowed)
        for k, allowed in zip(ATTRIBUTES, base.attribute_domains, strict=True)
    )
    # Odd-valued locks can leave every coarse allocation off the 400-point ledger.
    # Keep each lock and admit the full legal grid for this pass.
    if not _balances(coarse_values, limits["stat_total"]):
        coarse_values = base.attribute_domains
    return DiscoveryRequest(
        **{**vars(base), "profile": PROFILE, "objective": objective},
        attribute_grid_step=step,
        required_masteries=mastery,
        required_skills=required,
        coarse_attributes=coarse_values,
        roll_seeds=seeds,
        discovery_seed=_integer(request.get("discovery_seed", 0), "discovery_seed", 0, 2**32 - 1),
        equipment_stages=freeze_equipment(request.get("screen_equipment", [])),
    )

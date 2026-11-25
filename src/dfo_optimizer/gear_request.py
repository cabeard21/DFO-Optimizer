"""Compile source equipment placements and observed acquisition facts for native search."""

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from .equipment import equipment_catalog, inspect_item, legal_catalog_items

MODIFIERS = ("speed", "destruction", "cast_speed_pct", "power_pct", "pierce",
             "cost_pct", "enhanced_destruction", "intelligence")
MODES = {"owned_only", "owned_plus_budget", "available_catalog", "theoretical_bis"}
MAX_MONEY = (1 << 53) - 1


def mapping(value, label):
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be an object")
    return value


def money(raw, label):
    result = {}
    for key, value in mapping(raw, label).items():
        if not isinstance(key, str) or not key or len(key) > 64:
            raise ValueError(f"invalid currency in {label}")
        if type(value) is not int or not 0 <= value <= MAX_MONEY:
            raise ValueError(f"invalid amount in {label}")
        result[key] = value
    return result


@dataclass(frozen=True)
class EquipmentOption:
    identity: str
    item: Mapping
    owned: bool
    hypothetical: bool
    price: tuple | None
    placements: tuple
    modifiers: tuple
    legendary: str | None
    worn: int | None
    container: str
    source: str | None


@dataclass(frozen=True)
class GearDomain:
    items: tuple
    locks: tuple
    budget: tuple
    mode: str
    slots: Mapping
    filtered: Mapping
    unsupported: Mapping
    current: Mapping
    generated: int
    worn_int: int = 0
    uncertain_worn: bool = False
    policy: object = None
    empty_mask: int = 0


def _availability(mode, owned, obtainable, hypothetical, prices, budget, container, containers):
    if container not in containers and owned:
        return "container_unavailable"
    if owned:
        return None
    if mode == "owned_only":
        return "unowned"
    if hypothetical and mode != "theoretical_bis":
        return "hypothetical"
    if obtainable is not True and mode != "theoretical_bis":
        return "unobtainable" if obtainable is False else "availability_unknown"
    if mode == "owned_plus_budget":
        if prices is None:
            return "price_unknown"
        if any(value > budget.get(key, 0) for key, value in prices.items()):
            return "budget"
    return None


def _item(row, mode, budget, containers, career, settings):
    raw = mapping(row.get("item"), "item")
    source = mapping(row.get("acquisition", {}), "acquisition")
    owned = source.get("owned", True)
    obtainable = source.get("obtainable")
    hypothetical = source.get("hypothetical", False)
    if any(v is not None and type(v) is not bool for v in (owned, obtainable)) or type(hypothetical) is not bool:
        raise ValueError("acquisition flags must be true, false or unknown")
    if owned and hypothetical:
        raise ValueError("a hypothetical item cannot be owned")
    price = source.get("price")
    price = money(price, "price") if price is not None else None
    container = row.get("container", "pack" if owned else "catalog")
    if not isinstance(container, str):
        raise ValueError("invalid item container")
    worn = raw.get("equipSlot") if owned and container == "pack" else None
    if worn is not None and (type(worn) is not int or not 0 <= worn < 27):
        raise ValueError("invalid equipped slot")
    reason = _availability(mode, owned, obtainable, hypothetical, price, budget, container, containers)
    if reason:
        return None, (reason,), worn, ()
    details = inspect_item(dict(raw), career=career, worn_slot=worn, **settings)
    reasons = tuple(details["reasons"]) + tuple(details["unsupported"])
    if reasons or not details["placements"]:
        return None, reasons or ("no_placement",), worn, tuple(details["unsupported"])
    option = EquipmentOption(
        row["instance_id"], raw, owned is True, hypothetical,
        () if owned else None if price is None else tuple(sorted(price.items())),
        tuple((p["slot"], p["mask"]) for p in details["placements"]),
        tuple(details["modifiers"].get(k, 0) for k in MODIFIERS),
        details.get("legendary_id"), worn, container, source.get("source"),
    )
    return option, (), worn, ()


def _locks(raw, slots, identities):
    result = {}
    for name, value in mapping(raw, "locks").items():
        if name not in slots or (value is not None and
                                (not isinstance(value, str) or value not in identities)):
            raise ValueError(f"invalid lock at {name}")
        if value is not None and value in result.values():
            raise ValueError("cannot lock one copy to multiple slots")
        result[slots[name]] = value
    return tuple(sorted(result.items()))


def _source(request):
    character = mapping(request.get("character", {}), "character")
    gear = mapping(character.get("gear", {}), "character.gear")
    if "inventory" in request and gear.get("items"):
        raise ValueError("use offers for acquisitions alongside imported character items")
    entries = request.get("inventory", gear.get("items", []))
    offers = request.get("offers", [])
    if not isinstance(entries, (list, tuple)) or not isinstance(offers, (list, tuple)):
        raise ValueError("inventory and offers must be lists")
    candidates = list(entries)
    for row in offers:
        mapping(row, "offer")
        evidence = mapping(row.get("acquisition", {}), "offer acquisition")
        if evidence.get("owned",False) is True:
            raise ValueError("offers cannot establish an owned inventory copy")
        candidates.append({**row, "acquisition": {"owned": False, **evidence}})
    return gear, candidates


def prepare_inventory(request):
    gear, entries = _source(request)
    mode = request.get("mode", "owned_only")
    if not isinstance(mode, str) or mode not in MODES:
        raise ValueError("unsupported gear acquisition mode")
    budget = money(request.get("budget", {}), "budget")
    career = request.get("career", gear.get("career"))
    if career is not None:
        mapping(career, "career")
        for key in ("forbiddenMaterialsFlags","weaponArmorShieldsBitfield"):
            v=career.get(key,0)
            if type(v) is not int or not 0<=v<=2**32-1:
                raise ValueError(f"invalid career.{key}")
    auto = request.get("catalog", mode in ("available_catalog", "theoretical_bis"))
    if type(auto) is not bool:
        raise ValueError("catalog must be a boolean")
    if auto and mode not in ("available_catalog", "theoretical_bis"):
        raise ValueError("automatic catalog requires available_catalog or theoretical_bis")
    templates = request.get("catalog_templates")
    if templates is not None and (not isinstance(templates, (list, tuple)) or
                                  any(type(x) is not int or x < 0 for x in templates)):
        raise ValueError("catalog_templates must list source template IDs")
    if templates is not None and not auto:
        raise ValueError("catalog_templates requires catalog generation")
    access = request.get("catalog_access", [])
    if not isinstance(access, (list, tuple)) or any(s != "tier6_pile_level45_luck50" for s in access):
        raise ValueError("catalog_access must list supported acquisition sources")
    catalog_character = request.get("character", {"gear": {"career": career}})
    generated = list(legal_catalog_items(catalog_character,
                                         theoretical=mode == "theoretical_bis",
                                         template_indices=templates, access=access)) if auto else []
    slots = {k: v for k, v in equipment_catalog()["slots"].items() if 0 <= v < 27}
    exclusions = request.get("exclusions", [])
    if not isinstance(exclusions, (list, tuple)) or not all(isinstance(s, str) for s in exclusions):
        raise ValueError("exclusions must be item IDs")
    excluded = set(exclusions)
    settings = {"bow_left_hand": request.get("bow_left_hand", False), "gender": gear.get("gender")}
    if type(settings["bow_left_hand"]) is not bool:
        raise ValueError("bow_left_hand must be boolean")
    containers = request.get("available_containers", ["pack"])
    if (not isinstance(containers, (list, tuple)) or
            any(k not in ("pack", "wagon", "bag") for k in containers)):
        raise ValueError("available_containers may contain pack, wagon or bag")
    found, current, filtered, unsupported, options = set(), {}, {}, {}, []
    worn_int = 0
    uncertain_worn = False
    for row in (*entries, *generated):
        key = mapping(row, "inventory record").get("instance_id")
        if not isinstance(key, str) or not key or len(key) > 256 or key in found:
            raise ValueError("invalid or duplicate physical instance_id")
        found.add(key)
        option, reasons, worn, blockers = _item(row, mode, budget, containers, career, settings)
        if blockers:
            unsupported[key] = blockers
        if worn is not None:
            if worn in current:
                raise ValueError("multiple items claim the same equipped slot")
            current[worn] = key
            if option is None:
                uncertain_worn = True
            else:
                worn_int += option.modifiers[7]
        if reasons or key in excluded:
            filtered[key] = reasons + (("excluded",) if key in excluded else ())
        else:
            options.append(option)
    return GearDomain(tuple(sorted(options, key=lambda a: a.identity)),
                      _locks(request.get("locks", {}), slots, found), tuple(sorted(budget.items())),
                      mode, MappingProxyType(slots), MappingProxyType(filtered), MappingProxyType(unsupported), MappingProxyType(current),
                      len(generated),worn_int,uncertain_worn)

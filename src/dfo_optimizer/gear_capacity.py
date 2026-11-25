"""Immediate spell-point availability while moving equipment to its final slots."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Capacity:
    intelligence: int
    quarters: int
    bonus: int
    explicit: int
    current_int: int
    uncertain_worn: bool


def capacity(request, domain):
    values = request.get("capacity", {})
    if not isinstance(values,dict) or set(values)-{"intelligence","non_equipment_bonus","post_swap_sp"}:
        raise ValueError("capacity must describe Intelligence, a flat maximum bonus, or hypothetical post_swap_sp")
    character = request.get("character",{})
    gear = character.get("gear",{})
    stats = character.get("observations",{}).get("stats") or {}
    intel = values.get("intelligence", stats.get("intelligence"))
    bonus = values.get("non_equipment_bonus")
    explicit = values.get("post_swap_sp")
    for label, n, limit in (("intelligence",intel,255),("non_equipment_bonus",bonus,2**30),
                            ("post_swap_sp",explicit,2**30)):
        if n is not None and (type(n) is not int or not 0 <= n <= limit):
            raise ValueError(f"invalid capacity.{label}")
    if explicit is not None and len(values)>1:
        raise ValueError("post_swap_sp is an alternative hypothetical resource state")
    career = request.get("career",gear.get("career"))
    # chargen.spellPointMultiplier then formulas.spellPointsFor. No career
    # means the getter reads the stored value, so no INT-derived cap is known.
    bits = (career or {}).get("abilityFlagsAndSpellPointsBitfield",0x1000)
    if type(bits) is not int or not 0 <= bits <= 2**32-1:
        raise ValueError("invalid career magery flags")
    q = {0:12,4:8,8:7,12:6,16:4,20:2}.get((bits & 0x1c00)>>8,4) if career is not None else 0
    return Capacity(-1 if intel is None else min(100,intel),q,-1 if bonus is None else bonus,
                    -1 if explicit is None else explicit, domain.worn_int, domain.uncertain_worn)


def spendable(policy, original, layout, domain, total_int):
    if policy.explicit >= 0:
        return policy.explicit, policy.explicit
    changed = {i:item.identity for i,item in layout.items()} != dict(domain.current)
    if not changed:
        return original, original
    retained = sum(item.modifiers[7] for slot,item in layout.items()
                   if item.worn==slot and not item.legendary)
    lost = max(0,policy.current_int-retained)
    # An unknown career can lose at most the verified maximum multiplier (3x)
    # per removed INT. An unreviewed worn item may also alter the flat pool.
    safe = 0 if policy.uncertain_worn else max(0,original-(lost*(policy.quarters or 12)+3)//4)
    possible = original
    if policy.intelligence>=0 and policy.quarters:
        base = min(100,policy.intelligence+retained)*policy.quarters//4
        safe=max(safe,base+max(0,policy.bonus))
        if policy.bonus>=0:
            possible=min(original,min(100,policy.intelligence+total_int)*policy.quarters//4+policy.bonus)
    return min(safe,possible),possible

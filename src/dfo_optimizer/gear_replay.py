"""Independent legality, acquisition and spell-math replay of retained loadouts."""
from collections import Counter

from .gear_request import MODIFIERS
from .gear_capacity import spendable
from .spell_reference import evaluate_reference
from .spell_request import AXES

# The first open position is selected by equipTable.js. Either-handed weapons
# additionally have an explicit hand-drop action and need no temporary donor.
PAIRS = {"Amulet1": "Amulet0", "Bracelet1": "Bracelet0", "Ring1": "Ring0",
         "Bracer1": "Bracer0", "Mark1": "Mark0", "Crystal1": "Crystal0",
         "Cloak1": "Cloak2"}


def _selected(row, domain):
    layout = {}
    occupied, seen = 0, set()
    for slot, index in enumerate(row["slots"]):
        if index < 0:
            continue
        item = domain.items[index]
        mask = dict(item.placements).get(slot)
        if mask is None or occupied & mask or item.identity in seen:
            raise RuntimeError("Native loadout failed independent physical placement verification")
        seen.add(item.identity)
        occupied |= mask
        layout[slot] = item
    for slot, lock in domain.locks:
        if (layout[slot].identity if slot in layout else None) != lock:
            raise RuntimeError("Native loadout violates a requested slot lock")
    for second, first in PAIRS.items():
        s, f = domain.slots[second], domain.slots[first]
        if s not in layout or f in layout or layout[s].worn == s:
            continue
        kept = layout[s].identity
        if domain.current.get(f) not in (None, kept):
            continue
        if not any(i.owned and i.identity != kept and f in dict(i.placements) for i in domain.items):
            raise RuntimeError("A paired-slot finalist lacks a temporary donor")
    return layout


def fold_worn_modifiers(slotted_modifiers, ctx):
    """Fold identified items in physical equip-slot order over gear-free channels."""
    seen = set()
    total = Counter()
    for legendary, modifiers in slotted_modifiers:
        duplicate = legendary and legendary in seen
        for name, value in modifiers.items():
            if name == "enhanced_destruction" or not duplicate:
                total[name] += value
        seen.add(legendary)
    result = dict(ctx)
    result["speed"] = min(100, max(0, ctx["speed"] + total["speed"]))
    result["live_skill"] += total["enhanced_destruction"] + total["destruction"]
    result["pierce"] += total["pierce"]
    for key, channel in (("focus_pct", "cost_pct"), ("cast_speed_pct", "cast_speed_pct"),
                         ("power_pct", "power_pct")):
        result[key] += min(30, total[channel])
    return result, dict(total)


def _spending(layout, domain):
    totals = Counter()
    purchases = []
    unknown = False
    for item in layout.values():
        if item.owned:
            continue
        price = None if item.price is None else dict(item.price)
        unknown |= price is None
        totals.update(price or {})
        purchases.append({"instance_id": item.identity, "hypothetical": item.hypothetical,
                          "price": price, "source": item.source})
    remaining = {k: v - totals[k] for k, v in domain.budget}
    if domain.mode == "owned_plus_budget" and (unknown or any(
            v > dict(domain.budget).get(k, 0) for k, v in totals.items())):
        raise RuntimeError("Native loadout exceeds acquisition resources")
    return {"purchases": purchases, "known_cost": dict(totals),
            "total_cost": None if unknown else dict(totals),
            "budget_remaining": remaining if domain.mode == "owned_plus_budget" else None}


def replay(row, domain, spec, policy, empty_mask):
    layout = _selected(row, domain)
    ctx, total = fold_worn_modifiers(
        ((item.legendary, dict(zip(MODIFIERS,item.modifiers,strict=True))) for item in layout.values()),
        spec.native_context())
    ctx["available_sp"], _ = spendable(policy, ctx["available_sp"],layout,domain,total.get("intelligence",0))
    occupancy = {k:None for k in domain.slots}
    for anchor,it in layout.items():
        mask=dict(it.placements)[anchor]
        if mask & empty_mask:
            raise RuntimeError("Native loadout occupied a locked empty slot")
        for label,i in domain.slots.items():
            if mask & (1<<i):
                occupancy[label]=it.identity
    recipe = tuple(row["recipe"])
    if (len(recipe) != 7 or any(v not in axis for v, axis in zip(recipe, spec.domains)) or
            recipe[2] > recipe[3] or recipe[4] > recipe[5]):
        raise RuntimeError("Native gear finalist spell is outside the declared domain")
    metrics = evaluate_reference(ctx, recipe)
    if (not metrics["affordable"] or
            any(metrics[k] != row[k] for k in ("cost_sp", "outcomes", "health_loss_sum")) or
            round(metrics["cast_rate"] * 200) != row["rate_200"]):
        raise RuntimeError("Native gear finalist disagrees with independent spell replay")
    if spec.price_factor is None:
        metrics["purchase_gold"] = None
    slots = {name: layout[n].identity if n in layout else None for name, n in domain.slots.items()}
    changed = {name: {"from": domain.current.get(n), "to": slots[name]}
               for name, n in domain.slots.items() if domain.current.get(n) != slots[name]}
    return {"loadout": slots, "occupancy": occupancy, "changed_slots": changed,
            "items": [{"instance_id": item.identity, "container": item.container,
                       "owned": item.owned, "hypothetical":item.hypothetical, "source":item.source,
                       "item": dict(item.item)} for item in layout.values()],
            "spell": {"effect_id": spec.effect_id, **dict(zip(AXES, recipe, strict=True))},
            "modifiers": total, "effective": {k: ctx[k] for k in ("speed", "live_skill", "climb",
                         "pierce", "cast_speed_pct", "power_pct", "focus_pct","available_sp")},
            "metrics": metrics, "validated": True, **_spending(layout, domain)}

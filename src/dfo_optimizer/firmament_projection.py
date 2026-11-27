"""Independent scalar replay of reviewed Firmament caster channels."""

from .gear_request import prepare_inventory

CHANNEL_NAMES = (
    "spellPower", "spellPierce", "castSpeed", "castCost", "castCost.Destruction",
    "skill.Destruction", "skillPct.Destruction", "speed", "pct.speed", "intelligence",
    "pct.intelligence", "mp", "mpPct",
)
_MINS = (-20, 0, -15, -20, 0, -15, 0, -15, 0, -15, 0, 0, 0)
_MAXS = (30, 10, 15, 25, 20, 15, 20, 15, 15, 15, 15, 75, 15)


def _clip(value, low, high):
    return max(low, min(high, value))


def _share(base, percent):
    return max(0, base) * max(0, percent) // 100


def _channels(gains, prices):
    gains = tuple(_clip(gain, lo, hi) for gain, lo, hi in zip(gains, _MINS, _MAXS, strict=True))
    totals = tuple(_clip(gain + price, lo, hi) for gain, price, lo, hi in
                   zip(gains, prices, _MINS, _MAXS, strict=True))
    discount = min(25, gains[3] + gains[4]) + totals[3] + totals[4] - gains[3] - gains[4]
    return totals, discount


def tree_vectors(tree, catalog):
    """Build source-law gain and price vectors for a checked allocation."""
    rows = [catalog["nodes"][key]["stats"] for key in [tree["start"], *tree["keys"]] if key]
    gains = tuple(sum(max(0, row.get(channel, 0)) for row in rows) for channel in CHANNEL_NAMES)
    prices = tuple(sum(min(0, row.get(channel, 0)) for row in rows) for channel in CHANNEL_NAMES)
    return gains, prices


def projection_basis(character, stars, catalog):
    """Resolve the fixed, uneffected inputs that both native searches share."""
    observations = character["observations"]
    permanent = observations.get("stats", {})
    caster = character["gear"].get("base_caster", {})
    speed, intelligence, destruction = permanent.get("speed"), permanent.get("intelligence"), caster.get("destruction_trained")
    if any(type(value) is not int or value < 0 for value in (speed, intelligence, destruction)):
        raise ValueError("Firmament scoring requires known permanent Speed, Intelligence and Destruction")
    domain = prepare_inventory({"character": character, "mode": "owned_only"})
    by_id = {row["instance_id"]: row["item"] for row in character["gear"]["items"]}
    unresolved = [by_id[key].get("name", key) for key in domain.current.values()
                  if key in domain.filtered or key in domain.unsupported]
    if unresolved or domain.uncertain_worn or observations.get("worn_equipment_issues"):
        details = unresolved or observations.get("worn_equipment_issues") or ["unknown equipment"]
        raise ValueError("Firmament scoring needs verified worn gear: " + ", ".join(details))
    career = character["gear"].get("career")
    if not isinstance(career, dict):
        raise ValueError("Firmament scoring requires known career Magery")
    bits = career.get("abilityFlagsAndSpellPointsBitfield", 0x1000)
    if type(bits) is not int or not 0 <= bits < 2**32:
        raise ValueError("Invalid saved career Magery")
    # chargen.spellPointMultiplier: the low ability bits are outside the multiplier field.
    quarters = {0: 12, 4: 8, 8: 7, 12: 6, 16: 4, 20: 2}.get((bits & 0x1C00) >> 8, 4)
    renown_sp = stars // catalog["stars_per_renown"] * catalog["renown_sp"]
    return speed, intelligence, destruction, domain.worn_int, quarters, 0, renown_sp


def project_reference(context, projection, gains, prices):
    """Apply Firmament to a Gear-folded native spell context for replay."""
    speed, _, destruction, *_ = projection
    totals, discount = _channels(gains, prices)
    speed_gain = _clip(totals[7] + _share(speed, totals[8]), -15, 15)
    destruction_gain = _clip(totals[5] + _share(destruction, totals[6]), -15, 15)
    return {**context, "power_pct": context["power_pct"] + totals[0],
            "pierce": context["pierce"] + totals[1], "cast_speed_pct": context["cast_speed_pct"] + totals[2],
            "live_skill": max(0, context["live_skill"] + destruction_gain),
            "speed": _clip(context["speed"] + speed_gain, 0, 100), "firmament_cost_pct": discount}


def maximum_sp_reference(projection, gains, prices, equip_int):
    _, intelligence, _, _, quarters, flat, renown = projection
    totals, _ = _channels(gains, prices)
    gain = _clip(totals[9] + _share(intelligence, totals[10]), -15, 15)
    live = _clip(intelligence + equip_int + gain, 0, 100 + max(0, gain))
    raw = live * quarters // 4 + flat
    extra = _clip(totals[11] + _share(raw, totals[12]), 0, 75)
    return max(0, raw + renown + extra)

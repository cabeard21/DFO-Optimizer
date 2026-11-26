"""Single-effect release costs for ordinary prospective school practice.

Each row is a reviewed EFFECT_COST_TABLE entry in the pinned spellcost.js.
effectCost truncates the midpoint and level increment before applying the
school term. hostMagic.tallyCastSkills credits one use at physical release.
"""

# (cast school, component, A, B). These effects cover all six schools.
_EFFECTS = {
    (4, 0): (22, "magnitude", 20, 28),
    (10, 8): (23, "magnitude", 20, 28),
    (15, 255): (24, "duration", 8, 40),
    (25, 255): (25, "duration", 20, 100),
    (14, 255): (26, "duration", 60, 100),
    (17, 255): (27, "chance", 20, 100),
}


def release_cost(record, school):
    if record.get("minimumCastingCost") or record.get("pvpKitCost") or record.get("path"):
        return None
    slots = record.get("effects")
    if not isinstance(slots, list) or not 1 <= len(slots) <= 3 or any(
        not isinstance(row, dict) or type(row.get("type")) is not int for row in slots
    ):
        return None
    real = [row for row in slots if row["type"] >= 0]
    if len(real) != 1 or type(real[0].get("subType")) is not int:
        return None
    effect = real[0]
    law = _EFFECTS.get((effect["type"], effect["subType"] & 255))
    target = record.get("rangeType")
    if law is None or law[0] != school or type(target) is not int or target not in range(5):
        return None
    if school == 22 and target == 0:
        return None  # A self-damage release affects the HP projection.
    _, component, a, b = law
    if component == "magnitude":
        names = ("magnitudeBaseLow", "magnitudeBaseHigh", "magnitudeLevelBase",
                 "magnitudeLevelHigh", "magnitudePerLevel")
    else:
        names = tuple(component + key for key in ("Base", "Mod", "PerLevel"))
    values = [effect.get(key) for key in names]
    if any(type(v) is not int or not 0 <= v <= 255 for v in values):
        return None
    if component == "magnitude":
        lo, hi, inc_lo, inc_hi, divisor = values
        if lo > hi or inc_lo > inc_hi:
            return None
        base, increment = (lo + hi) // 2, (inc_lo + inc_hi) // 2
    else:
        base, increment, divisor = values
    return {"component_gold": a * base + b * (increment // max(1, divisor)),
            "range_multiplier_twice": (2, 2, 3, 4, 5)[target],
            "self_heal": school == 23 and target == 0}

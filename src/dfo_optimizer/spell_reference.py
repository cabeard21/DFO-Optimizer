"""Independent scalar replay for returned spells. Never enumerate search candidates here."""
from collections import Counter
from functools import lru_cache
from math import floor


def _round_js(value):
    whole = floor(value)
    return whole + (value - whole >= 0.5)


def _save(ctx, element):
    flag = (8, 16, 4, 32, 2)[element]
    adjustments = (("resistant", 25), ("immune", 50), ("low_tolerance", -25), ("critical_weakness", -50))
    tolerance = next((v for key, v in adjustments if ctx[key] & flag), 0)
    initial = 50 + tolerance + ctx["resist_mods"][element]
    if initial >= 100:
        return 100, True
    return max(5, min(95, initial + ctx["willpower"] // 10 - ctx["pierce"])), False


@lru_cache(maxsize=64)
def _save_rolls(chance):
    return tuple(Counter(100 if roll > chance else max(0, 100 - 5 * (chance - roll))
                         for roll in range(1, 101)).items())


@lru_cache(maxsize=32_768)
def _one_magnitude(raw, chance, hp, potency):
    damage = loss = kills = 0
    for percent, n in _save_rolls(chance):
        scaled = raw * percent // 100
        points = max(1, _round_js(scaled * potency)) if scaled else 0
        damage += points * n
        loss += min(hp, points) * n
        kills += (points >= hp) * n
    return damage, loss, kills


def _probabilities(ctx, recipe, chance, immune, potency):
    el, _r, blo, bhi, plo, phi, per = recipe
    q = ctx["level"] // per
    den = (bhi - blo + 1) * (phi - plo + 1) * 10_000
    resist_pass = max(0, 100 - ctx["elemental_resists"][el])
    damage = hp_loss = kills = 0
    if not immune and resist_pass:
        # Count the (base, plus) pairs producing each raw value. Saves are rolled
        # independently of magnitude; identical percentage outcomes share a count.
        for raw in range(blo + q * plo, bhi + q * phi + 1):
            if q:
                left = max(plo, -((bhi - raw) // q))
                right = min(phi, (raw - blo) // q)
                count = max(0, right - left + 1)
            else:
                count = phi - plo + 1
            if count:
                points, loss, lethal = _one_magnitude(raw, chance, ctx["target_hp"], potency)
                weight = count * resist_pass
                damage += points * weight
                hp_loss += loss * weight
                kills += lethal * weight
    return damage, hp_loss, kills, den


def evaluate_reference(ctx, recipe):
    """Recompute fixed-cast results from wire inputs using two independent rolls."""
    el, target, blo, bhi, plo, phi, per = recipe
    base_gold = 20 * ((blo + bhi) // 2) + 28 * (((plo + phi) // 2) // per)
    skill = ctx["live_skill"]
    effect_sp = base_gold * (110 - skill) // 400 if skill <= 100 else base_gold * 1000 // (400 * skill)
    half_mult = (2, 2, 3, 4, 5)[target]
    gold = base_gold * half_mult // 2
    raw_sp = max(5, effect_sp * half_mult // 2)
    cost = max(1, _round_js(raw_sp * (100 - min(30, ctx["focus_pct"])) / 100))
    cost = max(1, _round_js(cost * (100 - ctx.get("firmament_cost_pct", 0)) / 100))
    price = max(1, _round_js(gold * ctx["price_factor"]))
    rate = min(2, max(0.5, 1 + (ctx["speed"] - 50) / 200 + ctx["cast_speed_pct"] / 100))
    potency = (1 + max(0, ctx["climb"] - 100) * 0.01) * max(0.5, 1 + ctx["power_pct"] / 100)
    chance, immune = _save(ctx, el)
    damage_sum, loss_sum, kill_sum, den = _probabilities(ctx, recipe, chance, immune, potency)
    damage, loss, kills = damage_sum / den, loss_sum / den, kill_sum / den
    return {"gold": gold, "effect_sp": effect_sp, "purchase_gold": price, "cost_sp": cost,
            "affordable": ctx["available_sp"] >= cost, "save_chance": chance, "immune": immune,
            "potency": potency, "cast_rate": rate, "recovery_seconds": 0.7 / rate,
            "release_seconds": 0.2 / rate, "damage_sum": damage_sum, "health_loss_sum": loss_sum,
            "kill_sum": kill_sum, "outcomes": den, "expected_damage": damage,
            "expected_health_loss": loss, "kill_probability": kills,
            "damage_per_sp": loss / cost, "dps": loss / (0.7 / rate)}

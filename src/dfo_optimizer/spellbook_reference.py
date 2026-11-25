"""Shortlist-only independent replay of the terminal state of a finite effect sequence."""
from collections import Counter
from functools import lru_cache

from .spell_reference import _round_js, _save, _save_rolls


def _state(raw):
    return {"cast_speed_pct": 0, "climb": 0, "power_pct": 0, "pierce": 0,
            "focus_pct": 0, "price_factor": 1.0, "resistant": 0, "immune": 0,
            "low_tolerance": 0, "critical_weakness": 0, "resist_mods": (0,)*5,
            "elemental_resists": (0,)*5, **raw}


def _tally(ctx, route):
    draw = [80 * e[1] + 140 * (e[2] // e[5]) if e[0] else
            20 * ((e[1] + e[2]) // 2) + 28 * (((e[3] + e[4]) // 2) // e[5])
            for e in route[2]]
    supplied = ctx["live_skill"]
    extent = [a * 1000 // (400 * supplied) if supplied > 100 else a * (110-supplied) // 400
              for a in draw]
    strength = (2, 2, 3, 4, 5)[route[1]]
    native = max(5, sum(extent) * strength // 2)
    expected = int((native * (100 - min(30, ctx["focus_pct"])) + 50) // 100)
    pool = sum(draw) * strength // 2
    return (0 if ctx.get("free_cast") else expected), pool, max(1, _round_js(pool * ctx["price_factor"]))


@lru_cache(maxsize=512)
def _costs(choices, chance, available, curvature, hp):
    """Precompute the chance of exceeding each possible health loss before rendering the terminal plan."""
    loss = Counter()
    offered = 0
    total = sum(h for _, h in choices) * 10000
    for value, h in choices:
        for progress, charge in _save_rolls(chance):
            x = value * progress // 100
            edge = max(1, _round_js(x*curvature)) if x else 0
            n = h * available * charge
            loss[min(hp, edge)] += n
            offered += edge * n
    loss[0] += total - sum(loss.values())
    return tuple((k,v/total) for k,v in sorted(loss.items()) if v), offered/total


def _source_sp(ctx, member, element, access):
    a, b, c, d, e = member[1:]
    pol = ctx["level"] // e
    sample = Counter(i + pol*j for i in range(a, b+1) for j in range(c,d+1))
    bias = (1 + max(0, ctx["climb"]-100) / 100) * max(0.5, 1 + ctx["power_pct"]/100)
    chance, immune = _save(ctx, element)
    if immune or not access:
        return [(0, 1.0)], 0
    return _costs(tuple(sorted(sample.items())), chance, access, bias, ctx["target_hp"])


def _integer_weights(probabilities):
    # Binary floats are already rationals with power-of-two denominators.
    terms = [(degree, *value.as_integer_ratio()) for degree, value in probabilities if value]
    denominator = max(d for _, _, d in terms)
    return {degree: n * (denominator // d) for degree, n, d in terms}, denominator


def _pack_polynomial(weights, width):
    digits = bytearray((max(weights) + 1) * width)
    for power, coefficient in weights.items():
        digits[power*width:(power+1)*width] = coefficient.to_bytes(width, "little")
    return int.from_bytes(digits, "little")


def _apply_damage(remaining, losses):
    alive = {hp: p for hp, p in remaining.items() if hp > 0 and p}
    dead = remaining.get(0, 0.)
    if not alive:
        return {0: dead}
    losses = [(d, p) for d, p in losses if p]
    highest = max(alive)
    span = highest - min(alive) + max(d for d, _ in losses) + 1
    # Large gaps between reachable HP values should not allocate dense arrays.
    if len(alive) * len(losses) <= 65_536 or span > 8 * (len(alive) + len(losses)):
        updated = Counter()
        if dead:
            updated[0] = dead
        for hp, weight in alive.items():
            for damage, chance in losses:
                updated[max(0, hp-damage)] += weight * chance
        return updated

    # Exact polynomial multiplication in CPython's native bigint implementation
    # avoids a Python callback per pair on wide shortlist witnesses. Fold the lethal
    # tail after multiplying, so a large starting HP never sizes the polynomial.
    prior, a = _integer_weights((highest-hp, p) for hp, p in alive.items())
    incoming, b = _integer_weights(losses)
    total = sum(prior.values()) * sum(incoming.values())
    width = (total.bit_length()+7)//8  # each output coefficient fits; no carries between powers
    product = _pack_polynomial(prior, width) * _pack_polynomial(incoming, width)
    count = max(prior) + max(incoming) + 1
    digits = product.to_bytes(width * count, "little")
    denominator = a*b
    result = {}
    survivors = 0
    for power in range(min(highest, count)):
        weight = int.from_bytes(digits[power*width:(power+1)*width], "little")
        if weight:
            survivors += weight
            result[highest-power] = weight / denominator
    result[0] = dead + (total-survivors) / denominator
    return result


def replay(raw, route):
    target = _state(raw)
    needed_sp, search_gold, price = _tally(target, route)
    el, _, spells = route
    core = target["target_hp"]
    cut = 1 - min(100, target["elemental_resists"][el]) / 100
    current = {core: 1.0}
    result = 0.0
    for material in spells:
        if material[0]:
            hint = min(100, material[1]+material[2]*(target["level"]//material[5]))/100
            points, exclusive = _save({**target, "pierce": 0}, el)
            test = sum(p for k, p in _save_rolls(points) if k > 0) / 100
            remain = 0 if exclusive else hint * cut * test
            result += remain * sum(k*v for k,v in current.items())
            current = {k: v*(1-remain) for k,v in current.items()}
            current[0] = current.get(0,0) + remain
        else:
            requested, before_count = _source_sp(target, material, el, int(round(cut*100)))
            result += before_count
            current = _apply_damage(current, requested)
    added = sum((core-k)*v for k,v in current.items())
    rated = min(2, max(.5, 1+(target["speed"]-50)/200 + target["cast_speed_pct"]/100))
    return {"expected_damage": result, "expected_health_loss": added, "kill_probability": current.get(0,0),
            "gold": search_gold, "purchase_gold": price, "cost_sp": needed_sp, "dps": added/(.7/rated),
            "release_seconds": .2 / rated, "recovery_seconds": .7 / rated}

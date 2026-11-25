"""Independent, scalar replay of one emitted route through the online skill law.

This module validates witnesses. Production graph expansion belongs to the
native engine. Times are personal classic minutes unless a field ends in ms.
"""
from copy import deepcopy
from math import floor, inf


MULTIPLIERS = (12, 1, 1, 5, 15, 15, 15, 15, 15, 15, 15, 15, 15, 2, 1, 2,
               2, 1, 2, 1, 4, 50, 1, 2, 1, 1, 2, 1, 2, 2, 2, 2, 2, 1, 8)
COMBAT = {19, 20, 28, 29, 30, 31, 32, 33, 34}
MAGIC = set(range(22, 28))


def initial_effort():
    return dict(practice=0, rest_passes=0, minutes=0, spent=0)


def require(ok, reason):
    if not ok:
        raise ValueError(reason)


def effective(skill):
    bonus = sum(n for threshold, n in ((125, 2), (150, 3), (175, 4), (200, 6))
                if skill >= threshold)
    return skill if skill <= 100 else 100 + (skill - 100) // 4 + bonus


def skill_sum(s):
    def group(key):
        return sorted((effective(s["skills"][i] if i in s["mastered"] else min(100, s["skills"][i]))
                       for i in s[key]), reverse=True)
    return sum(group("primary") + group("major")[:2] + group("minor")[:1])


def earned_level(start, current):
    room = 800 - start
    if room <= 0:
        return 45
    return max(1, min(45, (28 * room + 647 * min(current - start, room)) // (15 * room)))


def _price(s, i, value, level):
    base = floor(value * MULTIPLIERS[i] * s["advancement_multiplier"] * 1.04**level * 2 / 5) + 1
    return base * (1 if value < 100 else 1.5 if value < 125 else 2 if value < 150
                   else 4 if value < 200 else inf)


def _pending(s):
    if s["level"] < earned_level(s["starting_sum"], s["current_sum"]):
        s["pending_level"] = s["level"] + 1
    elif s["level"] >= 45:
        s["pending_level"] = s["pending_pool"] = -1


def _check(s, effort):
    if s["minutes"] - s["last_check"] <= 360:
        return
    s["last_check"] = s["minutes"]
    effort["rest_passes"] += 1
    high = max(s["current_sum"], skill_sum(s))
    price_level = max(s["level"], earned_level(s["starting_sum"], high))
    reflex = 65536 - (s["reflexes"] - 2) * 8192
    raised = False
    for i, raw in enumerate(s["skills"]):
        uses = floor(s["uses"][i] * reflex / 65536)
        if raw >= 100 and i in s["mastered"]:
            if raw == 200:
                continue
            price = _price(s, i, raw, price_level)
            points = s["progress"][i] + uses / price
            s["uses"][i] = 0
            s["progress"][i] = points
            if points < 1:
                continue
            s["progress"][i] = (points - 1) * price / _price(s, i, raw + 1, price_level)
        else:
            base = floor(raw * MULTIPLIERS[i] * s["advancement_multiplier"] * 1.04**price_level * 2 / 5) + 1
            # Ordinary skills retain classic JS signed-32-bit right shift. The
            # mastered branch above uses Math.floor on the unwrapped product.
            signed_product = (s["uses"][i] * reflex + 2**31) % 2**32 - 2**31
            if signed_product // 65536 < base:
                continue
            s["uses"][i] = 0
            if raw >= 100:
                continue
        s["skills"][i] += 1
        raised = True
    if raised:
        s["current_sum"] = max(s["current_sum"], skill_sum(s))
    _pending(s)


def _quality(skill, level):
    if level <= 0:
        return 0.
    ratio = (5 * level + 30) / skill
    if ratio < .75:
        return 0.
    if ratio < 1:
        return ((ratio - .75) * 4) ** 2
    return 1 + .5 * min(1., (ratio - 1) / .5)


def _tally(s, i, amount):
    raw = s["skills"][i]
    if raw < 100 or i not in s["mastered"]:
        s["uses"][i] = min(20000, s["uses"][i] + amount)
        return
    if raw == 200:
        return
    level = s["challenge_level"] if s["challenge_at"] >= 0 and s["real_ms"] - s["challenge_at"] <= 6000 else 0
    q = _quality(raw, level)
    q, burst = (q, 40) if i in COMBAT else (max(.25, q), 10) if i in MAGIC else (1, 6)
    if not q:
        return
    now = s["real_ms"]
    decayed = s["spam_recent"][i] * .5 ** (max(0, now - s["spam_at"][i]) / 60000)
    recent = decayed + amount * q
    s["spam_recent"][i], s["spam_at"][i] = recent, now
    total = s["fractions"][i] + amount * q * min(1, burst / recent)
    whole = floor(total)
    s["fractions"][i] = total - whole
    s["uses"][i] += whole


def _cast_price(s, a):
    if "recipe" not in a:
        return a.get("sp_cost", 0)
    _, target, lo, hi, plus_lo, plus_hi, per = a["recipe"]
    base = 20 * ((lo + hi) // 2) + 28 * (((plus_lo + plus_hi) // 2) // per)
    raw = s["skills"][22]
    live = max(0, effective(raw if 22 in s["mastered"] else min(raw, 100)) + a.get("skill_bonus", 0))
    unscaled = base * (110 - live) // 400 if live <= 100 else base * 1000 // (400 * live)
    cost = max(5, unscaled * (2, 2, 3, 4, 5)[target] // 2)
    return max(1, floor(cost * (100 - min(30, a.get("focus_pct", 0))) / 100 + .5))


def _practice(s, a, e):
    i = a["skill"]
    if s["skills"][i] >= a.get("until_skill", 201):
        return
    if a.get("spell", -1) >= 0:
        require(a["spell"] in s["known"], "spell is not known")
    count = a.get("count", 1)
    cost = _cast_price(s, a) * count
    require(s["sp"] >= cost, "insufficient current SP")
    debit = a.get("fatigue_cost", 0)
    require(debit <= s["fatigue"], "insufficient fatigue for practice")
    s["fatigue"] -= debit
    s["sp"] -= cost
    for _ in range(count):
        s["real_ms"] += a.get("cadence_ms", 0)
        if a.get("challenge_level", 0):
            s["challenge_level"], s["challenge_at"] = a["challenge_level"], s["real_ms"]
        if "horizontal_m" in a or "vertical_m" in a:
            s["odometer_h"] += a.get("horizontal_m", 0)
            s["odometer_v"] += a.get("vertical_m", 0)
            if s["skills"][i] >= 100 and i in s["mastered"]:
                if s["skills"][i] >= 200:
                    continue
                reading = (s["odometer_v"] if i == 18 else s["odometer_h"] +
                           (s["odometer_v"] if i == 17 else 0))
                previous = s["move_mark"][i]
                s["move_mark"][i] = reading
                if previous < 0 or previous > reading:
                    s["move_credit"][i] = 0.
                    continue
                stride = {3: 1., 17: 3., 18: .5, 21: 1.}[i]
                credit = min(2., s["move_credit"][i] + (reading - previous) / stride)
                counted = min(a.get("amount", 1), credit)
                s["move_credit"][i] = credit - counted
                total = s["fractions"][i] + counted
                s["uses"][i] += floor(total)
                s["fractions"][i] = total - floor(total)
                continue
        _tally(s, i, a.get("amount", 1))
    e["practice"] += count


def _pay(s, amount, e):
    require(s["gold"] >= amount, "insufficient gold for purchase")
    s["gold"] -= amount
    e["spent"] += amount


def _train(s, a, e):
    i = a["skill"]
    require(s["skills"][i] <= 50, "trainer requires permanent skill at or below 50")
    require(s["minutes"] - s["last_training"] >= 720, "trainer cooldown")
    fatigue = a.get("fatigue_cost", 1980)
    require(s["fatigue"] >= fatigue, "insufficient fatigue for training")
    cost = a.get("gold_cost")
    if cost is None:
        cost = max(1, floor((100 if a["member"] else 400) * s["level"] * a.get("price_factor", 1) + .5))
    _pay(s, cost, e)
    s["last_training"] = s["minutes"]
    s["fatigue"] -= fatigue
    _tally(s, i, a["roll"] * MULTIPLIERS[i])
    e["practice"] += 1


def _master(s, skill):
    require(s["skills"][skill] >= 100, "mastery requires earned skill 100")
    require(skill not in s["mastered"], "skill already mastered")
    group = next(((s[k], n) for k, n in (("primary", 3), ("major", 2), ("minor", 1)) if skill in s[k]), None)
    require(group and len(set(group[0]).intersection(s["mastered"])) < group[1], "no available mastery slot")
    s["mastered"] = sorted([*s["mastered"], skill])
    s["uses"][skill] = 0


def _distribute(s, a, budget):
    if "allocation_order" in a:
        points = [0] * 8
        left = budget
        for i in a["allocation_order"]:
            points[i] = min(left, 100 - s["attributes"][i])
            left -= points[i]
    else:
        points = a["allocation"]
    require(sum(points) == min(budget, sum(100 - v for v in s["attributes"])), "incorrect attribute point spend")
    attributes = [x + d for x, d in zip(s["attributes"], points, strict=True)]
    require(all(v <= 100 for v in attributes), "attribute cap exceeded")
    s["attributes"] = attributes


def _level(s, a):
    if a.get("if_due") and (s["pending_level"] != s["level"] + 1 or s["level"] >= 45):
        return
    require(s["pending_level"] == s["level"] + 1 and s["level"] < 45, "level has not been earned")
    _distribute(s, a, 5 if s["pending_pool"] < 0 else s["pending_pool"])
    s["level"] += 1
    s["pending_level"] = s["pending_pool"] = -1
    _pending(s)


def transition(state, action, effort):
    """Apply a single compiled action to detached state, or explain its first unmet gate."""
    s, e = deepcopy(state), dict(effort)
    kind = action["kind"]
    delta = action.get("minutes", 0)
    if kind != "practice":
        s["real_ms"] += action.get("real_elapsed_ms", 0)
    if kind == "practice":
        if s["skills"][action["skill"]] >= action.get("until_skill", 201):
            return s, e
        _practice(s, action, e)
    elif kind == "train":
        _train(s, action, e)
        delta = 180
    elif kind == "rest":
        wait = s["minutes"] - s["last_rest"]
        require(s["last_rest"] < 0 or wait < 0 or wait >= 120, "online night cooldown")
        delta = 480
        s["last_rest"] = s["minutes"] + delta
        for _ in range(8):
            _tally(s, 0, 1)
        for k in ("sp", "fatigue"):
            if action.get("refill_" + k, -1) >= 0:
                s[k] = max(s[k], action["refill_" + k])
    elif kind == "level":
        _level(s, action)
    elif kind == "oghma":
        bit = 1 << action["copy"]
        require(s.get("oghma_mask", 0) & bit, "Oghma artifact was already consumed")
        _distribute(s, action, 30)
        s["oghma_mask"] ^= bit
        s["pending_level"] = s["pending_pool"] = -1
    elif kind == "firmament":
        require(s.get("firmament") == action["firm_from"], "Firmament allocation starts from a different tree")
        s["firmament"] = action["firm_to"]
    elif kind == "master":
        try:
            _master(s, action["skill"])
        except ValueError:
            if not action.get("if_eligible"):
                raise
    elif kind == "choose":
        key = action["family"] + "_path"
        require(s[key] < 0, "family already has a specialization")
        require(set(action["pair"]).issubset(s["mastered"]), "specialization requires both mastered skills")
        s[key] = action["path"]
    elif kind == "reset":
        key = action["family"] + "_path"
        require(s[key] >= 0, "no specialization to reset")
        bank = max(0, 200000 - s["gold"])
        require(bank <= s.get("bank_gold", 0), "insufficient gold for reset")
        _pay(s, 200000 - bank, e)
        if bank:
            s["bank_gold"] -= bank
            e["spent"] += bank
        s[key] = -1
    elif kind == "buy":
        require(action["spell"] not in s["known"], "spell already owned")
        if action.get("path", -1) >= 0:
            require(s[action["family"] + "_path"] == action["path"], "required specialization unavailable")
        _pay(s, action["gold_cost"], e)
        s["known"] = sorted([*s["known"], action["spell"]])
    else:
        require(kind in ("skip", "check"), "unsupported action")
        if action.get("short_rest"):
            require(s["last_rest"] >= 0 and 0 <= s["minutes"] + delta - s["last_rest"] < 120,
                    "short rest unavailable when a night is due")
    s["minutes"] += delta
    e["minutes"] += delta
    if kind in ("rest", "check"):
        _check(s, e)
    return s, e


def goal_met(s, goal):
    return (s["level"] >= goal.get("level", 1)
            and all(s["skills"][int(k)] >= v for k, v in goal.get("skills", {}).items())
            and all(s["attributes"][int(k)] >= v for k, v in goal.get("attributes", {}).items())
            and set(goal.get("mastered", ())).issubset(s["mastered"])
            and set(goal.get("known", ())).issubset(s["known"])
            and ("firmament" not in goal or s.get("firmament") == goal["firmament"])
            and all(k not in goal or s[k] == goal[k] for k in ("arcane_path", "martial_path")))

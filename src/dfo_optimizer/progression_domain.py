"""Compile finite, evidenced action opportunities for the online progression solver."""
import math
from copy import deepcopy
from dataclasses import dataclass

from .progression_replay import MAGIC, require


def integer(value, label, lo=0, hi=2**31 - 1):
    require(type(value) is int and lo <= value <= hi, f"{label} must be an integer in [{lo}, {hi}]")
    return value


def fields(obj, allowed, label):
    require(isinstance(obj, dict), f"{label} must be an object")
    require(all(isinstance(k, str) for k in obj), f"{label} field names must be strings")
    extra = set(obj).difference(allowed)
    require(not extra, f"unknown {label} fields {sorted(extra)}")
    return obj


def boolean(value, label):
    require(type(value) is bool, f"{label} must be boolean")
    return value


def evidence(value):
    require(isinstance(value, str) and 0 < len(value.strip()) <= 2048, "activity requires attributed opportunity evidence")
    return value


def skill_id(i):
    return integer(i, "skill id", 0, 34)


def _spell_id(i):
    return integer(i, "game spell index", -(2**31), 2**31 - 1)


def _indices(obj, name, hi, max_value):
    require(isinstance(obj, dict), f"{name} must map numeric IDs to thresholds")
    result = {}
    for k, v in obj.items():
        require(type(k) is int or isinstance(k, str) and k.isascii() and k.isdecimal(), f"invalid {name} index")
        n = integer(int(k), name, 0, hi)
        require(n not in result, f"duplicate {name} index")
        result[n] = integer(v, name, 0, max_value)
    return result


def windows(raw):
    sources = [k for k in ("stages", "activities", "cycles") if k in raw]
    require(len(sources) == 1, "provide one of stages, activities, cycles")
    if "activities" in raw:
        count = integer(raw.get("max_events", 12), "max_events", 1, 100_000)
        rows = [raw["activities"]] * count
    elif "cycles" in raw:
        rows = []
        require(isinstance(raw["cycles"], list), "cycles must be a list")
        for cycle in raw["cycles"]:
            fields(cycle, ("repeat", "windows"), "cycle")
            n = integer(cycle.get("repeat", 1), "repeat", 1, 100_000)
            w = cycle.get("windows")
            require(isinstance(w, list) and 0 < len(w) and len(w)*n + len(rows) <= 100_000,
                    "invalid cycle windows or too many stages")
            rows += w * n
    else:
        rows = raw["stages"]
    require(isinstance(rows, list) and len(rows) <= 100_000, "stages must be a bounded list")
    require(all(isinstance(w, list) and 0 < len(w) <= 4096 for w in rows), "each stage needs alternatives")
    require(sum(map(len, rows)) <= 1_000_000, "too many progression alternatives")
    return rows


def _spell_data(s, rows, goal):
    records = {}
    ids = set(s.get("known") or s.get("known_indices") or [])
    for record in s.get("spell_records") or (s.get("spells") or {}).get("records", []):
        if type(record.get("index")) is int:
            records[record["index"]] = record
    seen = set()
    for window in rows:
        if id(window) in seen:
            continue
        seen.add(id(window))
        for action in window:
            require(isinstance(action, dict), "action must be an object")
            if "spell" in action:
                ids.add(_spell_id(action["spell"]))
            if action.get("kind") == "buy" and "record" in action:
                r = action["record"]
                require(isinstance(r, dict) and r.get("index") == action.get("spell"), "purchase spell record mismatch")
                if r["index"] in records:
                    require(records[r["index"]] == r, "conflicting records for one spell index")
                records[r["index"]] = r
    known_goal = goal.get("known", [])
    require(isinstance(known_goal, list), "goal known must be a list")
    ids.update(_spell_id(i) for i in known_goal)
    require(len(ids) <= 256, "native spell domain supports up to 256 game indices")
    return sorted(ids), records


class Gap(ValueError):
    """Insufficient provenance to compile this opportunity."""


def need(ok, reason):
    if not ok:
        raise Gap(reason)


_CLOCK = {"minutes", "last_check"}
_CAREER = {"skills", "mastered", "primary", "major", "minor"}
_RAISE = _CLOCK | _CAREER | {"starting_sum", "current_sum", "reflexes", "advancement_multiplier",
                             "level", "uses", "progress", "pending_level", "pending_pool"}
_NEEDS = {
    "skip": set(), "practice": {"skills", "mastered", "uses", "fractions"},
    "level": {"attributes", "level", "pending_level", "pending_pool", "starting_sum", "current_sum"},
    "master": _CAREER | {"uses"}, "choose": {"mastered"}, "reset": {"gold"},
    "train": {"level", "skills", "uses", "minutes", "last_training", "gold", "fatigue"},
    "buy": {"gold", "known"}, "rest": _RAISE | {"last_rest"}, "check": _RAISE,
}
_COMMON = {"kind", "evidence", "real_elapsed_ms"}
_FIELDS = {
    "skip": set(), "check": {"minutes", "trigger", "fare_gold"}, "rest": {"refill_sp", "refill_fatigue", "site"},
    "train": {"skill", "guild", "member", "roll", "price_factor"},
    "practice": {"skill", "spell", "cadence_ms", "challenge_level", "count", "minutes", "until_skill",
                 "activity", "horizontal_m", "vertical_m", "fatigue_cost"},
    "level": {"allocation", "allocation_order", "if_due"}, "master": {"skill", "if_eligible"},
    "choose": {"family", "path"}, "reset": {"family"},
    "buy": {"spell", "gold_cost", "family", "path", "record"},
}


def get_recipe(record):
    if record.get("minimumCastingCost") or record.get("pvpKitCost") or record.get("path"):
        return None
    rows = record.get("effects")
    if not isinstance(rows, list) or any(not isinstance(e, dict) or type(e.get("type")) is not int for e in rows):
        return None
    entries = [e for e in rows if e["type"] >= 0]
    if len(entries) != 1 or (entries[0]["type"], entries[0].get("subType")) != (4, 0):
        return None
    effect = entries[0]
    names = ("magnitudeBaseLow", "magnitudeBaseHigh", "magnitudeLevelBase", "magnitudeLevelHigh", "magnitudePerLevel")
    if any(type(effect.get(k)) is not int for k in names):
        return None
    recipe = [record.get("element"), record.get("rangeType"), *(effect[k] for k in names)]
    if (type(recipe[0]) is not int or type(recipe[1]) is not int
            or recipe[0] not in range(5) or recipe[1] not in (1, 2, 3, 4)
            or not 0 <= recipe[2] <= recipe[3] <= 255 or not 0 <= recipe[4] <= recipe[5] <= 255
            or not 1 <= recipe[6] <= 255):
        return None
    return recipe


@dataclass
class Domain:
    source_state: dict
    missing: set
    path_rows: list
    spell_ids: list
    records: dict
    trainers: dict
    temples: set
    time_model: dict

    def path(self, family, name):
        require(family in ("arcane", "martial"), "unknown specialization family")
        for i, row in enumerate(self.path_rows):
            if row["id"] == name and row["family"] == family:
                return i, row
        raise ValueError(f"unknown {family} path {name!r}")

    def compile_goal(self, g):
        fields(g, ("level", "skills", "mastered", "attributes", "known", "arcane_path", "martial_path"), "goal")
        require(g, "progression goal is empty")
        out = {}
        if "level" in g:
            out["level"] = integer(g["level"], "goal level", 1, 45)
        for key, hi, cap in (("skills", 34, 200), ("attributes", 7, 100)):
            if key in g:
                out[key] = _indices(g[key], key, hi, cap)
        for key in ("mastered", "known"):
            if key in g:
                require(isinstance(g[key], list), f"goal {key} must be a list")
                out[key] = ([skill_id(i) for i in g[key]] if key == "mastered"
                            else [self.spell_ids.index(_spell_id(i)) for i in g[key]])
        for family in ("arcane", "martial"):
            key = family + "_path"
            if key in g:
                out[key] = self.path(family, g[key])[0]
        return out

    def compile_action(self, a):
        kind = a.get("kind")
        require(type(kind) is str and kind in _FIELDS, f"unknown progression action {kind!r}")
        fields(a, _COMMON | _FIELDS[kind], kind)
        out = {"kind": kind}
        deps = set(_NEEDS[kind])
        if kind in ("practice", "rest", "check", "train", "buy"):
            need(isinstance(a.get("evidence"), str) and a["evidence"].strip(), f"missing {kind} opportunity evidence")
            evidence(a["evidence"])
        if "real_elapsed_ms" in a:
            require(kind != "practice", "practice time uses cadence_ms")
            out["real_elapsed_ms"] = integer(a["real_elapsed_ms"], "real_elapsed_ms")
        if "skill" in a or kind in ("practice", "train", "master"):
            out["skill"] = skill_id(a.get("skill"))
        if kind in ("rest", "check"):
            need(self.source_state.get("chargen_done") is True, "skill checks require completed chargen")
        if kind == "practice":
            out.update(self.practice(a, deps))
        elif kind == "check":
            need(a.get("trigger") in ("short_rest_end", "fast_travel_arrival"),
                 "skill check requires an observed completed short rest or arrival")
            out["minutes"] = integer(a.get("minutes", 0), "elapsed personal minutes")
            if a["trigger"] == "short_rest_end":
                require("fare_gold" not in a, "fare_gold applies only to fast-travel arrivals")
                deps.add("last_rest")
                out["short_rest"] = True
            else:
                # world.js charges coach/ship fees in coin and other fees from total on hand.
                need("fare_gold" in a, "fast-travel arrival requires an observed total fare")
                need(integer(a["fare_gold"], "total travel fare") == 0,
                     "paid travel requires separate coin-only and total-fare affordability")
        elif kind == "rest":
            for k, cap in (("refill_sp", "max_sp"), ("refill_fatigue", "max_fatigue")):
                if k in a:
                    n = integer(a[k], k)
                    need(a.get("site") in ("bed", "camp"), "full recovery requires an uninterrupted bed or camp")
                    need(self.source_state.get(cap) is not None and n <= self.source_state[cap], f"unverified {k} capacity")
                    if k == "refill_sp":
                        flags = (self.source_state.get("career") or {}).get("abilityFlagsAndSpellPointsBitfield", 0)
                        need(not flags & 8, "training route requires the optional online no-regen exception")
                        need(n <= 8 * max(1, self.source_state[cap] // 8), "requested SP exceeds eight verified recovery ticks")
                    else:
                        need(n <= 8 * max(1, self.source_state[cap] // 8), "requested fatigue exceeds eight recovery ticks")
                    out[k] = n
        elif kind == "train":
            guild = a.get("guild")
            require(isinstance(guild, str), "guild must be a string")
            need(out["skill"] in self.trainers.get(guild, ()), "guild does not offer this skill")
            out["member"] = boolean(a.get("member"), "trainer membership")
            need(out["member"] or guild in self.temples, "non-temple trainer requires guild membership")
            out["roll"] = integer(a.get("roll"), "recorded training roll", 10, 20)
            factor = a.get("price_factor", 1)
            require(type(factor) in (float, int) and math.isfinite(factor) and 0 < factor <= 100, "invalid price_factor")
            out["price_factor"], out["fatigue_cost"] = factor, 1980
        elif kind == "level":
            require(("allocation" in a) != ("allocation_order" in a), "choose allocation or allocation_order")
            key = "allocation" if "allocation" in a else "allocation_order"
            require(isinstance(a[key], list) and len(a[key]) == 8, f"{key} requires eight entries")
            out[key] = [integer(v, key, 0, 7 if key == "allocation_order" else 30) for v in a[key]]
            if key == "allocation_order":
                require(len(set(out[key])) == 8, "allocation_order must be a permutation")
            out["if_due"] = boolean(a.get("if_due", False), "if_due")
        elif kind == "master":
            out["if_eligible"] = boolean(a.get("if_eligible", False), "if_eligible")
        if kind in ("reset", "choose") or kind == "buy" and "path" in a:
            family = a.get("family")
            require(family in ("arcane", "martial"), "unknown specialization family")
            deps.add(family + "_path")
            out["family"] = family
            if kind != "reset":
                out["path"], row = self.path(family, a.get("path"))
                if kind == "choose":
                    out["pair"] = row["skills"]
        if kind == "buy":
            require(("family" in a) == ("path" in a), "provide both purchase path and family")
            out["spell"] = self.spell_ids.index(_spell_id(a.get("spell")))
            out["gold_cost"] = integer(a.get("gold_cost"), "observed purchase price")
            need(a["spell"] in self.records, "missing purchase spell record")
            record = self.records[a["spell"]]
            owner = next((row["id"] for row in self.path_rows if row.get("signature") == a["spell"]), None)
            if owner or record.get("path"):
                need(a.get("family") == "arcane" and a.get("path") == (owner or record["path"]), "signature requires its path")
            need(self.source_state.get("has_spellbook") is True, "spellbook required for purchase")
        if kind == "reset":
            deps.add("bank_gold")
        gaps = sorted(deps.intersection(self.missing))
        need(not gaps, "missing starting observation " + ", ".join(gaps))
        return out

    def practice(self, a, deps):
        skill = a["skill"]
        out = {"amount": 1, "count": integer(a.get("count", 1), "practice count", 1, 100000),
               "minutes": integer(a.get("minutes", 0), "elapsed personal minutes"),
               "challenge_level": integer(a.get("challenge_level", 0), "challenge level", 0, 2000)}
        if a.get("until_skill") is not None:
            out["until_skill"] = integer(a["until_skill"], "until_skill", 1, 200)
        out["cadence_ms"] = integer(a.get("cadence_ms", 0), "cadence_ms", 0, 1_000_000)
        # At the ordinary online clock rate five real seconds advance one personal minute.
        minimum = out["count"] * out["cadence_ms"] // 5000
        if "minutes" not in a:
            out["minutes"] = minimum
        else:
            require(out["minutes"] >= minimum, "personal minutes do not cover the declared practice cadence")
        if skill in MAGIC:
            need(not self.source_state.get("environmental_magery"), "environmental magery requires a verified environment")
            need("spell" in a, "magic practice requires a known spell record")
            deps.update(("sp", "known"))
            game_id = a["spell"]
            record = self.records.get(game_id)
            need(record is not None, f"unresolved game spell record {game_id}")
            recipe = get_recipe(record)
            need(recipe is not None and skill == 22 and
                 not any(row.get("signature") == game_id for row in self.path_rows),
                 "unsupported practice spell effect or school")
            need(self.source_state.get("has_spellbook") is True, "casting requires a spellbook")
            need(out["cadence_ms"] >= 1400,
                 "repeated cast cadence must allow the slowest supported casting recovery")
            need(not self.source_state.get("practice_modifiers_unknown"), "unverified spell cost modifiers")
            out.update(spell=self.spell_ids.index(game_id), recipe=recipe,
                       skill_bonus=self.source_state.get("skill_bonus", 0),
                       focus_pct=self.source_state.get("focus_pct", 0))
        else:
            require("spell" not in a, "nonmagic practice cannot use a spell")
            activities = {"polite_conversation": (1,), "blunt_conversation": (2,), "failed_pacification": range(4, 13),
                          "lockpick_attempt": (13,), "completed_trade": (14,), "pickpocket_attempt": (15,),
                          "stealth_check": (16,), "motion": (3, 17, 18, 21)}
            activity = a.get("activity")
            require(activity is None or isinstance(activity, str), "practice activity must be a string")
            need(skill in activities.get(activity, ()), "no verified gameplay tally for this skill and activity")
            if a.get("activity") == "motion":
                need("horizontal_m" in a or "vertical_m" in a, "movement requires measured odometer displacement")
                need("fatigue_cost" in a, "movement requires an observed total exertion debit")
                deps.add("fatigue")
                out["fatigue_cost"] = integer(a["fatigue_cost"], "movement fatigue debit")
                for k in ("horizontal_m", "vertical_m"):
                    v = a.get(k, 0)
                    require(type(v) in (int, float) and math.isfinite(v) and 0 <= v <= 10000, "invalid motion distance")
                    out[k] = v
            else:
                require(not {"fatigue_cost", "horizontal_m", "vertical_m"}.intersection(a),
                        "movement measurements require motion practice")
        return out

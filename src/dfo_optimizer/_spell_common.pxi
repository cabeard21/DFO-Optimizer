# Shared C++ declarations and validated conversion for the spell and gear kernels.
from libcpp cimport bool as cpp_bool
from libc.stdint cimport int64_t

cdef extern from "spell_kernel.hpp" namespace "dfo_spell":
    cdef cppclass Context:
        int level, live_skill, climb, speed, available_sp, target_hp, willpower
        int power_pct, pierce, cast_speed_pct, focus_pct
        int resistant, immune, low_tolerance, critical_weakness
        int resist_mods[5]
        int elemental_resists[5]
        double price_factor
        cpp_bool free_cast
    cdef cppclass Recipe:
        int element, range_type, base_low, base_high, level_low, level_high, per_level
    cdef cppclass Score:
        int gold, purchase_gold, effect_sp, cost_sp, save_chance
        cpp_bool affordable, immune
        int64_t damage_sum, health_loss_sum, kill_sum, outcomes
        double expected_damage, expected_health_loss, kill_probability, damage_per_sp, dps
        double cast_rate, release_seconds, recovery_seconds, potency
    Score evaluate_direct "dfo_spell::evaluate"(const Context&, const Recipe&) noexcept nogil

cdef int _spell_int(object value, str label, int lo, int hi) except? -1:
    if type(value) is not int or not lo <= value <= hi:
        raise ValueError(f"{label} must be an integer in [{lo}, {hi}]")
    return value

cdef Context prepare_context(dict data) except *:
    cdef Context c
    cdef int i
    c.level = _spell_int(data["level"], "level", 1, 1000)
    c.live_skill = _spell_int(data["live_skill"], "live_skill", 0, 10000)
    c.climb = _spell_int(data["climb"], "climb", 0, 140)
    c.speed = _spell_int(data["speed"], "speed", 0, 100)
    c.available_sp = _spell_int(data["available_sp"], "available_sp", 0, 2147483647)
    c.target_hp = _spell_int(data["target_hp"], "target_hp", 1, 2147483647)
    c.willpower = _spell_int(data["willpower"], "willpower", 0, 100)
    c.power_pct = _spell_int(data.get("power_pct",0), "power_pct", -100, 1000)
    c.pierce = _spell_int(data.get("pierce",0), "pierce", 0, 1000)
    c.cast_speed_pct = _spell_int(data.get("cast_speed_pct",0), "cast_speed_pct", -100, 1000)
    c.focus_pct = _spell_int(data.get("focus_pct",0), "focus_pct", 0, 1000)
    c.resistant = _spell_int(data.get("resistant",0), "resistant", 0, 127)
    c.immune = _spell_int(data.get("immune",0), "immune", 0, 127)
    c.low_tolerance = _spell_int(data.get("low_tolerance",0), "low_tolerance", 0, 127)
    c.critical_weakness = _spell_int(data.get("critical_weakness",0), "critical_weakness", 0, 127)
    mods=data.get("resist_mods",(0,0,0,0,0))
    wards=data.get("elemental_resists",(0,0,0,0,0))
    if len(mods)!=5 or len(wards)!=5:
        raise ValueError("resist_mods and elemental_resists need one value for each element")
    for i in range(5):
        c.resist_mods[i]=_spell_int(mods[i], "resist_mods", -1000, 1000)
        c.elemental_resists[i]=_spell_int(wards[i], "elemental_resists", 0, 1000)
    factor=data.get("price_factor",1.0)
    if type(factor) not in (float,int) or not 0 < factor <= 1000:
        raise ValueError("price_factor must be in (0, 1000]")
    c.price_factor=factor
    free=data.get("free_cast",False)
    if type(free) is not bool:
        raise ValueError("free_cast must be boolean")
    c.free_cast=free
    return c

cdef Recipe prepare_recipe(object row) except *:
    cdef Recipe r
    if len(row)!=7:
        raise ValueError("spell row must contain seven ordered integer settings")
    r.element=_spell_int(row[0],"element",0,4)
    r.range_type=_spell_int(row[1],"range_type",1,4)
    r.base_low=_spell_int(row[2],"base_low",1,100)
    r.base_high=_spell_int(row[3],"base_high",r.base_low,100)
    r.level_low=_spell_int(row[4],"level_low",1,100)
    r.level_high=_spell_int(row[5],"level_high",r.level_low,100)
    r.per_level=_spell_int(row[6],"per_level",1,20)
    return r

cdef tuple recipe_tuple(const Recipe& r):
    return (r.element,r.range_type,r.base_low,r.base_high,r.level_low,r.level_high,r.per_level)

cdef dict unpack_score(const Score& s):
    return {
        "gold": s.gold, "purchase_gold": s.purchase_gold, "effect_sp": s.effect_sp,
        "cost_sp": s.cost_sp, "affordable": bool(s.affordable), "save_chance": s.save_chance,
        "immune": bool(s.immune), "cast_rate": s.cast_rate, "release_seconds": s.release_seconds,
        "recovery_seconds": s.recovery_seconds, "potency": s.potency,
        "damage_sum": s.damage_sum, "health_loss_sum": s.health_loss_sum, "kill_sum": s.kill_sum,
        "outcomes": s.outcomes, "expected_damage": s.expected_damage, "expected_health_loss": s.expected_health_loss,
        "kill_probability": s.kill_probability, "damage_per_sp": s.damage_per_sp if s.cost_sp else None,
        "dps": s.dps,
    }

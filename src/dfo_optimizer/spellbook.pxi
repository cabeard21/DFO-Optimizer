# Native Spellmaker search writes each complete recipe into its shared M5 access path.
from libcpp.vector cimport vector

cdef extern from "spellbook.hpp" namespace "dfo_book":
    cdef cppclass Settings:
        int effect_kind, base_low, base_high, plus_low, plus_high, per_level
        int chance_base, chance_increment
    cdef cppclass Bundle:
        int element, range_type
        vector[Settings] effects
    cdef cppclass SpellScore:
        int gold, cost_sp, purchase_gold
        double expected_health_loss, expected_damage, kill_probability, dps
    SpellScore score_bundle "dfo_book::evaluate"(const Context&, const Bundle&) except + nogil

cdef Bundle prepare_bundle(object row) except *:
    cdef Bundle spell
    cdef Settings e
    if len(row) != 3 or not 1 <= len(row[2]) <= 3:
        raise ValueError("A Spellmaker recipe must search 1 to 3 effects")
    spell.element = _spell_int(row[0], "element", 0, 4)
    spell.range_type = _spell_int(row[1], "target", 1, 4)
    for member in row[2]:
        if len(member) != 6:
            raise ValueError("A candidate effect needs six settings")
        e.effect_kind = _spell_int(member[0], "effect ID", 0, 1)
        if e.effect_kind:
            e.chance_base = _spell_int(member[1], "chance base", 1, 100)
            e.chance_increment = _spell_int(member[2], "chance increment", 1, 100)
        else:
            e.base_low = _spell_int(member[1], "magnitude base low", 1, 100)
            e.base_high = _spell_int(member[2], "magnitude base high", e.base_low, 100)
        e.plus_low = _spell_int(member[3], "effect plus low", 0 if e.effect_kind else 1, 0 if e.effect_kind else 100)
        e.plus_high = _spell_int(member[4], "effect plus high", e.plus_low, 0 if e.effect_kind else 100)
        e.per_level = _spell_int(member[5], "level divisor", 1, 20)
        spell.effects.push_back(e)
    return spell

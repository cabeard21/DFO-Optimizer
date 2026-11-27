# Shared conversion for the two native callers of Firmament projection.
cdef extern from "firmament_projection.hpp" namespace "dfo_firmament":
    cdef cppclass Channels:
        int gains[13]
        int prices[13]
    cdef cppclass Projection:
        int permanent_speed, permanent_intelligence, permanent_destruction
        int worn_intelligence, quarters, flat_capacity, renown_sp


cdef Channels pack_channels(object gains, object prices) except *:
    cdef Channels result
    if len(gains) != 13 or len(prices) != 13:
        raise ValueError("Firmament projection requires thirteen gains and prices")
    for i in range(13):
        result.gains[i] = _spell_int(gains[i], "Firmament gain", 0, 100000)
        result.prices[i] = _spell_int(prices[i], "Firmament price", -100000, 0)
    return result


cdef Projection pack_projection(object values) except *:
    cdef Projection result
    speed, intelligence, destruction, worn_int, quarters, flat, renown = values
    result.permanent_speed = _spell_int(speed, "permanent Speed", 0, 255)
    result.permanent_intelligence = _spell_int(intelligence, "permanent Intelligence", 0, 255)
    result.permanent_destruction = _spell_int(destruction, "permanent Destruction", 0, 1000)
    result.worn_intelligence = _spell_int(worn_int, "worn Intelligence", 0, 27000)
    result.quarters = _spell_int(quarters, "magery multiplier quarters", 0, 12)
    result.flat_capacity = _spell_int(flat, "flat capacity", -(1 << 26), 1 << 26)
    result.renown_sp = _spell_int(renown, "Renown SP", 0, 10000)
    return result

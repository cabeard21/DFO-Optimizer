# cython: language_level=3
"""Coarse-grained native calls. All Python conversions happen outside traversal."""
import math
from array import array

import cython
from cpython.array cimport array as c_array, clone
from libc.stdint cimport INT32_MIN, INT32_MAX, int32_t, int64_t, uint64_t
from libcpp cimport bool as cppbool
from libcpp.vector cimport vector

cdef extern from "native_build.hpp":
    const char* dfo_compiler() noexcept
    const char* dfo_flags() noexcept

cdef extern from "class_search.hpp" namespace "dfo":
    cdef cppclass CancelFlag:
        void cancel() noexcept
        cppbool has_incumbent() noexcept
    cdef cppclass Trait:
        int id, side, cost, family
        cppbool required
        void block(int other) noexcept
    cdef cppclass Options:
        vector[Trait] traits
        vector[int] hp, races
        vector[vector[int]] attributes, skills
        int target, k
        uint64_t max_nodes, memory_bytes, magic_mask
        double wall_seconds
        cppbool max_intelligence, stop_after_top, require_magic
    cdef cppclass Candidate:
        int hp, race, count
        int attributes[8]
        int skills[12]
        int traits[14]
    cdef enum End:
        exhausted
        top_k
        node_limit
        time_limit
        memory_limit
        cancelled
    cdef cppclass Output:
        End end
        uint64_t nodes, pruned, leaves, work_bytes
        double first_seconds
        vector[Candidate] best
    Output search(const Options&, CancelFlag&) except + nogil
    int hp_points(int hp) noexcept nogil


def build_info():
    return {"compiler": dfo_compiler().decode("ascii"), "flags": dfo_flags().decode("ascii")}


cdef class CancelToken:
    """Thread-safe one-shot token; call cancel() while another thread searches."""
    cdef CancelFlag flag

    def cancel(self):
        self.flag.cancel()

    def has_incumbent(self):
        """Whether this token's search has retained its first feasible class."""
        return bool(self.flag.has_incumbent())


@cython.boundscheck(False)
@cython.wraparound(False)
cdef Py_ssize_t _batch(const int32_t[::1] hp, const int32_t[::1] positive,
                       const int32_t[::1] negative, int32_t[::1] points,
                       double[::1] multipliers) noexcept nogil:
    cdef Py_ssize_t i
    cdef int64_t value
    cdef int setting, adv, dis
    for i in range(hp.shape[0]):
        setting, adv, dis = hp[i], positive[i], negative[i]
        if setting < 4 or setting > 30 or adv < 0 or dis > 0:
            return i
        value = <int64_t>hp_points(setting) + adv + dis
        if value < INT32_MIN or value > INT32_MAX:
            return i
        points[i] = <int32_t>value
        multipliers[i] = 0.3 + 2.7 * (<double>value + 12.0) / 52.0
    return -1


def evaluate_batch(const int32_t[::1] hp not None, const int32_t[::1] advantages not None,
                   const int32_t[::1] disadvantages not None):
    cdef Py_ssize_t n = hp.shape[0]
    cdef Py_ssize_t invalid
    if n != advantages.shape[0] or n != disadvantages.shape[0]:
        raise ValueError("HP and adjustment arrays must have the same length")
    cdef c_array points = clone(array("i"), n, False)
    cdef c_array advancement = clone(array("d"), n, False)
    cdef int32_t[::1] point_view = points
    cdef double[::1] advancement_view = advancement
    with nogil:
        invalid = _batch(hp, advantages, disadvantages, point_view, advancement_view)
    if invalid >= 0:
        raise ValueError(f"invalid HP, signed adjustment or total at row {invalid}")
    return {"rows": n, "points": points, "advancement": advancement}


def _whole(value, low, high, field):
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f"{field} must be an integer from {low} to {high}")
    return value


def _domain(values, low, high, field):
    if not isinstance(values, (list, tuple, range)) or len(values) > high - low + 1:
        raise ValueError(f"invalid {field} domain")
    checked = [_whole(v, low, high, field) for v in values]
    if len(set(checked)) != len(checked):
        raise ValueError(f"duplicate value in {field} domain")
    return checked


cdef vector[Trait] _trait_table(rows):
    cdef vector[Trait] packed
    cdef Trait row
    cdef int j, other
    if not isinstance(rows, (list, tuple)) or len(rows) > 128:
        raise ValueError("at most 128 trait rows are supported")
    ids = set()
    conflicts = {}
    for item in rows:
        trait_id, side, cost, blocked, required, family = item
        row.id = _whole(trait_id, 0, 127, "trait ID")
        if trait_id in ids:
            raise ValueError("duplicate trait ID")
        ids.add(trait_id)
        row.side = _whole(side, 0, 1, "trait side")
        row.cost = _whole(cost, -14 if side else 0, 0 if side else 14, "trait cost")
        row.family = _whole(family, 0, 3, "last-writer family")
        if type(required) is not bool:
            raise ValueError("required must be boolean")
        row.required = required
        for other in _domain(blocked, 0, 127, "conflicting IDs"):
            conflicts.setdefault(trait_id, set()).add(other)
            conflicts.setdefault(other, set()).add(trait_id)
        packed.push_back(row)
    for j in range(packed.size()):
        for other in conflicts.get(packed[j].id, ()):
            packed[j].block(other)
    return packed


cdef vector[vector[int]] _domains(rows, int size, int low, int high, field):
    cdef vector[vector[int]] packed
    if not isinstance(rows, (list, tuple)) or len(rows) != size:
        raise ValueError(f"expected {size} {field} domains")
    for domain in rows:
        packed.push_back(_domain(domain, low, high, field))
    return packed


cdef dict _decode(Output& out):
    cdef size_t i
    cdef int j
    cdef Candidate c
    results = []
    for i in range(out.best.size()):
        c = out.best[i]
        results.append({
            "race": c.race, "hp": c.hp,
            "attributes": tuple([c.attributes[j] for j in range(8)]),
            "skills": tuple([c.skills[j] for j in range(12)]),
            "traits": tuple([c.traits[j] for j in range(c.count)]),
        })
    reasons = ("exhausted", "top_k", "node_limit", "time_limit", "memory_limit", "cancelled")
    return {
        "results": results, "termination": reasons[<int>out.end],
        "nodes": out.nodes, "pruned": out.pruned, "leaves": out.leaves,
        "first_feasible_seconds": out.first_seconds if out.leaves else None,
        "work_bytes": out.work_bytes,
    }


def search_classes(*, traits, hp_values, races, attributes, skills, target, top_k, max_nodes,
                   wall_seconds=0.0, memory_bytes=67108864, objective="examples",
                   stop_after_top=False, CancelToken cancel=None, require_magic=False, magic_skills=()):
    cdef Options options
    cdef Output result
    cdef int skill
    cdef CancelToken token = CancelToken() if cancel is None else cancel
    options.traits = _trait_table(traits)
    options.hp = _domain(hp_values, 4, 30, "HP")
    options.races = _domain(races, 1, 8, "race")
    options.attributes = _domains(attributes, 8, 10, 75, "attribute")
    options.skills = _domains(skills, 12, 0, 34, "skill")
    options.target = _whole(target, -12, 40, "target difficulty")
    options.k = _whole(top_k, 1, 10000, "top_k")
    options.max_nodes = _whole(max_nodes, 0, 2**63-1, "max_nodes")
    options.memory_bytes = _whole(memory_bytes, 0, 2**63-1, "memory_bytes")
    if type(wall_seconds) not in (int, float) or not math.isfinite(wall_seconds) or wall_seconds < 0:
        raise ValueError("wall_seconds must be finite and non-negative")
    if objective not in ("examples", "max_intelligence"):
        raise ValueError("unsupported class objective")
    if type(stop_after_top) is not bool or type(require_magic) is not bool:
        raise ValueError("search switches must be boolean")
    if stop_after_top and objective != "examples":
        raise ValueError("stop_after_top applies only to feasibility examples")
    options.wall_seconds = wall_seconds
    options.max_intelligence = objective == "max_intelligence"
    options.stop_after_top = stop_after_top
    options.require_magic = require_magic
    options.magic_mask = 0
    for skill in _domain(magic_skills, 0, 34, "magic skills"):
        options.magic_mask |= (<uint64_t>1) << skill
    with nogil:
        result = search(options, token.flag)
    return _decode(result)

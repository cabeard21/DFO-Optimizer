# distutils: language = c++
from libcpp.string cimport string
from libc.stdint cimport uint64_t
from libc.math cimport isfinite
include "_spell_common.pxi"
include "spellbook.pxi"

cdef extern from "spell_kernel.hpp" namespace "dfo_spell":
    cdef cppclass Gate "dfo_spell::Token":
        void cancel() noexcept nogil
        cpp_bool has_incumbent() noexcept nogil

cdef extern from "spellbook_loadouts.hpp" namespace "dfo_book":
    cdef cppclass PolicyFrontierPoint:
        double loss
        int64_t gold
        int sp
        vector[int] plans
    cdef cppclass SearchResult:
        vector[PolicyFrontierPoint] routes
        uint64_t nodes, pruned
        double first_incumbent_seconds
        string end
    cdef cppclass SearchLimits:
        int casts, sp
        int64_t gold
        uint64_t max_nodes, memory_bytes
        double wall_seconds
    SearchResult select_policy(const Context&,const vector[Bundle]&,const vector[int]&,
                          const vector[int]&,const SearchLimits&,Gate&) except + nogil

cdef class CancelToken:
    cdef Gate active
    def cancel(self):
        self.active.cancel()
    def has_incumbent(self):
        return self.active.has_incumbent()

cdef dict unpack(SpellScore p, object available):
    return {"gold": p.gold, "cost_sp": p.cost_sp, "purchase_gold": p.purchase_gold,
            "expected_damage": p.expected_damage, "expected_health_loss": p.expected_health_loss,
            "kill_probability": p.kill_probability, "dps": p.dps, "affordable": p.cost_sp <= available,
            "damage_per_sp": p.expected_health_loss / p.cost_sp if p.cost_sp else None}

def evaluate_many(dict context, spells):
    cdef Context c = prepare_context(context)
    cdef vector[Bundle] possibilities
    cdef vector[SpellScore] scored
    cdef size_t k
    for each in spells:
        possibilities.push_back(prepare_bundle(each))
    with nogil:
        for k in range(possibilities.size()):
            scored.push_back(score_bundle(c,possibilities[k]))
    return [unpack(scored[k], c.available_sp) for k in range(scored.size())]

def search_book(dict context, paths, desired, *, int casts, gold, max_nodes, wall_seconds,
                memory_bytes, CancelToken token=None):
    cdef Context c = prepare_context(context)
    cdef vector[Bundle] actual
    cdef vector[int] threshold, sequence
    cdef SearchLimits v
    cdef SearchResult result
    cdef size_t k
    if token is None:
        token = CancelToken()
    v.casts = _spell_int(casts, "cast horizon", 1, 64)
    if type(gold) is not int or not 0 <= gold <= 2**53-1:
        raise ValueError("gold must be a nonnegative safe integer")
    v.gold = gold
    v.sp = c.available_sp
    if not 0 <= max_nodes <= 2**63-1 or not 0 < memory_bytes <= 2**63-1:
        raise ValueError("Invalid range for search budgets")
    v.max_nodes, v.memory_bytes = max_nodes, memory_bytes
    if not isfinite(wall_seconds) or wall_seconds < 0:
        raise ValueError("Invalid wall_seconds")
    v.wall_seconds = wall_seconds
    if len(paths)>3000:
        raise ValueError("Provide at most 3000 dated spell offers")
    for record, route in paths:
        actual.push_back(prepare_bundle(record))
        threshold.push_back(_spell_int(route,"quote route", -1, 1))
    for each in desired:
        sequence.push_back(_spell_int(each,"policy event index",0,len(paths)-1))
    if sequence.size() != 0 and sequence.size() != casts:
        raise ValueError("The requested sequence and horizon disagree")
    with nogil:
        result = select_policy(c,actual,threshold,sequence,v,token.active)
    policies = [{"expected_damage": result.routes[k].loss, "gold_spent": result.routes[k].gold,
                 "sp_spent": result.routes[k].sp, "paid_casts": list(result.routes[k].plans)}
                for k in range(result.routes.size())]
    return {"termination": result.end.decode(), "policies": policies,
            "nodes": result.nodes, "pruned": result.pruned, "first_seconds": result.first_incumbent_seconds}

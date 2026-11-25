# cython: language_level=3
"""Native single-effect direct spell evaluation and finite-domain search."""
import math

from libc.stdint cimport uint64_t
from libcpp.vector cimport vector

include "_spell_common.pxi"

cdef extern from "spell_kernel.hpp" namespace "dfo_spell":
    cdef cppclass Token:
        void cancel() noexcept
        cpp_bool has_incumbent() noexcept
        cpp_bool is_cancelled() noexcept nogil
    cdef enum Objective:
        pareto
        dps
        efficiency
    cdef enum End:
        exhausted
        node_limit
        time_limit
        memory_limit
        cancelled
    cdef cppclass Limits:
        uint64_t max_nodes, memory_bytes
        double wall_seconds
        int top_k
        Objective objective
    cdef cppclass Choice:
        Recipe recipe
        uint64_t ties
    cdef cppclass Result:
        End end
        uint64_t nodes, leaves, pruned, work_bytes
        double first_seconds
        vector[Choice] best
    Result find "dfo_spell::search"(const Context&,const vector[vector[int]]&,const Limits&,Token&) except + nogil
    cdef cppclass Bench:
        uint64_t rows, checksum
        double seconds
    Bench bench "dfo_spell::benchmark"(const Context&,const vector[Recipe]&,int) noexcept nogil


cdef class CancelToken:
    cdef Token flag
    def cancel(self):
        self.flag.cancel()

    def has_incumbent(self):
        return bool(self.flag.has_incumbent())


def evaluate(dict context, recipe):
    cdef Context c=prepare_context(context)
    cdef Recipe r=prepare_recipe(recipe)
    cdef Score s
    with nogil:
        s=evaluate_direct(c,r)
    return unpack_score(s)


cdef vector[Recipe] _recipes(object recipes) except *:
    cdef vector[Recipe] rows
    for row in recipes:
        rows.push_back(prepare_recipe(row))
    return rows


def evaluate_batch(dict context, recipes):
    cdef Context c=prepare_context(context)
    cdef vector[Recipe] rows=_recipes(recipes)
    cdef vector[Score] scores
    cdef size_t i
    scores.resize(rows.size())
    with nogil:
        for i in range(rows.size()):
            scores[i]=evaluate_direct(c,rows[i])
    return [unpack_score(scores[i]) for i in range(rows.size())]


def evaluate_contexts(contexts, recipe, CancelToken token=None):
    """Evaluate one fixed spell across a bounded, ordered sensitivity series."""
    cdef vector[Context] rows
    cdef vector[Score] scores
    cdef Recipe spell=prepare_recipe(recipe)
    cdef size_t i
    if not 1 <= len(contexts) <= 64:
        raise ValueError("A spell curve needs 1 to 64 points")
    for context in contexts:
        rows.push_back(prepare_context(context))
    scores.reserve(rows.size())
    if token is None:
        token=CancelToken()
    with nogil:
        for i in range(rows.size()):
            if token.flag.is_cancelled():
                break
            scores.push_back(evaluate_direct(rows[i],spell))
    return [unpack_score(scores[i]) for i in range(scores.size())]


def benchmark_rows(dict context, recipes, repeats):
    cdef Context c=prepare_context(context)
    cdef vector[Recipe] rows=_recipes(recipes)
    cdef int repeat=_spell_int(repeats,"repeats",1,100000000)
    cdef Bench result
    if rows.empty():
        raise ValueError("benchmark requires spell recipes")
    with nogil:
        result=bench(c,rows,repeat)
    return {"rows":result.rows,"seconds":result.seconds,"checksum":result.checksum}


cdef vector[vector[int]] _domains(object domains) except *:
    cdef vector[vector[int]] d
    cdef vector[int] values
    cdef int i, item
    if len(domains)!=7:
        raise ValueError("seven spell domains are required")
    bounds=((0,4),(1,4),(1,100),(1,100),(1,100),(1,100),(1,20))
    for i in range(7):
        values.clear()
        for value in domains[i]:
            item=_spell_int(value,"domain",bounds[i][0],bounds[i][1])
            if not values.empty() and item<=values.back():
                raise ValueError("each spell domain must be sorted and unique")
            values.push_back(item)
        if values.empty():
            raise ValueError("spell domains must be non-empty")
        d.push_back(values)
    return d


def search(dict context, domains, *, objective="pareto", top_k=10, max_nodes=0,
           wall_seconds=0.0, memory_bytes=67108864, CancelToken token=None):
    cdef Context c=prepare_context(context)
    cdef vector[vector[int]] d=_domains(domains)
    cdef Limits limits
    cdef Result out
    if objective not in ("pareto","dps","damage_per_sp"):
        raise ValueError("unknown spell objective")
    limits.objective=pareto if objective=="pareto" else dps if objective=="dps" else efficiency
    limits.top_k=_spell_int(top_k,"top_k",1,1000000)
    for value in (max_nodes,memory_bytes):
        if type(value) is not int or not 0<=value<2**64:
            raise ValueError("node and memory limits must be nonnegative integers below 2^64")
    if type(wall_seconds) not in (int,float) or not math.isfinite(wall_seconds) or wall_seconds<0:
        raise ValueError("wall_seconds must be finite and nonnegative")
    limits.max_nodes=max_nodes
    limits.memory_bytes=memory_bytes
    limits.wall_seconds=wall_seconds
    if token is None:
        token=CancelToken()
    with nogil:
        out=find(c,d,limits,token.flag)
    endings=("exhausted","node_limit","time_limit","memory_limit","cancelled")
    return {"end":endings[out.end],"nodes":out.nodes,"leaves":out.leaves,"pruned":out.pruned,
            "work_bytes":out.work_bytes,"first_seconds":out.first_seconds,
            "rows":[recipe_tuple(out.best[i].recipe) for i in range(out.best.size())],
            "multiplicities":[out.best[i].ties for i in range(out.best.size())]}

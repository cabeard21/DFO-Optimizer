# cython: language_level=3
"""Validated conversion of a gear domain to one GIL-free native call."""
from libc.stdint cimport uint32_t, uint64_t
from libcpp.vector cimport vector
from math import isfinite
include "_spell_common.pxi"
include "_firmament_projection.pxi"

cdef extern from "gear_search.hpp" namespace "dfo_gear":
    cdef cppclass Cancel:
        void cancel() noexcept
        cpp_bool has_incumbent() noexcept
    cdef cppclass Option:
        int mods[8]
        int legendary, worn
        cpp_bool owned
        vector[uint64_t] price
    cdef cppclass Place:
        int item
        uint32_t mask
    cdef cppclass Slot:
        int id, lock, current, preferred
        vector[Place] entries
    cdef cppclass Config:
        vector[Option] items
        vector[Slot] slots
        vector[vector[int]] axes
        vector[uint64_t] budget
        uint64_t max_nodes, memory_bytes, per_state
        double wall_seconds
        uint32_t empty_mask
        int intelligence, quarters, bonus, post_sp, current_int
        cpp_bool uncertain_worn
        cpp_bool firmament_enabled
        Channels firmament
        Projection projection
    cdef cppclass SpellPoint:
        uint64_t loss, outcomes
        int cost, rate_200
        int setting(int) noexcept
    cdef cppclass Point:
        SpellPoint spell
        int changes, pieces
        int slot(int) noexcept
    cdef cppclass Report:
        vector[Point] points
        uint64_t nodes, pruned, leaves, evaluations, hits, misses, work_bytes, product
        double first_seconds
        cpp_bool sampled
        uint64_t uncertain_sp
        int end
    Report search(const Config&,const Context&,Cancel&) except + nogil

cdef class CancelToken:
    cdef Cancel flag
    def cancel(self):
        self.flag.cancel()
    def has_incumbent(self):
        return bool(self.flag.has_incumbent())

def _bounded(value, label, lo, hi):
    if type(value) is not int or not lo <= value <= hi:
        raise ValueError(f"invalid {label}")
    return value

cdef vector[Option] _items(object rows, int currencies):
    cdef vector[Option] items
    cdef Option opt
    cdef int i
    for mods, price, legendary, worn, owned in rows:
        if len(mods)!=8 or len(price)!=currencies or type(owned) is not bool:
            raise ValueError("invalid packed equipment option")
        for i in range(8):
            opt.mods[i]=_bounded(mods[i],"equipment modifier",0,1000)
        opt.price=[_bounded(v,"currency",0,(1<<53)-1) for v in price]
        opt.legendary=_bounded(legendary,"legendary group",-1,len(rows))
        opt.worn=_bounded(worn,"worn slot",-1,26)
        opt.owned=owned
        items.push_back(opt)
    return items

cdef vector[Slot] _slots(object domains, int n):
    cdef vector[Slot] result
    cdef Slot s
    cdef Place p
    if len(domains)!=27:
        raise ValueError("expected all 27 equipment slots")
    for i,(lock,current,preferred,places) in enumerate(domains):
        s.id=i
        s.lock=_bounded(lock,"slot lock",-2,n)
        s.current=_bounded(current,"current item",-1,n)
        s.preferred=_bounded(preferred,"preferred slot",-1,26)
        s.entries.clear()
        for idx,mask in places:
            p.item=_bounded(idx,"physical item",0,n-1)
            p.mask=_bounded(mask,"occupancy",1,(1<<27)-1)
            if not mask & (1<<i):
                raise ValueError("placement omits its own slot")
            s.entries.push_back(p)
        result.push_back(s)
    return result

def traverse(context, axes, items, slots, budget, *, max_nodes, memory_bytes,
             wall_seconds, per_state, CancelToken cancel=None, empty_mask=0,
             capacity=(-1,0,-1,-1,0,False), firmament=None):
    cdef Context ctx=prepare_context(context)
    cdef Config cfg
    cdef Report out
    cdef Point p
    cdef CancelToken token=CancelToken() if cancel is None else cancel
    if len(axes)!=7:
        raise ValueError("expected seven spell axes")
    for axis,lo,hi in zip(axes,(0,1,1,1,1,1,1),(4,4,100,100,100,100,20)):
        if len(axis)>hi-lo+1 or tuple(sorted(set(axis)))!=tuple(axis):
            raise ValueError("spell axis must be sorted and unique")
        cfg.axes.push_back([_bounded(v,"spell setting",lo,hi) for v in axis])
    cfg.budget=[_bounded(v,"budget",0,(1<<53)-1) for v in budget]
    cfg.items=_items(items,len(budget))
    cfg.slots=_slots(slots,len(items))
    cfg.max_nodes=_bounded(max_nodes,"max_nodes",0,(1<<63)-1)
    cfg.memory_bytes=_bounded(memory_bytes,"memory_bytes",1,(1<<63)-1)
    cfg.per_state=_bounded(per_state,"per_state",0,10000000)
    if type(wall_seconds) not in (int,float) or not isfinite(wall_seconds) or wall_seconds<0:
        raise ValueError("invalid wall_seconds")
    cfg.wall_seconds=wall_seconds
    intel,q,flat,hypothesis,worn_int,uncertain=capacity
    cfg.empty_mask=_bounded(empty_mask,"empty occupancy",0,(1<<27)-1)
    cfg.intelligence=_bounded(intel,"base intelligence",-1,100)
    cfg.quarters=_bounded(q,"magery multiplier",0,12)
    cfg.bonus=_bounded(flat,"capacity bonus",-1,1<<30)
    cfg.post_sp=_bounded(hypothesis,"post-swap SP",-1,1<<30)
    cfg.current_int=_bounded(worn_int,"worn Intelligence",0,27000)
    if type(uncertain) is not bool:
        raise ValueError("invalid capacity evidence")
    cfg.uncertain_worn=uncertain
    cfg.firmament_enabled=firmament is not None
    if cfg.firmament_enabled:
        projection, gains, prices=firmament
        cfg.projection=pack_projection(projection)
        cfg.firmament=pack_channels(gains, prices)
    with nogil:
        out=search(cfg,ctx,token.flag)
    rows=[]
    for p in out.points:
        rows.append({"slots":tuple([p.slot(i) for i in range(27)]),
                     "recipe":tuple([p.spell.setting(i) for i in range(7)]),
                     "health_loss_sum":p.spell.loss,"outcomes":p.spell.outcomes,
                     "cost_sp":p.spell.cost,"rate_200":p.spell.rate_200,
                     "changed_slots":p.changes})
    return {"results":rows,"termination":("exhausted","node_limit","time_limit","memory_limit","cancelled")[out.end],
            "nodes":out.nodes,"pruned":out.pruned,"leaves":out.leaves,"evaluations":out.evaluations,
            "cache_hits":out.hits,"cache_misses":out.misses,"work_bytes":out.work_bytes,
            "first_feasible_seconds":out.first_seconds if out.first_seconds>=0 else None,
            "uncertain_sp_recipes":out.uncertain_sp,
            "spell_grid_cardinality":out.product,"sampled_spells":bool(out.sampled)}

"""Pack a frozen Firmament graph and run one GIL-free search."""
from libc.stdint cimport uint64_t
from libcpp.vector cimport vector
from math import isfinite

include "_spell_common.pxi"
include "_firmament_projection.pxi"

cdef extern from "spell_kernel.hpp" namespace "dfo_spell":
    cdef cppclass Token:
        void cancel() noexcept
        cpp_bool has_incumbent() noexcept

cdef extern from "firmament_search.hpp" namespace "dfo_firmament":
    cdef cppclass Node:
        cpp_bool start, life, keystone
        vector[int] neighbors
        Channels stats
    cdef cppclass Options:
        vector[Node] graph
        int start, stars, craft
        vector[int] held
        Projection projection
        uint64_t max_nodes, memory_bytes
        double wall_seconds
    cdef cppclass Point:
        int start, cost, available, rate_200
        int64_t loss, outcomes
        vector[int] keys, additions
    cdef cppclass Report:
        Point baseline
        vector[Point] candidates
        int end
        uint64_t nodes, work_bytes
    Report search(const Options&, const Context&, const Recipe&, Token&) except + nogil


cdef class CancelToken:
    cdef Token flag

    def cancel(self):
        self.flag.cancel()

    def has_incumbent(self):
        return bool(self.flag.has_incumbent())


cdef dict unpack(const Point& point):
    return {"start": point.start, "keys": point.keys, "additions": point.additions,
            "cost_sp": point.cost, "available_sp": point.available, "rate_200": point.rate_200,
            "health_loss_sum": point.loss, "outcomes": point.outcomes}


cdef uint64_t _limit(object value, str label, int minimum) except? 0:
    if type(value) is not int or not minimum <= value <= (1 << 63) - 1:
        raise ValueError(f"Invalid Firmament {label}")
    return value


cdef void pack_graph(Options& cfg, object nodes) except *:
    cdef Node node
    cdef int size = len(nodes)
    if not 1 <= size <= 1024:
        raise ValueError("Firmament graph size must be in [1, 1024]")
    for index, (start, life, keystone, neighbors, gains, prices) in enumerate(nodes):
        if any(type(flag) is not bool for flag in (start, life, keystone)) or start and (life or keystone):
            raise ValueError("Invalid Firmament node flags")
        if len(neighbors) > size or len(set(neighbors)) != len(neighbors) or index in neighbors:
            raise ValueError("Invalid Firmament neighbors")
        node.start, node.life, node.keystone = start, life, keystone
        node.neighbors = [_spell_int(n, "Firmament node", 0, size - 1) for n in neighbors]
        node.stats = pack_channels(gains, prices)
        cfg.graph.push_back(node)


def _validate_branches(nodes, starting_sign, held, stars, craft):
    if starting_sign < 0:
        if held:
            raise ValueError("Firmament nodes require a starting sign")
        return
    if not nodes[starting_sign][0] or len(set(held)) != len(held) or any(nodes[i][0] for i in held):
        raise ValueError("Invalid held Firmament tree")
    connected = {starting_sign}
    selected = set(held)
    pending = [starting_sign]
    while pending:
        current = pending.pop()
        if nodes[current][2]:
            continue
        for node in nodes[current][3]:
            if node in selected and node not in connected:
                connected.add(node)
                pending.append(node)
    combat = sum(not nodes[i][1] for i in held)
    if not selected <= connected or combat > stars or len(held) > stars + craft:
        raise ValueError("Held Firmament tree is disconnected or out of budget")


def traverse(context, recipe, nodes, starting_sign, held, stars, craft, projection, *,
             max_nodes, wall_seconds, memory_bytes, CancelToken cancel=None):
    cdef Options cfg
    cdef Context ctx = prepare_context(context)
    cdef Recipe spell = prepare_recipe(recipe)
    cdef Report result
    cdef CancelToken token = CancelToken() if cancel is None else cancel
    pack_graph(cfg, nodes)
    cfg.start = _spell_int(starting_sign, "Firmament start", -1, len(nodes) - 1)
    cfg.held = [_spell_int(i, "held Firmament node", 0, len(nodes) - 1) for i in held]
    cfg.stars = _spell_int(stars, "Firmament Stars", 0, 98)
    cfg.craft = _spell_int(craft, "Firmament Craft points", 0, 125)
    _validate_branches(nodes, cfg.start, cfg.held, cfg.stars, cfg.craft)
    cfg.projection = pack_projection(projection)
    cfg.max_nodes = _limit(max_nodes, "node limit", 0)
    cfg.memory_bytes = _limit(memory_bytes, "memory budget", 1)
    if type(wall_seconds) not in (int, float) or not isfinite(wall_seconds) or wall_seconds < 0:
        raise ValueError("Invalid Firmament wall limit")
    cfg.wall_seconds = wall_seconds
    with nogil:
        result = search(cfg, ctx, spell, token.flag)
    return {"baseline": unpack(result.baseline), "candidates": [unpack(p) for p in result.candidates],
            "termination": ("exhausted", "node_limit", "time_limit", "memory_limit", "cancelled")[result.end],
            "nodes": result.nodes, "work_bytes": result.work_bytes}

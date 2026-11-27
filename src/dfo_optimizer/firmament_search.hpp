#pragma once

#include "firmament_projection.hpp"

#include <bitset>
#include <queue>
#include <unordered_set>

namespace dfo_firmament {

using dfo_spell::u64;
using dfo_spell::i64;
using dfo_spell::Clock;
using dfo_spell::Token;

constexpr int max_nodes_in_graph = 1024;
using Mask = std::bitset<max_nodes_in_graph>;

struct Node {
    bool start{}, life{}, keystone{};
    std::vector<int> neighbors;
    Channels stats;
};

struct Options {
    std::vector<Node> graph;
    int start = -1, stars{}, craft{};
    std::vector<int> held;
    Projection projection;
    u64 max_nodes{}, memory_bytes{};
    double wall_seconds{};
};

struct Point {
    int start = -1, cost{}, available{}, rate_200{};
    i64 loss{}, outcomes{};
    std::vector<int> keys, additions;
};

struct Report {
    Point baseline;
    std::vector<Point> candidates;
    int end = dfo_spell::exhausted;
    u64 nodes{}, work_bytes{};
};

struct State {
    Mask held;
    Channels totals;
    int start = -1, added = -1, combat{}, life{};
    size_t parent = std::numeric_limits<size_t>::max();
    int cost{}, available{}, rate_200{};
    i64 loss{}, outcomes{};
};

inline i64 speed_score(const State& state) noexcept { return state.loss * state.rate_200; }

inline int efficiency_order(const State& a, const State& b) noexcept {
    const i64 left = (a.cost ? a.loss : 0) * std::max(1, b.cost);
    const i64 right = (b.cost ? b.loss : 0) * std::max(1, a.cost);
    return (left > right) - (left < right);
}

inline bool tie_winner(const State& a, const State& b) noexcept {
    if (a.combat + a.life != b.combat + b.life) return a.combat + a.life < b.combat + b.life;
    if (a.start != b.start) return a.start < b.start;
    // Equal cardinality: presence of the earliest differing key is lexicographically first.
    for (size_t bit = 0; bit < a.held.size(); ++bit)
        if (a.held[bit] != b.held[bit]) return a.held[bit];
    return false;
}

class Search {
    static constexpr u64 state_bytes = 4 * sizeof(State) + 512;
    const Options& options;
    const dfo_spell::Context& context;
    const dfo_spell::Recipe& recipe;
    Token& token;
    Clock::time_point started = Clock::now();
    Report report;
    std::vector<State> arena;
    std::unordered_set<Mask> visited;
    using Pending = std::tuple<i64, int, size_t>;
    std::priority_queue<Pending> pending;
    std::vector<size_t> frontier;

    bool interrupted() {
        if (token.is_cancelled()) report.end = dfo_spell::cancelled;
        else if (options.wall_seconds > 0 &&
                 std::chrono::duration<double>(Clock::now() - started).count() >= options.wall_seconds)
            report.end = dfo_spell::time_limit;
        return report.end != dfo_spell::exhausted;
    }

    void score(State& state) const {
        auto projected = project(context, state.totals, options.projection);
        projected.available_sp = maximum_sp(state.totals, options.projection, options.projection.worn_intelligence);
        const auto result = dfo_spell::evaluate(projected, recipe);
        state.cost = result.cost_sp;
        state.available = projected.available_sp;
        state.rate_200 = int(std::round(result.cast_rate * 200));
        state.loss = result.health_loss_sum;
        state.outcomes = result.outcomes;
    }

    static bool dominates(const State& a, const State& b) {
        const auto diff = speed_score(a) - speed_score(b);
        const int efficiency = efficiency_order(a, b);
        return diff >= 0 && efficiency >= 0 && (diff > 0 || efficiency > 0 || tie_winner(a, b));
    }

    void publish(size_t id) {
        const auto& here = arena[id];
        if (here.cost > here.available) return;
        for (const auto other : frontier) if (dominates(arena[other], here)) return;
        frontier.erase(std::remove_if(frontier.begin(), frontier.end(),
                       [&](size_t other) { return dominates(here, arena[other]); }), frontier.end());
        frontier.push_back(id);
        token.incumbent.store(true, std::memory_order_relaxed);
    }

    void enqueue(State state) {
        if (interrupted() || visited.count(state.held)) return;
        if (options.max_nodes && report.nodes >= options.max_nodes) {
            report.end = dfo_spell::node_limit;
            return;
        }
        if (state_bytes > options.memory_bytes || report.work_bytes > options.memory_bytes - state_bytes) {
            report.end = dfo_spell::memory_limit;
            return;
        }
        score(state);
        const auto id = arena.size();
        visited.insert(state.held);
        arena.push_back(state);
        ++report.nodes;
        report.work_bytes += state_bytes;
        publish(id);
        if (state.start >= 0) {
            // Preserve every legal candidate within the budget. Favor deeper connectors on equal damage.
            pending.emplace(speed_score(state), state.combat + state.life, id);
        }
    }

    Point point(const State& state) const {
        Point result;
        result.start = state.start;
        result.cost = state.cost;
        result.available = state.available;
        result.rate_200 = state.rate_200;
        result.loss = state.loss;
        result.outcomes = state.outcomes;
        for (size_t i = 0; i < options.graph.size(); ++i)
            if (int(i) != state.start && state.held[i]) result.keys.push_back(int(i));
        auto here = &state;
        while (here->added >= 0) {
            result.additions.push_back(here->added);
            if (here->parent == std::numeric_limits<size_t>::max()) break;
            here = &arena[here->parent];
        }
        std::reverse(result.additions.begin(), result.additions.end());
        return result;
    }

    void expand(size_t id) {
        const State state = arena[id];
        if (state.combat + state.life == options.stars + options.craft) return;
        Mask adjacent;
        for (size_t i = 0; i < options.graph.size(); ++i) {
            if (!state.held[i] || options.graph[i].keystone) continue;
            for (const int neighbor : options.graph[i].neighbors) adjacent.set(neighbor);
        }
        adjacent &= ~state.held;
        for (size_t i = 0; i < options.graph.size() && !interrupted(); ++i) {
            if (!adjacent[i] || options.graph[i].start) continue;
            auto child = state;
            if (options.graph[i].life) ++child.life;
            else ++child.combat;
            if (child.combat > options.stars || child.combat + child.life > options.stars + options.craft) continue;
            child.parent = id;
            child.added = int(i);
            child.held.set(i);
            child.totals.add(options.graph[i].stats);
            enqueue(child);
        }
    }

public:
    Search(const Options& options, const dfo_spell::Context& context,
           const dfo_spell::Recipe& recipe, Token& token)
        : options(options), context(context), recipe(recipe), token(token) {}

    Report run() {
        State baseline;
        baseline.start = options.start;
        if (options.start >= 0) {
            baseline.held.set(options.start);
            baseline.totals.add(options.graph[options.start].stats);
            for (const int id : options.held) {
                baseline.held.set(id);
                baseline.totals.add(options.graph[id].stats);
                if (options.graph[id].life) ++baseline.life;
                else ++baseline.combat;
            }
        }
        score(baseline);
        report.baseline = point(baseline);
        enqueue(baseline);
        if (options.start < 0) {
            for (size_t i = 0; i < options.graph.size() && !interrupted(); ++i) {
                if (!options.graph[i].start) continue;
                State start;
                start.start = start.added = int(i);
                start.held.set(i);
                start.totals.add(options.graph[i].stats);
                enqueue(start);
            }
        }
        while (!pending.empty() && !interrupted()) {
            const size_t id = std::get<2>(pending.top());
            pending.pop();
            expand(id);
        }
        std::sort(frontier.begin(), frontier.end(), [&](size_t a, size_t b) {
            return std::make_tuple(speed_score(arena[a]), a) > std::make_tuple(speed_score(arena[b]), b);
        });
        for (const size_t id : frontier) report.candidates.push_back(point(arena[id]));
        return std::move(report);
    }
};

inline Report search(const Options& options, const dfo_spell::Context& context,
                     const dfo_spell::Recipe& recipe, Token& token) {
    return Search(options, context, recipe, token).run();
}

}  // namespace dfo_firmament

#pragma once

#include <algorithm>
#include <array>
#include <atomic>
#include <bitset>
#include <chrono>
#include <cstdint>
#include <limits>
#include <vector>

namespace dfo {

// The wrapper enforces these pinned snapshot limits before releasing the GIL.
constexpr int side_slots = 7;
constexpr int max_trait_cost = 14;
constexpr int offset = side_slots * max_trait_cost;
using Costs = std::bitset<2 * offset + 1>;
using Clock = std::chrono::steady_clock;

struct CancelFlag {
    std::atomic<bool> value{false};
    std::atomic<bool> has_result{false};
    void cancel() noexcept { value.store(true, std::memory_order_relaxed); }
    bool has_incumbent() const noexcept { return has_result.load(std::memory_order_relaxed); }
};

struct Trait {
    int id, side, cost, family;
    bool required;
    uint64_t conflicts[2]{};
    void block(int other) noexcept { conflicts[other / 64] |= uint64_t(1) << (other % 64); }
};

struct Options {
    std::vector<Trait> traits;
    std::vector<int> hp, races;
    std::vector<std::vector<int>> attributes, skills;
    int target, k;
    uint64_t max_nodes, memory_bytes, magic_mask;
    double wall_seconds;
    bool max_intelligence, stop_after_top, require_magic;
};

struct Candidate {
    int hp{}, race{}, attributes[8]{}, skills[12]{}, traits[14]{}, count{};
    uint64_t ordinal{};
};

enum End { exhausted, top_k, node_limit, time_limit, memory_limit, cancelled };

struct Output {
    End end = exhausted;
    uint64_t nodes{}, pruned{}, leaves{}, work_bytes{};
    double first_seconds = -1;
    std::vector<Candidate> best;
};

inline int hp_points(int hp) noexcept {
    return hp < 8 ? 2 * (hp - 8) : hp - 8;
}

class Search {
    // For each suffix and each pair of available slot counts, keep all reachable
    // signed costs, relaxing conflicts. A missing sum proves no legal completion.
    using Suffix = std::array<std::array<Costs, side_slots + 1>, side_slots + 1>;
    const Options& o;
    CancelFlag& cancel;
    const Clock::time_point start = Clock::now();
    Output out;
    std::vector<Suffix> reachable;
    std::array<std::bitset<601>, 9> stat_sums{};
    Candidate current{};
    int family_at[14]{};

    double elapsed() const { return std::chrono::duration<double>(Clock::now() - start).count(); }

    bool step() {
        if (out.end != exhausted) return false;
        if (o.max_nodes && out.nodes >= o.max_nodes) out.end = node_limit;
        else if (cancel.value.load(std::memory_order_relaxed)) out.end = cancelled;
        else if (o.wall_seconds && !(out.nodes % 256) && elapsed() >= o.wall_seconds)
            out.end = time_limit;
        if (out.end != exhausted) return false;
        ++out.nodes;
        return true;
    }

    void build_reachability() {
        reachable.resize(o.traits.size() + 1);
        for (auto& pos : reachable.back()) for (auto& neg : pos) neg.set(offset);
        for (int i = int(o.traits.size()) - 1; i >= 0; --i) {
            const Trait& t = o.traits[i];
            const auto& next = reachable[i + 1];
            for (int a = 0; a <= side_slots; ++a) for (int d = 0; d <= side_slots; ++d) {
                auto& sums = reachable[i][a][d];
                if (!t.required) sums = next[a][d];
                if (t.side == 0 && a) sums |= next[a - 1][d] << t.cost;
                if (t.side == 1 && d) sums |= next[a][d - 1] >> (-t.cost);
            }
        }
        stat_sums[8].set(0);
        for (int i = 7; i >= 0; --i)
            for (int value : o.attributes[i]) stat_sums[i] |= stat_sums[i + 1] << value;
    }

    bool better(const Candidate& a, const Candidate& b) const {
        if (o.max_intelligence && a.attributes[1] != b.attributes[1])
            return a.attributes[1] > b.attributes[1];
        return a.ordinal < b.ordinal;
    }

    void keep() {
        if (!out.leaves) out.first_seconds = elapsed();
        current.ordinal = out.leaves++;
        auto cmp = [this](const Candidate& a, const Candidate& b){ return better(a, b); };
        if (int(out.best.size()) < o.k) {
            out.best.push_back(current);
            std::push_heap(out.best.begin(), out.best.end(), cmp);
        } else if (better(current, out.best.front())) {
            std::pop_heap(out.best.begin(), out.best.end(), cmp);
            out.best.back() = current;
            std::push_heap(out.best.begin(), out.best.end(), cmp);
        }
        if (out.leaves == 1) cancel.has_result.store(true, std::memory_order_relaxed);
        if (o.stop_after_top && int(out.best.size()) == o.k) out.end = top_k;
    }

    void assign_skills(int slot, uint64_t selected) {
        if (!step()) return;
        if (slot == 6 && o.require_magic && !(selected & o.magic_mask)) { ++out.pruned; return; }
        if (slot == 12) {
            for (int race : o.races) {
                if (!step()) break;
                current.race = race;
                keep();
            }
            return;
        }
        for (int skill : o.skills[slot]) {
            if (out.end != exhausted) break;
            const auto bit = uint64_t(1) << skill;
            if (bit & selected) { ++out.pruned; continue; }
            current.skills[slot] = skill;
            assign_skills(slot + 1, selected | bit);
        }
    }

    void allocate_stats(int slot, int remaining) {
        if (!step()) return;
        if (remaining < 0 || !stat_sums[slot][remaining]) { ++out.pruned; return; }
        if (slot == 8) { assign_skills(0, 0); return; }
        for (int value : o.attributes[slot]) {
            if (out.end != exhausted) break;
            current.attributes[slot] = value;
            allocate_stats(slot + 1, remaining - value);
        }
    }

    // parseCareerData overwrites the last value in three independent flag fields.
    // Swapping within the family enumerates each possible last writer exactly once.
    void last_winners(int family) {
        if (!step()) return;
        if (family == 4) { allocate_stats(0, 400); return; }
        int last = -1;
        for (int i = 0; i < current.count; ++i)
            if (family_at[i] == family) last = i;
        if (last < 0) { last_winners(family + 1); return; }
        for (int i = 0; i <= last && out.end == exhausted; ++i) {
            if (family_at[i] != family) continue;
            std::swap(current.traits[i], current.traits[last]);
            last_winners(family + 1);
            std::swap(current.traits[i], current.traits[last]);
        }
    }

    void choose(int i, int delta, int a, int d, uint64_t lo, uint64_t hi) {
        if (!step()) return;
        if (delta < -offset || delta > offset || !reachable[i][a][d][offset + delta]) {
            ++out.pruned;
            return;
        }
        if (i == int(o.traits.size())) { last_winners(1); return; }
        const auto& t = o.traits[i];
        // Prefer fewer optional advantages; include disadvantages first to fund locks early.
        if (!t.required && !t.side) choose(i + 1, delta, a, d, lo, hi);
        if (out.end != exhausted) return;
        if ((t.side ? d : a) && !(t.conflicts[0] & lo) && !(t.conflicts[1] & hi)) {
            int n = current.count++;
            current.traits[n] = t.id;
            family_at[n] = t.family;
            uint64_t bit = uint64_t(1) << (t.id % 64);
            choose(i + 1, delta - t.cost, a - int(!t.side), d - t.side,
                   lo | (t.id < 64 ? bit : 0), hi | (t.id >= 64 ? bit : 0));
            --current.count;
        } else ++out.pruned;
        if (!t.required && t.side && out.end == exhausted) choose(i + 1, delta, a, d, lo, hi);
    }

public:
    Search(const Options& options, CancelFlag& flag) : o(options), cancel(flag) {}

    Output run() {
        // Input tables are already validated. Budget bounds solver-owned scratch,
        // retained candidates and the compact snapshot; RSS is benchmarked separately.
        out.work_bytes = sizeof(Search) + sizeof(Options) + sizeof(Suffix) * (1 + o.traits.size())
                       + sizeof(Candidate) * o.k + sizeof(Trait) * o.traits.capacity()
                       + sizeof(int) * (o.races.capacity() + o.hp.capacity())
                       + sizeof(std::vector<int>) * (o.skills.capacity() + o.attributes.capacity());
        for (const auto& row : o.skills) out.work_bytes += row.capacity() * sizeof(int);
        for (const auto& row : o.attributes) out.work_bytes += row.capacity() * sizeof(int);
        if (out.work_bytes > o.memory_bytes) { out.end = memory_limit; return std::move(out); }
        out.best.reserve(o.k);
        build_reachability();
        for (int hp : o.hp) {
            if (out.end != exhausted) break;
            current.hp = hp;
            choose(0, o.target - hp_points(hp), side_slots, side_slots, 0, 0);
        }
        std::sort(out.best.begin(), out.best.end(),
                  [this](const Candidate& a, const Candidate& b){ return better(a, b); });
        return std::move(out);
    }
};

inline Output search(const Options& options, CancelFlag& flag) { return Search(options, flag).run(); }
} // namespace dfo

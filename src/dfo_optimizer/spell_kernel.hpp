#pragma once

#include <algorithm>
#include <array>
#include <atomic>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <limits>
#include <numeric>
#include <tuple>
#include <vector>

namespace dfo_spell {

using Clock = std::chrono::steady_clock;
using i64 = std::int64_t;
using u64 = std::uint64_t;

// Frozen inputs for an online-snapshot player casting at an ordinary PvE foe.
// The field "climb" is effective earned Destruction, before equipment bonuses.
struct Context {
    int level = 1, live_skill = 0, climb = 0, speed = 50, available_sp = 0;
    int target_hp = 1, willpower = 50, power_pct = 0, pierce = 0, cast_speed_pct = 0, focus_pct = 0;
    int resistant = 0, immune = 0, low_tolerance = 0, critical_weakness = 0;
    int resist_mods[5]{}, elemental_resists[5]{};
    double price_factor = 1.0;
    bool free_cast = false;
};

struct Recipe {
    int element, range_type, base_low, base_high, level_low, level_high, per_level;
    bool operator<(const Recipe &b) const noexcept {
        return std::tie(element, range_type, base_low, base_high, level_low, level_high, per_level) <
               std::tie(b.element, b.range_type, b.base_low, b.base_high, b.level_low, b.level_high,
                        b.per_level);
    }
};

struct Score {
    int gold{}, purchase_gold{}, effect_sp{}, cost_sp{}, save_chance{};
    bool affordable{}, immune{};
    i64 damage_sum{}, health_loss_sum{}, kill_sum{}, outcomes{};
    double expected_damage{}, expected_health_loss{}, kill_probability{}, damage_per_sp{}, dps{};
    double cast_rate{}, release_seconds{}, recovery_seconds{}, potency{};
};

struct Price {
    int gold, effect_sp, cost;
};

inline Price price(const Context &c, const Recipe &r) noexcept {
    // spellcost.js effectCost takes the truncated midpoints before the
    // component divides the level magnitude by the setting's level divisor.
    const int component =
        20 * ((r.base_low + r.base_high) / 2) + 28 * (((r.level_low + r.level_high) / 2) / r.per_level);
    const i64 skill = c.live_skill;
    const int sp = int(skill > 100 ? i64(component) * 1000 / (400 * skill) : component * (110 - skill) / 400);
    const int twice_range_multiplier = r.range_type + 1;
    const int floored = std::max(5, sp * twice_range_multiplier / 2);
    const int discount = std::clamp(c.focus_pct, 0, 30);
    const int paid = c.free_cast ? 0 : int((i64(floored) * (100 - discount) + 50) / 100);
    return {component * twice_range_multiplier / 2, sp, paid};
}

struct Landing {
    int save{}, ward_passes{}, hp{};
    double potency{};
};

inline Landing landing(const Context &c, int element) noexcept {
    // Career precedence is significant for conflicting flags. The immunity
    // threshold is checked after equipment resistance, before willpower/pierce.
    constexpr int flags[] = {8, 16, 4, 32, 2};
    const int flag = flags[element];
    int saving = 50 + c.resist_mods[element];
    if (c.resistant & flag)
        saving += 25;
    else if (c.immune & flag)
        saving += 50;
    else if (c.low_tolerance & flag)
        saving -= 25;
    else if (c.critical_weakness & flag)
        saving -= 50;
    saving = saving >= 100 ? 100 : std::clamp(saving + c.willpower / 10 - std::max(0, c.pierce), 5, 95);
    const double school = 1.0 + std::max(0, c.climb - 100) * 0.01;
    return {saving, 100 - std::clamp(c.elemental_resists[element], 0, 100), c.target_hp,
            school * std::max(0.5, 1.0 + c.power_pct / 100.0)};
}

inline double rate(const Context &c) noexcept {
    return std::clamp(1.0 + (std::clamp(c.speed, 0, 100) - 50) / 200.0 + c.cast_speed_pct / 100.0, 0.5,
                      2.0);
}

struct Totals {
    i64 damage{}, loss{}, kills{};
    void add(int n, int hp, int rolls) noexcept {
        damage += i64(n) * rolls;
        loss += i64(std::min(n, hp)) * rolls;
        if (n >= hp) kills += rolls;
    }
    Totals &operator+=(const Totals &b) noexcept {
        damage += b.damage;
        loss += b.loss;
        kills += b.kills;
        return *this;
    }
    void add_weighted(const Totals &b, int weight) noexcept {
        damage += b.damage * weight;
        loss += b.loss * weight;
        kills += b.kills * weight;
    }
};

inline int with_power(int saved, double potency) noexcept {
    if (!saved || potency == 1.0) return saved;
    // Math.round for bounded nonnegative JS Numbers. Adding 0.5 before
    // truncation would round a representable value just below a half up.
    const double scaled = saved * potency;
    const int whole = int(scaled);
    return std::max(1, whole + int(scaled - whole >= 0.5));
}

inline Totals outcomes_for(int raw, const Landing &target) noexcept {
    Totals t;
    if (target.save == 100 || !target.ward_passes) return t;
    // Roll equal to the saving chance also delivers 100%. Each of the
    // preceding 19 D100 faces has a distinct positive partial result.
    t.add(with_power(raw, target.potency), target.hp, 101 - target.save);
    for (int step = 1; step < std::min(20, target.save); ++step)
        t.add(with_power(raw * (100 - 5 * step) / 100, target.potency), target.hp, 1);
    return t;
}

inline int roll_pairs(const Recipe &r) noexcept {
    return (r.base_high - r.base_low + 1) * (r.level_high - r.level_low + 1);
}

inline Totals distribution(const Recipe &r, int q, const Landing &target) noexcept {
    Totals totals;
    if (target.save == 100 || !target.ward_passes) return totals;
    const int base_width = r.base_high - r.base_low, bonus_width = r.level_high - r.level_low;
    if (!q) {
        for (int base = r.base_low; base <= r.base_high; ++base)
            totals.add_weighted(outcomes_for(base, target), bonus_width + 1);
        return totals;
    }
    const int span = base_width + q * bonus_width + 1;
    if (span < roll_pairs(r)) {
        // Count the pairs realizing each raw magnitude. Each bonus fixes
        // exactly one base; both must fall in their inclusive intervals.
        const int first = r.base_low + q * r.level_low;
        for (int k = 0; k < span; ++k) {
            const int low = k > base_width ? (k - base_width + q - 1) / q : 0;
            const int high = std::min(bonus_width, k / q);
            if (low <= high) totals.add_weighted(outcomes_for(first + k, target), high - low + 1);
        }
        return totals;
    }
    for (int base = r.base_low; base <= r.base_high; ++base)
        for (int bonus = r.level_low; bonus <= r.level_high; ++bonus)
            totals += outcomes_for(base + q * bonus, target);
    return totals;
}

inline Score evaluate(const Context &c, const Recipe &r) noexcept {
    const auto p = price(c, r);
    const auto target = landing(c, r.element);
    const int q = c.level / r.per_level;
    const auto totals = distribution(r, q, target);
    Score s;
    s.gold = p.gold;
    s.effect_sp = p.effect_sp;
    s.cost_sp = p.cost;
    s.purchase_gold = std::max(1, int(std::round(p.gold * c.price_factor)));
    s.affordable = p.cost <= c.available_sp;
    s.save_chance = target.save;
    s.immune = target.save == 100;
    s.cast_rate = rate(c);
    s.release_seconds = 0.2 / s.cast_rate;
    s.recovery_seconds = 0.7 / s.cast_rate;
    s.potency = target.potency;
    s.outcomes = i64(roll_pairs(r)) * 10000;
    s.damage_sum = totals.damage * target.ward_passes;
    s.health_loss_sum = totals.loss * target.ward_passes;
    s.kill_sum = totals.kills * target.ward_passes;
    s.expected_damage = double(s.damage_sum) / s.outcomes;
    s.expected_health_loss = double(s.health_loss_sum) / s.outcomes;
    s.kill_probability = double(s.kill_sum) / s.outcomes;
    s.damage_per_sp = p.cost ? s.expected_health_loss / p.cost : 0;
    s.dps = s.expected_health_loss / s.recovery_seconds;
    return s;
}

struct Token {
    std::atomic_bool stopped{false}, incumbent{false};
    void cancel() noexcept { stopped.store(true, std::memory_order_relaxed); }
    bool has_incumbent() const noexcept { return incumbent.load(std::memory_order_relaxed); }
};

// Bounds are enforced by the Cython boundary and shared by native gear.
// A threshold grid records D100-weighted HP loss for each (base,bonus)
// point. A rectangle query exactly sums the full pair of uniform rolls.
struct Grid {
    int stride{};
    std::vector<i64> sums, by_raw;
    void build(const Landing &target, int q, int max_base, int max_bonus) {
        stride = max_bonus + 1;
        sums.assign((max_base + 1) * stride, 0);
        by_raw.resize(max_base + q * max_bonus + 1);
        for (int n = 1; n < int(by_raw.size()); ++n)
            by_raw[n] = outcomes_for(n, target).loss * target.ward_passes;
        for (int i = 1; i <= max_base; ++i) {
            i64 row = 0;
            for (int j = 1; j <= max_bonus; ++j) {
                row += by_raw[i + q * j];
                sums[i * stride + j] = sums[(i - 1) * stride + j] + row;
            }
        }
    }
    i64 sum(const Recipe &r) const noexcept {
        const int a = (r.base_low - 1) * stride, b = r.base_high * stride;
        return sums[b + r.level_high] - sums[a + r.level_high] - sums[b + r.level_low - 1] +
               sums[a + r.level_low - 1];
    }
};

// C++17/MSVC has no portable unsigned 128-bit multiply. Use a checked
// cross-product when possible, then compare continued fractions exactly.
inline int compare(u64 a, u64 b, u64 c, u64 d) noexcept {
    constexpr auto limit = std::numeric_limits<u64>::max();
    if (a <= limit / d && c <= limit / b) {
        const u64 l = a * d, r = c * b;
        return (l > r) - (l < r);
    }
    int sign = 1;
    for (;;) {
        const u64 l = a / b, r = c / d;
        if (l != r) return l > r ? sign : -sign;
        const u64 la = a % b, ra = c % d;
        if (!la || !ra) return sign * ((la > 0) - (ra > 0));
        a = b;
        b = la;
        c = d;
        d = ra;
        sign = -sign;
    }
}

enum Objective { pareto, dps, efficiency };
enum End { exhausted, node_limit, time_limit, memory_limit, cancelled };
struct Choice {
    Recipe recipe{};
    u64 loss{}, outcomes{}, ties{};
    int cost{};
};
struct Limits {
    u64 max_nodes = 0, memory_bytes = 67108864;
    double wall_seconds = 0.0;
    int top_k = 10;
    Objective objective = pareto;
};
struct Result {
    End end = exhausted;
    u64 nodes = 0, leaves = 0, pruned = 0, work_bytes = 0;
    double first_seconds = -1;
    std::vector<Choice> best;
};

inline int dmg_order(const Choice &a, const Choice &b) noexcept {
    return compare(a.loss, a.outcomes, b.loss, b.outcomes);
}
inline int efficiency_order(const Choice &a, const Choice &b) noexcept {
    return compare(a.loss, a.outcomes * a.cost, b.loss, b.outcomes * b.cost);
}
inline bool before(const Choice &a, const Choice &b, Objective mode) noexcept {
    const int cmp = mode == efficiency ? efficiency_order(a, b) : dmg_order(a, b);
    if (cmp) return cmp > 0;
    return a.recipe < b.recipe;
}

struct Pair {
    int low, high;
};
inline std::vector<Pair> pairs(const std::vector<int> &lo, const std::vector<int> &hi) {
    std::vector<Pair> result;
    size_t n = 0;
    for (int a : lo) n += hi.end() - std::lower_bound(hi.begin(), hi.end(), a);
    result.reserve(n);
    for (int a : lo)
        for (auto it = std::lower_bound(hi.begin(), hi.end(), a); it != hi.end(); ++it)
            result.push_back({a, *it});
    return result;
}

using Domains = std::vector<std::vector<int>>;

class Search {
    const Context &c;
    const Domains &domain;
    const Limits &limits;
    Token &token;
    Clock::time_point start = Clock::now();
    Result out;
    Grid grid;
    // The highest delivered damage at a fixed SP cost dominates every lower
    // one at that cost in both objectives. Merge costs only after traversal.
    std::vector<Choice> cost_winners;
    std::vector<Pair> bases, bonuses;

    double elapsed() const noexcept { return std::chrono::duration<double>(Clock::now() - start).count(); }
    bool stopped() {
        if (token.stopped.load(std::memory_order_relaxed))
            out.end = cancelled;
        else if (limits.wall_seconds && elapsed() >= limits.wall_seconds)
            out.end = time_limit;
        return out.end != exhausted;
    }
    void keep(const Choice &cand) {
        if (limits.objective == pareto) {
            auto &row = cost_winners[cand.cost];
            const int order = row.ties ? dmg_order(cand, row) : 1;
            if (order > 0)
                row = cand;
            else if (!order) {
                ++row.ties;
                if (cand.recipe < row.recipe) row.recipe = cand.recipe;
            }
            return;
        }
        auto cmp = [&](const Choice &a, const Choice &b) { return before(a, b, limits.objective); };
        if (int(out.best.size()) < limits.top_k) {
            out.best.push_back(cand);
            std::push_heap(out.best.begin(), out.best.end(), cmp);
        } else if (cmp(cand, out.best.front())) {
            std::pop_heap(out.best.begin(), out.best.end(), cmp);
            out.best.back() = cand;
            std::push_heap(out.best.begin(), out.best.end(), cmp);
        }
    }
    void visit(const Recipe &r, bool seed) {
        ++out.nodes;
        const int cost = price(c, r).cost;
        if (cost > c.available_sp || (!cost && limits.objective != dps)) {
            ++out.pruned;
            return;
        }
        ++out.leaves;
        const i64 loss = seed ? evaluate(c, r).health_loss_sum : grid.sum(r);
        keep({r, u64(loss), u64(roll_pairs(r)) * 10000, 1, cost});
        if (out.leaves == 1) {
            out.first_seconds = elapsed();
            token.incumbent.store(true, std::memory_order_relaxed);
        }
    }
    void frontier() {
        // Nonnegative damage: a higher-cost winner can dominate a cheaper
        // one only via higher damage. Walk in descending damage and keep
        // record efficiencies. Equal zero metrics have only one group.
        for (const auto &r : cost_winners)
            if (r.ties) out.best.push_back(r);
        std::sort(out.best.begin(), out.best.end(), [](const Choice &a, const Choice &b) {
            const int d = dmg_order(a, b);
            return d ? d > 0 : a.cost < b.cost;
        });
        size_t n = 0;
        for (const auto &r : out.best) {
            if (!n || efficiency_order(r, out.best[n - 1]) > 0)
                out.best[n++] = r;
            else if (!r.loss && !out.best[n - 1].loss) {
                auto &rep = out.best[n - 1];
                rep.ties += r.ties;
                if (r.recipe < rep.recipe) rep.recipe = r.recipe;
            }
        }
        out.best.resize(n);
    }
    Recipe recipe_at(u64 group, u64 rank) const noexcept {
        const auto &a = bases[rank / bonuses.size()];
        const auto &b = bonuses[rank % bonuses.size()];
        const int element = domain[0][group % domain[0].size()];
        group /= domain[0].size();
        const int range = domain[1][group % domain[1].size()];
        const int per = domain[6][group / domain[1].size()];
        return {element, range, a.low, a.high, b.low, b.high, per};
    }
    void traverse() {
        const u64 cells = u64(bases.size()) * bonuses.size();
        const u64 groups = domain[0].size() * domain[1].size() * domain[6].size();
        const u64 total = cells * groups;
        const u64 budget = limits.max_nodes ? std::min(total, limits.max_nodes) : total;
        auto quota = [&](u64 group) { return (group + 1) * budget / groups - group * budget / groups; };
        // Seed minimum, maximum and both cross-corners before scanning any
        // one element. This also gives wall-limited runs diverse incumbents.
        std::array<u64, 4> seeds{0, cells - 1, bonuses.size() - 1, cells - bonuses.size()};
        std::array<u64, 4> distinct{};
        int count = 0;
        for (auto s : seeds)
            if (std::find(distinct.begin(), distinct.begin() + count, s) == distinct.begin() + count)
                distinct[count++] = s;
        for (int j = 0; j < count; ++j)
            for (u64 g = 0; g < groups; ++g) {
                if (u64(j) >= quota(g)) continue;
                if (stopped()) return;
                visit(recipe_at(g, distinct[j]), true);
            }
        std::sort(distinct.begin(), distinct.begin() + count);
        int old_element = -1, old_q = -1;
        for (u64 g = 0; g < groups; ++g) {
            // Process range modes for one (element, divisor) together to
            // reuse its grid. Quotas/recipes retain the seed order above.
            const u64 per = g / (domain[1].size() * domain[0].size());
            const u64 elem = (g / domain[1].size()) % domain[0].size(), range = g % domain[1].size();
            const u64 group = elem + domain[0].size() * (range + per * domain[1].size());
            const u64 n = quota(group);
            if (n <= u64(count)) continue;
            if (stopped()) return;
            const int q = c.level / domain[6][per];
            if (domain[0][elem] != old_element || q != old_q) {
                old_element = domain[0][elem];
                old_q = q;
                grid.build(landing(c, old_element), q, domain[3].back(), domain[5].back());
            }
            const u64 rest = n - count, remaining = cells - count;
            for (u64 i = 0; i < rest; ++i) {
                if (!(out.nodes % 256) && stopped()) return;
                // A uniform stride over the unseeded ranks, identity in
                // exhaustive mode. Inflate the rank across the known holes.
                u64 rank = rest == 1 ? remaining / 2 : i * (remaining - 1) / (rest - 1);
                for (int j = 0; j < count; ++j)
                    if (distinct[j] <= rank) ++rank;
                visit(recipe_at(group, rank), false);
            }
        }
        if (budget < total) out.end = node_limit;
    }

  public:
    Search(const Context &ctx, const Domains &d, const Limits &l, Token &t)
        : c(ctx), domain(d), limits(l), token(t) {}
    Result run() {
        if (stopped()) return std::move(out);
        // Upper bound evaluated before any arena allocation. Includes both
        // candidate and finalist slots at the worst possible affordable cost.
        Recipe highest{0,
                       domain[1].back(),
                       domain[3].back(),
                       domain[3].back(),
                       domain[5].back(),
                       domain[5].back(),
                       domain[6].front()};
        const auto slots = limits.objective == pareto ? 1 + std::min(price(c, highest).cost, c.available_sp)
                                                      : limits.top_k;
        const size_t grid_cells = (domain[3].back() + 1) * (domain[5].back() + 1);
        const size_t raw_cells = domain[3].back() + (c.level / domain[6].front()) * domain[5].back() + 1;
        const size_t max_pairs = domain[2].size() * domain[3].size() + domain[4].size() * domain[5].size();
        out.work_bytes = sizeof(Search) + sizeof(i64) * (grid_cells + raw_cells) +
                         sizeof(Pair) * max_pairs +
                         sizeof(Choice) * slots * (limits.objective == pareto ? 2 : 1);
        if (out.work_bytes > limits.memory_bytes) {
            out.end = memory_limit;
            return std::move(out);
        }
        grid.sums.reserve(grid_cells);
        grid.by_raw.reserve(raw_cells);
        if (limits.objective == pareto) cost_winners.resize(slots);
        out.best.reserve(slots);
        bases = pairs(domain[2], domain[3]);
        bonuses = pairs(domain[4], domain[5]);
        if (!bases.empty() && !bonuses.empty()) traverse();
        if (limits.objective == pareto)
            frontier();
        else
            std::sort(out.best.begin(), out.best.end(),
                      [&](const Choice &a, const Choice &b) { return before(a, b, limits.objective); });
        return std::move(out);
    }
};

inline Result search(const Context &c, const Domains &d, const Limits &l, Token &t) {
    return Search(c, d, l, t).run();
}

struct Bench {
    u64 rows{}, checksum{};
    double seconds{};
};
inline Bench benchmark(const Context &c, const std::vector<Recipe> &recipes, int repeat) noexcept {
    const auto start = Clock::now();
    u64 checksum = 0;
    for (int i = 0; i < repeat; ++i)
        for (const auto &r : recipes) {
            const Score s = evaluate(c, r);
            checksum += u64(s.health_loss_sum) + u64(s.cost_sp);
        }
    return {u64(recipes.size()) * repeat, checksum,
            std::chrono::duration<double>(Clock::now() - start).count()};
}
} // namespace dfo_spell

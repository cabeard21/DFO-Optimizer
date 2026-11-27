#pragma once
#include "spell_kernel.hpp"
#include "firmament_projection.hpp"
#include <algorithm>
#include <array>
#include <atomic>
#include <chrono>
#include <cstdint>
#include <limits>
#include <map>
#include <stdexcept>
#include <vector>

namespace dfo_gear {
using Clock = std::chrono::steady_clock;
using Slots = std::array<int, 27>;
using Mods = std::array<int, 10>;
using RecipeKey = std::array<int, 7>;

struct Cancel {
    std::atomic<bool> stopped{false}, ready{false};
    void cancel() noexcept { stopped.store(true); }
    bool has_incumbent() const noexcept { return ready.load(); }
};
struct Option {
    int mods[8]{}, legendary = -1, worn = -1;
    bool owned = false;
    std::vector<uint64_t> price;
};
struct Place { int item = -1; uint32_t mask = 0; };
struct Slot {
    int id = 0, lock = -2, current = -1, preferred = -1;
    std::vector<Place> entries;
};
struct Config {
    std::vector<Option> items;
    std::vector<Slot> slots;
    std::vector<std::vector<int>> axes;
    std::vector<uint64_t> budget;
    uint64_t max_nodes = 0, memory_bytes = 0, per_state = 0;
    double wall_seconds = 0;
    uint32_t empty_mask = 0;
    int intelligence=-1, quarters=0, bonus=-1, post_sp=-1, current_int=0;
    bool uncertain_worn=false;
    bool firmament_enabled=false;
    dfo_firmament::Channels firmament{};
    dfo_firmament::Projection projection{};
};
struct SpellPoint {
    RecipeKey recipe{};
    uint64_t loss = 0, outcomes = 1;
    int cost = 1, rate_200 = 200;
    int setting(int i) const { return recipe.at(i); }
};
struct Point {
    SpellPoint spell;
    Slots slots{};
    int changes = 0, pieces = 0;
    int slot(int i) const { return slots.at(i); }
    int setting(int i) const { return spell.recipe.at(i); }
};
struct Report {
    std::vector<Point> points;
    int end = 0;  // exhaustion, nodes, wall, memory, cancel
    uint64_t nodes = 0, pruned = 0, leaves = 0, evaluations = 0, hits = 0, misses = 0;
    uint64_t work_bytes = 0, product = 1;
    bool sampled = false;
    uint64_t uncertain_sp = 0;
    double first_seconds = -1;
};

inline void fold(Mods& total, const Option& option, bool lines) {
    for (int i = 0; i < 8; ++i)
        if (lines || i == 6) total[i] += option.mods[i];
}

inline dfo_spell::Context apply(const dfo_spell::Context& base, const Mods& mod) {
    auto ctx = base;
    // The audited standalone slice has no statMaxMods. A supplied speed above
    // 100 already implies an external cap lift and is rejected at the boundary.
    ctx.speed = std::clamp(base.speed + mod[0], 0, 100);
    ctx.live_skill += mod[1] + mod[6];
    ctx.cast_speed_pct += std::min(30, mod[2]);
    ctx.power_pct += std::min(30, mod[3]);
    ctx.pierce += mod[4];
    ctx.focus_pct += std::min(30, mod[5]);
    return ctx;
}

inline bool better_tie(const Point& a, const Point& b) {
    if (a.changes != b.changes) return a.changes < b.changes;
    if (a.pieces != b.pieces) return a.pieces < b.pieces;
    for (int i = 0; i < 27; ++i) {
        if (a.slots[i] == b.slots[i]) continue;
        if (a.slots[i] < 0 || b.slots[i] < 0) return b.slots[i] < 0;
        return a.slots[i] < b.slots[i];
    }
    return a.spell.recipe < b.spell.recipe;
}

inline int order(const SpellPoint& a, const SpellPoint& b, bool speed) {
    if (speed) return dfo_spell::compare(a.loss*a.rate_200, a.outcomes,
                                         b.loss*b.rate_200, b.outcomes);
    // A free-cast request has an undefined SP-efficiency axis for every row.
    if (!a.cost || !b.cost) return 0;
    return dfo_spell::compare(a.loss,a.outcomes*a.cost,b.loss,b.outcomes*b.cost);
}
inline bool dominates(const SpellPoint& a, const SpellPoint& b) {
    return order(a,b,true)>=0 && order(a,b,false)>=0;
}

class Traversal {
    const Config& cfg;
    const dfo_spell::Context& base;
    Cancel& flag;
    Clock::time_point start = Clock::now();
    Slots selected{};
    std::vector<bool> used;
    std::vector<uint64_t> spent;
    Report out;
    std::map<Mods, std::vector<SpellPoint>> cache;
    uint64_t fixed_bytes = 0, cache_bytes = 0;
    std::vector<SpellPoint> local;
    dfo_spell::Grid grid;
    bool cacheable = true;
    uint64_t polls = 0;

    double elapsed() const { return std::chrono::duration<double>(Clock::now()-start).count(); }
    bool interrupted() {
        if (!(++polls % 64)) {
            if (flag.stopped.load(std::memory_order_relaxed)) out.end = 4;
            else if (cfg.wall_seconds && elapsed() >= cfg.wall_seconds) out.end = 2;
        }
        return out.end != 0;
    }
    bool step() {
        if (flag.stopped.load(std::memory_order_relaxed)) out.end = 4;
        else if (cfg.max_nodes && out.nodes >= cfg.max_nodes) out.end = 1;
        else if (cfg.wall_seconds && elapsed() >= cfg.wall_seconds) out.end = 2;
        if (out.end) return false;
        ++out.nodes;
        return true;
    }
    bool fits(uint64_t extra) {
        const auto bytes = fixed_bytes + cache_bytes + (grid.sums.capacity()+grid.by_raw.capacity())*sizeof(int64_t) + out.points.capacity()*sizeof(Point)
                         + local.capacity()*sizeof(SpellPoint) + extra;
        if (bytes > cfg.memory_bytes) return false;
        out.work_bytes = std::max(out.work_bytes, bytes);
        return true;
    }
    void publish(const SpellPoint& spell) {
        Point p;
        p.spell = spell;
        p.slots = selected;
        for (const Slot& slot : cfg.slots) {
            p.pieces += selected[slot.id] >= 0;
            p.changes += selected[slot.id] != slot.current;
        }
        for (auto& q : out.points) {
            if (!dominates(q.spell, spell)) continue;
            if (dominates(spell,q.spell) && better_tie(p,q)) q = p;
            return;
        }
        auto& points = out.points;
        points.erase(std::remove_if(points.begin(), points.end(), [&](const Point& q) {
            return dominates(spell, q.spell);
        }), points.end());
        if (points.size() == points.capacity()) {
            const auto next = std::max<size_t>(1, 2*points.size());
            if (!fits(next*sizeof(Point))) { out.end = 3; return; }
            points.reserve(next);
        }
        points.push_back(p);
        if (out.first_seconds < 0) { out.first_seconds = elapsed(); flag.ready.store(true); }
    }
    void remember(const SpellPoint& p) {
        if (!cacheable) return;
        for (auto& q : local) {
            if (!dominates(q,p)) continue;
            if (dominates(p,q) && p.recipe < q.recipe) q = p;
            return;
        }
        local.erase(std::remove_if(local.begin(), local.end(), [&](const SpellPoint& q) {
            return dominates(p,q);
        }), local.end());
        if (local.size() == local.capacity()) {
            const auto next = std::max<size_t>(1, 2*local.size());
            if (!fits(next*sizeof(SpellPoint))) {cacheable = false; return;}
            local.reserve(next);
        }
        local.push_back(p);
    }
    bool reachable(const Slot& slot) const {
        // A second-only jewel slot is reachable with the first slot temporarily
        // occupied. Owned accessible pieces are eligible temporary donors.
        const int id = selected[slot.id];
        if (slot.preferred < 0 || id < 0 || selected[slot.preferred] >= 0 || id == slot.current) return true;
        const auto& preferred = cfg.slots.at(slot.preferred);
        if (preferred.current >= 0 && preferred.current != id) return true;
        for (auto place : preferred.entries)
            if (place.item != id && cfg.items[place.item].owned) return true;
        return false;
    }
    Mods modifiers() const {
        Mods total{};
        std::array<int, 27> seen{};
        int count = 0;
        for (auto id : selected) if (id >= 0) {
            const Option& item = cfg.items[id];
            bool first = true;
            if (item.legendary >= 0) {
                first = std::find(seen.begin(), seen.begin()+count, item.legendary) == seen.begin()+count;
                if (first) seen[count++] = item.legendary;
            }
            fold(total, item, first);
        }
        int retained=0;
        bool changed=false;
        for (const auto& s:cfg.slots) {
            const int id=selected[s.id];
            changed |= id!=s.current;
            if (id>=0 && id==s.current && cfg.items[id].legendary<0)
                retained+=cfg.items[id].mods[7];
        }
        int safe=base.available_sp, possible=safe;
        if (cfg.firmament_enabled) {
            const auto maximum = [&](int equipment_int) {
                return dfo_firmament::maximum_sp(cfg.firmament, cfg.projection, equipment_int);
            };
            const int original = std::min(safe, maximum(cfg.projection.worn_intelligence));
            possible = std::min(original, maximum(total[7]));
            safe = changed ? std::min(possible, maximum(retained)) : possible;
        } else if (cfg.post_sp>=0) safe=possible=cfg.post_sp;
        else if (changed) {
            const int delta=std::max(0,cfg.current_int-retained);
            safe=cfg.uncertain_worn ? 0 : std::max(0,safe-(delta*(cfg.quarters?cfg.quarters:12)+3)/4);
            if (cfg.intelligence>=0 && cfg.quarters) {
                const int floor=std::min(100,cfg.intelligence+retained)*cfg.quarters/4+std::max(0,cfg.bonus);
                safe=std::max(safe,floor);
                if (cfg.bonus>=0)
                    possible=std::min(possible,std::min(100,cfg.intelligence+total[7])*cfg.quarters/4+cfg.bonus);
            }
        }
        total[7]=0;
        total[8]=std::min(safe,possible);
        total[9]=possible;
        return total;
    }
    RecipeKey unpack(uint64_t index) const {
        RecipeKey key{};
        // Keep element and scaling divisor fixed across consecutive rectangles.
        for (int j : {5,4,3,2,1,6,0}) {
            const auto& axis = cfg.axes[j];
            key[j] = axis[index % axis.size()];
            index /= axis.size();
        }
        return key;
    }
    void score() {
        for (const Slot& s : cfg.slots) if (!reachable(s)) { ++out.pruned; return; }
        ++out.leaves;
        const auto mods = modifiers();
        auto hit = cache.find(mods);
        if (hit != cache.end()) {
            ++out.hits;
            for (const auto& p : hit->second) { if (interrupted()) return; publish(p); }
            return;
        }
        ++out.misses;
        auto ctx = apply(base, mods);
        if (cfg.firmament_enabled)
            ctx = dfo_firmament::project(ctx, cfg.firmament, cfg.projection);
        ctx.available_sp=mods[8];
        cacheable = true;
        local.clear();
        const auto n = cfg.per_state ? std::min(out.product, cfg.per_state) : out.product;
        if (n < out.product) out.sampled = true;
        const int high = cfg.axes[3].back(), bonus = cfg.axes[5].back();
        const auto cells = size_t(high+1)*(bonus+1);
        const auto raw_cells = size_t(high+(ctx.level/cfg.axes[6].front())*bonus+1);
        // A large exact domain benefits from rectangle prefix sums shared
        // with M2. A tight memory budget can still evaluate every roll directly.
        const bool use_grid = n==out.product && n>=512 && fits((cells+raw_cells)*sizeof(int64_t));
        int last_element=-1, last_divisor=-1;
        for (uint64_t i = 0; i < n; ++i) {
            if (!step()) return;
            // Exact integer stratification; the quotient/remainder form avoids
            // multiplication by the full cardinality for broad spell domains.
            uint64_t index = i;
            if (n < out.product && n > 1) {
                const auto span = out.product - 1, last = n - 1;
                index = i * (span / last) + i * (span % last) / last;
            }
            const auto r = unpack(index);
            if (r[2] > r[3] || r[4] > r[5]) continue;
            const dfo_spell::Recipe recipe{r[0],r[1],r[2],r[3],r[4],r[5],r[6]};
            const auto price = dfo_spell::price(ctx, recipe);
            ++out.evaluations;
            if (price.cost > ctx.available_sp) {
                if (price.cost <= mods[9]) ++out.uncertain_sp;
                continue;
            }
            uint64_t loss;
            if (use_grid) {
                if (r[0]!=last_element || r[6]!=last_divisor) {
                    grid.build(dfo_spell::landing(ctx,r[0]),ctx.level/r[6],high,bonus);
                    last_element=r[0]; last_divisor=r[6];
                }
                loss=uint64_t(grid.sum(recipe));
            } else loss=uint64_t(dfo_spell::evaluate(ctx,recipe).health_loss_sum);
            const int rate_200 = std::clamp(200+ctx.speed-50+2*ctx.cast_speed_pct,100,400);
            SpellPoint p{r,loss,uint64_t(dfo_spell::roll_pairs(recipe))*10000,price.cost,rate_200};
            publish(p);
            if (out.end) return;
            remember(p);
        }
        const auto bytes = sizeof(Mods)+sizeof(std::vector<SpellPoint>)+80+local.size()*sizeof(SpellPoint);
        if (cacheable && fits(bytes) && cache_bytes+bytes < cfg.memory_bytes/3) {
            cache.emplace(mods, local);
            cache_bytes += bytes;
        }
    }
    bool affordable(const Option& item) const {
        for (size_t i = 0; i < spent.size(); ++i)
            if (item.price[i] > cfg.budget[i]-spent[i]) return false;
        return true;
    }
    void choose(const Slot& s, const Place& p, uint32_t occupied) {
        const auto& item = cfg.items[p.item];
        if (used[p.item] || ((occupied|cfg.empty_mask) & p.mask) || !affordable(item)) {++out.pruned; return;}
        for (size_t i = 0; i < spent.size(); ++i) spent[i] += item.price[i];
        selected[s.id] = p.item;
        used[p.item] = true;
        visit(s.id+1, occupied | p.mask);
        used[p.item] = false;
        selected[s.id] = -1;
        for (size_t i = 0; i < spent.size(); ++i) spent[i] -= item.price[i];
    }
    void visit(int index, uint32_t occupied) {
        if (!step()) return;
        while (index < 27 && cfg.slots[index].entries.empty() && cfg.slots[index].lock < 0) ++index;
        if (index == 27) {score(); return;}
        const auto& slot = cfg.slots[index];
        if (slot.lock != -1) for (const auto& p : slot.entries) {
            if (interrupted()) return;
            if (slot.lock >= 0 && p.item != slot.lock) continue;
            choose(slot, p, occupied);
            if (out.end) return;
        }
        if (slot.lock < 0) visit(index+1, occupied);
    }
public:
    Traversal(const Config& c, const dfo_spell::Context& ctx, Cancel& f)
        : cfg(c), base(ctx), flag(f), used(c.items.size()), spent(c.budget.size()) { selected.fill(-1); }
    Report run() {
        fixed_bytes = sizeof(*this)+sizeof(cfg)+cfg.budget.size()*16
                    + cfg.items.size()*(sizeof(Option)+1)+cfg.slots.size()*sizeof(Slot);
        for (auto& s:cfg.slots) fixed_bytes += s.entries.capacity()*sizeof(Place);
        for (auto& i:cfg.items) fixed_bytes += i.price.capacity()*8;
        for (auto& axis:cfg.axes) {
            fixed_bytes += sizeof(axis)+axis.capacity()*sizeof(int);
            if (!axis.empty() && out.product > std::numeric_limits<uint64_t>::max()/axis.size())
                throw std::invalid_argument("spell grid cardinality exceeds uint64");
            out.product *= axis.size();
        }
        if (!fits(0)) out.end = 3;
        else if (out.product) visit(0,0);
        return std::move(out);
    }
};
inline Report search(const Config& cfg, const dfo_spell::Context& context, Cancel& flag) {
    return Traversal(cfg,context,flag).run();
}
} // namespace dfo_gear

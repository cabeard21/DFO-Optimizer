#pragma once
// Included inside the dfo namespace after the class-search value types.

struct TraitFeatures {
    int magery_quarters{}, materials{}, gear{}, absorption{};
};
struct GearMasks {
    int materials{}, gear{};
};
struct DiscoveryConfig {
    bool exhaustive{}, stable_examples{};
    uint32_t seed{};
    uint64_t required_masteries{}, required_skills{};
    std::array<TraitFeatures, 128> features{};
    std::vector<uint32_t> rolls;
    std::vector<std::vector<GearMasks>> stages;
    void trait(int id, int magery, int metal, int gear, int absorption) {
        features[id] = {magery, metal, gear, absorption};
    }
    void add_stage() { stages.emplace_back(); }
    void item(int metal, int gear) { stages.back().push_back({metal, gear}); }
};

struct ScreenFeatures {
    int hp{}, absorption{}, destruction_sum{}, sp_sum{}, speed_sum{};
    std::array<int, 32> eligible{};
    bool pareto{};
};
#include "discovery_frontier.hpp"
struct DiscoveryOutput {
    Output visited;
    std::vector<ScreenFeatures> features;
    uint64_t unique_screened{}, attempts{};
    uint64_t pareto_overflows{}, pareto_retained{}, pareto_capacity{};
};

inline uint64_t scramble(uint64_t value) noexcept {
    value ^= value >> 30;
    value *= 0xbf58476d1ce4e5b9ULL;
    value ^= value >> 27;
    value *= 0x94d049bb133111ebULL;
    return value ^ (value >> 31);
}

struct BirthTape {
    std::array<int, 8> attribute_bonus{};
    int pool{}, misc_destruction{};
    std::array<int, 12> career{};

    explicit BirthTape(uint32_t seed) {
        auto draw = [&seed](int span) {
            seed = 1664525u * seed + 1013904223u;
            return int((uint64_t(seed) * span) >> 32);
        };
        for (int& x : attribute_bonus)
            x = draw(11);
        pool = 6 + draw(9);
        for (int i = 0; i < 35; ++i) {
            const int value = 3 + draw(4);
            if (i == 22)
                misc_destruction = value;
        }
        for (int i = 0; i < 12; ++i)
            career[i] = (i < 3 ? 28 : i < 6 ? 18 : 13) + draw(4);
        for (const auto bounds : {std::pair<int, int>{0, 3}, {3, 6}, {6, 12}})
            for (int point = 0; point < 6; ++point)
                ++*std::min_element(career.begin() + bounds.first, career.begin() + bounds.second);
    }
};

// One bounded native archive. Race partitions prevent a traversal prefix or
// race tie from filling all positions. Within a race, effect/group strata map
// to differing objective orders. Replacement is a screening heuristic only.
class DiscoveryScreen {
    struct Seen {
        std::array<uint8_t, 37> document{};
        int next{-1};
    };
    struct Entry {
        Candidate candidate{};
        ScreenFeatures features{};
        uint64_t identity{};
        int next{-1};
        bool used{};
    };
    const Options& o;
    const DiscoveryConfig& cfg;
    std::vector<Entry> entries;
    std::vector<int> buckets;
    std::vector<BirthTape> tapes;
    std::array<FeatureFrontier, 9> frontiers;
    std::array<int, 9> race_index{}, filled{};
    std::array<int, 13> destruction_by_slot{};
    std::array<uint64_t, 13> suffix_skills{};
    std::vector<Seen> seen;
    std::vector<int> seen_buckets;
    int magery_quarters{}, materials{}, gear{};
    ScreenFeatures current{};
    uint64_t random_state;
    bool sampled{};

    static uint64_t identity(const Candidate& c) {
        uint64_t hash = 14695981039346656037ULL;
        auto add = [&hash](int n) { hash = (hash ^ unsigned(n)) * 1099511628211ULL; };
        add(c.race);
        add(c.hp);
        for (int n : c.attributes)
            add(n);
        for (int n : c.skills)
            add(n);
        for (int i = 0; i < c.count; ++i)
            add(c.traits[i]);
        return scramble(hash);
    }
    static bool equal(const Candidate& a, const Candidate& b) {
        return a.hp == b.hp && a.race == b.race && a.count == b.count &&
               std::equal(a.attributes, a.attributes + 8, b.attributes) &&
               std::equal(a.skills, a.skills + 12, b.skills) &&
               std::equal(a.traits, a.traits + a.count, b.traits);
    }
    size_t visit_capacity() const {
        if (!sampling())
            return 0;
        const size_t limit = std::max(256, 64 * o.k);
        // A new sampled leaf always requires eight attribute and twelve skill
        // frames. Bound the set size before allocation for short node budgets.
        return o.max_nodes ? std::min<uint64_t>(limit, 1 + o.max_nodes / 20) : limit;
    }
    bool first_visit(const Candidate& c, uint64_t hash) {
        if (!sampling())
            return true;
        Seen key{};
        auto ptr = key.document.begin();
        *ptr++ = uint8_t(c.hp);
        *ptr++ = uint8_t(c.race);
        *ptr++ = uint8_t(c.count);
        for (int n : c.attributes)
            *ptr++ = uint8_t(n);
        for (int n : c.skills)
            *ptr++ = uint8_t(n);
        for (int i = 0; i < c.count; ++i)
            *ptr++ = uint8_t(c.traits[i]);
        int& head = seen_buckets[hash % seen_buckets.size()];
        for (int i = head; i >= 0; i = seen[i].next)
            if (key.document == seen[i].document)
                return false;
        key.next = head;
        head = int(seen.size());
        seen.push_back(key);
        return true;
    }
    int race_slots(int i) const {
        const int races = int(o.races.size());
        return races > o.k ? 1 : (i + 1) * o.k / races - i * o.k / races;
    }
    uint64_t stratum(const Candidate& c) const {
        uint64_t group = 0;
        for (int i = 0; i < 12; ++i)
            if (c.skills[i] >= 22 && c.skills[i] <= 27)
                group |= uint64_t(i < 3 ? 1 : i < 6 ? 2 : 3) << (2 * (c.skills[i] - 22));
        uint64_t signature = group ^ (uint64_t(materials) << 16) ^ (uint64_t(gear) << 32) ^
                             (uint64_t(current.absorption) << 48);
        for (int i = 0; i < c.count; ++i)
            signature = scramble(signature ^ uint64_t(c.traits[i] + 1));
        return scramble(signature);
    }
    std::array<int, 6> axes(const ScreenFeatures& f) const {
        int items = 0;
        for (size_t i = 0; i < cfg.stages.size(); ++i)
            items += f.eligible[i];
        return {f.sp_sum, f.speed_sum, f.destruction_sum, items, f.hp, int(f.absorption != 0)};
    }
    bool better(const ScreenFeatures& value, uint64_t hash, const Entry& old, int lane) const {
        const auto a = axes(value), b = axes(old.features);
        for (int i = 0; i < int(a.size()); ++i) {
            const auto j = (lane + i) % a.size();
            if (a[j] != b[j])
                return a[j] > b[j];
        }
        return hash < old.identity;
    }
    void unlink(int index) {
        int* link = &buckets[entries[index].identity % buckets.size()];
        while (*link != index)
            link = &entries[*link].next;
        *link = entries[index].next;
    }

  public:
    uint64_t attempts{};
    DiscoveryScreen(const Options& options, const DiscoveryConfig& settings)
        : o(options), cfg(settings), random_state(settings.seed) {}
    size_t work_bytes() const {
        size_t bytes = sizeof(*this) + sizeof(cfg) + cfg.rolls.capacity() * sizeof(uint32_t) +
                       sizeof(BirthTape) * cfg.rolls.size() +
                       cfg.stages.capacity() * sizeof(std::vector<GearMasks>) +
                       (sizeof(Entry) + sizeof(ScreenFeatures) + 2 * sizeof(int)) * o.k + 2 * sizeof(int) +
                       visit_capacity() * (sizeof(Seen) + 2 * sizeof(int));
        for (const auto& stage : cfg.stages)
            bytes += stage.capacity() * sizeof(GearMasks);
        if (!cfg.stable_examples)
            for (size_t i = 0; i < o.races.size(); ++i)
                bytes += (FeatureFrontier::capacity_for(race_slots(int(i))) + 1) * sizeof(FeaturePoint);
        if (sampling())
            bytes += 20 * sizeof(std::array<int, 66>);
        return bytes;
    }
    void initialize() {
        entries.resize(o.k);
        buckets.assign(2 * o.k + 1, -1);
        if (sampling()) {
            seen.reserve(visit_capacity());
            seen_buckets.assign(2 * visit_capacity() + 1, -1);
        }
        tapes.reserve(cfg.rolls.size());
        for (auto seed : cfg.rolls) {
            const auto& t = tapes.emplace_back(seed);
            for (int i = 0; i < 12; ++i)
                destruction_by_slot[i] += t.career[i];
            destruction_by_slot[12] += t.misc_destruction;
        }
        for (size_t i = 0; i < o.races.size(); ++i) {
            race_index[o.races[i]] = int(i);
            if (!cfg.stable_examples)
                frontiers[i].initialize(race_slots(int(i)), int(cfg.stages.size()));
        }
        for (int i = 11; i >= 0; --i) {
            suffix_skills[i] = suffix_skills[i + 1];
            for (int skill : o.skills[i])
                suffix_skills[i] |= uint64_t(1) << skill;
        }
    }
    uint64_t random() {
        random_state += 0x9e3779b97f4a7c15ULL;
        return scramble(random_state);
    }
    bool sampling() const { return !cfg.exhaustive && !cfg.stable_examples; }
    bool have_examples(uint64_t leaves) const {
        return cfg.stable_examples && !cfg.exhaustive && leaves >= uint64_t(o.k);
    }
    bool stop_branch() const { return sampling() && sampled; }
    void restart() {
        sampled = false;
        ++attempts;
    }
    bool sample_limit() const { return attempts >= uint64_t(std::max(256, 64 * o.k)); }
    bool skills_possible(int slot, uint64_t selected, const int* skills) const {
        // An upper bound on remaining required mastery slots ignores slot domains.
        // No skill outside its career group can consume its quota.
        const auto required = (cfg.required_masteries | cfg.required_skills) & ~selected;
        if (required & ~suffix_skills[slot])
            return false;
        int grouped[3]{}, missing = 0, must_pick = 0;
        for (int i = 0; i < slot; ++i)
            if ((uint64_t(1) << skills[i]) & cfg.required_masteries)
                ++grouped[i < 3 ? 0 : i < 6 ? 1 : 2];
        auto count = [](uint64_t bits) {
            int n = 0;
            while (bits) {
                bits &= bits - 1;
                ++n;
            }
            return n;
        };
        missing = count(cfg.required_masteries & ~selected);
        must_pick = count(required);
        if (must_pick > 12 - slot || grouped[0] > 3 || grouped[1] > 2 || grouped[2] > 1)
            return false;
        const int free = std::max(0, 3 - slot) +
                         std::min(2 - grouped[1], std::max(0, 6 - std::max(slot, 3))) +
                         std::min(1 - grouped[2], std::max(0, 12 - std::max(slot, 6)));
        return missing <= free;
    }
    void prepare_traits(const Candidate& c) {
        magery_quarters = 2;
        materials = 0;
        gear = 0;
        current = {};
        current.hp = 25 + c.hp;
        for (int i = 0; i < c.count; ++i) {
            const auto& t = cfg.features[c.traits[i]];
            if (t.magery_quarters)
                magery_quarters = t.magery_quarters;
            materials |= t.materials;
            gear |= t.gear;
            if (t.absorption)
                current.absorption = t.absorption;
        }
        for (size_t i = 0; i < cfg.stages.size(); ++i)
            for (auto item : cfg.stages[i])
                current.eligible[i] += !(materials & item.materials) && !(gear & item.gear);
    }
    void prepare_stats(const Candidate& c) {
        current.sp_sum = 0;
        current.speed_sum = 0;
        for (const auto& t : tapes) {
            auto attrs = t.attribute_bonus;
            for (int i = 0; i < 8; ++i)
                attrs[i] += c.attributes[i];
            for (int point = 0; point < t.pool; ++point)
                ++*std::min_element(attrs.begin(), attrs.end());
            current.sp_sum += attrs[1] * magery_quarters / 4;
            current.speed_sum += attrs[6];
        }
    }
    void keep(const Candidate& c) {
        sampled = true;
        current.destruction_sum = destruction_by_slot[std::find(c.skills, c.skills + 12, 22) - c.skills];
        if (cfg.stable_examples) {
            if (c.ordinal < uint64_t(o.k))
                entries[size_t(c.ordinal)] = {c, current, 0, -1, true};
            return;
        }
        const uint64_t hash = identity(c);
        if (!first_visit(c, hash))
            return;
        frontiers[race_index[c.race]].retain(c, current, hash);
        for (int p = buckets[hash % buckets.size()]; p >= 0; p = entries[p].next)
            if (entries[p].identity == hash && equal(c, entries[p].candidate))
                return;
        const int n = int(o.races.size()), r = race_index[c.race];
        const int start = o.k < n ? r % o.k : r * o.k / n;
        const int size = o.k < n ? 1 : (r + 1) * o.k / n - start;
        const int lane = int(stratum(c) % size);
        int index = start + lane;
        if (entries[index].used && filled[r] < size && o.k >= n)
            for (int j = 1; j < size; ++j) {
                const int other = start + (lane + j) % size;
                if (!entries[other].used) {
                    index = other;
                    break;
                }
            }
        Entry& old = entries[index];
        if (old.used) {
            if (!better(current, hash, old, index - start))
                return;
            unlink(index);
        } else
            ++filled[r];
        int& bucket = buckets[hash % buckets.size()];
        old = {c, current, hash, bucket, true};
        bucket = index;
    }
    void publish_front_point(const FeaturePoint& p, DiscoveryOutput& result) {
        result.visited.best.push_back(p.candidate);
        result.features.push_back(p.features);
        result.features.back().pareto = true;
        ++result.pareto_retained;
        for (int i = buckets[p.identity % buckets.size()]; i >= 0; i = entries[i].next)
            if (entries[i].identity == p.identity && equal(entries[i].candidate, p.candidate)) {
                entries[i].used = false;
                break;
            }
    }
    void finish(DiscoveryOutput& result) {
        result.unique_screened = sampling() ? seen.size() : result.visited.leaves;
        result.attempts = attempts;
        result.visited.best.reserve(o.k);
        result.features.reserve(o.k);
        std::array<const FeaturePoint*, 8> shared{};
        std::array<int, 9> published{};
        for (size_t i = 0; !cfg.stable_examples && i < o.races.size(); ++i) {
            const auto& frontier = frontiers[i];
            result.pareto_overflows += frontier.overflows;
            result.pareto_capacity += FeatureFrontier::capacity_for(race_slots(int(i)));
            for (const auto& p : frontier.retained()) {
                if (size_t(o.k) >= o.races.size()) {
                    publish_front_point(p, result);
                    ++published[i];
                } else {
                    // When fewer positions than races were requested compare
                    // each race's representative only to the shared-slot winner.
                    const auto slot = i % o.k;
                    const auto* prev = shared[slot];
                    if (!prev ||
                        better(p.features, p.identity,
                               Entry{prev->candidate, prev->features, prev->identity, -1, true}, int(slot)))
                        shared[slot] = &p;
                }
            }
        }
        for (auto p : shared)
            if (p)
                publish_front_point(*p, result);
        for (const auto& e : entries)
            if (e.used && int(result.visited.best.size()) < o.k) {
                const int race = race_index[e.candidate.race];
                if (!cfg.stable_examples && published[race] >= race_slots(race))
                    continue;
                result.visited.best.push_back(e.candidate);
                result.features.push_back(e.features);
                ++published[race];
            }
    }
};

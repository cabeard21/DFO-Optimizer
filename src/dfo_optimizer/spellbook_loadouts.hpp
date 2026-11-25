#pragma once
#include "spellbook.hpp"
#include <algorithm>
#include <array>
#include <string>

namespace dfo_book {
struct PolicyFrontierPoint {
    double loss{};
    int64_t gold{};
    int sp{};
    std::vector<int> plans;
};
struct SearchResult {
    std::vector<PolicyFrontierPoint> routes;
    dfo_spell::u64 nodes{}, pruned{};
    double first_incumbent_seconds = -1;
    std::string end = "exhausted";
};
struct SearchLimits {
    int casts{}, sp{};
    int64_t gold{};
    dfo_spell::u64 max_nodes{}, memory_bytes{};
    double wall_seconds{};
};

inline bool dominates_or_ties(const PolicyFrontierPoint& a, const PolicyFrontierPoint& b) {
    return a.loss >= b.loss && a.gold <= b.gold && a.sp <= b.sp;
}

// A fixed loadout can include both known spells and made spells priced at this one stage.
class NativeLoadoutSearch {
    const std::vector<SpellScore>& scores;
    const std::vector<int>& purchase_prices;
    const std::vector<int>& fixed_policy;
    const SearchLimits& opt;
    dfo_spell::Token& token;
    dfo_spell::Clock::time_point now;
    std::vector<int> times_cast, casts;
    SearchResult out;

    double elapsed() const {
        return std::chrono::duration<double>(dfo_spell::Clock::now() - now).count();
    }
    bool stop() {
        if (token.stopped.load(std::memory_order_relaxed)) out.end = "cancelled";
        else if (opt.wall_seconds && elapsed() >= opt.wall_seconds) out.end = "time_limit";
        else if (opt.max_nodes && out.nodes >= opt.max_nodes) out.end = "node_limit";
        return out.end != "exhausted";
    }
    void exact_step(int root, int64_t gold, int cost, double loss) {
        if (stop()) return;
        ++out.nodes;
        if (int(casts.size()) == opt.casts) {
            remember(gold, cost, loss);
            return;
        }
        if (!fixed_policy.empty()) {
            admit(fixed_policy[casts.size()], gold, cost, loss);
            return;
        }
        // Every cast has the same fixed stage and stationary target. A cast does not
        // change resources other than its one spendable SP balance and gold purchase.
        // Costs are positive and taking the projected policies in nondecreasing order
        // visits each distinct combination of terminal expected outcomes once.
        for (int i = root; i < int(scores.size()) && out.end == "exhausted"; ++i)
            admit(i, gold, cost, loss);
    }
    void admit(int value, int64_t gold, int cost, double loss) {
        bool first = !times_cast[value];
        auto next = scores[value];
        auto weight = first ? purchase_prices[value] : 0;
        if (weight < 0 || weight > opt.gold - gold || next.cost_sp > opt.sp - cost) {
            ++out.pruned;
            return;
        }
        ++times_cast[value];
        casts.push_back(value);
        exact_step(value, gold + weight, cost + next.cost_sp, loss + next.expected_health_loss);
        casts.pop_back();
        --times_cast[value];
    }
    void remember(int64_t gold, int cost, double value) {
        PolicyFrontierPoint curve{value, gold, cost, {}};
        for (const auto& b : out.routes) if (dominates_or_ties(b, curve)) return;
        auto next = std::remove_if(out.routes.begin(), out.routes.end(), [&](const PolicyFrontierPoint& b) {
            return dominates_or_ties(curve, b);
        });
        out.routes.erase(next, out.routes.end());
        size_t per = (sizeof(PolicyFrontierPoint) + sizeof(int) * opt.casts + 2 * sizeof(void *));
        size_t prefix = sizeof(NativeLoadoutSearch) + times_cast.size() * (sizeof(SpellScore) + 3 * sizeof(int)) + opt.casts*32;
        if (prefix + per * (2 * (out.routes.size() + 1)) > opt.memory_bytes) {
            out.end = "memory_limit";
            return;
        }
        curve.plans = casts;
        out.routes.push_back(std::move(curve));
        if (out.first_incumbent_seconds < 0) {
            out.first_incumbent_seconds = elapsed();
            token.incumbent.store(true, std::memory_order_relaxed);
        }
    }
public:
    NativeLoadoutSearch(const std::vector<SpellScore>& p, const std::vector<int>& b, const std::vector<int>& fixed,
               const SearchLimits& projections, dfo_spell::Token& t, dfo_spell::Clock::time_point start)
        : scores(p), purchase_prices(b), fixed_policy(fixed), opt(projections), token(t),
          now(start), times_cast(p.size(),0) {}
    SearchResult execute() {
        exact_step(0, 0, 0, 0);
        return std::move(out);
    }
};

inline SearchResult select_policy(const Context& ctx, const std::vector<Bundle>& spells,
                                  const std::vector<int>& routes, const std::vector<int>& policy,
                                  const SearchLimits& goal, dfo_spell::Token& token) {
    auto now = dfo_spell::Clock::now();
    auto deadline = now + std::chrono::duration_cast<dfo_spell::Clock::duration>(
        std::chrono::duration<double>(goal.wall_seconds));
    SpellAccess retention{&token, goal.wall_seconds ? &deadline : nullptr, goal.memory_bytes};
    const size_t downstream = spells.size() * (sizeof(SpellScore) + sizeof(Bundle) +
        3*sizeof(Settings) + 3*sizeof(int)) + policy.size()*sizeof(int) + sizeof(retention);
    try {
        enforce_limits(&retention, downstream);
        retention.memory_bytes -= downstream;
        std::vector<SpellScore> probabilities;
        probabilities.reserve(spells.size());
        std::vector<int> quotes = routes;
        for (size_t i=0; i < spells.size(); ++i) {
            const auto score = evaluate(ctx, spells[i], &retention);
            probabilities.push_back(score);
            if (quotes[i] == 1) quotes[i] = score.purchase_gold;
        }
        auto price_limit = goal;
        price_limit.memory_bytes = retention.memory_bytes;
        return NativeLoadoutSearch(probabilities, quotes, policy, price_limit, token, now).execute();
    } catch (const SearchLimitReached& goal) {
        SearchResult limited;
        limited.end = goal.reason;
        return limited;
    }
}
} // namespace dfo_book

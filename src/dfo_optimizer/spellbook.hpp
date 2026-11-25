#pragma once
#include "spell_kernel.hpp"
#include <cmath>
#include <cstddef>
#include <stdexcept>
#include <string>

namespace dfo_book {
using dfo_spell::Context;

// The sequence is the exact Spellmaker effect order on the game's recipe.
struct Settings {
    // Damage Health (0) uses the four magnitude fields. Disintegrate (1) uses the chance fields.
    int effect_kind{}, base_low{}, base_high{}, plus_low{}, plus_high{}, per_level{};
    int chance_base{}, chance_increment{};
};
struct Bundle {
    int element{}, range_type{};
    std::vector<Settings> effects;
};
struct SpellScore {
    int gold{}, cost_sp{}, purchase_gold{};
    double expected_health_loss{}, expected_damage{}, kill_probability{}, dps{};
};
struct SpellAccess {
    dfo_spell::Token* token{};
    const dfo_spell::Clock::time_point* deadline{};
    size_t memory_bytes = std::numeric_limits<size_t>::max();
};
struct SearchLimitReached { const char* reason; };
inline void enforce_limits(const SpellAccess* access, size_t bytes = 0) {
    if (!access) return;
    if (access->token && access->token->stopped.load(std::memory_order_relaxed))
        throw SearchLimitReached{"cancelled"};
    if (access->deadline && dfo_spell::Clock::now() >= *access->deadline)
        throw SearchLimitReached{"time_limit"};
    if (bytes > access->memory_bytes) throw SearchLimitReached{"memory_limit"};
}

using Prize = SpellScore; // Compatibility with the lifecycle accumulator.

inline int stored_gold(const Settings& s) {
    if (s.effect_kind == 0)
        return 20 * ((s.base_low + s.base_high) / 2) + 28 * (((s.plus_low + s.plus_high) / 2) / s.per_level);
    return 80 * s.chance_base + 140 * (s.chance_increment / s.per_level);
}

inline void price_bundle(const Context& ctx, const Bundle& b, SpellScore& out) {
    int base_gold = 0, base_sp = 0;
    for (const auto& s : b.effects) {
        int gold = stored_gold(s);
        base_gold += gold;
        // The range multiplier applies after the projected spell SP is calculated for each effect.
        base_sp += ctx.live_skill > 100 ? gold * 1000 / (400 * ctx.live_skill)
                                        : gold * (110 - ctx.live_skill) / 400;
    }
    int scale = b.range_type + 1;
    out.gold = base_gold * scale / 2;
    out.purchase_gold = std::max(1, int(std::round(out.gold * ctx.price_factor)));
    int adjusted = std::max(5, base_sp * scale / 2);
    out.cost_sp = ctx.free_cast ? 0 : (adjusted * (100 - std::clamp(ctx.focus_pct, 0, 30)) + 50) / 100;
}

struct SpellOutcome {
    std::vector<double> choices;
    double expected_damage{};
};

inline SpellOutcome spell_damage_states(const Context& ctx, const Settings& effect,
                                      const dfo_spell::Landing& domain) {
    int q = ctx.level / effect.per_level;
    int max_value = dfo_spell::with_power(effect.base_high + q * effect.plus_high, domain.potency);
    if (domain.save == 100 || !domain.ward_passes) return {{1.0}, 0.0};
    std::vector<double> points(1 + std::min(ctx.target_hp, max_value), 0.0);
    int count = (effect.base_high - effect.base_low + 1) * (effect.plus_high - effect.plus_low + 1);
    std::vector<int> candidates(1 + effect.base_high + q*effect.plus_high, 0);
    for (int base = effect.base_low; base <= effect.base_high; ++base)
        for (int plus = effect.plus_low; plus <= effect.plus_high; ++plus)
            ++candidates[base + q * plus];
    double earned = 0;
    for (size_t raw = 1; raw < candidates.size(); ++raw) {
        if (!candidates[raw]) continue;
        auto price = [&](double weight, int mark) {
            double amount = weight * candidates[raw] * domain.ward_passes;
            int out = dfo_spell::with_power(int(raw) * mark / 100, domain.potency);
            points[std::min(ctx.target_hp, out)] += amount;
            earned += amount * out;
        };
        price(101 - domain.save, 100);
        for (int n = 1; n < std::min(20, domain.save); ++n) price(1, 100 - 5 * n);
    }
    double limit = double(count) * 10000;
    double nonblocked_mass = std::accumulate(points.begin(), points.end(), 0.0);
    points[0] += limit - nonblocked_mass; // D100 rolls blocked by the HP ward or the chance-based save
    for (double& point : points) point /= limit;
    return {std::move(points), earned / limit};
}

inline double disintegrate_probability(const Context& ctx, const Settings& effect,
                               const dfo_spell::Landing& power) {
    // Spell policy generates two D100 draws: an effect chance and the source's
    // nonzero savingThrow test. Disintegrate does not consume spell penetration.
    if (power.save == 100) return 0;
    int chance = std::min(100, effect.chance_base + effect.chance_increment * (ctx.level / effect.per_level));
    return double(chance) * power.ward_passes * (100 - std::max(0, power.save - 20)) / 1000000.0;
}

inline std::vector<double> convolve_damage(const std::vector<double>& previous,
                                           const std::vector<double>& current, int cap,
                                           const SpellAccess* access) {
    size_t bound = std::min<size_t>(cap, previous.size() + current.size() - 2);
    std::vector<double> total(bound + 1, 0.0);
    std::vector<double> tail(current.size()+1, 0.0);
    for (size_t k = current.size(); k > 0; --k) tail[k-1] = tail[k] + current[k-1];
    for (size_t accumulated = 0; accumulated < previous.size(); ++accumulated) {
        if ((accumulated & 15) == 0) enforce_limits(access);
        if (!previous[accumulated]) continue;
        size_t last = std::min(current.size(), size_t(cap) - accumulated);
        for (size_t j = 0; j < last; ++j)
            total[accumulated + j] += previous[accumulated] * current[j];
        if (last < current.size()) total[cap] += previous[accumulated] * tail[last];
    }
    return total;
}

inline double damage_mean(const std::vector<double>& state) {
    double average = 0;
    for (size_t i = 1; i < state.size(); ++i) average += i * state[i];
    return average;
}

// On the last damage slot only clipped damage and the lethal tail probability are needed.
// Prefix moments and suffix probabilities obtain both in O(previous support + slot support).
struct ExpectedDamage { double points{}, kill_probability{}; };
inline ExpectedDamage final_damage_moments(const std::vector<double>& prior_damage,
                                     const std::vector<double>& slot_damage, int hp) {
    std::vector<double> tail(slot_damage.size()+1), partial_mean(slot_damage.size()+1);
    for (size_t i = slot_damage.size(); i > 0; --i) tail[i-1] = tail[i] + slot_damage[i-1];
    for (size_t i = 0; i < slot_damage.size(); ++i)
        partial_mean[i+1] = partial_mean[i] + i * slot_damage[i];
    ExpectedDamage moments;
    for (size_t dealt = 0; dealt < prior_damage.size(); ++dealt) {
        size_t limit = size_t(hp) - dealt;
        size_t gate = std::min(limit, slot_damage.size());
        moments.kill_probability += prior_damage[dealt] * tail[gate];
        moments.points += prior_damage[dealt] * (dealt + partial_mean[gate] + limit*tail[gate]);
    }
    return moments;
}

inline SpellScore evaluate(const Context& ctx, const Bundle& b, const SpellAccess* access=nullptr) {
    SpellScore out;
    price_bundle(ctx, b, out);
    auto volume = dfo_spell::landing(ctx, b.element);
    auto ignore = ctx;
    ignore.pierce = 0;
    auto chance = dfo_spell::landing(ignore, b.element);
    int raw = 0, wanted = 0;
    for (const auto& effect : b.effects) if (!effect.effect_kind) {
        int bound = effect.base_high + (ctx.level / effect.per_level) * effect.plus_high;
        raw = std::max(raw, bound);
        wanted += dfo_spell::with_power(bound, volume.potency);
    }
    const auto cast_bytes = sizeof(double) * 5 * (1 + std::min(wanted,ctx.target_hp))
        + (1 + raw) * sizeof(int);
    enforce_limits(access, cast_bytes);
    // loadout and search proofs want the output after every action has been selected,
    // but a lethal spell's own contribution is the remaining HP at that *particular* step.
    double survived = 1.0, expected_damage = 0.0;
    ExpectedDamage exact;
    size_t remaining = std::count_if(b.effects.begin(), b.effects.end(),
                                     [](const auto& stage) { return stage.effect_kind == 0; });
    std::vector<double> shape{1.0};
    for (const auto& effect : b.effects) {
        if (effect.effect_kind == 0) {
            auto stage = spell_damage_states(ctx, effect, volume);
            expected_damage += stage.expected_damage;
            --remaining;
            if (wanted < ctx.target_hp) {
                exact.points += stage.expected_damage;
            } else if (!remaining) {
                exact = final_damage_moments(shape, stage.choices, ctx.target_hp);
            } else {
                shape = convolve_damage(shape, stage.choices, ctx.target_hp, access);
                exact.points = damage_mean(shape);
            }
        } else {
            double visit = disintegrate_probability(ctx, effect, chance);
            expected_damage += survived * visit * (ctx.target_hp - exact.points);
            survived *= 1.0 - visit;
        }
    }
    double other_loss = exact.points;
    out.expected_damage = expected_damage;
    out.expected_health_loss = other_loss + (1.0 - survived) * (ctx.target_hp - other_loss);
    out.kill_probability = std::min(1.0, (1.0 - survived) + survived * exact.kill_probability);
    out.dps = out.expected_health_loss / (0.7 / dfo_spell::rate(ctx));
    return out;
}
} // namespace dfo_book

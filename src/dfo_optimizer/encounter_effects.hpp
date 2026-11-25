#pragma once
#include "spell_kernel.hpp"
#include <cstdint>
#include <stdexcept>

namespace dfo_enc {

// A finite observed tape replays game-owned draws exactly. Generated simulations
// draw from xorshift32; the generator and seed are optimizer inputs.
struct Draws {
    std::vector<double> tape;
    const std::vector<double>* borrowed = nullptr;
    std::size_t cursor = 0;
    std::uint32_t state = 0;
    double next() {
        const auto& sequence = borrowed ? *borrowed : tape;
        if (!sequence.empty()) {
            if (cursor >= sequence.size()) throw std::invalid_argument("Encounter random tape exhausted");
            double value = sequence[cursor++];
            if (!(value >= 0 && value < 1)) throw std::invalid_argument("Random draw must be in [0, 1)");
            return value;
        }
        ++cursor;
        if (!state) state = 0x6d2b79f5u;
        state ^= state << 13;
        state ^= state >> 17;
        state ^= state << 5;
        return double(state) / 4294967296.0;
    }
};
struct Effect {
    int type{}, subtype{};
    int climb=-1;
    int base_low=1, base_high=1, plus_low=1, plus_high=1, per_level=1;
    int chance_base=1, chance_increment=1, chance_per_level=1;
    int duration_base=1, duration_increment=1, duration_per_level=1;
};
struct EffectOutcome {
    int damage{}, healing{}, shield{}, rounds{};
};

inline int effect_gold(const Effect& e) {
    int mag = (e.base_low + e.base_high)/2;
    int per = ((e.plus_low + e.plus_high)/2) / e.per_level;
    int dur = e.duration_increment / e.duration_per_level;
    if ((e.type == 4 && e.subtype == 0) || (e.type == 10 && e.subtype == 8))
        return 20*mag + 28*per;
    if (e.type == 5 && e.subtype == 255)
        return 80*e.chance_base + 140*(e.chance_increment/e.chance_per_level);
    if (e.type == 35 && e.subtype == 255)
        return 28*e.duration_base + 8*dur + 80*mag + 60*per;
    if (e.type == 18 && e.subtype == 255)
        return 100*e.duration_base + 20*dur + 8*mag + 8*per;
    if (e.type == 19 && e.subtype == 255)
        return 20*e.duration_base + 100*dur + 20*e.chance_base + 100*(e.chance_increment/e.chance_per_level);
    throw std::invalid_argument("Unsupported encounter effect");
}

inline int roll_magnitude(const Effect& e, int level, Draws& draws) {
    const int base = e.base_low + int(draws.next()*(1+e.base_high-e.base_low));
    const int plus = e.plus_low + int(draws.next()*(1+e.plus_high-e.plus_low));
    return base + plus * (level/e.per_level);
}

inline int save_percent(const dfo_spell::Landing& landing, Draws& draws) {
    if (landing.ward_passes < 100 && int(100*draws.next()) < 100-landing.ward_passes) return 0;
    if (landing.save == 100) return 0;
    int roll = 1 + int(100*draws.next());
    return 100 - 5*std::clamp(landing.save-roll, 0, 20);
}

struct Defenses {
    int absorb_chance{}, reflect_chance{}, resist_chance{};
    bool career_absorbs{}, enchant_absorbs{};
    std::vector<int> set_absorb_chances;
};
inline bool chance_passes(int percent, Draws& draws) {
    return percent > 0 && int(100*draws.next()) < percent;
}
inline int try_absorb(const Defenses& defense, const Effect& effect, int range, int receiver_live,
                      int available_sp, int paid_self, Draws& draws) {
    if (effect.type != 4 && effect.type != 5) return 0;
    const int component = effect_gold(effect);
    const int scaled = receiver_live > 100 ? component*1000/(400*receiver_live)
                                           : component*(110-receiver_live)/400;
    const int cost = std::max(5, scaled*std::max(2,range+1)/2);
    const int drink = paid_self > 0 ? std::min(cost,paid_self) : cost;
    if (drink > available_sp) return 0;
    if (chance_passes(std::min(50,defense.absorb_chance), draws)) return drink;
    for (int chance : defense.set_absorb_chances)
        if (chance_passes(chance,draws)) return drink;
    return defense.career_absorbs || (defense.enchant_absorbs && chance_passes(50,draws)) ? drink : 0;
}
inline bool reflects(const Defenses& d, Draws& draws) { return chance_passes(d.reflect_chance,draws); }
inline bool resists(const Defenses& d, Draws& draws) { return chance_passes(d.resist_chance,draws); }
inline int absorb_refund(int total_absorbed, int paid_self=0) {
    return (paid_self > 0 ? std::min(total_absorbed,paid_self) : total_absorbed)/2;
}

// Silence.Start refreshes an incumbent before testing the new cast's chance.
// It saves only on a new instance. -1 represents absence; 0 lasts until the next round sweep.
inline int silence_rounds(const Effect& e, const dfo_spell::Context& ctx, int element, int incumbent_rounds,
                          Draws& draws) {
    const int fresh = e.duration_base + e.duration_increment * std::max(1,ctx.level/e.duration_per_level);
    if (fresh <= 0) return incumbent_rounds;
    const int chance = e.chance_base + e.chance_increment*(ctx.level/e.chance_per_level);
    const int threshold = dfo_spell::with_power(chance,1.0 + std::max(0,ctx.climb-100)*.01);
    const bool passed = int(100*draws.next()) < threshold;
    if (incumbent_rounds >= 0) return std::max(incumbent_rounds,fresh-1);
    if (!passed) return -1;
    auto unpierced = ctx;
    unpierced.pierce = 0;
    return save_percent(dfo_spell::landing(unpierced,element),draws) > 0 ? fresh-1 : -1;
}

// This closed lane admits hostile Damage Health/Disintegrate and CasterOnly
// Heal Health, Shield and Regenerate. Caller supplies the cast school's climb.
inline EffectOutcome apply_effect(const Effect& e, const dfo_spell::Context& ctx, int element,
                                  int current_hp, int max_hp, Draws& draws,
                                  bool self=false, bool run_regen=true) {
    EffectOutcome out;
    if (e.type == 4 && e.subtype == 0 && !self) {
        const auto landing = dfo_spell::landing(ctx, element);
        const int raw = roll_magnitude(e, ctx.level, draws);
        const int amount = raw * save_percent(landing, draws) / 100;
        out.damage = dfo_spell::with_power(amount, landing.potency);
        return out;
    }
    if (e.type == 5 && e.subtype == 255 && !self) {
        if (1 + int(100*draws.next()) > e.chance_base+e.chance_increment*(ctx.level/e.chance_per_level))
            return out;
        auto unpierced = ctx;
        unpierced.pierce = 0;
        if (save_percent(dfo_spell::landing(unpierced, element), draws) > 0)
            out.damage = current_hp;
        return out;
    }
    bool heal = e.type == 10 && e.subtype == 8;
    bool shield = e.type == 35 && e.subtype == 255;
    bool regen = e.type == 18 && e.subtype == 255;
    if (!self || !(heal || shield || regen))
        throw std::invalid_argument("Unsupported encounter effect or target");
    if (shield || regen)
        out.rounds = e.duration_base + e.duration_increment * std::max(1, ctx.level/e.duration_per_level);
    if (regen && (out.rounds <= 0 || !run_regen)) return out;
    int points = dfo_spell::with_power(roll_magnitude(e, ctx.level, draws),
                                       1.0 + std::max(0, ctx.climb - 100)*0.01);
    if (shield) out.shield = out.rounds > 0 ? points : 0;
    else out.healing = std::min(points, max_hp-current_hp);
    return out;
}

} // namespace dfo_enc

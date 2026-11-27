#pragma once

#include "spell_kernel.hpp"

namespace dfo_firmament {

enum Channel {
    power, pierce, cast_speed, cost, destruction_cost, destruction, destruction_pct,
    speed, speed_pct, intelligence, intelligence_pct, mp, mp_pct, channel_count
};

struct Channels {
    int gains[channel_count]{}, prices[channel_count]{};

    void add(const Channels& node) noexcept {
        for (int index = 0; index < channel_count; ++index) {
            gains[index] += node.gains[index];
            prices[index] += node.prices[index];
        }
    }
};

struct Projection {
    int permanent_speed = 0, permanent_intelligence = 0, permanent_destruction = 0;
    int worn_intelligence = 0, quarters = 0, flat_capacity = 0, renown_sp = 0;
};

struct ChannelValue {
    int gain, price;
    int total() const noexcept { return gain + price; }
};

// firmamentLaw.js treeStats clamps gains before charging signed prices.
inline ChannelValue channel(const Channels& tree, Channel id, int lo, int hi) noexcept {
    const int gain = std::clamp(tree.gains[id], lo, hi);
    return {gain, std::clamp(gain + tree.prices[id], lo, hi) - gain};
}

inline int stat_gain(const Channels& tree, Channel raw, Channel pct, int permanent,
                     int pct_cap) noexcept {
    return std::clamp(channel(tree, raw, -15, 15).total() +
                      permanent * channel(tree, pct, 0, pct_cap).total() / 100, -15, 15);
}

// chargen.js defineLiveMaxMagicka and firmamentPowers.js firmamentLayer.
inline int maximum_sp(const Channels& tree, const Projection& base, int gear_intelligence) noexcept {
    const int gain = stat_gain(tree, intelligence, intelligence_pct, base.permanent_intelligence, 15);
    const int live = std::clamp(base.permanent_intelligence + gear_intelligence + gain,
                                0, 100 + std::max(gain, 0));
    const int unlayered = live * base.quarters / 4 + base.flat_capacity;
    const int flat = channel(tree, mp, 0, 75).total();
    const int share = std::max(0, unlayered) * channel(tree, mp_pct, 0, 15).total() / 100;
    return std::max(0, unlayered + std::min(75, flat + share) + base.renown_sp);
}

inline dfo_spell::Context project(dfo_spell::Context ctx, const Channels& tree,
                                 const Projection& base) noexcept {
    ctx.power_pct += channel(tree, power, -20, 30).total();
    ctx.pierce += channel(tree, pierce, 0, 10).total();
    ctx.cast_speed_pct += channel(tree, cast_speed, -15, 15).total();
    ctx.speed += stat_gain(tree, speed, speed_pct, base.permanent_speed, 15);
    ctx.live_skill = std::max(0, ctx.live_skill +
        stat_gain(tree, destruction, destruction_pct, base.permanent_destruction, 20));
    // The fixed supported spell is single-school Destruction.
    const auto general = channel(tree, cost, -20, 25);
    const auto school = channel(tree, destruction_cost, 0, 20);
    ctx.firmament_cost_pct = std::min(25, general.gain + school.gain) + general.price + school.price;
    return ctx;
}

}  // namespace dfo_firmament

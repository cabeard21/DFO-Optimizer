#pragma once
#include "encounter_kernel.hpp"
#include <memory>

namespace dfo_lifecycle {
// The physical loadout and owned policy are fixed here. Current HP/SP are supplied
// only after the search has applied purchases and all prior checkpoint outcomes.
struct EncounterOption {
    std::shared_ptr<const dfo_enc::Encounter> scenario;
    dfo_spell::Context caster;
    std::shared_ptr<const std::vector<dfo_enc::Spell>> book;
    std::vector<dfo_enc::Rule> rules;
    uint32_t seed{};
    int wellspring_pct=0;
};

inline uint64_t scene_bytes(const dfo_enc::Encounter& scene) {
    uint64_t bytes=sizeof(scene)+scene.enemies.size()*sizeof(dfo_enc::Foe)+
        scene.incoming.size()*sizeof(dfo_enc::Incoming)+scene.recovery.size()*sizeof(dfo_enc::Recovery)+
        scene.tape.size()*sizeof(double)+scene.rooms.size()*sizeof(dfo_enc::Room)+
        scene.wards.set_absorb_chances.size()*sizeof(int);
    for (const auto& foe:scene.enemies) bytes+=foe.wards.set_absorb_chances.size()*sizeof(int);
    for (const auto& room:scene.rooms)
        bytes+=room.enemies.size()*sizeof(int)+room.incoming.size()*sizeof(dfo_enc::Incoming);
    return bytes;
}
}

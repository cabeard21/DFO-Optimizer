#pragma once
// Included inside namespace dfo. Values are packed from authenticated creation
// kits.
struct StarterWeapon {
  int skill, materials, gear;
};

// Merge bounded native finalists from disjoint difficulty slices. Skill
// positions in a group keep their original mechanics, but use a shared
// signature for diversity.
class BeginnerPanel {
  using Shape = std::array<int, 28>;
  using TraitSet = std::array<int, 14>;
  using SkillOrder = std::array<int, 12>;
  struct Row {
    int difficulty, race, shape, traits, skills, headroom, gear;
    double sp;
  };
  std::vector<Row> rows;
  std::map<Shape, int> shapes;
  std::map<TraitSet, int> trait_sets;
  std::map<SkillOrder, int> skill_orders;

public:
  void add(int difficulty, int race, const std::vector<int> &traits,
           const std::vector<int> &skills, uint64_t backup, int headroom,
           int gear, double sp, bool refined) {
    Shape shape;
    shape.fill(-1);
    shape[0] = race;
    std::copy(traits.begin(), traits.end(), shape.begin() + 1);
    std::sort(shape.begin() + 1, shape.begin() + 1 + traits.size());
    std::copy_n(skills.begin(), refined ? 12 : 6, shape.begin() + 15);
    if (!refined) {
      std::sort(shape.begin() + 15, shape.begin() + 18);
      std::sort(shape.begin() + 18, shape.begin() + 21);
    }
    shape[27] = int(backup >> 28);
    int idx = shapes.emplace(shape, int(shapes.size())).first->second;
    int trait_id = 0, skill_id = 0;
    if (refined) {
      TraitSet traits_key{};
      SkillOrder skills_key{};
      std::copy_n(shape.begin() + 1, 14, traits_key.begin());
      std::copy_n(shape.begin() + 15, 12, skills_key.begin());
      trait_id = trait_sets.emplace(traits_key, int(trait_sets.size())).first->second;
      skill_id = skill_orders.emplace(skills_key, int(skill_orders.size())).first->second;
    }
    rows.push_back({difficulty, race, idx, trait_id, skill_id, headroom, gear, sp});
  }
  std::vector<int> select(int limit, const std::vector<int> &prior,
                          const CancelFlag &cancel, double seconds, bool refined) const {
    const auto started = Clock::now();
    std::vector<int> chosen;
    std::vector<bool> taken(rows.size()), used(shapes.size());
    std::vector<bool> used_traits(trait_sets.size()), used_skills(skill_orders.size());
    std::array<bool, 9> races{};
    std::array<bool, 53> difficulties{};
    auto accept = [&](int i) {
      const auto &r = rows[i];
      chosen.push_back(i);
      taken[i] = true;
      used[r.shape] = true;
      if (refined) {
        used_traits[r.traits] = true;
        used_skills[r.skills] = true;
      }
      races[r.race] = true;
      difficulties[r.difficulty + 12] = true;
    };
    for (int i : prior)
      accept(i);
    auto preference = [&](const Row &r) {
      int cost = chosen.size() < 2
                     ? -std::abs(r.difficulty - (chosen.empty() ? -12 : -11))
                     : 0;
      bool sp_first = chosen.size() % 2 == 0;
      return std::array<double, 9>{double(!used[r.shape]),
                                   double(cost),
                                   double(!difficulties[r.difficulty + 12]),
                                   double(!races[r.race]),
                                   double(refined && !used_traits[r.traits]),
                                   double(refined && !used_skills[r.skills]),
                                   sp_first ? r.sp : r.gear,
                                   sp_first ? r.gear : r.sp,
                                   double(r.headroom)};
    };
    while (chosen.size() < std::min(rows.size(), size_t(limit))) {
      int best = -1;
      std::array<double, 9> score{};
      for (size_t i = 0; i < rows.size(); ++i) {
        if (!(i & 255) &&
            (cancel.is_cancelled() ||
             (seconds &&
              std::chrono::duration<double>(Clock::now() - started).count() >=
                  seconds)))
          return chosen;
        if (!taken[i]) {
          const auto next = preference(rows[i]);
          if (best < 0 || next > score) {
            best = int(i);
            score = next;
          }
        }
      }
      accept(best);
    }
    return chosen;
  }
};
struct KitPart {
  int weight;
  std::vector<StarterWeapon> weapons;
};
struct BeginnerGate {
  std::array<int, 82> attack_costs{};
  // For each iron/steel and leather/chain kit variant: 35 skill rows and the
  // shared pack.
  std::vector<KitPart> parts;
  std::vector<KitPart> probes;
  std::vector<int> plate_weights, capacity;
  void add_part(int weight) { parts.push_back({weight, {}}); }
  void add_weapon(int skill, int materials, int gear) {
    parts.back().weapons.push_back({skill, materials, gear});
  }
  void add_probe(int weight) { probes.push_back({weight, {}}); }
  void add_probe_weapon(int skill, int materials, int gear) {
    probes.back().weapons.push_back({skill, materials, gear});
  }
  size_t bytes() const {
    size_t size =
        sizeof(BeginnerGate) + parts.capacity() * sizeof(KitPart) +
        (capacity.capacity() + plate_weights.capacity()) * sizeof(int);
    size += probes.capacity() * sizeof(KitPart);
    for (const auto *table : {&parts, &probes})
      for (const auto &row : *table)
        size += row.weapons.capacity() * sizeof(StarterWeapon);
    return size;
  }
  int verdict(const Candidate &c, int materials, int gear, int min_strength,
              int &headroom, uint64_t &backups) const {
    int metal = 10;
    for (int i = 0; i < 10; ++i)
      if (!(materials & (1 << i)) &&
          (metal == 10 || plate_weights[i] < plate_weights[metal]))
        metal = i;
    if (metal == 10 || (gear & (4 << 6)))
      return 1;
    const int luck = c.attributes[7];
    uint64_t skills = 0;
    for (int i : c.skills)
      skills |= uint64_t(1) << i;
    const bool merchant = std::find(c.skills, c.skills + 6, 14) != c.skills + 6;
    // Weights are integer 1/400 kg, including each gold piece.
    auto evaluate = [&](const std::vector<KitPart> &table, int offset,
                        int decile, int &room, uint64_t &usable) {
      const bool upgrade = 1 + 10 * decile <= (luck < 56 ? luck / 2 : luck);
      const bool steel = (materials & 1) || (upgrade && !(materials & 2));
      const bool chain = (gear & (1 << 6)) || (upgrade && !(gear & (2 << 6)));
      const int start = offset + 36 * (int(steel) * 2 + int(chain));
      int load = 5 + (luck - 5) * decile / 10 +
                 (merchant ? luck + (3 * luck) * decile / 10 : 0);
      usable = 0;
      for (int i = 0; i <= 6; ++i) {
        const auto &part = table[start + (i == 6 ? 35 : c.skills[i])];
        load += part.weight;
        for (const auto &weapon : part.weapons)
          if (!(weapon.materials & materials) && !(weapon.gear & gear))
            usable |= skills & (uint64_t(1) << weapon.skill);
      }
      room = capacity[min_strength] - load - plate_weights[metal];
      return (room < 0 ? 2 : 0) | (!usable ? 4 : 0);
    };
    int rejects = evaluate(parts, 0, 5, headroom, backups);
    for (int i = 0; i < 6; ++i) {
      uint64_t usable;
      int room;
      rejects |= evaluate(probes, 144 * i, 1 + 4 * (i / 2), room, usable);
    }
    return rejects;
  }
};

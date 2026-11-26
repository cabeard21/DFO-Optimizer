#pragma once
// Included by discovery_screen.hpp inside the dfo namespace.

struct FeaturePoint {
    Candidate candidate;
    ScreenFeatures features;
    uint64_t identity;
};

// Each race has an independent Pareto archive over observed screening features.
// This policy is only for admission. Equal features or a dominance relation
// here do not establish equivalence or dominance of feasible downstream builds.
class FeatureFrontier {
    static constexpr int maximum = 64;
    int limit{}, stages{};
    std::vector<FeaturePoint> points;

    static int coordinate(const ScreenFeatures& f, int axis) {
        switch (axis) {
        case 0:
            return f.sp_sum;
        case 1:
            return f.speed_sum;
        case 2:
            return f.destruction_sum;
        case 3:
            return f.hp;
        case 4:
            return int(f.absorption != 0);
        default:
            return f.eligible[axis - 5];
        }
    }
    int relation(const ScreenFeatures& candidate, const ScreenFeatures& incumbent) const {
        bool higher = false, lower = false;
        for (int j = 0; j < 5 + stages; ++j) {
            const int a = coordinate(candidate, j), b = coordinate(incumbent, j);
            higher |= a > b;
            lower |= a < b;
            if (higher && lower)
                return 2;
        }
        return int(higher) - int(lower);
    }
    size_t most_crowded() const {
        // NSGA-II crowding distance computed on the retained local point set.
        // Normalize each nonconstant axis by its observed extent. Absolute
        // feature scales therefore cannot change the overflow decision.
        std::array<double, maximum + 1> distance{};
        std::array<size_t, maximum + 1> order{};
        const size_t n = points.size();
        for (size_t i = 0; i < n; ++i)
            order[i] = i;
        for (int axis = 0; axis < 5 + stages; ++axis) {
            auto value = [&](size_t i) { return coordinate(points[i].features, axis); };
            std::sort(order.begin(), order.begin() + n, [&](size_t i, size_t j) {
                const int a = value(i), b = value(j);
                return a != b ? a < b : points[i].identity < points[j].identity;
            });
            const int span = value(order[n - 1]) - value(order[0]);
            if (!span)
                continue;
            distance[order[0]] = distance[order[n - 1]] = std::numeric_limits<double>::infinity();
            for (size_t i = 1; i + 1 < n; ++i)
                distance[order[i]] += double(value(order[i + 1]) - value(order[i - 1])) / span;
        }
        size_t worst = 0;
        for (size_t i = 1; i < n; ++i) {
            if (distance[i] < distance[worst] ||
                (distance[i] == distance[worst] && points[i].identity > points[worst].identity))
                worst = i;
        }
        return worst;
    }

  public:
    uint64_t overflows{};
    static int capacity_for(int race_slots) { return std::min(maximum, (race_slots + 1) / 2); }
    void initialize(int race_slots, int stage_count) {
        limit = capacity_for(race_slots);
        stages = stage_count;
        points.reserve(limit + 1);
    }
    void retain(const Candidate& c, const ScreenFeatures& f, uint64_t identity) {
        for (size_t i = 0; i < points.size();) {
            const int compare = relation(f, points[i].features);
            if (compare < 0)
                return;
            if (!compare) {
                if (identity < points[i].identity)
                    points[i] = {c, f, identity};
                return;
            }
            if (compare == 1) {
                // Transitivity: a point which dominates one frontier member
                // cannot be dominated by another current member.
                points[i] = points.back();
                points.pop_back();
            } else
                ++i;
        }
        points.push_back({c, f, identity});
        if (int(points.size()) > limit) {
            const size_t discard = most_crowded();
            points[discard] = points.back();
            points.pop_back();
            ++overflows;
        }
    }
    const std::vector<FeaturePoint>& retained() const { return points; }
};

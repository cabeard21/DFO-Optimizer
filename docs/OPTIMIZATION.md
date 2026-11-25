# Optimization

## Class search

The default query finds examples at the Dhargo construction floor. It uses HP 30, 3× INT Magery, all eight race IDs, a balanced all-50 class attribute vector, and one reproducible 12-skill assignment. Fixing the latter two domains keeps the first query focused on trait construction. Supply `attribute_domains` or twelve `skill_domains` to search alternatives. User-supplied skill slot order is meaningful, and all 12 selections must be distinct.

The public JSON request also accepts `race_ids`, `hp_values`, `trait_ids`, `required_trait_ids`, `difficulty_points`, `magicka_multiplier`, and the documented profile switches. Numeric IDs refer to the hashed bundle. A null Magery lock leaves Magery free. The certified domain includes request locks and profile exclusions. The optional `max_intelligence` objective maximizes the class-editor INT floor. Later rolled and earned attributes remain separate.

| Profile setting | Default | Effect |
|---|---|---|
| `require_day_and_night_casting` | true | Exclude all four limited or disabled casting options for daylight and darkness |
| `allow_high_risk_disadvantages` | false | Exclude damage from sunlight or holy places, critical weaknesses, and low tolerance to paralysis |
| `allow_unverified_advantageous_behavior` | false | Exclude inability to regenerate spell points. Explicit inclusion still marks recovery as unknown |
| `require_magic_school` | true | Require a magic school in the primary or major skills for the starting spell set |

The default node budget is 1,000,000 and the default native working-memory budget is 64 MiB. Set `max_nodes: 0` to remove the node cap or set a positive `wall_seconds` to add a wall-clock deadline. `memory_bytes` covers the estimated native search tables, compact input and retained candidates. Process RSS additionally includes Python, the allocator, stacks and JSON results. Scope and work counters are recorded separately in each result.

## Bounds and result identity

- Search native trait subsets in a stable order. A table indexed by suffix and remaining advantage/disadvantage allowances relaxes conflicts to compute reachable signed costs. If the required sum is absent from that superset, every legal completion fails as well. Search still checks accumulated conflict masks and required picks.
- Enumerate each distinct last writer within the three order-sensitive career fields. Other permutations of the same picks with identical writes and restrictions share one representative. Keep the full selected restrictions on each returned document.
- A suffix table for the remaining attribute domains rejects impossible balances. Skill masks enforce uniqueness across all groups. Check the first six slots for starting-set eligibility when requested.
- With `exact: true`, exhaust the declared domain subject to the stated budgets. Proof requires actual exhaustion or a proven inconsistent lock. Bounded examples can stop after the requested count. A node or time limit with no incumbent reports an incomplete search. Stable traversal resolves equal objectives. Wall-clock-limited incumbents can vary between runs.

The service reports native work and revalidates each finalist independently through the class document path. The deterministic digest excludes timing. All benchmarks in this milestone use one worker.

## Direct spell and equipment frontiers

Each frontier point gives the expected target HP actually lost per recast second and per SP. Target HP, current SP, effective casting skill, earned mastery, and the caster's speed belong to the frozen request. A fixed evaluation can also show pre-overkill damage and whether the caster can pay for the spell. The repeat-cast scenario assumes each cast lands on a target at the specified HP and funds are available.

For Damage Health, the two inclusive magnitude intervals, level divisor, five elements and four legal target modes yield 10,201,000,000 legal settings. The spell solver builds cumulative HP-loss tables and scores a pair of intervals with a rectangle sum. Complete Pareto queries retain a representative of each distinct nondominated metric pair. Exactness requires exhaustion of the declared domain. Finite budgets return the best points visited; use the reported limits, work counts and stopping reason to reproduce them.

Joint equipment search preserves physical copies, filters candidate slots and acquisition routes, and evaluates each retained modifier combination with the same spell kernel. Memoization is local to the request. Inspect both the outer equipment limit and the per-loadout spell limit. A complete traversal of loadouts with sampled spells still has a bounded result. The available and theoretical catalog modes describe their generated roll universe. A user can supply explicit observed copies and confirmed offers at actual prices.

Changing Intelligence equipment can lower the maximum SP during a swap. The solver checks immediate affordability, retaining casts affordable at the conservative available pool. If a possible higher pool could admit more recipes, the response reports `unknown_swap_capacity` on exhaustion. A separately supplied `capacity.post_swap_sp` models a stated hypothetical pool. Physical empty-hand locks also exclude the second hand occupied by a two-handed item. Each result records both the item's anchor slot and all occupied slots.

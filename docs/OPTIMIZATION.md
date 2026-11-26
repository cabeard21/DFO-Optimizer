# Optimization

Encounter search compares complete priority policies on the same initial state and seed panel. The reported proof applies to the submitted policies and finite trials. Event, memory, time or policy limits can terminate search early. Only completed policy trials enter the frontier. The independent replay verifies returned metrics and trace order. A fresh finite search is required to reproduce the optimality claim. [Encounter qualification](M6-M7-ACCEPTANCE.md)

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

## Spellcaster discovery

Select `spellcaster_discovery_v1` for a prospective class search. The default fixes HP at 30, Magery at 3× INT and difficulty at −12 (0.30×). It admits all eight races and the eligible trait catalog under the safety and casting settings above. Requiring simultaneous eligibility for six school masteries places three schools in primary, two in major and one in minor. Earning mastery still requires skill 100 and a free slot. Skill order affects which birth draws go to each school. The solver preserves the twelve ordered positions. Birth and progression replay use those positions for starting skills, spell selection and subsequent training opportunities.

The initial bounded search uses the configured coarse grid for each attribute and balances the editor's 400 points. Exhaustive mode uses the full declared domains. Adaptive lifecycle search can widen the panel and try the adjacent allowed attribute values around a replayed family while fixing its other class decisions. Every pass consumes the shared lifecycle budget. Its report identifies the domain, stopping reason and any neighborhood center.

The bounded native generator seeks one legal document per seeded traversal attempt and rotates through the races. Attempts may revisit a document. A packed identity includes HP, race, ordered skills, attributes and ordered traits. The native set compares the full identity on a hash collision. Per pass, `leaves` counts visited legal documents including repeats and `unique_screened` counts distinct screened documents. The sample cap is the larger of 256 and 64 times `top_k`. Node, time, memory or cancellation limits can end the pass earlier. Repeated work across lifecycle passes is charged again. Published family identities identify the distinct admissions.

Screening uses the common birth tapes and the source's default allocation of each birth pool. The feature frontier favors greater mean birth SP, cast rate, earned birth Destruction, initial HP, conditional spell absorption eligibility and compatible item count at each declared stage. Each race maintains a native feature frontier with capacity equal to half its panel allotment, rounded up, up to 64 representatives. Equal feature vectors share a representative in that frontier. When the frontier overflows, normalized crowding distance chooses a representative to remove, with a deterministic identity tie-break. Read `pareto_capacity`, `pareto_retained` and `pareto_overflows` in the native counters. Overflow can lose nondominated vectors. A panel smaller than the race count also limits how many race representatives can be published.

Additional positions preserve alternatives across race, trait selections and school placement. Material prohibitions affect the measured compatibility of actual items in each supplied pool. The lifecycle evaluator handles price, acquisition, occupied gear positions and competing loadouts. A conditional absorption flag records the source's effective last writer. An actual absorption event also requires the environment, a hostile spell and its verified combat conditions.

Class legality bounds cover suffix difficulty, attribute balance, skill membership and remaining mastery quotas. Feature comparisons only choose which families receive lifecycle work. Read enumeration, admission and downstream completeness independently. A reduced domain can prove an optimum after all three layers finish and every applicable witness passes replay. Results from a broad screened panel describe the evaluated families, birth rolls, scenario and search budget.

## Direct spell and equipment frontiers

Each frontier point gives the expected target HP actually lost per recast second and per SP. Target HP, current SP, effective casting skill, earned mastery, and the caster's speed belong to the frozen request. A fixed evaluation can also show pre-overkill damage and whether the caster can pay for the spell. The repeat-cast scenario assumes each cast lands on a target at the specified HP and funds are available.

For Damage Health, the two inclusive magnitude intervals, level divisor, five elements and four legal target modes yield 10,201,000,000 legal settings. The spell solver builds cumulative HP-loss tables and scores a pair of intervals with a rectangle sum. Complete Pareto queries retain a representative of each distinct nondominated metric pair. Exactness requires exhaustion of the declared domain. Finite budgets return the best points visited; use the reported limits, work counts and stopping reason to reproduce them.

Joint equipment search preserves physical copies, filters candidate slots and acquisition routes, and evaluates each retained modifier combination with the same spell kernel. Memoization is local to the request. Inspect both the outer equipment limit and the per-loadout spell limit. A complete traversal of loadouts with sampled spells still has a bounded result. The available and theoretical catalog modes describe their generated roll universe. A user can supply explicit observed copies and confirmed offers at actual prices.

Changing Intelligence equipment can lower the maximum SP during a swap. The solver checks immediate affordability, retaining casts affordable at the conservative available pool. If a possible higher pool could admit more recipes, the response reports `unknown_swap_capacity` on exhaustion. A separately supplied `capacity.post_swap_sp` models a stated hypothetical pool. Physical empty-hand locks also exclude the second hand occupied by a two-handed item. Each result records both the item's anchor slot and all occupied slots.

## Progression and lifecycle proof scopes

Progression returns nondominated routes for the supplied schedule of opportunities, resource observations and goal. Compare the number of practice actions, eligible raise passes, elapsed personal minutes and spending separately. Each route carries the actual decisions needed to reproduce it. A missing bank balance can block a paid reset while an unrelated, fully evidenced route remains usable. The replay command checks that exported actions and checkpoints agree with the frozen request.

Lifecycle compares stage-specific direct-hit DPS, progression effort and total gold spent on the same paired birth rolls. Its final-checkpoint-only view exposes the early score associated with maximizing the final checkpoint. The default paired panel uses eight seeds. A build with supplied realized rolls or an imported save has a single starting state. The optional `sensitivity` field reruns the same inputs at requested gold or node limits. `class_search` can supply a native M1 candidate panel. A truncated class panel also bounds the lifecycle proof.

For bounded family searches each class and roll receives an initial probe while budget remains. Unfinished pairs share the remaining nodes in larger trials ordered by observed final-checkpoint score. The reported work includes repeated exploration. Search retains earlier independently replayed witnesses. Read `stopping_reasons`, the covered rolls and the reported frontier recovery alongside timing. [Design decision](adr/0004-progression-and-lifecycle.md)

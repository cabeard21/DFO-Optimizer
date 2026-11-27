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

### Beginner class admission

The beginner workflow commits to one race and one ordered game class before drawing birth attributes or
forking scenarios. Its manual Breton and High Elf classes pass the pinned creator's import and Create
checks. A race control uses the Breton document unchanged on a High Elf. A material control retains the
Breton race and replaces the five-point Adamantium prohibition with the five-point Ebony prohibition.
The benchmark's explicit finite domains exclude these controls.

The production profile sets class HP to 30, Magery to 3× Intelligence and requires unrestricted day/night
casting. It checks simultaneous eligibility for three primary, two major and one minor magic school
mastery. It also requires at least one owned, affordable direct-damage spell on every paired birth.
Destruction in major grants Arcane Arrow. Primary also grants Minor Shock. The pinned
`calculateCastCost` table covers each raw birth skill. Certification checks the owned record and release
price using the independent progression evaluator. A character who starts with only healing or utility
may pass game creation while failing the beginner caster profile.
Slower advancement settings enter the same downstream evaluation as 0.30× classes. The default
sampler places a melee skill among the six starting-kit skills. It excludes phobias and disease
vulnerability by preference. Explicit trait domains can include them. High-risk disadvantages, reduced
magic, elemental or paralysis saves, the plate prohibition and unverified SP-regeneration loss fail the
profile. Disease vulnerability and phobias in an imported class remain visible to the player.

The native kernel counts admissible physical copies after applying item material, armor and weapon masks,
matching a trained melee skill and checking condition. It replays kit-table weights in integer units of
1/400 kg. Capacity uses realized Strength after birth allocation. A candidate must carry its pack,
gold and one compatible plain cuirass on every paired birth. The hypothetical cuirass is the lightest
compatible material available in the theoretical catalog. A report names it so an Ebony assumption is
visible. This test grants no item. Six source-generated equipment probes cover male and female characters
on constant 0.1, 0.5 and 0.9 kit tapes. An unreviewed mod weapon cannot establish a backup. The ordinary
lifecycle still uses the declared male 0.5 kit. Mixed RNG streams, biography rewards and acquisition
remain outside these certificates.

The per-family catalog report covers 180 weapon template–metal encodings, 143 armor template–material
encodings and 91 other wearable forms in the reviewed equipment catalog. It records accepted and rejected
material codes for each template, including the code-to-name table. These are class equip checks before
gender-specific wear, vendor availability, pricing, ownership and the acquired loadout. The
plate/weapon material count requires at least one reviewed career backup weapon type and an equippable
plain cuirass in the same metal.

Quick, Standard and Thorough request 4, 24 and 100 discoveries in addition to the two authored controls
and two authored baselines. When budgets permit, each larger panel retains the earlier panel in order.
Each disjoint integer difficulty slice receives at most 18,000 class nodes by default. Quick samples
−12, −11, −8, 0 and 16. Standard samples 21 slices and Thorough samples all 53. The default stat grid is
10, 20, 30, 40, 50, 60, 70 and 75 with the exact 400-point ledger. All eight races enter each slice.
The native frontier observes paired birth SP, speed, Destruction, capacity left after the kit and cuirass,
absorption and catalog compatibility. A native merge preserves different race/trait/group/usable-weapon
signatures first. It prefers the lowest-cost endpoint and neighboring cost for the first two slots, then
alternates actual birth SP with catalog breadth. These are admission choices. Final recommendations
use independently replayed scenarios. The report distinguishes visited nodes, unique creator-legal
classes screened, kit-certified candidates, admitted discoveries and evaluated builds. Exhaustion and
complete admission apply only to a named finite domain. A zero-result bounded screen leaves feasibility
open. A proven conflict may include a one-edit alternative with a named, already certified witness.

Regenerate the fixed probes with
`python tools/ruleset/beginner_classes.py --source vendor/dfo-source --check`.

### General spellcaster discovery

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

# Codex handoff: Daggerfall Online spellcasting build optimizer

**Project:** `dfo-optimizer` (proposed repository name)  
**Date:** 2026-11-24  
**Status:** implementation specification, not an implemented optimizer  
**Primary user objective:** discover the strongest practical spellcasting characters from character creation through capped progression, and optimize their spells, equipment and upgrade paths.  
**Default optimization policy:** Dhargo-style minimum legal advancement difficulty; solo PvE first; evaluate both progression and endgame rather than hard-coding a preferred class.

## 1. Instructions to Codex

Implement a standalone, locally runnable, deterministic optimization application. Start by inspecting the source repositories below. Pin the ruleset, document its supported mechanics, and establish native computation and validation infrastructure in the first milestone. Do not implement a slow Python exhaustive search with the intent of compiling it later.

Treat this document as the product requirements and initial architecture, not as a claim that all previously discussed mechanics are correct. Source code, verified in-game observations and explicitly identified assumptions take precedence over prior AI recommendations. If the workspace already contains code, inspect it before changing the proposed layout. Do not modify either reference repository or the running game. Keep the application offline and read-only with respect to the game; import user-provided data and export plans. Do not automate gameplay, inject into the client, or call undocumented private game endpoints.

Work in vertical slices that are runnable and tested. Each milestone must leave a usable CLI and a reproducible benchmark. Document decisions in short ADRs, run the acceptance commands, and report observed results, unresolved mechanics and performance regressions. Do not label a milestone complete based on scaffolding alone.

### Reference repositories and evidence

- **Primary mechanics:** https://github.com/Lattymoy/daggerfall-js-source — the repository README identifies the public edition as the 2026-11-02 snapshot and states that live development continues privately. Pin an actual commit SHA at implementation time, not just `main`. The repository is MIT-licensed; preserve applicable notices when reusing code.
- **Reference application:** https://github.com/cabeard21/osrs_recommender — review `README.md`, `docs/ARCHITECTURE.md`, `pyproject.toml`, `tracker/gear/`, relevant tests, native build scripts and benchmark infrastructure. Its documented gear domain uses a shared service, frozen inputs, explicit hypotheses, item restrictions, budget, bounded search and transparent unsupported mechanics. Its project configuration includes an optional Cython 3 native build. Carry over the principles, not OSRS-specific formulas or database models.
- **Secondary reference:** https://www.daggerfallonlinewiki.com/ — source-linked discovery and descriptions; resolve discrepancies against the pinned code.
- **Build comparison:** Dhargo's DFO Advanced Martial Build Guide: https://docs.google.com/document/d/1DsTl-Ry2wIKL5fnAyqNQfp83S4ZMb_gkUvpFjJz6xxg/edit ; sample class files: https://drive.google.com/drive/folders/1GNvjKwC8XU5wXPA3VMkdWFNp3efRr8wb. Import available samples as validation fixtures, if supplied or accessible. These sample files have not been audited in this handoff. The user's stated design constraint is that Dhargo's builds sit at the minimum negative difficulty. Do not assume the guide's martial tradeoffs are automatically safe for mages.

## 2. Product scope and success criteria

The application should answer these questions using the same underlying mechanics engine:

1. **New character:** What legal race, class attributes, health setting, advantages, disadvantages, skill assignments and mastery choices produce the best caster for a specified goal, while achieving the difficulty floor?
2. **Progression:** For that exact starting character, what should I train, which permanent masteries should I select, where should I spend attribute points, which spells should I buy/create, what gear should I equip, and when should I switch specializations? What are the next meaningful milestones from my current state?
3. **Spellmaker:** Which legal spell settings and spellbooks optimize damage, cast cost, sustain, survival and utility at my actual level and skill values against specified targets?
4. **Gear optimizer:** What complete legal equipment configuration is best for this build, target and budget? What is the best owned loadout, what upgrades are worthwhile, and what is the theoretical best attainable loadout? Include enchantments, affixes, sockets and conditional powers when supported by evidence.
5. **Capped character:** What are the Pareto-optimal final character states and complete loadouts? Which class decisions permanently limit them, and how much progression effort is required to reach them?
6. **Sensitivity:** How does the recommendation change with target resistances, encounter duration, enemy density, availability, budget, risk tolerance, mechanics uncertainty or objectives?

Do not define one universal best mage. Provide a clearly specified default and selectable objectives. The same build can be best at burst DPS and poor at sustained dungeon clearing. A higher peak DPS result is not automatically better for a low-level character.

### Initial scope

- Solo PvE direct damage and resource costs first, then protection, healing, sustained combat, multi-target and conditional powers.
- Pure spellcasters first; support spellswords as a later search profile without baking martial assumptions into the data model.
- Support new-character planning and imported/manual current-character snapshots. Preserve immutable choices when optimizing an existing character.
- Progression from initial state to the confirmed cap, including post-level-cap mastery and supported permanent power progression. Distinguish character-level cap from mastery and equipment caps.
- First-class gear and spell optimization, not just an endgame build list.
- No universal tier list, fabricated market prices, gameplay bot, online save mutation or unverified PvP ranking. PvP and party support must be separate rulesets when implemented.

## 3. Mechanics extraction and version control

### 3.1 Ruleset pipeline

Clone or otherwise obtain the public source locally. Keep it read-only and outside the application package (for example `vendor/dfo-source`, gitignored if appropriate). Record the source URL, SHA, snapshot date, extraction schema version, generated content hash and supported live client version (unknown unless actually established). Supply a command such as `dfo ruleset build --source <path> --commit <sha>` that produces a reviewable ruleset bundle. Optimizing a frozen bundle must require no network requests.

Use typed, deterministic extraction of source constants, catalogs and IDs where feasible; prefer invoking pure JS exports in a pinned Node test harness or AST extraction over regex over minified or localized code. Extract only what is needed, validate all generated data and keep hand-authored interpretations separate. Do not execute arbitrary user-supplied JavaScript. If full game assets are required, document the legitimate acquisition procedure and do not redistribute proprietary assets.

Maintain a mechanic registry containing `mechanic_id`, implementation status, source SHA, file/symbol/line or test reference, mode applicability, known limits, assumptions, and verification status. Suggested statuses: `source_verified`, `live_verified`, `assumption`, `unsupported`, `conflicting`. A source-confirmed mechanic is not necessarily live-confirmed. A release note may indicate a change without supplying its complete formula. Never silently use vanilla Daggerfall/DFU behavior to fill missing DFO mechanics.

### 3.2 Source audit checklist

The following paths are entry points, not an exhaustive inventory. Locate the authoritative call sites, tests, server-facing behavior and data definitions in the pinned tree; do not rely on a function's name alone.

| Mechanic | Source entry points |
|---|---|
| Class construction and import/export | `src/systems/customClass.js`, `specialAdvantages.js`, character creation UI/wizard and serialization code |
| Races, attributes, skill values and class skills | `src/systems/races.js`, `skills.js`, `statMods.js`, `src/combat/formulas.js`, level-up and mastery modules |
| Progression and training | `src/systems/skillSoftcap.js`, skill-use/challenge gating, mastery, level-up, training, starting rolls and biography modules |
| Spell legality and cost | `src/systems/spellcost.js`, `spellcast.js`, `spell/spellMaker.js`, `effects.js`, spell catalogs |
| Casting throughput and potency | `src/systems/castSpeed.js`, `spell/spellPower.js`, actual casting animation/cooldown scheduling |
| Resistance and absorption | `spellcast.js`, effect-specific application paths, race/class flags, enemy definitions |
| Specializations | `src/systems/arcanePowers.js`, martial power and specialization unlock/change logic |
| Loot, affixes, caps and progression powers | `src/systems/loot/lootPowers.js`, `firmamentPowers.js`, related loot/catalog, progression and set modules |
| Equipment and crafting | `src/systems/equip.js`, `armorMaterials.js`, `enchanting.js`, `enchantmentCatalogue.js`, item/weapon templates, artifacts, gems, crafting and economy paths |
| Recovery and physical tradeoffs | `src/systems/rest/rest.js`, `potionRecipes.js`, `src/combat/pcaao.js`, physical combat, disease/poison/paralysis paths |
| Targets and encounter scaling | enemy catalogs, enemy scaling, combat/mastery hooks, damage and mitigation, online instance behavior |

### 3.3 Verified initial invariants and hypotheses

The public `customClass.js` directly defines class HP setting bounds 4–30, difficulty bounds −12 to +40, editable attribute bounds 10–75, and an initial attribute value of 50. It defines HP difficulty contribution as `hp - 8` for HP ≥8, otherwise `-2*(8-hp)`; total difficulty adds trait costs. The advancement multiplier is `0.3 + 2.7*(difficulty+12)/52`. Thus at difficulty −12 it is 0.30, and HP setting 30 costs +22. Verify final class validation, sum-preserving attribute editing, and serialization as well as the numeric formulas. The same file builds 3 primary, 3 major and 6 minor skill entries. `specialAdvantages.js` defines a seven-item maximum and unique-choice categories; audit per-window limits and every incompatibility gate.

The following are **regression candidates from earlier discussion, not certified implementation facts**. Audit each before ranking candidates using it:

- Max Magery 3× INT, proposed cost +10; floor class goal and no day/night casting restriction by default.
- Online resting may ignore the Inability to Regenerate Spell Points restriction. Verify online mode and all relevant recovery paths; this could differ on the live server. Provide an alternate profile where the restriction has its intended adverse effect. Do not market a build that depends on unintended behavior as robust.
- Phobias may affect physical damage but not spell effects. Trace direct, indirect, signature and proc damage and any attack-roll impact. If a phobia is harmless for pure casting, it still restricts fallback attacks and uses a class slot.
- Racial/class saving-throw ordering, immunity thresholds and conditional absorption must be tested, not assumed from displayed text. A Breton resistance stack or High Elf immunity may interact with weaknesses in non-obvious ways.
- Source-discussed level cap 45, six permanent mastery selections (3 primary / 2 major / 1 minor), trained cap 200 versus effective skill 140 before further modifiers, and specialization pairing/change costs. Confirm each and the actual skill-count/level-up law. Never confuse effective skill, earned skill and equipment-boosted skill.
- Source-discussed cast rate `1 + (SPD-50)/200`, cast rate cap 2, effect price and school-cost scaling, five-SP minimum, scaling magnitude and duration, and earned mastery potency. Verify integer rounding, floors, modifier order, applicable effects, target multipliers and minimum costs. Prior example spell costs/damage and specialization rankings are not golden values.
- Soulbinder, Battlemage, Riftwalker, Shadowcaster, Spellbreaker, Necromancer and Elementalist: confirm mastery prerequisites, signature cooldowns, kill/mark/shield/concealment conditions, resource returns, and how they actually affect sustained throughput. Do not assign 100% conditional uptime by default. Audit all other available specializations, not only these candidates.

Seed the previous proposed High Elf and Breton mage classes as untrusted comparison fixtures, once their trait legality is checked. The optimizer must be able to beat them, not be constrained to reproduce them. Export class JSON only using the real validated game format. Do not infer a schema from previous conversations.

## 4. Optimization objective and constraints

### 4.1 Hard constraints (default `dhargo_pve` profile)

- Exactly the minimum legal class difficulty, **−12**, advancement multiplier **0.30×**. Reject values below the legal floor; do not merely clamp display or advancement while allowing invalid classes.
- Default lock 3× INT Magery and 30 HP setting as requested design priorities, subject to legal source validation. Expose independent locks so a sensitivity run can determine whether relaxing them improves performance. If the combined locks are infeasible, report that rather than silently increasing difficulty.
- No total inability to cast in daylight or darkness; default excludes partial casting restrictions and high-risk damage/paralysis penalties. User can explicitly allow them in a separate profile.
- Legal unique skills, class trait combinations, attribute bounds and budget, race restrictions, earned points, prerequisites, mastery quotas, specialization exclusivity and all equipment requirements.
- Respect exact available resources, item locks, inventory counts, carried weight/slots, acquisition access and time/version assumptions. Do not assume a maxed character at early checkpoints.
- Default require positive practical damage capability from character creation and a verified feasible training route, unless explicitly running a cap-only theoretical query. For unsupported early mechanics mark the relevant plan portion unknown, not proven feasible.

### 4.2 Objective functions

Return separate metrics, Pareto frontiers and configurable rankings rather than hiding tradeoffs in one arbitrary rating. Support lexicographic ordering, minimum floors (e.g., survival and magicka reserve), weighted objectives with declared normalization and scenario weights, and top-K diverse results. Default priority: feasible progression, then sustained solo dungeon efficiency, then endgame damage/survival tradeoffs. Provide explicit presets for `early_game`, `balanced_progression`, `sustained_dungeon`, `boss_burst`, `boss_sustain`, `tank_caster`, `low_budget`, `owned_only` and `theoretical_bis`. User-defined floors override defaults.

Metrics:

- **Damage:** expected delivered damage/cast, damage/second, damage per actual SP spent, probability/distribution of lethal damage, overkill, time-to-kill and kill throughput.
- **Sustain:** spell costs, healing/mitigation cast opportunity cost, regeneration/refund/absorption, expected net SP over an encounter, capacity clipping, potion usage, rest frequency and time. Report damage/SP as undefined when denominator is zero; do not use infinities to rank a build.
- **Defense:** HP, armor, resistance and save outcomes, damage taken, shield and healing uptime, incoming physical/magical damage, status hazards, death probability or explicit proxy, action lockouts, recovery and resources. Avoid a universal EHP formula where the underlying mechanics differ.
- **Progression:** skill practice requirements, gate feasibility, milestone effort, capped-state value, gold or other currency/resource costs, and time only where a supported rate model or user assumption exists. Count rest, travel/training and resource time if modeled. Unknown time is not zero.
- **Robustness:** performance against different targets and environmental conditions, including adverse ruleset assumptions. Provide worst-case or quantile metrics as alternatives to expected value.

For progression, use one consistent set of irreversible class decisions across all milestones. Let `Q_t` be a stage score for an explicit scenario mix and `w_t` its declared weight; an optional normalized objective is `sum(w_t * Q_t)` minus declared effort/cost penalties. Also support lexicographic and Pareto comparisons without scalar weights. Do not use arbitrary level weights to imply real leveling time. Provide a cap-only objective separately and show its early-game tradeoffs. State whether metrics cover direct-hit damage, a restricted rotation or a full supported encounter model.

### 4.3 Scenarios and evaluation fidelity

Represent each target/scenario with versioned data: level/tier, source-linked enemy type and scaling inputs, HP, element/effect saves and immunities, incoming damage/timing, range and AoE hit counts, combat horizon, environment, movement/interruptions if supported, initial HP/SP, encounter sequence and recovery rules. Mark authored weights and hit counts as assumptions. Include real source-backed examples as available plus synthetic stress tests.

Use a cheap exact/analytic evaluator for supported direct damage and expected outcomes. For more complex cases use a deterministic event engine with exact discrete transitions or distributions where practical, and seeded Monte Carlo only where necessary. Simulate casts, legal timing/cooldowns, ongoing effects/tick ordering, stacking/refresh, shielding, kills, resource caps, buffs, procs and interruptions. Use common random numbers for comparative Monte Carlo, publish seed, sample count and confidence/error estimates. Never treat ratio of expectations as an exact time-to-kill. Report censored failures (e.g., runs that run out of magicka) rather than averaging only successful kills.

## 5. Search engines and coupling strategy

Do not form the Cartesian product of every race, trait combination, stat allocation, mastery, spell, gear configuration and progression path. The space is combinatorial; decompose it while preserving correctness labels. Every candidate returned by any search must pass a final independent feasibility and mechanics evaluation. Exactness is scoped to the declared ruleset, objective, candidate universe, and modeled effects.

### 5.1 Class and mastery search

- Enumerate legal advantages/disadvantages by stable numeric ID. Build conflict bitsets and per-category limits from verified rules. Use cost reachability DP, meet-in-the-middle subset enumeration or branch-and-bound by remaining trait slots and reachable signed cost. Precompute feasible `(hp, adv_mask, dis_mask)` groups. Respect legal intermediate/import constraints if the real creator imposes them.
- Iterate all applicable races. Preserve material/armor/weapon prohibition masks, effect modifiers, environmental flags, start bonuses and disadvantages through later stages. A restricted class cannot be evaluated using unrestricted BIS gear.
- Group class trait combinations only when their future mechanical effects, constraints and acquisition/training implications are equivalent for the entire objective. Retain distinct alternatives where risk or progression differs. Do not prune on magicka and health alone.
- Enumerate or optimize class stat allocations under the exact attribute budget, actual integer increments and chargen limits; do not permanently assume INT/SPD/END/WIL are the optimum. Keep starting floors, random/allocated chargen bonus points and later earned attribute points distinct. Condition recommendations on actual rolls or evaluate a declared roll distribution. Avoid assuming maximum rolls in ordinary progression.
- Treat class skill group and mastery selection as decision variables. Use symmetry reduction only when skill ordering is truly irrelevant. Mastery placement must account for group quotas, XP and level-count effects, unlock paths, training restrictions and future specialization options. Include backup/utility skills; support all-six-schools as an explicit profile rather than a hard rule for all objectives.
- Generate all legal specialization options from mastery state. A future specialization cannot contribute earlier, and a switch consumes the confirmed currency/time cost and must satisfy any locks. Support permanent decision locks for an existing character.

### 5.2 Progression planner

Model progression as a directed state transition problem. A state records actual level, earned/base attributes and unspent points, trained and effective skill values, practice/gate state, mastery slots, available specializations, permanent powers, unlocked spells, inventory/equipment, resources, and source/observation provenance. An edge is a legal activity or decision with prerequisites, changes, and an effort/cost model. Include events for earned skill milestones, level-ups, attribute allocation, mastery selection, training and real-use gates, acquiring spells, gear acquisition, specialization swaps, enchanting and supported permanent progression. Do not assume all attributes/skills can rise independently to their caps.

Use event-driven checkpoints, not an arbitrary skill-by-skill loop over every possible point. Derive important breakpoints (cost floor changes, level milestones, mastery/gear/specialization unlocks, damage/cast-time breakpoints), while retaining intermediate states needed to establish reachability. Default display milestones: actual starting state, levels 5/10/15/20/25/30/35/40, confirmed level cap and capped mastery/power state; merge or change these when rules dictate. Always report user-requested checkpoints.

- For reduced fixtures, solve the state graph exhaustively or with exact multiobjective DP/shortest-path search. In production use Pareto label-setting with dominance only over states with identical future-relevant constraints, then bounded best-first/beam search where the state explosion demands it. Beam width and quantization are explicit quality controls, not proof of optimality. Revisit promising candidates with expanded budgets.
- A stage gear or spell result is a feasible configuration for that stage, not necessarily globally optimal. Reuse purchases across stages, retain prior owned items and charge only incremental expenditure. Include resource acquisition and training conditions; distinguish required practice count from wall time. No fictional loot drop rates or training rates.
- Use a coarse-to-fine outer search over class/mastery families; inside each, plan milestones and use gear/spell optimizers with progressively larger candidate budgets. Preserve a diverse frontier and reserve a share of the search budget for candidates initially ranked poorly. A class that loses at level 1 may win later, and vice versa.
- Keep an independent reachable-plan validator that replays the selected decisions. Return a cap-only upper-bound comparison if legal reachability cannot yet be established, clearly marked as theoretical. Never silently bridge unavailable actions, missing unlocks or unsupported training gates.
- Report the selected class, chronological stage states, recommended actions, incremental and cumulative effort/cost, skill/mastery/attribute decisions, spells and gear changes, unlocks, metrics and alternatives. Allow resuming the plan from an observed character snapshot and reoptimizing remaining choices.

### 5.3 Spellmaker and spellbook optimizer

Represent a spell as target mode, element and one or more legal effects with their exact magnitude ranges, level scaling, durations, chance, effect-specific options and any spellmaker limits. Include purchased/predefined spells and specialization signatures when available. Decode from and encode to human-readable game settings.

- Enumerate legal single effects and settings natively. Derive valid ranges from the spellmaker and effect catalog; do not assume all effects share ranges or modifiers. Include touch, ranged, area, self, and other supported targeting types with real constraints. Distinguish level-scaled damage from fixed magnitude, DOT from immediate damage, and effect-element resistance from school skill.
- Calculate cast cost, effective timing, damage/healing distribution, duration and utility exactly under the frozen character/target state. Retain cost/magnitude discontinuities, integer rounding and minimum cost plateaus. Only reduce a parameter to a breakpoint when proof shows it cannot remove an optimum for the entire considered interval. Preserve variable magnitude/chance distributions where they affect kill probability, wasted damage or procs.
- Build exact or bounded Pareto frontiers of legal single-effect spells; combine multi-effect spells subject to effect count, target compatibility, cost interactions, rounding and cast savings. Dominance on isolated effects is unsafe when combined rounding or triggered effects differ; disable it unless proven. A high expected magnitude is not universally preferable to reliable lethal damage.
- Optimize the **spellbook and casting policy**, not just one spell. Include efficient fillers, burst, multiple elements, area, shield/heal, resource recovery, debuffs and relevant utility. Model training spells separately, with real-use skill progression gating and legality. Include purchase/creation cost, availability and casting conditions.
- Offer `fixed_spell`, `auto_spell`, `fixed_spellbook` and `auto_spellbook`. Enumerate bounded legal policies or small rotations for early implementation. For richer scenarios, use event simulation and state-dependent policies (health, shield, SP, target condition, cooldowns). Report what policy space was searched. An instantaneous unrestricted recast is not an admissible policy.
- Cache compact spell primitives using relevant level, earned/live skill, modifiers, effect configuration, target and ruleset version. Avoid creating Python objects for every combination or recalculating all spells per gear leaf.

### 5.4 Gear optimizer (OSRS Recommender equivalent)

Implement a shared `GearService` with immutable inputs and outputs. At minimum accept character snapshot, scenario, objective, fixed/auto spell policy, equipment/item locks, exclusions, budget, permitted acquisition modes, and search limits. Support complete slot sets, occupied/empty slots, alternative forms, two-handed conflicts, slot multiplicity, duplicate/unique limits, class/race restrictions and acquisition gates. Derive the slot universe and all rules from DFO, not OSRS.

Item data must distinguish:

| Catalog layer | Meaning |
|---|---|
| Item template | Base type, slot(s), allowed materials, inherent stats, level/skill requirements and other restrictions |
| Concrete item instance | Specific material, rolled affixes and values, enchantments, sockets, charges, condition, unique identity |
| Affix/power definition | Eligibility, value ranges, effect stacking groups, caps, activation conditions, source and supported evaluator |
| Acquisition evidence | Confirmed owned, observed price/time, source availability, drop/craft requirements, or explicit unknown |

Offer four gear modes: `owned_only` (specific observed copies); `owned_plus_budget` (legal confirmed acquisitions within known incremental cost); `available_catalog` (known obtainable gear without requiring ownership); `theoretical_bis` (explicitly hypothetical legal rolls). Also support user-imported candidate sets. Randomized loot is not a single fixed item: do not enumerate impossible affix combinations, assume max rolls are readily obtainable, or treat an unsupported item effect as zero. Display ideal rolls separately from items the player can actually equip or acquire. If prices are absent, offer price-independent tradeoff tables or known-cost feasible subsets; unknown is not free. Treat currencies separately unless a confirmed exchange rate applies.

**Native search strategy**

1. Build filtered slot domains using legal requirement masks. Preserve physical item identity and copies. Produce reason codes for filtered candidates.
2. Compile compact modifier contributions, slot occupancy bitsets, activation tags, set membership, acquisition resources and conditional-effect state. Pre-sort high-quality candidates to establish strong early incumbents.
3. Apply conservative exact-equivalence and proven dominance reductions. Do not prune solely on isolated spell damage, armor, price, or nominal stat sum. Stat caps, thresholds, set bonuses, elemental matchups, cast-cost floors, unique-item interactions and spell/gear synergy can reverse dominance. Use exhaustive differential tests to validate each reduction.
4. Search legal complete configurations with native branch-and-bound. Order constrained slots first; incrementally update occupancy, resource totals and modifier aggregates. For upper bounds, use optimistic remaining contributions and relax coupling only in the direction that preserves admissibility. If a valid bound cannot be established, do not use it for exact pruning. Include all compatible spell possibilities in the optimistic bound when claiming joint exactness.
5. Use bounded beam, best-first or staged shortlist methods for very large theoretical spaces; retain candidates around meaningful caps and conditional synergies. Report discarded candidate counts, search limits and the scope of any exactness claim. Use incumbent warm-starts and wider reruns for quality checks.
6. Re-evaluate finalists with the complete supported mechanics (including selected spells, procs, resource clipping, defense and encounter dynamics). Validate equipment actions and resources independently. Produce top-K diverse setups, not permutations of indistinguishable rings or equivalent equipment.

Return a complete loadout, physical item IDs and roll details, total and capped modifiers, spells/policy, damage and sustain metrics, defense metrics, acquisition plan, budget remaining, changed equipment, per-item marginal change under reoptimization, rejected alternatives and explanation of binding constraints. Provide best-owned vs budget-upgrade vs theoretical-BIS comparisons. Marginal benefit must be computed by a full valid reevaluation, not isolated additive stats. Support item locks and alternative loadouts for different scenarios, including shared inventory and purchases in a later joint multi-role mode.

### 5.5 Joint optimization and correctness labels

The best spell depends on gear, the best gear depends on spells, and both depend on the class and target. Do not optimize each once in isolation and label the result globally optimal.

- For small domains, implement an exact joint spell/gear/class benchmark solver to establish oracle results. For larger domains, use nested search with shared feasible incumbents, admissible relaxed upper bounds where available, and memoization keyed by relevant class/state/scenario. Use alternating optimization and top-K expansion as heuristics, not proofs. Report gaps only from mathematically valid bounds.
- At early search stages use cheap validated proxies/relaxations to prioritize work. Final ranking must use the requested supported fidelity. Keep candidates diverse enough to avoid systematically eliminating builds whose strength is sustain or conditional interaction.
- Result statuses: `optimal_proven` (declared finite search space exhausted or bounded with proof), `best_found_bounded`, `infeasible_proven`, `no_feasible_found`, `unsupported`, `cancelled`. Add explicit candidate scope and data-coverage fields. Timeout/beam exhaustion is never proof of infeasibility. Exactness over a shortlist is not exactness over the full catalog.

## 6. Performance-first implementation architecture

### 6.1 Technology choice

Recommended default: Python 3.12+ for typed domain contracts, ingestion, CLI, orchestration, reports and optional local UI; **Cython 3 with C/C++** for mechanics hot paths and search. This follows the user's prior OSRS workflow but avoids postponing compilation. Use one native implementation, not redundant production implementations in multiple compiled languages. Rust/PyO3 or a fully native stack is acceptable if Codex documents a concrete portability/performance/maintenance reason before implementation. Native execution is mandatory regardless of language choice.

Package using `pyproject.toml` and a reproducible PEP 517 build, with pinned compatible dependencies, platform build instructions and CI-built wheels at least for Windows x64 and Linux x64. Support local desktop execution first; portable Linux and ARM64 are useful later. Do not require a cloud service for optimization. Python reference implementations exist only for tiny-fixture testing, explanation and differential validation; no silent fallback to interpreted production search if a compiled module is missing. Fail clearly with build instructions or offer an explicitly limited reference/debug mode.

### 6.2 Suggested layout

```text
 dfo-optimizer/
   AGENTS.md                   # non-negotiable mechanics, performance and test rules
   README.md                   # installation, examples, known limitations
   pyproject.toml              # native build and dependencies
   Makefile                    # install/build/test/benchmark/validate targets
   docs/
     ARCHITECTURE.md
     MECHANICS.md               # source-linked coverage matrix
     OPTIMIZATION.md            # objectives, search scope and proofs
     PERFORMANCE.md             # baseline hardware, profiling and regression policy
     adr/
   src/dfo_optimizer/
     domain/                    # frozen typed contracts, IDs, validated assumptions
     content/                   # catalog and ruleset loading, provenance
     reference/                 # independent slow reference for small inputs
     native/                    # .pyx/.pxd + optional C++ kernels
       mechanics.*
       class_search.*
       spell_search.*
       gear_search.*
       progression_search.*
       encounter_sim.*
     services/                  # shared deterministic public entry points
     cli/                       # CLI and JSON results
     storage/                   # local versioned snapshots/caches, not authoritative rules
     ui/                        # later milestone; uses services only
   tools/
     extract_ruleset/           # pinned JS source adapters / Node oracle
   content/                     # generated data + reviewed annotations
   tests/
     unit/ parity/ exhaustive/ property/ integration/ regression/
     fixtures/
   benchmarks/
     workloads/ results/
```

The layout is a proposal; preserve an existing repository's conventions if present. Keep a clean dependency direction: `domain/content -> mechanics/native -> search -> services -> CLI/UI/MCP`. One scoring/evaluation path for all surfaces, not independent UI calculations.

### 6.3 Native kernel contract (non-negotiable)

- All high-cardinality loops: class subset enumeration, attribute/mastery scans, spell parameter enumeration, equipment DFS/bounds, large frontier maintenance, simulation batches and progression expansion — must run as compiled typed code. Even small mechanics functions called from these loops must not cross into Python.
- Expose coarse-grained batch calls through typed memoryviews/contiguous numeric arrays or C structs. Use stable integer IDs, bitsets, packed enums, indexed tables, structure-of-arrays for hot vectors where appropriate, and compact state IDs. Avoid Python dataclasses, dictionaries, strings, tuples, per-leaf allocation and callbacks in inner loops. Convert validated domain objects once per request or ruleset load.
- Use `cdef`/`cfunc`, typed loop variables, `noexcept` where safe, `nogil` kernels and C/C++ containers/preallocated arenas. Verify that `nogil` code does not repeatedly reacquire the GIL for exceptions or callbacks. Release it during CPU-bound batches. Disable bounds/wrap checks only in validated regions with tests and debug builds. Inspect Cython annotation output for unintended Python interaction.
- Use correct integer widths and JS-compatible truncation/floor/rounding semantics; do not blindly use C integer division for negative values. Match ordering and caps exactly. Avoid `-ffast-math` or unsafe numeric shortcuts unless equivalence is proven. Account for overflow, NaN/unsupported states and deterministic ties.
- Precompute ruleset-dependent tables once (costs, valid combination masks, static item contributions, skill thresholds, affix constraints), use incremental aggregates and rollback in search, reuse scratch space and avoid copying full character/loadout state per branch.
- Limit Python/native crossings to validation, batched submissions, coarse progress/cancellation and result decoding. Construct detailed explanations for selected finalists, not every search node.
- Use bounded caches with keys including ruleset hash, mechanic/engine version, relevant normalized state, candidate set, scenario, objective and search assumptions. Cache score components separately when dependencies are smaller. Distinguish exact results from budget-limited incumbents. Invalidation must cover version, content, ownership and price changes. Avoid network or database queries in hot paths.
- Add parallelism only after serial native search and pruning are efficient. Partition independent root branches, scenarios or build families; native threads with GIL released or processes with shared/memory-mapped read-only data. Use deterministic work ordering/merge and stable tie-breakers. Avoid oversubscription, copying entire catalogs per task and nondeterministic reduction drift. Default to a sensible worker limit and allow override. Measure 1/2/4/8-worker scaling; reproducible node-budget mode should return stable results independent of worker count where promised.
- Provide cancellation and time/node/memory budgets, with an anytime best feasible incumbent and coarse progress counters. UI must stay responsive; do not run optimizer work on its event loop. Separate reproducible node limits from wall-clock limits (the latter may return different incumbents). Never kill a search without returning its termination reason where possible.

### 6.4 Benchmark plan and performance gates

Create benchmarks **in milestone zero**, before a real catalog/UI. Record hardware, OS, Python/compiler versions, native flags, source hash, catalog dimensions, search parameters and seed. Use fixed reproducible synthetic fixtures and source-backed representative workloads. Include cold and warm runs, single-worker baselines and multiworker runs. Measure wall time, CPU time, p50/p95, peak RSS, allocation counts where practical, nodes visited/pruned, leaves scored, evaluations/sec, cache hit rate, bound/heuristic quality and final objective.

Initial engineering targets below are **proposed acceptance budgets, not measured performance or promises**. On a documented modern desktop with at least 8 logical CPU threads and 16 GB RAM, calibrate a single-worker baseline before changing any targets. Preserve exact fixture correctness irrespective of speed.

| Workload | Proposed target / budget |
|---|---|
| Warm single direct combat evaluation, no search | p95 under 10 ms end-to-end CLI service invocation excluding process startup; benchmark native batch separately |
| Native mechanics throughput | ≥1 million simple direct-effect evaluations/sec single worker on a fixed synthetic kernel workload, or document measured bottleneck and revised target |
| Small class/trait exact fixture | Under 1 s; matches exhaustive oracle |
| Warm interactive gear query | First feasible result under 1 s; typical bounded result within 3 s, representative frozen catalog |
| Complex joint gear/spell query | First feasible result within 3 s; default 10 s wall budget, user-extensible |
| Full chargen-to-cap search | First feasible validated plan within 30 s on representative supported workload; default 120 s budget, user-extensible |
| Memory | Target peak RSS under 1 GB for typical gear query; 2 GB for default full search; declare larger research workloads |
| Quality | Exact reduced fixtures match oracle; for bounded fixtures report measured gap vs offline exact/long-budget baseline wherever available; no unqualified global-optimum claim |

Make performance regressions testable: record benchmark results in JSON; compare median repeated measurements on the same machine; investigate >10% throughput/latency regression or >20% memory increase. Use stable operation-count checks in ordinary CI, timing gates on dedicated runners/local reproducible hardware. Do not make noisy shared CI timing the sole correctness gate. Benchmark with pruning disabled on tiny problems, with adversarial high-synergy/capped-stat inputs, and on large randomized affix catalogs. Use `cProfile`/sampling profiler for orchestration and native profiler/perf/ETW/appropriate tools for compiled loops. Profile before micro-optimizing, but choose efficient architecture on day one.

Do not achieve speed by silently reducing candidate breadth, ignoring effects or weakening quality. Whenever a search limit changes, compare both speed and objective quality. Require a performance report and correctness/parity test with each major search change.

## 7. Public contracts and user interface

### 7.1 Data and service boundaries

Use frozen, typed input/output schemas with explicit units, versioning, canonical IDs and three-valued evidence (`known_true`, `known_false`, `unknown`). Avoid database-specific types in domain APIs. Validate every input before passing it to native code. Store user observations separately from hypothetical states; simulation must never overwrite the current character.

Core types (names illustrative):

- `RulesetRef`: source SHA, content hash, engine/schema versions, mode, verification date, supported mechanics.
- `ClassSpec`: race, editable attribute floors, HP setting, trait selections, grouped skills, difficulty and advancement calculated from rules, permanent choices.
- `CharacterSnapshot`: class, actual level, earned/base/live stats and skills, mastery, unlocks, current HP/SP, specialization, progression powers, inventory instances and observation freshness.
- `SpellSpec`, `SpellbookSpec`, `CastingPolicySpec`: exact effect parameters and scheduling constraints.
- `ItemTemplate`, `ItemInstance`, `AffixSpec`, `Loadout`: identity, occupancy, bonuses, activation conditions, costs, evidence.
- `ScenarioSpec`: target and environment, timeline, assumptions, resource state and weights.
- `ObjectiveSpec`: metrics, direction, constraints, normalization, objective/phase weights and uncertainty policy.
- `SearchSpec`: mode, candidates, locks, exclusions, node/time/memory budget, worker count, seed, top-K and quality mode.
- `BuildPlan`: starting class, ordered progression steps and checkpoint snapshots, gear/spell choices, final build, cost/effort and metrics.
- `SearchResult[T]`: incumbent(s), status, proof scope, bounds/gap if valid, assumptions, unsupported mechanics, input/ruleset hashes, timing and search counters, validation result.

Create a shared `OptimizationService` for class/build/progression and a `GearService` for gear requests; they delegate to the same mechanics and search core. A standalone `evaluate_build` verifies arbitrary proposed setups and reports intermediate calculations with mechanic IDs. Do not expose implementation-dependent native array schemas as the public API.

### 7.2 CLI (first deliverable)

Illustrative commands; Codex should define and test precise schemas and arguments. All optimization commands take frozen inputs, support JSON output, and use native engines in production.

```sh
# Extract and inspect a pinned game snapshot.
dfo ruleset build --source ./vendor/dfo-source --commit <sha> --out ./content/ruleset
dfo ruleset validate --ruleset ./content/ruleset
dfo ruleset coverage

# Validate / import / export a class through the verified real game schema.
dfo class validate --class fixtures/mage.json
dfo class optimize --profile dhargo_pve --top 20 --output classes.json
dfo class export --class-id <id> --output character-class.json

# Current-character and spell/gear searches.
dfo character import --input my-character.json
dfo evaluate --request examples/evaluate.json
dfo spell optimize --request examples/spell.json
dfo gear optimize --request examples/gear-owned.json
dfo gear optimize --request examples/gear-budget.json
dfo gear optimize --request examples/gear-bis.json

# Full lifecycle search and remaining-path replanning.
dfo build optimize --request examples/chargen-to-cap.json --output plan.json
dfo build replan --request examples/current-character.json --output revised.json
dfo build compare --plans plan-a.json plan-b.json

# Validation and performance.
dfo benchmark --suite smoke --workers 1 --output benchmarks/latest.json
```

The request file should support a profile such as:

```json
{
  "schema_version": 1,
  "ruleset": {"content_hash": "<generated-hash>", "mode": "online_snapshot"},
  "start": {"type": "new_character"},
  "class_constraints": {
    "difficulty_points": -12,
    "hp_setting": 30,
    "magicka_multiplier": 3.0,
    "require_day_and_night_casting": true,
    "allow_high_risk_disadvantages": false,
    "allow_unverified_advantageous_behavior": false
  },
  "goal": {"type": "capped_progression", "profile": "balanced_progression"},
  "checkpoints": [1, 5, 10, 15, 20, 25, 30, 35, 40, "level_cap", "mastery_cap"],
  "scenarios": [
    {"id": "mixed_solo_pve", "weight": 1.0}
  ],
  "gear": {"mode": "available_catalog", "unknown_price_policy": "exclude_from_budget_ranking"},
  "spell": {"mode": "auto_spellbook"},
  "search": {"mode": "balanced", "top_k": 10, "wall_seconds": 120, "workers": 4, "seed": 42}
}
```

This example is a proposed API, not a game save format. Define the scenario and profile in checked-in versioned fixtures; do not invent enemy stats to populate an allegedly source-backed preset. An optional snapshot-specific profile may use the documented regeneration exception if verified; a strict live-safe profile must not depend on it. If default constraints leave no proven feasible class, surface the blocker and the nearest legal alternatives without silently relaxing them.

### 7.3 Desktop UI (after core validation)

Build a lightweight local UI, inspired by the OSRS Gear Optimizer, not a separate simulation implementation. Recommended views:

| View | User task |
|---|---|
| Character Creator | Lock race/skills/traits/attributes; compare legal classes, difficulty budget and tradeoffs; export validated JSON |
| Progression | Inspect stages from actual starting state to cap, upcoming unlocks, training plan and gear/spell upgrades |
| Spell Lab | Edit exact Spellmaker settings, plot damage/SP and DPS across levels/skills, compare spells and optimize |
| Gear | Select current character/scenario, lock equipment slots, budget and acquisition mode; show full loadouts and upgrade deltas |
| Compare | Side-by-side builds/gear/spells and metric/Pareto charts; explain constraints, uncertainties and score differences |
| Data / Diagnostics | Ruleset version, mechanics coverage, user item import, search quality and benchmark reports |

Support search cancellation, first-feasible results, progressive incumbent updates and detailed final explanations. Expose quick, balanced, exhaustive (only where tractable), and research modes with their limits. Keep large calculations off the UI thread. Persist user preferences and snapshots locally; do not introduce a database server or authentication for the first desktop release. Optional later read-only MCP functions should use the same domain services, e.g. `get_character`, `evaluate_build`, `optimize_spells`, `optimize_gear`, `optimize_build`, `get_progression_plan`. Do not split mechanics logic across API surfaces.

## 8. Correctness and validation strategy

### 8.1 Independent source oracle

Build a test-only Node harness against the pinned public JS where pure exports are available. Stub only clearly isolated dependencies and document all stubs. Do not use production Python or Cython functions to generate their own expected test outputs. Where invoking source directly is impossible, derive fixtures from source and independent calculations, marking evidence. Export golden JSON vectors with source SHA, inputs, expected intermediate/output values and mode. Preserve game rounding and operation order, inclusive/exclusive random ranges and relevant JS arithmetic behavior.

Golden fixtures must cover class trait costs and conflict combinations, −12 legality, advancement, attribute budgets and class JSON round trips; race/class save ordering; skill caps and mastery/level arithmetic; spell effect price and actual cast costs including minimum floors, targeting and rounding; level-scaled magnitudes/durations; timing modifiers/caps; potency and penetration stacking; shield/healing/resource return caps; equipment requirements/slot collisions; enemy scaling and relevant conditional power triggers.

### 8.2 Differential, exhaustive and property tests

- Native evaluator vs independent oracle on every verified mechanic; reference vs native over randomized valid inputs and edge cases. Test negative values, cap boundaries, skill 99/100/101, maximum values, exact threshold transitions and malformed input. Use exact comparison for integer mechanics and declared tolerances for floating values.
- Compare each exact/pruned solver against brute force on small randomized spaces, including top-K ties, shared resources, two-handed items, affix constraints, set effects, spell cost rounding, threshold effects, and cross-spell/gear interactions. Prove or test the admissibility of every pruning bound against exact completion on reduced cases.
- Confirm that adding a legal candidate cannot lower the true optimum in exact mode, relaxing a constraint cannot worsen an exact optimum, irrelevant permutations do not alter results, and no budget or copy count is exceeded. In bounded mode do not assert monotonic quality unless warm-starts guarantee preservation of feasible incumbents.
- Replay progression plans from their starting state with an independent legality checker; validate irreversible choices and earned-point accounting. Ensure no cap-only fixture is described as attainable without a legal path. Compare a reduced joint lifecycle search against an exhaustive state graph.
- Test deterministic result hashes (excluding runtime statistics), stable tie breaks, seeded simulations, cancellation, time/node/memory limit behavior, cold/warm caches, and native single/multiple-worker equivalence where specified.
- Test unsupported mechanics and stale/unknown ownership/prices explicitly. Unsupported effects that could change a ranking exclude affected candidates from certified numeric ranking or produce an explicitly partial lower/upper-bound evaluation with no misleading global claim.
- Integration tests must invoke installed compiled wheels and confirm the engine is native. No CI path should pass by silently switching to Python. Maintain a small pure-Python debug path only when explicitly requested. Run debug builds with bounds checks and memory safety tools/sanitizers where practical.

### 8.3 Live validation

Create a manual in-game observation protocol: source/version, character sheet, class JSON, exact spellmaker settings, displayed cast cost, target, observed result and uncertainty. Compare observations with predicted intermediate values. The public snapshot can diverge from live servers; do not auto-update mechanics based on anecdote. Support scoped version overlays with source/provenance, tests and content hashes. Validate class import using the user's authorized normal UI, not a live-server API. Maintain a separate `snapshot` and `live_verified` coverage report.

## 9. Milestones and definition of done

Each milestone must include documentation, native/reference parity where applicable, reproducible benchmarks, test evidence and an example invocation. Do not start by building the dashboard.

| Milestone | Deliverable | Acceptance gate |
|---|---|---|
| M0 — Foundation | Clone/pin source and audit OSRS patterns; create ruleset registry, architecture ADRs, native build, CI, benchmark harness and tiny evaluator | Installed Windows/Linux native module; test proves real native execution; source oracle sample and recorded serial throughput; documented current coverage |
| M1 — Class | Full legal trait catalog, difficulty/attributes/skills/race validation, native class search, import/export adapters | Exact reduced-domain enumeration; default −12 and 0.30×; maximum HP/Magery when feasible; real schema round-trip; unsafe/unknown behavior visible |
| M2 — Spell math | Direct spell evaluation, cost/cast-speed/potency/saving throws, native single-effect search, fixed/automatic spell CLI | Source fixtures and exact reduced spell search; damage/SP and DPS with explicit assumptions; no unverified previous spell example treated as truth |
| M3 — Gear | Item catalog, ownership/budget/locks, native exact and bounded gear search with fixed/auto spells | Complete legal gear sets; brute-force oracle parity on small joint problems; cap/threshold/unique/slot tests; known-vs-hypothetical gear distinction; representative speed/quality benchmark |
| M4 — Progression | Skill advancement, leveling, attribute/mastery selection, specialization availability, event graph, native search from creation/current state | Reduced full-path oracle; independently replayable stage plan; no future stats or unlock leakage; legal capped state or explicit reachability gap; reports on progression effort |
| M5 — Lifecycle joint search | Multi-effect spells, stage-specific gear/spellbook, outer class refinement and capped progression comparison | End-to-end reproducible `build optimize`; compares baseline classes; cross-stage resource accounting; bounded vs exact scope; documented Pareto/sensitivity results |
| M6 — Sustain and advanced effects | Supported event engine, buffs, shields/heals, procs, specialization triggers, AoE, supported permanent progression and realistic enemy scenarios | Verified event ordering, resource clipping, seeded repeatability, encounter metrics and unsupported-effect gating; performance regression tests |
| M7 — Desktop product | Local UI, import/export, side-by-side results, diagnostics, responsive cancellation | Same service results as CLI; owned/budget/BIS examples; distribution build; reproducible user workflow; clear ruleset mismatch warnings |

Milestone sequencing may overlap if it reduces risk, but native build and source-oracle work must precede production search. A prototype that optimizes only direct damage or lacks supported progression is a scoped prototype, not a complete lifecycle optimizer. Final release acceptance requires M0–M7 core deliverables or explicit user-approved reductions. Add PvP, group roles, shared multi-role gear and MCP only after the core is reliable.

### Required completion report for each implementation session

1. Features implemented and exact files changed.
2. Mechanics verified (source IDs and tests), unsupported mechanics and assumptions remaining.
3. Commands executed and actual test/build results, including failures and skipped tests.
4. Benchmark machine/workload, before/after elapsed time, throughput, memory, nodes and objective quality; identify whether native paths were exercised.
5. Search guarantees and limitations; examples of actual legal results with source/ruleset hash.
6. Next milestone and concrete blockers. Do not report a target as a measured result or promise performance without evidence.

## 10. Day-one AGENTS.md policy (copy into repository)

```markdown
# Engineering rules
- Use the pinned DFO source and verified fixtures as the mechanics authority.
- Record provenance and verification status for every scored mechanic. Never silently invent missing mechanics, ignore a material effect or conflate snapshot with live behavior.
- Default class search enforces minimum legal difficulty (-12 / 0.30x in the initial verified snapshot). No silent relaxation of user constraints.
- Build and exercise native kernels from the first milestone. High-cardinality searches and repeated evaluators must be compiled and batch-oriented. No per-candidate Python callbacks or object creation in production hot loops. Missing native module is an explicit error, not a silent fallback.
- Keep source oracle, independent small reference and production native implementations testable against one another. Match integer and rounding semantics exactly.
- Optimize only declared objectives over legal candidates. Report exact proof scope or bounded-best-found status. No heuristic truncation marketed as global optimality or infeasibility.
- Every pruning rule needs proof or conservative scope plus exhaustive differential tests. Never sacrifice search quality invisibly for speed.
- Freeze all input snapshots and content hashes; no network or database I/O in optimization loops. Hypothetical operations never mutate observed character data.
- Reuse one mechanics/service boundary for CLI, UI and integrations. Keep item eligibility, acquisition, ownership and rolled properties separate.
- Preserve deterministic seeds/ties and versioned results. Add tests and benchmark evidence with every significant mechanics or performance change.
- Keep development local/read-only with respect to the game. No gameplay automation, private endpoint access or client injection.
- Follow the milestone gates in DFO_Spellcasting_Optimizer_Codex_Handoff.md. Report blockers and actual measurements instead of guessing.
```

## 11. Initial Codex execution prompt

Place this handoff in the root of the intended new repository. Start Codex with the following request:

> Read `DFO_Spellcasting_Optimizer_Codex_Handoff.md` in full. Treat it as the product specification. Inspect the current workspace and the referenced DFO and OSRS Recommender repositories; pin the DFO source SHA and preserve reference-repository boundaries. Implement M0 and M1 first, with a real compiled native extension, independent source-oracle tests, exhaustive reduced fixtures, native performance benchmarks and a usable CLI. Write the AGENTS.md policy and architecture/mechanics/performance docs. Do not begin a slow Python production optimizer or the GUI. Do not assume any prior mage build is optimal. Enforce the verified minimum difficulty and report class legality, candidate coverage and exactness. Then proceed through the remaining milestones in tested vertical slices if feasible. At the end of each session report actual test results, native benchmark results, search guarantees, unsupported mechanics and blockers, and leave the project in a runnable state.

## 12. Handoff limitations and design decisions

- No implementation or performance measurements have been produced yet; targets are engineering budgets to validate, not demonstrated speeds.
- The public DFO source is a dated snapshot. The full rules, exact live behavior, all equipment rolls and all relevant source paths have not been audited here. Treat source entry points and historical mage calculations as investigation targets, not certified formulas.
- The public OSRS README, architecture and project configuration were reviewed; its complete native kernel implementation was not inspected here. Codex should inspect it before reusing patterns. No code from either reference repo is embedded in this handoff.
- Dhargo's actual exported classes were not opened in this task. User-stated minimum difficulty is the design requirement; use supplied/importable examples as comparison fixtures rather than proof of legality.
- Python/Cython, local-first CLI/desktop, solo PvE, initial 30 HP and 3× Magery locks, strict uncertainty policy, default search budgets and milestone order are proposed engineering/product defaults. Make configurable where specified. A mathematically exact result is possible for reduced finite spaces; the full coupled lifecycle search is likely to require bounded methods. Report this distinction explicitly.

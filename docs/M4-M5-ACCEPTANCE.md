# M4 and M5 acceptance

Version 0.3.0 adds native progression, spellbook and lifecycle search to the existing class, spell and equipment engines. The mechanics authority is the public online snapshot at `a3eb1605ea1dc391b691fe314377458a7e63e483`. The reviewed ruleset digest is `e8d974f193cc266b6fdbaaae73f35bc5e1bb446fe8cfa22a65da3c21269ca886`. The three new kernels run in-process in compiled C++17 via Cython. Each emitted route is checked by a separate scalar implementation. [Decision record](adr/0004-progression-and-lifecycle.md) · [CLI commands](../README.md)

## M4 progression

| Frozen scenario | Independently replayed outcome |
|---|---|
| Reduced training choice | Three casts, 361 personal minutes, zero gold. The alternative takes one guild session, 541 minutes and 100 gold. Both satisfy the same earned-skill goal. [Request](../examples/progression-tradeoffs.json) |
| Current character approaching the cap | Level 44 becomes 45, Destruction advances from 99 to 101, the character uses its sixth mastery slot and selects Battlemage. [Request](../examples/progression-mastery.json) |
| New character to the cap | The fixed birth and declared activities reach level 45 in 5,889 transitions, 609,465 practice actions and 453 qualifying raise passes. The route takes 7,558,200 personal minutes and spends zero gold. [Request](../examples/progression-creation-to-cap.json) |
| Legacy observations | The planner returns the missing prerequisite and a replayable prefix. A portable snapshot can be used for the observations it actually records. [Request](../examples/progression-legacy-gap.json) |

The cap workload supplies eligible targets, fresh conversations, locked doors and uninterrupted beds. It demonstrates reachability under these opportunities. Estimating time in real play requires measured activity rates and access. The mastery fixture starts from an observed late-game state. It exercises a separate question from the new-character cap witness.

Starting damage depends on funding. The seed-42 Breton comparison caster has 210 SP and 32 trained Destruction. Minor Shock costs 28 SP and deals 4.15444 expected HP loss on the declared 300 HP target. The source-created 8-HP-setting fixture owns Minor Shock too, but starts with 27 SP. A planner that checked only spell ownership would incorrectly promise an immediate cast.

## M5 lifecycle

On the reduced two-roll comparison, the M1 Breton class and a High Elf with the same class tie on the scored direct-hit scenario. The seed-42 checkpoint scores at zero, four and nine gold are 6.053619, 16.285670 and 17.243650 DPS. On seed 97 the same spending levels yield 5.964595, 16.046175 and 17.004155 DPS. Prices and vendor windows are synthetic inputs. Fourteen reconstructed martial comparison classes pass character creation and fail the selected caster locks. The original proposed historical mage files were unavailable. [Paired request](../examples/build-lifecycle.json) · [Comparison corpus](../tests/fixtures/dhargo/README.md)

With one starting SP pool and two encounters, spending SP on the stronger policy first yields 16.285670 then 6.053619 DPS. Saving it for the second encounter reverses those scores at equal spending and training effort. The final-checkpoint-only objective favors the second route. The lifecycle frontier retains both. [Reversal request](../examples/build-checkpoint-reversal.json)

Rerunning the paired request with total budgets of zero, four and nine gold produced four, eight and twelve class/roll witnesses, respectively. The lowest peak final DPS across the paired seeds rose from 5.964595 to 16.046175 to 17.004155. To reproduce the comparison, add `"sensitivity": {"budget_gold": [0, 4, 9], "max_nodes": [500]}` to the paired request. The funded save example checks the tradeoff between guild training and equipment within a single total gold ceiling. [Current-character request](../examples/build-replan-current.json)

The complete creation-to-cap workload returns a free build and a build that buys the quoted five-gold ring at birth. They reach 72.699405 and 76.188976 DPS at level 45. Purchases persist through later checkpoints. The encounter assumes an ordinary stationary target and one landed hit per cast. [Full lifecycle request](../examples/build-creation-to-cap.json)

## Evidence and limits

The source oracle exercises online character creation, 15 arcane and 15 martial mastery pairs and 90 cases including practice and level calculations, source clocks, trainer restrictions and reset behavior. The Spellmaker oracle independently generates nine direct-effect scenarios. The stock-record reader reproduces the game's signed effect bytes, first duplicate ID and Free Action correction. Proprietary classic spell files stay local. The reduced path and purchase tests also enumerate complete small domains independently. [Progression fixture](../tests/fixtures/progression-oracle.json) · [Spell fixture](../tests/fixtures/spellbook-oracle.json) · [Stock reader tests](../tests/test_stock_spells.py)

Creation seeds reproduce sampled legal rolls and use a declared kit roll of 0.5. Save replanning assumes the character has already entered the pinned online leveling mode. Spell records, current SP and important live modifiers sometimes require separate observations. Unresolved active effects, specialization combat bonuses, other effect types, boss reactions, live-world access and arbitrary generation of equipment offers limit the applicable encounters. Proofs cover the frozen finite domain. [Mechanics](MECHANICS.md) · [Search and budgets](OPTIMIZATION.md)

The default class profile requires the reviewed difficulty floor, 30 HP and 3× INT Magery. An explicit custom start can use a different creator-legal class. Environmental casting restrictions still require a verified environment. Lifecycle gear offers require a supported physical copy and a gold quote. The current planner leaves paid travel, uncertain SP clipping on a swap and optional purchases that could redirect a reset fee into the bank as explicit gaps. Checkpoint combat casts consume SP and grant no practice credit in this scenario.

## Distribution qualification

Both platform wheels were built from the same source archive. A byte check compared the archived package, tools, tests, fixtures and examples with the frozen workspace. Build and qualification ran locally on the desktop and an Ubuntu 24.04 x86-64 guest. The repository has no configured remote for a hosted CI run.

| Local qualification | Passed | Skipped | Line coverage |
|---|---:|---:|---:|
| Windows x64 installed wheel | 478 | 1 POSIX signal test | 91.08% Python |
| Ubuntu x64 installed wheel | 479 | 0 | 90.93% Python |
| GCC-instrumented native kernels | 246 | 0 | 1,379 of 1,411 lines (97.73%) |

All 18 class, combat, progression and lifecycle workloads agreed across platforms on the reported results and deterministic work. Every one of the ten measured C++ headers exceeded 91% line coverage. The release record includes both wheel digests and the digest of their shared source archive. [Qualification record](../benchmarks/results/m45-qualification.json) · [Native coverage](../benchmarks/results/ubuntu-m45-native-coverage.json) · [Timing and search quality](PERFORMANCE.md)

The original upstream JavaScript suites passed 157 tests on Linux. One test skipped for unavailable proprietary ARENA2 data. This includes 34 tests for the level-45 cap and online leveling rules in addition to the 13 upstream test files used by the wheel workflow. [CI configuration](../.github/workflows/wheels.yml)

Both installed suites import the six platform extensions and run the six upstream oracle generators. The Windows CLI separately opened the serialized cap plans and verified one progression witness and two lifecycle witnesses. Replay verifies the legality and scores of the published witnesses. Reproducing an optimality claim requires running the finite search again.

# Spell and equipment acceptance

Version 0.2.0 implements M2 and M3 for instant Damage Health on one ordinary PvE foe in the pinned online snapshot. The game source commit is `a3eb1605ea1dc391b691fe314377458a7e63e483`. The reviewed ruleset SHA-256 is `b8755e71e6c87e3efcf582325d49230a68db49910930127e72b0b12eff2bf183`. The historical M1 bundle remains valid for class queries. [Engineering decisions](adr/0003-spell-and-gear-search.md) · [Runnable CLI examples](../README.md)

## Independent evidence

| Check | Scope |
|---|---|
| Game spell host and effect assignment | 19 fixed cast vectors covering 20,100 discrete outcomes, plus six ready/click/resource cases. The public evaluator, native kernel and scalar reference agree on the covered cases. [Spell evidence](SPELL-MECHANICS.md) |
| Game save exporter | Generated a byte-reproducible 9,452-byte two-slot ZIP with an in-memory storage substitute. Fixed and automatic spell and gear workflows consume the exported bytes through the CLI. [Inputs and commands](../tests/fixtures/character/README.md) |
| Game equip window, modifier folds and item law | 128 equip-window cases and eight modifier comparisons. All 833 generated theoretical item copies for an unrestricted career passed `itemFindings`. [Equipment evidence](EQUIPMENT.md) |
| Reduced exact search | Independent enumeration checks the complete set of nondominated metric pairs. Coverage includes budgets, locks, two-handed occupancy, duplicate powers, effect caps and a casting-cost threshold. [Joint frontier tests](../tests/test_joint_frontier_review.py) |
| Nine original game suites | 99 passed, zero failed and one skipped in 2.89 seconds. One classic-class restriction check requires proprietary files supplied through `ARENA2_PATH`. [CI commands](../.github/workflows/wheels.yml) |

## Worked save

The synthetic exported character Arden has a saved Ember spell and an owned spare ring with +6% casting speed. The fixed spell reaches 8.400357 expected DPS at 18 SP. The game omits some online resource modifiers from its save. A separate, timestamped synthetic observation supplies the 42 current SP used for optimization. On the declared spell domain, optimizing the spell alone reaches 10.529881 DPS. Joint search returns four nondominated tradeoffs and reaches 11.117595 DPS at 18 SP by equipping the ring. The exact result is conditional on the supplied target, observation and domain. [Reproduce the joint search](../examples/gear-auto-from-save.json)

## Installed wheel qualification

Windows built the isolated source distribution and a CPython 3.12 x64 wheel from that archive. An Ubuntu 24.04 VM built a second wheel from the same archive with the pinned build dependencies. Each wheel ran `python tools/verify_wheel.py` in a fresh environment outside the checkout, including all four upstream fixture checks, `pip check`, and both benchmark suites. [Performance and search quality](PERFORMANCE.md)

| Target | Measured result |
|---|---|
| Windows 10 x64, MSVC | 309 tests passed in 30.96 s, 90.49% Python statement coverage. The POSIX subprocess SIGINT test skipped on Windows. |
| Ubuntu 24.04 x64, GCC 13.3 | 310 passed in 11.28 s, 90.21% Python statement coverage. The POSIX signal test passed. |
| Instrumented GCC build | 101 focused tests passed. The class header covered 121/121 executable lines, spell 293/306, gear 223/225 and build metadata 4/4. Combined coverage was 641/656 (97.71%). [Compiler report](../benchmarks/results/ubuntu-m23-native-coverage.json) |

An exploratory checkout run mixed an earlier installed wheel with `PYTHONPATH=src`, triggering the installed-metadata and cold/warm identity tests. The Ubuntu source-object mirror also initially lacked the save-export helper blobs. The clean runs above used matching wheels and the authenticated source inputs. The GitHub Actions workflow includes the same acceptance commands. This local checkout has no project remote configured to run hosted CI.

## Remaining scope

The available catalog uses explicit acquisition evidence, including a caller-confirmed loot source. The theoretical catalog includes a finite selection of legal rolls. Search reports the retained frontier, budgets, filtered copies, known purchase costs and the reason for stopping. A node limit, inner spell cap or unresolved post-swap pool can leave feasible improvements unexplored. [Search guarantees](OPTIMIZATION.md)

Live-server equivalence, stock spell definitions requiring classic assets, moving targets, extra splash victims, conditional powers, damage over time, reflection, absorption and multi-cast recovery remain open. M4 covers progression. It needs verified skill advancement and unlock gates, legal event transitions, and an independently replayable path from the starting state. [Mechanics register](MECHANICS.md)

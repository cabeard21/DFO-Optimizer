# M8 spellcaster discovery qualification

Run `dfo ui` and choose **Discover Spellcaster Build**. **Overall PvE** exposes tradeoffs between funded checkpoint performance and progression effort. The ranked family has a fixed race and game class document. Its route can respond to the realized birth roll. Inspect the per-seed witnesses and coverage before deciding on a permanent creation choice.

## Reproduce a recommendation

```sh
dfo build optimize --request examples/build-discovery-demo.json --output build/discovery.json
dfo build replay --plan build/discovery.json
python tools/run_discovery_demonstration.py --output build/m8-demo
dfo benchmark --suite discovery --workers 1 --output build/discovery-quality.json
```

The demonstration evaluates the default M1 example, the seven-material exact INT Breton, the same class on a High Elf, and newly admitted classes on common birth rolls. The seven-material INT example is the existing Breton baseline. It supplies no constraints to discovery. The demo archive contains individual workbench archives with full requests and results. The JSON summary records actual runtimes, native counters, route effort, gear exclusions and encounter outcomes. [Frozen request](../examples/build-discovery-demo.json) · [Measured comparison](../benchmarks/results/windows-m8-discovery-demo.json) · [Replayable archives](../benchmarks/results/windows-m8-discovery-demo.zip)

Class generation uses the pinned source revision `a3eb1605ea1dc391b691fe314377458a7e63e483`. The class screen checks HP, magicka, cast rate, eligible physical items and school placement. The progression oracle exercises paid release and skill credit for each supported school, earned level-up HP and ordinary bed recovery. The encounter oracle checks hostile spells against racial saves and conditional absorption. Unresolved gear, passive timing, spell records and acquisition inputs must appear as gaps where they affect the selected objective. No live verification is claimed. [Search mechanics](OPTIMIZATION.md) · [Progression and scenario assumptions](DISCOVERY-SCENARIOS.md) · [Pinned progression vectors](../tests/fixtures/progression-oracle.json) · [Pinned encounter vectors](../tests/fixtures/encounter-oracle.json)

## Admission quality

The benchmark compares an exhaustive reference, default adaptive admission, a diverse panel without lifecycle feedback and adaptive admission at a 3,000-node ceiling. Each comparison runs in a fresh process on equivalent opportunities and birth rolls. The development panel uses different cases or rolls. Both panels are frozen independently of the workbench presets. [Versioned requests](../src/dfo_optimizer/data/discovery-qualification-v1.json) The frozen qualification requests exercise an early/final checkpoint reversal, burst and sustained combat, equipment eligibility, school placement, hostile spell defenses and earned progression. Inspect `admission_complete` to see when a reduced case was cheap enough to finish exhaustively.

Scalar success includes objective-equivalent ties. Regret is the lost objective divided by the absolute exhaustive optimum. An undefined regret from a missing feasible result or missed zero optimum fails the gate. Pareto recall compares distinct objective vectors for the same roll. Discrete counts match exactly and floating coordinates use relative tolerance `1e-9` and absolute tolerance `1e-12`. Paired scalar family optima use the highest mean for a single class across the whole seed panel. Paired Pareto recall compares the complete objective vector among matching checkpoint shapes for the supported representative policies. These policies prioritize one axis across all rolls. The paired comparison measures recovery over that selector domain. The per-roll frontier measures each roll's supported routes independently.

Both the per-roll and paired family checks require full designated reference recovery, at least 95% held-out scalar recovery, mean regret at most 0.5%, worst regret at most 2% and at least 90% held-out Pareto recall. The CLI writes all results and exits with a failing status when the default misses a gate. The fixed smaller budget and screening-only results describe the measured runtime/quality tradeoff. Results on reduced domains cannot prove optimality for broad class discovery.

| Admission on the frozen reduced panels | Per-roll scalar recovery | Paired scalar recovery | Per-roll Pareto recall | Paired Pareto recall |
| --- | ---: | ---: | ---: | ---: |
| Default adaptive | 100% | 100% | 100% | 100% |
| Initial diverse panel | 87.5% | 100% | 75% | 50% |
| Adaptive with 3,000 nodes | 29.2% | 28.6% | 0% | 0% |

All three designated references were recovered in these runs. The default completed admission for all eleven finite cases, with zero measured loss for all 24 held-out scalar roll evaluations and all seven scalar family comparisons. Initial screening had 0.573% mean and 4.717% maximum per-roll regret. The binding 3,000-node run left some comparisons without an incumbent, so its aggregate regret is undefined.

A broad 250,000-node search screened 1,467 legal documents and retained 32 candidates in 45 ms on the installed Windows wheel. That service run processed 5.54 million nodes and 32,481 legal screens per second. [Windows discovery benchmark](../benchmarks/results/windows-m8-discovery.json) The retained panel represented all eight races, 32 attribute allocations, 32 ordered skill lists and 26 disadvantage selections. The equal-ceiling M1 workload stopped after finding 32 legal examples and covered one attribute allocation, one skill list and one disadvantage selection. M1 and discovery solve different objectives. Their counters describe work within each domain. Class traversal remains serial. Benchmarking several parallel partitions under the same wall and memory budget remains a separate optimization opportunity.

## Release checks

The installed-wheel verification runs the source oracles, tests, Chromium workflows and all six benchmark suites. The release comparison checks deterministic work and quality against 0.4.0 on the same host, with the four older suites also compared against 0.3.0. Process peak RSS includes Python, archive data and replay validation. The native memory limit accounts for solver-owned allocations. Wall-limited searches report the work that completed on the measured machine.

The Windows wheel passed all seven source-oracle commands, all six benchmark suites and the Chromium workbench checks. Pytest reported 757 passed and one Windows skip for POSIX signal delivery, with 91.02% Python line coverage. The release comparison preserved deterministic work and quality against both reference wheels. [Windows qualification](../benchmarks/results/windows-m8-qualification.json) · [Browser evidence](../benchmarks/results/windows-m8-browser-timings.json) · [Paired performance](PERFORMANCE.md#m8-windows-release-comparison)

The Ubuntu GCC instrumented build passed 450 tests and covered 97.21% of executable native header lines. All individual headers exceeded 80%. The verification used the same native sources and tests for discovery's class, progression, gear and encounter kernels. [Native coverage report](../benchmarks/results/ubuntu-m8-native-coverage.json)

The Ubuntu x86-64 wheel passed all seven source-oracle checks, six benchmarks and its Chromium test suite. Pytest reported 758 passed with 90.99% Python line coverage. Both platforms produced the same broad class digest and passed both discovery gates. Reduced discovery measurements matched on deterministic native work and quality across the platforms. Archive identities can differ when the frozen record contains platform-specific memory sizing. [Ubuntu qualification](../benchmarks/results/ubuntu-m8-qualification.json) · [Ubuntu discovery benchmark](../benchmarks/results/ubuntu-m8-discovery.json)

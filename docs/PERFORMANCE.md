# Performance baseline

## M0 and M1 acceptance

These are serial measurements from installed, optimized CPython 3.12 wheels on an AMD Ryzen 5 5600X. Windows 10 ran on the 12-thread desktop. Alpine Linux 3.22.8 ran in a two-vCPU x86-64 VirtualBox guest on the same host. The Windows build used MSVC with strict floating point. The Alpine build used GCC 14.2 with fast math and contraction disabled.

| M1 workload | Windows warm p50 / p95 | Alpine warm p50 / p95 | Native work and quality |
|---|---:|---:|---|
| Batch of 65,536 class difficulty and advancement rows | 0.306 / 0.356 ms | 0.770 / 0.966 ms | All returned points and multipliers checked, 214.17M and 85.17M rows/s respectively |
| Exact reduced class query | 2.00 / 4.48 ms | 5.30 / 5.89 ms | 78 nodes, 9 prunes, 4 leaves, all 4 expected class/race identities |
| Bounded catalog, 20 examples | 4.69 / 5.74 ms | 9.50 / 11.80 ms | 252 nodes, 66 prunes, 20 leaves, all 20 valid at −12 |

Each warm distribution has seven samples. Cold search starts a fresh installed CLI process and includes startup and JSON serialization. Exact/bounded cold times were 128.9/131.0 ms on Windows and 112.2/132.9 ms on Alpine. First-feasible native time on the bounded workload was 89.5 µs and 179.7 µs respectively. Whole-process peak RSS was 26.57 MiB and 25.26 MiB. The two systems returned identical search digests and work counts.

The M0 Windows foundation run measured 163.80M rows/s and 24.82 MiB peak RSS. Its difficulty workload and output digest match M1. The ruleset hash changed when M1 added verified Magery decoding to the registry. The fresh process, host load, and sub-millisecond batch duration affect these observations. They establish performance baselines for class arithmetic. Direct spell effects need their own workload in M2. [M0 Windows](../benchmarks/results/windows-m0.json) · [M1 Windows](../benchmarks/results/windows-m1.json) · [M1 Alpine](../benchmarks/results/linux-m1.json)

A separate Ubuntu 24.04.5 userspace on the Alpine guest kernel exercised the glibc 2.39 wheel with CPython 3.12.3 and GCC 13.3 on one active vCPU. Its serial warm medians were 272.50M batch rows/s, 2.03 ms for the exact query, and 5.31 ms for the bounded query. Peak RSS was 26.53 MiB. Input, work and result digests matched the other platforms. These local VM times serve as reproduction records. [M1 Ubuntu](../benchmarks/results/ubuntu-m1.json)

## Reproduction and regression checks

Run `dfo benchmark --suite smoke --workers 1 --output build/smoke.json`. Retain the report's engine binary hash, compiler flags, ruleset hash, workload version, input domains, and hardware description. CI checks complete reduced-domain identities and deterministic node and leaf counts. Benchmarks run with release flags. Single-query timings include result decoding and independent finalist validation.

For timing comparisons, compare medians of repeated runs on the same idle machine using matching ruleset, workload and search limits. Investigate latency/throughput regressions larger than 10% or RSS growth above 20%. Compare result hashes, leaves, retained identities and objective quality before attributing a speed change to optimization. Later gear, spell and progression workloads need their own baselines and quality references.

The instrumented C++ search header reached 135/135 executable lines with MSVC and 121/121 with GCC. The compilers attribute executable lines differently. On Linux, `python tools/verify_native_coverage.py --output build/native-coverage.json` builds a disposable instrumented extension, runs the focused kernel tests, and enforces 80% executable-line coverage for the production search header. [MSVC report](../benchmarks/results/windows-native-coverage.json) · [GCC report](../benchmarks/results/linux-native-coverage.json)

## M2 and M3 measurements

`dfo benchmark --suite combat --workers 1` ran against installed CPython 3.12.10/MSVC and CPython 3.12.3/GCC 13.3 wheels on the same Ryzen 5 5600X. Ubuntu 24.04 ran in a one-vCPU, 4 GiB guest with glibc 2.39. Warm distributions contain seven serial calls. Cold CLI measurements create a fresh process. Inputs, frontier points, hashes, CPU and wall samples, RSS and search counters are included in the reports. The two platforms returned identical result hashes and deterministic work counts. [Windows combat](../benchmarks/results/windows-m23.json) · [Ubuntu combat](../benchmarks/results/ubuntu-m23.json)

| Workload | Windows warm p50 / p95 | Ubuntu warm p50 / p95 | Work per query |
|---|---:|---:|---|
| Native batch of 65,536 simple direct-effect evaluations | 4.72 / 5.25 ms | 2.01 / 4.22 ms | 13.87M and 32.56M rows/s respectively, scalar checksum matched |
| Fixed spell, including request and result validation | 0.18 / 1.85 ms | 0.28 / 2.52 ms | One recipe. Cold CLI 121 / 95 ms |
| Exact reduced spell search | 0.73 / 0.85 ms | 0.70 / 2.90 ms | All 648 legal settings, seven frontier points |
| Full spell domain with 100,000-node budget | 7.80 / 10.34 ms | 5.75 / 9.15 ms | 13,185 scores and 86,815 prunes in a 10.201B-setting domain |
| Exact reduced joint search | 8.64 / 12.05 ms | 9.44 / 13.20 ms | 16,065 nodes, 21 equipment leaves, 7,128 spell scores |
| 36 owned items and one fixed spell | 15.53 / 16.85 ms | 20.14 / 29.47 ms | 60,000 nodes, 195 distinct spell evaluations, 54,682 cache hits |
| 36 owned items with automatic spell selection | 21.80 / 22.20 ms | 27.16 / 33.80 ms | 75,000 nodes, 11,834 spell evaluations, 45,839 cache hits |

For the 36-item joint query, the first feasible result arrived at 12.35 ms on Windows and 13.59 ms on Ubuntu, measured from service entry through preparation and the first native incumbent. Cold CLI completion took 156 / 116 ms. Peak RSS over the combat suite was 28.94 / 28.12 MiB. The direct batch uses single-valued magnitude ranges. Interval-distribution throughput depends on range widths and caster/target state.

### Bounded search quality

Both reduced workloads have seven exact tradeoffs. At 128 nodes, spell search recovered four exact points, 98.48% of the area dominated by the exact frontier relative to zero, and 100% of peak DPS. At 700 nodes, joint search returned seven points, of which two occur on the exact frontier. It recovered 85.97% of dominated area and 99.02% of peak DPS. The 75,000-node inventory run has no measured global gap. Its useful guarantee is that the reported loadouts and recipes replay successfully under the request constraints.

### Class performance across releases

The class smoke query still returned four exact and twenty bounded candidates with the same 78 and 252 nodes respectively. Several timings crossed the 10% investigation threshold against the old baselines. For a same-host check, each machine alternated the 0.1.0 and 0.2.0 release wheels across six fresh serial runs, with seven warm calls per workload per run. The table reports medians of each release's three warm medians. [Windows paired samples](../benchmarks/results/windows-m23-class-comparison.json) · [Ubuntu paired samples](../benchmarks/results/ubuntu-m23-class-comparison.json)

| Class workload | Windows M1 → M2/M3 | Ubuntu M1 → M2/M3 |
|---|---:|---:|
| 65,536-row batch | 0.318 → 0.308 ms | 0.137 → 0.234 ms |
| Exact reduced class search | 1.928 → 2.027 ms | 1.751 → 2.325 ms |
| Bounded class examples | 4.129 → 4.569 ms | 4.187 → 4.280 ms |

Running the current engine against both historical and current rulesets added 0.15 ms to the exact query on Windows and 0.23 ms on Ubuntu. The expanded ruleset is copied and authenticated at service entry. The Ubuntu batch was variable, spanning 0.125–0.460 ms on the new wheel and 0.127–0.433 ms on the old wheel. Both wheels used the same class kernel sources and release flags. The cause of the remaining Ubuntu timing variation is unresolved. [Windows class acceptance](../benchmarks/results/windows-m23-class.json) · [Ubuntu class acceptance](../benchmarks/results/ubuntu-m23-class.json)

## M4 and M5 workload definitions

The progression and lifecycle suites each run a reduced exact request, a node-limited version of that request and a creation-to-level-45 request. Each workload starts the installed CLI cold, then runs five serial service calls and checks their result identities. The reports contain the input, native module hashes, deterministic work, observed CPU and wall times, time to first independently replayed route and whole-process peak RSS. The capped workloads include creation, all training transitions, Python replay and result assembly.

The reduced M4 fixture has two exact effort vectors. The reduced M5 fixture compares the checkpoint DPS and effort vectors within each paired roll and includes total gold spent on both training and purchases. Two different class witnesses can realize the same metric vector. Frontier recall counts distinct exact vectors recovered. A remaining gap on a reduced fixture does not give a numerical bound for a different full-size request. [Progression workload](../examples/progression-tradeoffs.json) · [Lifecycle workload](../examples/build-lifecycle.json)

The following measurements are from the installed 0.3.0 wheels built from the same source archive.

| 0.3.0 workload | Native nodes | Windows warm p50 / p95 | Ubuntu warm p50 / p95 |
|---|---:|---:|---:|
| M4 exact training tradeoffs | 4 | 9.18 / 15.27 ms | 6.01 / 8.16 ms |
| M4 bounded training tradeoffs | 3 | 4.95 / 8.82 ms | 6.24 / 8.82 ms |
| M4 creation to level 45 | 5,889 | 1.573 / 1.672 s | 1.158 / 1.416 s |
| M5 exact paired-class comparison | 1,704 | 82.79 / 94.16 ms | 56.31 / 66.39 ms |
| M5 bounded paired-class comparison | 500 | 90.86 / 96.48 ms | 73.39 / 79.78 ms |
| M5 joint creation to level 45 | 20,393 | 3.595 / 3.852 s | 2.582 / 3.385 s |

The same Ryzen 5 5600X ran Windows on the desktop and Ubuntu 24.04 on a one-vCPU, 4 GiB guest. M5 cold CLI completion took 2.718 s on Windows and 2.845 s on Ubuntu. Median time to the first independently replayed cap build was 3.564 s and 2.545 s, respectively. Peak process RSS was 155.36 MiB and 168.04 MiB across the lifecycle suite. M4 peaked at 48.86 MiB and 48.79 MiB. Both cap measurements meet the 30 s first-plan target on this fixed workload. The platforms agreed on the planning result hashes, frontier coordinates and deterministic node counts. [Windows progression](../benchmarks/results/windows-m45-progression.json) · [Ubuntu progression](../benchmarks/results/ubuntu-m45-progression.json) · [Windows lifecycle](../benchmarks/results/windows-m45-lifecycle.json) · [Ubuntu lifecycle](../benchmarks/results/ubuntu-m45-lifecycle.json)

At three nodes M4 recovered one of two exact effort vectors. At 500 nodes M5 emitted four distinct vectors, two of which match the six-point exact frontier. It found the free points for both seeds. It found a four-gold improvement at the second checkpoint and missed buying the same improvement for both encounters. It also missed the nine-gold points. The bounded M5 run took longer than exhaustive search on this small panel because it paid setup and replay costs across multiple refinement passes. The full cap search evaluated 40 spell bundles and reached 3,072 terminal purchase/policy combinations with 3,066 prunes.

### Earlier workloads on the 0.3.0 wheels

Each host alternated three fresh runs of each wheel. The table gives medians of the warm medians in milliseconds. Both releases returned the same results, search work and quality for all twelve workloads. Peak RSS for the class and combat suites stayed within 2% on both systems. [Windows paired runs](../benchmarks/results/windows-m45-release-comparison.json) · [Ubuntu paired runs](../benchmarks/results/ubuntu-m45-release-comparison.json)

| Workload | Windows 0.2.0 → 0.3.0 | Ubuntu 0.2.0 → 0.3.0 |
|---|---:|---:|
| Class mechanics batch | 0.296 → 0.447 | 0.219 → 0.258 |
| Bounded class search | 4.608 → 5.682 | 5.887 → 6.655 |
| Direct spell batch | 4.707 → 5.569 | 2.733 → 2.001 |
| Exact reduced spell search | 0.485 → 0.552 | 0.592 → 0.651 |
| Bounded reduced spell search | 0.371 → 0.466 | 0.348 → 0.354 |
| Full spell domain, 100,000 nodes | 7.464 → 6.639 | 5.519 → 8.392 |
| Exact reduced gear search | 7.315 → 5.682 | 8.159 → 5.938 |
| Owned gear and fixed spell | 17.041 → 15.187 | 19.966 → 17.657 |
| Joint gear and spell search | 22.333 → 22.272 | 22.743 → 27.538 |

Reopening and authenticating the expanded default rules on every gear query caused a reproducible slowdown during qualification. Gear and spells now share the previously authenticated packaged rules. Explicit caller-supplied rules still receive full validation. Using the same final Ubuntu binary and alternating only this admission behavior reduced warm exact gear time from 9.830 to 6.862 ms and joint search from 23.958 to 20.780 ms across eleven pairs. All outcomes matched. [Controlled gear comparison](../benchmarks/results/ubuntu-m45-gear-cache.json)

Four Ubuntu workloads crossed the 10% timing threshold in the three-run comparison. A diagnostic interleaved seventeen pairs between two long-lived processes with the same release wheels and requests. All four medians improved in that setting. Class mechanics was 0.136 → 0.126 ms, bounded class search 4.936 → 4.632 ms, full spell search 5.150 → 4.886 ms and joint search 19.689 → 18.426 ms. The spread between measurements matters when budgeting service latency. [Ubuntu warm samples](../benchmarks/results/ubuntu-m45-flagged-workloads.json)

On Windows, five workloads exceeded the 10% threshold in the three-run comparison. In seventeen interleaved warm pairs, direct spell batch was 4.534 → 4.531 ms, exact spell search 0.473 → 0.470 ms, bounded spell search 0.339 → 0.341 ms, class mechanics 0.303 → 0.308 ms and bounded class search 4.289 → 4.095 ms. Each sample reproduced its recorded result. No median in this diagnostic regressed by 2% or more. A separate ruleset test found that explicitly copying and authenticating the expanded class rules cost about 0.58 ms more than the previous bundle on this host. [Windows warm samples](../benchmarks/results/windows-m45-flagged-workloads.json) · [Class ruleset measurements](../benchmarks/results/windows-m45-ruleset-cost.json)

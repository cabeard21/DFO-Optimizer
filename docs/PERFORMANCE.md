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

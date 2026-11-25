# M0 and M1 acceptance record

## Delivered

The Windows and Alpine Linux x64 CPython 3.12 wheels ran the offline evaluator and class search with their compiled extensions. Every scoreable construction rule belongs to the pinned public snapshot. The source SHA is `a3eb1605ea1dc391b691fe314377458a7e63e483`. The reviewed ruleset SHA-256 is `293f927a36e9bdbc9504e8ed3f16582e326c9bcc5f7a8b84a241a81ae069a27d`. The live verification registry is empty. [Mechanics](MECHANICS.md) · [Architecture](ARCHITECTURE.md) · [Performance and raw benchmarks](PERFORMANCE.md)

A third CPython 3.12 wheel was built and installed in an Ubuntu 24.04.5 glibc 2.39 userspace on the Alpine guest kernel. All 144 tests passed with zero skips, 94.22% Python statement coverage, 121/121 executable C++ search lines covered, and 14/14 original Dhargo documents replayed. Both Linux wheels carry a generic x86-64 Linux wheel tag. Keep the Alpine build under `dist/alpine-musl/` and the Ubuntu build under `dist/ubuntu-glibc/` to distinguish their runtime libraries. [Ubuntu benchmark](../benchmarks/results/ubuntu-m1.json)

## Executed checks

| Command or workload | Observed result |
|---|---|
| `python -m build` | Windows isolated PEP 517 sdist → compiled CPython 3.12 x64 wheel |
| `python tools/verify_wheel.py` | Windows 143 passed, 1 POSIX-specific SIGINT test skipped, 95.12% Python statement coverage. Alpine 144 passed, 0 skipped, 94.22%. The register/emit/retain cancellation path also ran on Windows |
| `node --test test/systems/customclass.test.js test/systems/specialadvantages.test.js` in pinned DFO | 59 passed, 0 failed, 0 skipped |
| `python tools/ruleset/generate_oracle.py --source vendor/dfo-source --check` | Regenerated 27 class cases and 25 numeric vectors from the source. Results matched the checked-in fixture |
| `dfo ruleset build` + rebuild equality test | The newly extracted catalog matched the packaged file byte for byte |
| `python tools/verify_dhargo.py --download` | All 14 original public documents passed SHA-256, validation and normalized export checks |
| Headless replay of the actual 20 default candidates and one exact-search export | All 21 emitted documents passed the pinned game's import, normalized export, Create, 30 HP, 3× Magery, −12 difficulty and 0.30× advancement checks |
| Instrumented C++ kernel test runs | 28 native tests passed in the final line-coverage runs. These include 12 seeded exhaustive trait-space comparisons, order-sensitive flags, resource limits, cross-thread cancellation, and incumbent replacement |
| `dfo benchmark --suite smoke --workers 1` | Both release wheels returned four expected exact fixture classes and 20 bounded catalog examples, with matching deterministic hashes |
| `dfo class optimize --request examples/max-intelligence.json` | Exhausted 12 legal leaves in 182 nodes, retained three tied classes at INT 70. Result ID `272615c29bb361809abdd9017c55f45f2d2deff95afb477a724e464bfc0a20b5` |

The exact example includes a Breton with 30 HP per level, 3× INT Magery, INT 70, STR 30, and −12 difficulty/0.30× advancement. Its seven material prohibitions are steel, elven, dwarven, mithril, silver, adamantium, and iron. Candidate ID `053d593be46bb12ff25c323c12aea79ffbad0d294697abc72e666456cae2b34e` includes the race and game document. The exact maximum applies to the declared 9-trait, 2-race domain and its listed attribute and skill choices. The default 20-example run stops at its requested count, across 71 eligible traits. [Exact input](../examples/max-intelligence.json) · [Proof scope](OPTIMIZATION.md)

## Failures found and corrected

- A first Windows kernel run exposed an unsigned-promotion error at the negative 32-bit boundary. Fixed-width limits and signed boundary tests now cover both extremes.
- The upstream class tests depend on vendored UI manifests even in a headless Node process. Including the pinned manifest dependencies allowed both upstream suites to run.
- Review found inconsistencies in default starting-school validation and result-file identity checking. Profile validation now checks the same school constraint as search. Export verifies the selected candidate's ID against its content.
- The initial Alpine run passed 141 cases and failed two cancellation cases. Fixed-delay signal tests now wait for the native worker to publish its first incumbent. The final Linux suite exercises an actual subprocess SIGINT and checks the returned incumbent.
- The local WSL runtime stalled during launch. Linux acceptance ran in a separate local VirtualBox guest. Hosted GitHub Actions execution is pending a project remote. The workflow defines independent Windows and Ubuntu jobs.
- The first Ubuntu userspace run passed 143 tests and failed one simulated interrupt timeout. The guest kernel reported a 59-second vCPU stall. Repeating the full suite with one active guest vCPU passed all 144 cases, including actual SIGINT delivery.

## Follow-on work

M2 is direct spell math and native single-effect search. Starting damage, actual early training, class/gear synergies, mage combat rankings and live behavior remain open. Additional High Elf or Breton comparison builds require their original specifications. Preserve construction examples as candidates for those milestones and replay the optimizer for the new objectives.

## Files introduced

- **Project and build** — `AGENTS.md`, `README.md`, `.gitignore`, `.gitattributes`, `pyproject.toml`, `requirements-dev.txt`, `setup.py`, `MANIFEST.in`, `.github/workflows/wheels.yml`.
- **Package** under `src/dfo_optimizer/` — `__init__.py`, `native.py`, `native_build.hpp`, `_native.pyx`, `class_search.hpp`, `search_request.py`, `search.py`, `class_document.py`, `classes.py`, `ruleset.py`, `cli.py`, `benchmark.py`, `benchmark_host.py`.
- **Packaged content** under `src/dfo_optimizer/data/` — `DFO-NOTICES.txt`, `source-lock.json`, `mechanics.json`, `ruleset.json`, `extract.mjs`.
- **Verification tools** under `tools/` — `verify_wheel.py`, `verify_native_coverage.py`, `verify_dhargo.py`, `ruleset/generate_oracle.py`, `ruleset/oracle.mjs`, `ruleset/oracle-lock.json`.
- **Tests** under `tests/` — `test_installed.py`, `test_native_loader.py`, `test_native.py`, `test_ruleset.py`, `test_classes.py`, `test_search.py`, `test_cli.py`, `test_cli_cancel.py`, `test_dhargo.py`, `test_bench.py`, `fixtures/oracle_classes.json`, `fixtures/dhargo/README.md`, `fixtures/dhargo/observations.json`.
- **Example and records** — `examples/max-intelligence.json`. Under `benchmarks/results/` — `windows-m0.json`, `windows-m1.json`, `linux-m1.json`, `ubuntu-m1.json`, `windows-native-coverage.json`, `linux-native-coverage.json`.
- **Documentation** under `docs/` — `ARCHITECTURE.md`, `MECHANICS.md`, `OPTIMIZATION.md`, `PERFORMANCE.md`, `M0-M1-ACCEPTANCE.md`, `adr/0001-native-execution.md`, `adr/0002-evidence-and-scope.md`.

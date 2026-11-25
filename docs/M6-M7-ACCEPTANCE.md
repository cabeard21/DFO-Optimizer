# M6 encounters and M7 desktop qualification

The implementation targets DFO's public online source revision `a3eb1605ea1dc391b691fe314377458a7e63e483`. Release qualification is open. The prior accepted release is 0.3.0. [Source revision](https://github.com/Lattymoy/daggerfall-js-source/tree/a3eb1605ea1dc391b691fe314377458a7e63e483) · [M4 and M5 record](M4-M5-ACCEPTANCE.md)

## M6 evidence

The authenticated v4 ruleset digest is `d639d137937f8c42e3f26d281785defb44fb5071e9c2da179de4a8320401d5b1`. The registry audits 15 arcane and 15 martial paths. The tested ordinary spell encounter includes six martial interactions and complete signature checks for Aegis Bolt, Unravel and Siphon Life. Each other signature has an explicit admission boundary. [Release digest](../src/dfo_optimizer/data/encounter-release.sha256)

| Question | Reproduction and scope |
|---|---|
| Does a miss cost SP? | The distant target causes a paid projectile to expire. The emitted trace retains charge, release and impact or expiry. [Miss fixture](../examples/encounter-miss.json) |
| Can one cast hit several enemies? | A stationary pack supplies individual capsules and incoming blows. Common seeds compare wave, bolt and healing priorities. [Pack fixture](../examples/encounter-pack.json) |
| Can a character survive the next room? | The dungeon supplies room membership, enemy definitions, a transition and recovery. The second group activates after the first is cleared. [Dungeon fixture](../examples/encounter-dungeon.json) |
| How do defensive spells and signatures resolve? | Compare the pinned JS, compiled kernel and scalar replay on the same draw tapes. The source produced a 20-point Aegis shield on landing, 64 then 128 SP refunded on two 193-SP Unravel casts, and 14 HP healed by a 28-damage Siphon Life. [Oracle fixture](../tests/fixtures/encounter-oracle.json) |
| What is supplied by the player? | The classic importer reads a local career and attaches its record digest. Enemy current HP, overlays and attack times need observations or labeled hypothetical inputs. The Rat fixture separates catalog HP/damage ranges from the selected values. [Career reader](../src/dfo_optimizer/enemy_career.py) · [Rat fixture](../examples/encounter-rat.json) |
| Can a longer fight reverse the winning spell? | Surge won the 500 ms burst with 15 damage. Spark won at 20 s with 55 damage against the same foe, starting SP and draw tape. Native search explored 21 and 60 nodes respectively. The first independently validated results arrived at 20.69 and 9.10 ms in these two runs. [Build fixture](../examples/build-encounter-reversal.json) · [Measured policies and timings](../benchmarks/results/windows-m67-horizon-reversal.json) |
| Can a permanent choice be afforded? | Oghma consumes an identified artifact copy. The six-node Mage Firmament witness has two unspent stars. Its verified +4% spell power raised damage from 40 to 42 on the same draw tape. A stale capacity observation blocks that projection. [Progression tests](../tests/test_permanent_progression.py) · [Encounter integration tests](../tests/test_lifecycle_encounters.py) |

The encounter search can exhaust the submitted policies for its finite seed panel. The reported clear and death proportions describe those trials. Wilson intervals use an independent-seed sampling assumption. A fixed draw tape has no sampling interval. The restricted one-cast calculation enumerates the discrete outcome distribution when its preconditions hold. Unfinished runs contribute the entire horizon to censored clear time. Damage per SP is undefined when nothing was spent. Encounter evaluation establishes no population-wide build ranking. [Metric definitions](../src/dfo_optimizer/encounter.py) · [Probability calculation](../src/dfo_optimizer/encounter_statistics.py)

### Mechanics limits

Ordinary solo PvE uses supplied stationary geometry, scheduled attacks and declared recovery. PvP, boss scripts, movement AI and unobserved live-world access have no verified scores here. The duelist fixture is a single ordinary PvE opponent. Recipe identity and acquisition must match before signature riders activate. An identified specialization or a catalog entry alone establishes no combat bonus. Read each result's blockers and the per-path record. [Mechanics registry](../src/dfo_optimizer/data/encounter-mechanics.json) · [Path catalog](../src/dfo_optimizer/data/encounter-paths.json)

Projectile travel assumes an unobstructed lane and the stated first-impact distance. The continuous-time model rounds to microseconds. Actual impact in the game also depends on when the next frame updates the projectile. Intermediate walls, moving interceptors and frame-by-frame arbitration require additional inputs.

Joint lifecycle scoring has tighter prerequisites. A touch-only chain needs verified safe downtime and compatible intervening activities. Persistent effects need an exact transition. Hostile spell bundles, reflected player spells, self-blast and several equipment interactions require checkpoint defense or provenance that an ordinary save can omit. The public encounter service accepts more detailed observations for standalone fights. [Checkpoint prerequisites](../src/dfo_optimizer/lifecycle_encounter.py)

## M7 evidence

Run `dfo ui`, select **Gear & Loadouts** and search the **Best owned**, **Budget upgrades** and **Theoretical BIS** examples. Save the results, then inspect them in **Compare Builds**. To reproduce a run elsewhere, export its archive, open it in the second installation's local library and inspect the ruleset status before comparing scores. **Spell Lab** supports fixed-spell scaling and encounter searches. **Progression** displays the next action and checkpoint outcomes. [User commands](../README.md) · [Browser tests](../tests/test_workbench_browser.py)

The workbench preserves the original representation of imported JSON numbers when a player attaches a character or changes another field. For example, a player can change target HP and keep both a `1.0` price factor and an observation ID of `9007199254740993`. The Node tests exercise modern and older browser JSON parsers and check that comparison ignores object-key order while distinguishing different frozen numbers. [Editor regression tests](../tests/test_workbench_exact_json.py)

## Qualification record

| Gate | Evidence |
|---|---|
| Windows source build | MSVC 14.50 and CPython 3.12 compiled all seven extensions. The initial source-oracle and native encounter suite passed 53 tests in 0.15 s. A second build included room scheduling, martial hooks and frontier changes. |
| Native frontier and limits | The second build passed 31 native tests in 0.09 s, including all five objectives on 16 policies and five common seeds, draw-tape memory accounting, room transitions and martial effects. |
| Seeded public service and independent replay | The second build passed 44 focused tests in 0.25 s. The suite exercises the two-room dungeon, the 5 s magic-round clock, physical book eligibility, six martial listeners, a restricted exact distribution, immutable input snapshots and cancellation during validation. |
| Windows integration | A source checkout with the compiled extensions passed 107 tests in 4.10 s across the oracle, native encounters, lifecycle, Firmament, spell scaling and real HTTP requests. The final focused run passed 111 tests, including the native ending HP/SP witness and a 4% physical Wellspring ring that restored 8 SP on a 210 SP pool. These selections overlap. |
| Frozen source regression tests | The MSVC build passed 262 focused tests in 12.24 s, covering ruleset authentication, native searches, HTTP services and both JavaScript numeric-preservation paths. |
| Installed Windows wheel | 647 tests passed in 49.35 s, including all seven Chromium workflows. One POSIX signal test skipped. Python coverage was 91.28% (6,987 statements, 609 missed). All seven source oracles passed. Dependency verification passed and all 154 installed files checked against the wheel matched. |
| Sealed Windows artifacts | All 226 package, fixture, test and tool inputs checked against the extracted source archive matched the checkout. SHA-256 for the source archive is `b1d882fd2a31f29e1c35b03cbb84a10412c600fb5fac78747b0bbe6f55636732`. The wheel built from it has SHA-256 `fcbb131fbbb050ff33bfd549fae9f582b237fb90bad801b29b29356ffc96857b`. |
| Linux wheel | Pending. No Linux guest was available for this build. The Linux workflow runs the same installed-wheel qualification. |
| Instrumented native coverage | Pending for this revision. The Linux job runs `python tools/verify_native_coverage.py`. |
| Browser workflows | After system drive space was restored, Chromium passed the class, gear, progression, archive, numeric round trip and cancellation workflows on the sealed Windows wheel. The retry corrected test locators and timing observation. Class and gear results became visible 275–305 ms after clicking Run in the measured run. [Chromium measurements](../benchmarks/results/windows-m67-workbench-browser.json) |
| Windows serial performance | All five suites ran using the installed wheel. The three-policy pack used 258 events and retained two distinct frontier points in 2.12 ms warm. Peak RSS across the encounter suite was 27.76 MiB. [Measurements](PERFORMANCE.md) · [Wheel qualification and report hashes](../benchmarks/results/windows-m67-qualification.json) |
| Comparison with 0.3.0 | Across three alternating runs of each installed wheel, all 18 legacy workloads reproduced their inputs, work counts and objective results. Every slowdown was below the 10% investigation threshold. The largest suite-level peak RSS increase was 3.56%. [Paired release report](../benchmarks/results/windows-m67-release-comparison.json) |

Release qualification still needs the installed Linux tests, Linux Chromium workflows and compiler-instrumented native coverage. Hosted CI was not run. The 0.3.0 coverage and timings apply only to the earlier kernels.

<details>
<summary>Implementation files relative to the 0.3.0 checkout</summary>

| Directory | Files |
|---|---|
| `.` | `AGENTS.md`, `README.md`, `pyproject.toml`, `setup.py` |
| `.github/workflows` | `wheels.yml` |
| `benchmarks/results` | `windows-m67-admission-profile.json`, `windows-m67-combat.json`, `windows-m67-encounter.json`, `windows-m67-horizon-reversal.json`, `windows-m67-initial-comparison.json`, `windows-m67-lifecycle.json`, `windows-m67-progression.json`, `windows-m67-qualification.json`, `windows-m67-release-comparison.json`, `windows-m67-smoke.json`, `windows-m67-workbench-browser.json`, `windows-m67-workbench-http.json` |
| `docs` | `ARCHITECTURE.md`, `ENCOUNTER-BUILDS.md`, `M6-M7-ACCEPTANCE.md`, `MECHANICS.md`, `OPTIMIZATION.md`, `PERFORMANCE.md` |
| `examples` | `build-encounter-reversal.json`, `encounter-duel.json`, `encounter-dungeon.json`, `encounter-miss.json`, `encounter-pack.json`, `encounter-rat.json`, `spell-scaling.json` |
| `src/dfo_optimizer` | `_encounter.pxd`, `_encounter.pyx`, `_lifecycle.pyx`, `_native.pyx`, `_progression.pyx`, `_spells.pyx`, `character_files.py`, `cli.py`, `encounter.py`, `encounter_advanced_reference.py`, `encounter_benchmark.py`, `encounter_defenses.py`, `encounter_effects.hpp`, `encounter_frontier.hpp`, `encounter_kernel.hpp`, `encounter_powers.hpp`, `encounter_reference.py`, `encounter_request.py`, `encounter_signatures.py`, `encounter_statistics.py`, `enemy_career.py`, `firmament_combat.py`, `gear.py`, `lifecycle.py`, `lifecycle_combat.hpp`, `lifecycle_domain.py`, `lifecycle_encounter.hpp`, `lifecycle_encounter.py`, `lifecycle_replay.py`, `lifecycle_search.hpp`, `loadout_encounter.py`, `permanent_progression.py`, `progression.py`, `progression_domain.py`, `progression_mechanics.hpp`, `progression_replay.py`, `progression_search.hpp`, `ruleset.py`, `search.py`, `spell_curve.py`, `spell_kernel.hpp`, `spellbook.py`, `spells.py`, `workbench.py`, `workbench_files.py`, `workbench_jobs.py`, `workbench_services.py` |
| `src/dfo_optimizer/data` | `encounter-mechanics.json`, `encounter-paths.json`, `encounter-release.sha256`, `permanent-rules.json`, `permanent-rules.mjs`, `progression-lock.json`, `ruleset.json` |
| `src/dfo_optimizer/data/workbench` | `app.js`, `editor.js`, `exact-json.js`, `index.html`, `results.js`, `view.js`, `workbench.css` |
| `tests` | `conftest.py`, `test_encounter.py`, `test_encounter_benchmark.py`, `test_encounter_cli_contract.py`, `test_encounter_native.py`, `test_encounter_oracle.py`, `test_encounter_reference.py`, `test_enemy_career.py`, `test_installed.py`, `test_lifecycle_encounters.py`, `test_permanent_progression.py`, `test_release_benchmark_comparison.py`, `test_ruleset.py`, `test_spell_curve.py`, `test_workbench.py`, `test_workbench_assets.py`, `test_workbench_browser.py`, `test_workbench_exact_json.py` |
| `tests/fixtures` | `encounter-oracle.json` |
| `tools` | `compare_release_benchmarks.py`, `verify_native_coverage.py`, `verify_wheel.py` |
| `tools/ruleset` | `encounter_oracle.mjs`, `encounter_oracle.py`, `encounter_release.py`, `enemy_oracle.mjs`, `equipment.py`, `generate_character.py`, `progression_oracle.py`, `spell_oracle.py`, `spellbook_oracle.py` |

</details>

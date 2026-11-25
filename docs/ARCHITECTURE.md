# Architecture

The CLI submits a frozen class search to `dfo_optimizer.search.optimize_classes`. The request parser validates and normalizes domain IDs, objective and budgets. The service applies profile eligibility, passes compact tables to one native call, and decodes retained candidates. The independent class validator replays the game document for each published candidate. Search outputs include the normalized request or proof scope, content identity, termination and work counters. Later spell, gear and progression services should reuse these boundaries.

The offline bundle describes one supported game snapshot. A ruleset rebuild requires its Git objects and Node. Normal evaluation requires the installed wheel and the bundle. A class document contains builder choices. Race belongs in the optimizer snapshot. Keep observed character data separate from hypothetical classes when adding later milestones.

Class and progression services authenticate their private packaged snapshot once. When a caller supplies the current bundle, a compiled comparison checks the entire JSON tree against that private copy, including numeric types, signed zero and every object key. The service then reads its own copy. Earlier pinned versions and alternate JSON-compatible representations use canonical hashing and detachment. Changing a caller's dictionary after admission cannot alter the running search. [Admission regressions](../tests/test_ruleset.py)

## Validation boundaries

1. The test-only Node oracle invokes the pinned game's own parser, builder and career functions. Its fixtures carry their source revision.
2. Tests independently enumerate small spaces and compare complete sets, effective trait order, and deterministic ties.
3. The production extension performs batch evaluation and combinatorial search. The wheel acceptance suite imports the extension in a fresh environment, checks actual work and exercises the same CLI a user runs.

The repository builds one CPython platform wheel per Python version, OS and architecture. Windows x64 uses MSVC. Linux x64 uses a C++17 compiler. The Linux acceptance wheel targets its build environment. A broadly portable manylinux release would require a manylinux builder and auditwheel qualification.

## Spell and equipment services

Spell and gear requests use the same pinned instant-damage mechanics. A portable character snapshot carries separate observed and unequipped casting values, saved spell records, container-qualified item copies and observation provenance. The import adapter reads a selected slot locally. Optimization consumes the detached snapshot.

The spell service sends a validated caster, target and finite setting domains through a coarse Cython call. Its C++ kernel counts discrete outcomes and accumulates expected HP loss over legal magnitude intervals. The gear service evaluates or searches whole configurations, folding modifiers and calling the same C++ spell arithmetic. Independent scalar replay checks the published spells and the equipment solver's retained results. Each service reports its candidate universe and termination reason. The installed CLI and benchmark exercise those service entry points.

## Progression and lifecycle services

Progression, spellbook and lifecycle services accept the same frozen inputs from the CLI and benchmarks. The progression worker expands batched legal transitions. The spellbook worker evaluates ordered direct effects and paid cast sequences. The lifecycle worker carries equipment copies, purchases and reserved resources across checkpoint policies. Independent replay starts from the embedded character and observations. [Progression and lifecycle design](adr/0004-progression-and-lifecycle.md)

## Encounter execution and desktop jobs

The encounter service freezes caster, room geometry, enemies, incoming actions, rest opportunities, spells, policies and a seed panel. A single Cython call passes those tables to a C++ event queue. Each trial owns its RNG, cast tokens, effect clocks and HP/SP pools. Native search retains candidates on the requested objective. The separate scalar replay starts from the frozen request and verifies the per-trial totals, draw count and ordered first-trial trace for every emitted policy. The Node oracle loads the pinned game's own functions to provide a third comparison. [Encounter service](../src/dfo_optimizer/encounter.py) · [Native kernel](../src/dfo_optimizer/encounter_kernel.hpp) · [Game oracle](../tools/ruleset/encounter_oracle.mjs)

An encounter checkpoint can also run inside the native lifecycle search. A branch can carry a different loadout, learned spells, remaining HP or spendable SP into the next checkpoint. The domain rejects routes that would require an unobserved persistent effect or an unmodeled change of capacity. Fixed-spell sensitivity curves use a separate batch entry point in the existing native spell kernel and check each displayed point with the scalar distribution.

The workbench serves packaged HTML, CSS and JavaScript over loopback. An allowlist maps each job to the same Python service and native cancel token as the CLI. One worker owns an admitted request until it terminates. A preview is a complete, independently validated shorter run with its own budget. Archive export preserves the server's original JSON numbers. Closing the server cooperatively cancels active work. [Job service](../src/dfo_optimizer/workbench_jobs.py) · [Desktop qualification](M6-M7-ACCEPTANCE.md)

## Reference application audit

The OSRS audit used revision `97834e66983b906f800481ad46abcd2e5924babf`, including the architecture, build configuration, native transition/frontier code, integration tests and frozen benchmark replay. DFO uses frozen inputs, coarse native calls, exactness labels, result digests and separate service/kernel measurements. [OSRS Recommender](https://github.com/cabeard21/osrs_recommender/tree/97834e66983b906f800481ad46abcd2e5924babf)

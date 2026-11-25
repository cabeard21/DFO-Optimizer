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

## Current acceptance commands

Build a platform wheel with `python -m build` and run `python tools/verify_wheel.py`. Use the pinned source checkout in `vendor/dfo-source` or set `DFO_SOURCE` to an existing checkout containing the reviewed Git objects. Run `dfo benchmark --suite smoke --workers 1` for a comparable serial workload. Record host, build, work counters and result identity when updating timing baselines.

Spell and equipment releases also require `dfo benchmark --suite combat --workers 1`. Compare bounded and exact Pareto points on the same reduced request. Run the class, character-export, spell and equipment oracle regeneration checks against the pinned tree. Test the imported-save CLI and both new extensions in installed Windows and Linux wheels. On Linux run `python tools/verify_native_coverage.py` for compiler-instrumented coverage.

Keep earned and live Destruction separate, and track the timestamp and source of resource observations absent from a save. For gear, carry physical copy IDs, occupied positions, class restrictions, purchase evidence by currency and the spell selected at that loadout. State the actual roll universe and encounter assumptions with every frontier.

For progression, retain the online birth sum, greatest observed skill sum, fractional practice, rest and training clocks, unspent choices and irreversible masteries. Replay every published route from its frozen start. Report practice, game minutes, gold and any assumed real-time cadence separately. Track the first missing prerequisite when replay stops. A specialization unlock and acquiring its signature spell are distinct events.

Lifecycle comparisons use paired legal creation rolls and share only information available at each stage. Preserve owned item instances, learned spells and prior spending across checkpoints. Keep resource-distinct successors until their future options are demonstrably equivalent. Record time to the first independently replayed route in addition to native search time. Run both progression and lifecycle benchmark suites on the installed wheel.

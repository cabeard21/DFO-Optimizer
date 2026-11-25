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

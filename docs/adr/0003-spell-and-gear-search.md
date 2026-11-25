# Joint spell and equipment evaluation

M2 and M3 use a single native evaluator for the pinned direct Damage Health effect. For each caster state, a cumulative table of exact discrete HP-loss sums permits constant-time interval scoring after setup. The kernel applies the game's rounding and target HP cap to individual outcomes before averaging. Both fixed and optimized spells use these semantics. [Source replay and evidence](../SPELL-MECHANICS.md)

M3 searches whole loadouts. The native traversal tracks physical copies, occupied slots, purchases and resource state, then scores spells for the resulting modifier combination. This preserves interactions at cost floors, stat caps and repeated legendary effects. A per-request cache reuses equivalent spell work. A reduced joint fixture checks the resulting frontier by independently enumerating loadouts and recipes. [Joint differential tests](../../tests/test_joint_frontier_review.py)

Budgeted traversal can stop at either the equipment or spell layer. Results carry the actual termination, work and evidence scope. Timing uses a separate field from the deterministic result fingerprint. Theoretical rolls use a finite, reproducible catalog that allows source-law validation of every emitted item. [Equipment evidence](../EQUIPMENT.md)

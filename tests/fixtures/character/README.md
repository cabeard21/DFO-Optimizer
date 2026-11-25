# Export fixture

`export.zip` is a deterministic two-slot export of synthetic casters. The pinned game builds the custom spell, serializes the player, stores each slot, and writes its normal ZIP. The input includes a worn ring, a spare magic ring with +6% casting speed, a spellbook, a stock spell index, a custom spell, and items in the wagon and at the repairer. The only storage substitute is an in-memory implementation of the Web Storage interface. The exporter reads local Git blobs authenticated against the project's source locks.

Run `python tools/ruleset/generate_character.py --source vendor/dfo-source --check` to reproduce the bytes. Run `dfo character import --input tests/fixtures/character/export.zip --slot 0` to inspect the first character. For your own export, use **Move saves → Export all saves** in the game's enhanced Load menu.

The four worked requests use slot zero, Arden at level 5. The fixed requests use the exact Fire/By Touch settings of the saved Ember spell. The automatic requests search the listed values against one synthetic target. The game saves resources after removing online bonuses. The examples that constrain SP include a separately attributed, synthetic 42-SP observation. Supply a current observation from your own character sheet when using a personal export.

```sh
dfo evaluate --request examples/spell-fixed-from-save.json --character tests/fixtures/character/export.zip --slot 0
dfo spell optimize --request examples/spell-auto-from-save.json --character tests/fixtures/character/export.zip --slot 0
dfo gear evaluate --request examples/gear-fixed-from-save.json --character tests/fixtures/character/export.zip --slot 0
dfo gear optimize --request examples/gear-auto-from-save.json --character tests/fixtures/character/export.zip --slot 0
```

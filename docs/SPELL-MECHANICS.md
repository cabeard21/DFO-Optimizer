# Direct spell evidence

The M2 rules cover instant Damage Health `(4,0)` cast by a player at one ordinary PvE foe in the pinned online snapshot. Every result uses the live Destruction skill for pricing and the earned, mastery-limited school climb for potency. The model assumes one confirmed impact and sufficient time to repeat the input at the normal animation interval. The caller provides the foe's HP, Willpower and supported resistance state. [Mechanics registry](../src/dfo_optimizer/data/spell-mechanics.json)

| Calculation | Evidence and boundaries |
|---|---|
| Legal recipe | The maker accepts two independently ordered magnitude pairs, four non-self targeting modes and five elements. It prices one effect using integer averages. Each actual cast rolls both inclusive pairs independently. The level roll is multiplied by the integer quotient of caster level and the level divisor. [Extracted settings and coefficients](../src/dfo_optimizer/data/spell-rules.json) |
| Gold and SP | The UI quotes the chapter-adjusted gold amount. The cast uses the target multiplier, skill-scaled pricing and a baseline five-SP floor. Worn Focus then applies. In the oracle's two-ring example, 12% Focus reduces five SP to four. Affordability depends on current SP. The cast host fixes the quote when readied and charges on click. [Source vectors](../tests/fixtures/spell-oracle.json) |
| Landing | Elemental resistance can block the effect outright. Career tolerance precedence and resistance modifiers feed the immunity gate before the Willpower adjustment, penetration and final 5–95 clamp. The game prorates partial saves against a D100. It truncates saved magnitude before applying power and rounding. Each expected value weights complete discrete outcomes. [Independent upstream driver](../tools/ruleset/spell_oracle.mjs) |
| Rate and efficiency | At rate one the ordinary cast releases at 0.20 s and the next may start at 0.70 s. The hypothetical repeated-cast DPS uses the latter interval and an identically situated target for every cast. Damage/SP uses target HP loss and the SP charged. A refused cast spends zero SP. [Pinned animation](https://github.com/Lattymoy/daggerfall-js-source/blob/a3eb1605ea1dc391b691fe314377458a7e63e483/src/combat/fpsSpellCasting.js) |

## Reproduce the evidence

From an environment with the package installed, run:

```sh
python tools/ruleset/spell_oracle.py --source vendor/dfo-source --check
python -m pytest tests/test_spell_oracle.py
```

The rules extractor reads pinned module exports. An independent driver invokes the Spellmaker, cast host, effect assignment, live cost and power registries, and animation scheduler. Its 19 fixed-cast comparisons enumerate 20,100 equally weighted outcomes over magnitude and save rolls. Six additional host scenarios check payment timing, a changed skill, a drain between ready and click, a free cast, a refused ready and a touch miss. An overkill observation records both the damage sent to the foe and the health the host says that impact could take. The fixture records the synthetic inputs and stubs.

The source checkout supplies Git objects from the reviewed commit. Both drivers stage authenticated blobs in a temporary directory. Normal optimization uses the installed ruleset. The public snapshot has no verified live-version mapping. Projectile arrival, moving targets, splash victim counts, ongoing damage, absorption, reflection, recovery and conditional encounter powers require additional mechanics for a full encounter comparison.

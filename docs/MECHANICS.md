# Mechanics and evidence

Authority for this release is the November 2, 2026 public snapshot at `a3eb1605ea1dc391b691fe314377458a7e63e483`. Run `dfo ruleset coverage` for the machine-readable registry. Live client compatibility is unknown.

| Mechanic | Snapshot evidence and application |
|---|---|
| Difficulty and advancement | HP 4–30, with HP contribution `hp - 8` from 8 upwards and `2 * (hp - 8)` below 8. Add signed trait costs before the inclusive −12 to 40 creator check. Advancement is `0.3 + 2.7 * (points + 12) / 52`. [Source](https://github.com/Lattymoy/daggerfall-js-source/blob/a3eb1605ea1dc391b691fe314377458a7e63e483/src/systems/customClass.js#L19-L44) |
| Attributes, skills, reputations | Ordinary imported classes have eight integer attributes in 10–75 and a 400-point balance. The 12 distinct skill IDs form groups of 3/3/6. The creator checks its internal stat ledger. Its reset path can clear an imbalance. Generated classes use the 400-point rule. Reputation balance is checked when closing the reputation editor. Generated classes use neutral reputations. [Creator](https://github.com/Lattymoy/daggerfall-js-source/blob/a3eb1605ea1dc391b691fe314377458a7e63e483/src/ui/chargen.js) |
| Class-file contract | V1 stores skill names, attributes, HP, lists of trait picks, and reputations. The reader also accepts numeric skill IDs and partial drafts. It processes advantages first and reports skipped picks. A nonempty name, completed skills, balanced imported stats, and legal difficulty are separate Create checks. [Game adapter](https://github.com/Lattymoy/daggerfall-js-source/blob/a3eb1605ea1dc391b691fe314377458a7e63e483/src/systems/customClass.js#L268-L411) |
| Traits | 42 advantage and 48 disadvantage options. Each side admits up to seven. Primary uniqueness and secondary-specific conflicts apply. Healing, regeneration and absorption each permit multiple secondaries with a last-write career flag. Every chosen entry contributes its cost. [Trait definitions and career writes](https://github.com/Lattymoy/daggerfall-js-source/blob/a3eb1605ea1dc391b691fe314377458a7e63e483/src/systems/specialAdvantages.js) |
| Race and starting spells | The optimizer carries one of eight playable race IDs separately. A custom class with a magic school in primary or major qualifies for the Spellsword starting set. This selection alone leaves actual early damage and training viability unknown. [Races](https://github.com/Lattymoy/daggerfall-js-source/blob/a3eb1605ea1dc391b691fe314377458a7e63e483/src/systems/races.js) · [Starting set](https://github.com/Lattymoy/daggerfall-js-source/blob/a3eb1605ea1dc391b691fe314377458a7e63e483/src/systems/customClass.js#L169-L172) |

## Regression evidence

The 14 public Dhargo class files independently parse at −12 and 0.30× with zero skipped picks, 12 skills and 400 attribute points. One additional constructive witness pairs HP 30 (+22) and 3× INT Magery (+10) with prohibitions on steel, elven, dwarven, mithril, silver, adamantium and iron (−44). These seven restrictions consume the entire disadvantage allowance and must follow the class into future gear evaluation. [Dhargo comparison corpus](https://drive.google.com/drive/folders/1GNvjKwC8XU5wXPA3VMkdWFNp3efRr8wb)

## Open mechanics

Combat potency and saves, spell costs and timing, effective defensive tradeoffs, target-specific damage, gear access, online regeneration, and attainable training paths need later evidence. M1 can encode the associated flags and offer construction examples. It cannot certify survival, damage, progression feasibility or an optimal mage. Historical High Elf and Breton builds require actual source documents before they can serve as comparison fixtures.

For a live observation, retain the client version/date, mode, class export, race, sheet values, exact action or spell settings, target, displayed and observed values, and any uncertainty. Compare the intermediate result with the matching snapshot mechanic. A live overlay requires explicit evidence, a new hash, and a replay test.

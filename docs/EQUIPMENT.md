# Equipment evidence and search scope

Equipment uses public Daggerfall Online revision `a3eb1605ea1dc391b691fe314377458a7e63e483`. The catalog covers 122 classic templates across jewelry, weapons, armor, gems and the two clothing groups. Of those templates, 120 have a wearable placement. The adapter asks the game's own equip table for each template's slots, both bow-switch settings and its weapon proficiency. The optimizer also checks condition, class restrictions, metal, occupied hands and the identity of each physical copy. A broken or career-forbidden piece already worn in a valid slot can stay there. Moving it invokes the usual equip restrictions.

## Choosing a candidate pool

| Mode | Candidates |
| --- | --- |
| `owned_only` | Observed physical copies in accessible containers. Pack is the default. |
| `owned_plus_budget` | Owned items and confirmed obtainable offers with explicit prices that fit the supplied currency limits. |
| `available_catalog` | Owned items, confirmed offers and generated witnesses from a loot profile the caller confirms they can access. |
| `theoretical_bis` | Owned items, offers and hypothetical candidates from a finite list of templates, material representatives and roll combinations. |

With `catalog_access: ["tier6_pile_level45_luck50"]`, the available catalog adds magic rolls witnessed for a tier 6 non-boss pile, player level 45, Luck 50 and find multiplier 1. These values describe the particular source calculation. A level field in a save does not establish access to the pile. A witnessed roll has no quoted price. A second copy for a paired slot requires another acquisition. An offer or saved instance can supply separate evidence.

The extractor calls the game's base jewelry, armor and weapon factories, then runs `rollLootRarity` with up to 3,000 deterministic draws per base. It keeps the first eligible witness for each selected caster line on that base. The catalog holds 129 distinct witnesses and 79 further rolls selected for stronger observed lines. Witness seeds reproduce the rolls and do not estimate drop rates. Both pools can be limited with `catalog_templates`, a list of template indices.

The theoretical pool also constructs upper-band magic and rare caster rolls on weapons, armor, jewelry and clothing. It uses a legal flavor enchantment for a rare roll and chooses representative usable metals from the specified career. Two paired slots have distinct candidate copies. For an unrestricted career, the full generated domain contains 833 physical candidates. Search proofs apply to the requested candidate pool and reported spell domain. Other rolls, custom items, unpriced market stock or future acquisitions can yield other loadouts.

## Scored and unsupported effects

The decoder reads Speed, Intelligence, Destruction, Focus, Potency and cast-speed affixes. Gem contributions must match the stored sockets and their appended affix lines. It applies the per-piece gem cap and keeps legacy Enhances Skill separate from the affix fold. Duplicate legendary affixes count on the first applicable worn slot in equipment order. The gear evaluator applies the appropriate per-channel caps at loadout level. The catalog holds 40 legendary records for checking imported item properties. An item with an unsupported effect carries an exclusion reason.

Custom enchantments, curses, sigil sets, specialized templates and unmodeled legendary powers can affect a caster. Records with these effects or incomplete magic properties are excluded. Damage on a weapon strike, cast-on-use actions and incoming-attack effects belong to different scenarios from the stationary direct-spell evaluator. Game-world access, drop probability, market prices and live-server behavior require evidence outside this snapshot.

## Reproducing the source checks

From an environment with the project installed, run:

```powershell
python tools/ruleset/equipment.py --source vendor/dfo-source --check
python -m pytest tests/test_equipment.py -q
```

The first command reads the locked Git blobs, regenerates the catalog and independent fixtures, and passes every theoretical candidate through the upstream `itemFindings` function. The fixture contains 128 equip-window cases and eight comparisons against the source affix and power folds. The unit tests check the production decoder against those results. The source entry points are `src/systems/equip.js`, `src/characters/equipTable.js`, `src/systems/loot/lootRarity.js`, `src/systems/loot/lootPowers.js`, `src/systems/enchantments.js` and `src/systems/item/itemLaw.js`.

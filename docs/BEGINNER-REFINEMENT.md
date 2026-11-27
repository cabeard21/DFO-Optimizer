# Choosing a first spellcaster

Open the workbench and select **Recommend My First Spellcaster**. The recommendation and its alternatives use 0.30× advancement, 30 class HP and 3× Intelligence magery. The result gives the race, a game-importable class and a printable creation checklist. Skills remain in their creation order. Use **Compare slower builds** to see what a higher multiplier buys for equipment or defense while keeping the first recommendation available.

## What the comparisons measure

- Creation starts with the actual kit from paired rolls. Level 15 permits a representative set of mundane gear through ebony, subject to the class restrictions and carry capacity. The level-45 practical pool adds Orcish. The theoretical comparison adds Daedric and conditional access to selected Spell Maker recipes. Each checkpoint is a conditional access example. Item availability, acquisition prices and drop rates remain unknown.
- The main panel covers physical pressure, enemy casters, resistant targets, groups, dungeon sustain and recovery. Low-magicka fights start at up to one quarter of the pool. The gear comparison also tests fresh fights with zero spell points so the backup weapon and armor can affect the outcome. Held-spellbook equipment comparisons reuse the selected specialization and casting policy.
- Offensive spell candidates come from bounded native Spell Maker search. The defensive candidates use pinned prices and legal settings. Native policy selection uses a distinct tuning draw. Published combat uses two creation rolls and two combat draws with independent event replay. The simulated attacks and gear opportunities are authored scenarios.
- Arcane paths need the earned mastery pair. Battlemage is tested with its shield-dependent benefit and with an attributed offer for Aegis Bolt. Soulbinder measures eligible kill refunds. Soul Lance and trap-enhanced refunds require additional mechanics. Theoretical gear covers the reviewed mundane pool. Enchanted gear with unresolved joint encounter effects remains outside these scores.
- A dedicated Magic-damage opponent measures Breton's racial resistance. The panel has no hostile paralysis and does not exercise archery. Wood Elf short-blade bonuses apply when the equipped weapon uses that family.

The combat leader is selected by weakest clear and survival rates, then average clears. A build within five percentage points on those rates and five percent on capped damage can lead the recommendation if it has better practical upgrade access or owned-gear results. The advanced result shows the raw differences.

## Reproduce the runs

```powershell
dfo build recommend --thoroughness quick --output build/first-quick.json
dfo build recommend --thoroughness standard --output build/first-standard.json
dfo build recommend --thoroughness thorough --output build/first-thorough.json
dfo build recommend --compare-slower build/first-standard.json --output build/first-slower.json
dfo build replay --plan build/first-standard.json
dfo class export --result build/first-standard.json --output build/first.dfclass.json
```

The submitted historical workbench archive is retained losslessly in [the regression fixture](../tests/fixtures/beginner-submitted-archive.json.gz). Its original profile and result identity can still be replayed. Comparisons between the historical and refined panels should account for the changed equipment, spells, hostile damage and policy domains.

## Measured recommendation

**Choose the Breton spellblade at 0.30×.** Use the [game class](../benchmarks/results/m9-refinement-breton.dfclass.json) and [creation checklist](../benchmarks/results/m9-refinement-breton-checklist.txt). Start with Minor Shock up close, Arcane Arrow at range and Salve Bruise for healing. Keep the Iron Broadsword for low magicka. Look for an Ebony long blade and cuirass when available. Work toward Battlemage by mastering Destruction and Alteration, then buy Aegis Bolt when the shelf offers it.

| Paired refined panel | Mean survival | Survived and cleared | Capped damage/s | Compatible weapon and plate metals |
| --- | ---: | ---: | ---: | ---: |
| Recommended Breton | 97.7% | 73.1% | 110.74 | 4 |
| Submitted Wood Elf | 96.2% | 68.2% | 110.74 | 3 |
| Manual High Elf | 93.9% | 66.3% | 110.74 | 4 |

- The Breton permits Iron, Ebony, Orcish and Daedric. With the spellbook and path held fixed, the representative gear cut mean HP lost in the level-15 comparison from 24.7 to 8.7. At zero magicka it dealt 30.5 mean melee damage there versus 11.5 with owned gear. At cap those figures were 46.25 with representative gear, 10.0 with owned gear and 100.5 with theoretical gear. None of those four-draw capped fallback comparisons cleared the physical fight in time. The archived Wood Elf reached 124.0 mean melee damage in the theoretical pool.
- In the race-only comparisons, switching the archived class from Wood Elf to Breton changed mean damage taken from the birth Magic attacker from 47.75 to 31.5 HP. It did not change capped damage or mean clear rate. High Elf paralysis immunity remains a reason to reconsider if paralysis is important in the locations you play.
- On the Breton's common capped path subset, Battlemage with Aegis Bolt scored 122.87 DPS versus 77.35 with no path or with Battlemage alone. Soulbinder tied the latter damage figure and restored 41.25 SP per fight on average. Spellbreaker scored 88.10 DPS and Riftwalker 87.44. These are paired path-subset figures and use a different denominator from the all-scenario capped table.
- The 0.35× Argonian kept Adamantium, averaged 74.6% clears and 94.3% survival, and took about 169,339 practice actions versus the Breton's 143,035. The 0.56× one-ban Breton variant added Adamantium as a fifth compatible metal. It took about 270,146 practice actions, and its measured capped zero-magicka damage stayed at 46.25. Neither result displaced the chosen 0.30× build. Under the sampled beginner trait policy, the pinned cost ledger gives a conservative ceiling of four compatible metals at 0.30×.

| Search | Native classes screened | Fully evaluated | First checked / elapsed | Peak process RSS |
| --- | ---: | ---: | ---: | ---: |
| Quick | 2,048 | 8 | 3.09 / 30.05 s | 54.4 MiB |
| Standard | 8,192 | 33 | 3.73 / 120.07 s | 69.2 MiB |
| Thorough, 180-second override | 32,768 | 47 | 5.33 / 180.10 s | 93.4 MiB |

All three runs selected the same Breton on this machine. The longer runs evaluated more constructions with no change to the recommendation. Wall-limited run counts can vary by host load. Search and performance claims cover the finite declared candidates, recorded draws and supported mechanics. [Machine-readable comparisons and requests](../benchmarks/results/windows-m9-refinement.json)

The Standard result independently replayed all 33 fully evaluated classes and 8,712 ranking-panel outcomes on the installed Windows wheel. The historical archive independently replayed 25 classes and 9,300 outcomes with its original profile.

The Windows installed qualification passed 880 tests with one POSIX-only skip and 91.65% Python line coverage, including Chromium. The final wheel passed a further 32 focused installed tests after the replay-boundary and checklist refinements. All seven serial benchmark suites passed on that final wheel. Linux and live game behavior were outside this qualification.

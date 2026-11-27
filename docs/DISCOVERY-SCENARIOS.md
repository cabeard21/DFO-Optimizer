# Prospective spellcaster scenarios

The **Discover Spellcaster Build** presets submit ordinary lifecycle requests. Every result depends on the frozen opportunity schedule, equipment offers, birth tapes, target and supported mechanics. Use the guided editor or the full request to change these inputs before running a comparison.

| Preset | Compared outcome |
| --- | --- |
| Early caster development | Birth through the first earned level increase |
| Midgame caster progression | Birth through level 15 |
| Endgame direct damage | Funded direct spell DPS at level 45 |
| Sustained dungeon clearing | A level-one caster faces an Orc and an Orc Shaman in two rooms with HP and SP carried between them |
| Enemy spellcaster | A level-one caster faces an Orc Shaman with an explicit hostile spell and a darkness assumption |
| High-resistance opponent | Damage to an authored warded foe with Willpower 85 and an active 50% resistance ward |
| Multiple targets | The shared three-enemy pack with its frozen positions and incoming attacks |
| Creation to level 45 | Pareto tradeoffs in checkpoint DPS, practice, rests, game minutes and gold |
| Theoretical endgame equipment | Level-45 DPS with cost-free access to a finite panel of constructed rare item rolls |

Level-45 presets start with four screened classes, compare each on birth seeds 42 and 43 and share four million nodes across admission, progression and combat. Earlier and encounter presets start with eight classes, eight common rolls and one million nodes. All presets have a two-minute deadline. Edit the seed panel and budgets to compare additional rolls.

## What the shared itinerary assumes

Each family receives the same conditional access to a Spell Maker, practice activities, a full-recovery bed and one identified coin purse. The purse is a hypothetical pickup after creation. Setting its amount to zero removes it. Its contents, lodging access, frequency of qualifying activities and encounter sizes describe the scenario. They establish no drop rate, merchant stock, travel forecast or normal time to level. The common birth seed also selects the level-up HP rolls. Reported game minutes, training counts, gold and assumed real-time cadence have different units.

The circuit prioritizes magic schools in each skill group, then supported utility activities in the submitted slot order. Medical receives its ordinary rest tallies. Three primary, two major and one minor skill can receive permanent mastery after earning the prerequisite. Practice uses actual source starter spell records when present. A missing practice recipe can be inscribed as a newly identified single-effect custom spell and costs its computed Spell Maker price. Funded casts earn skill tallies, and capped skills stop consuming practice opportunities. The goal stops the circuit at its first attained checkpoint. The default compares two coherent allocation policies. One fills Intelligence then Speed, the other Speed then Intelligence. Both continue with Endurance, Willpower, Strength, Agility, Personality and Luck up to the verified caps. The native planner commits to a policy when it spends the first earned level's points. Remove `alternate_allocation_orders` to fix one policy or supply up to three alternatives. The demo freezes a single Intelligence-first route for the paired comparison.

Set `mastery_priority` to an ordered list of skill names to prefer specific eligible schools or utilities. The default practices and masters schools first within each quota. Set `itinerary.specialization` to an object containing an arcane `path` and a positive `after_circuit` to test an explicit selection opportunity. At that point both prerequisite masteries must have been earned. An optional `signature_offer` supplies a `gold_cost` and attributed `evidence`. The service constructs the source signature recipe from the authenticated path catalog, then charges the quoted price as a separate purchase opportunity. The ordinary presets compare classes before specialization. Scoring an active path requires the supported encounter context and the path's additional evidence.

Conditional lodging covers an uninterrupted bed after each practice session. A two-hour zero-fare arrival opportunity separates full nights. Caster practice assumes targets in range, successful releases, and the declared common challenge and cadence. The Dodging opportunity assumes an enemy swing reaches the character and rolls zero damage. The practical panel compares each subset of the three displayed caster pieces against empty caster slots. Each price, physical copy and rolled effect is visible in the input. The material-gated steel dagger is one of those copies. The theoretical panel compares a rare weapon, amulet, gloves and ring from the gear service's constructed roll universe. Neither pool establishes universal best-in-slot gear.

To substitute observed enemy defenses, run dfo encounter import-enemy --input MONSTER.BSA --mobile-id 21 --hp 32 with your local career archive and the HP you observed. Copy the returned target fields into the encounter, retain its record hash in the evidence and supply positions and schedule separately. A reported blocker identifies additional live facts required by that career.

## Sensitivity and reproduction

Add a sensitivity object to a practical discovery request to rerun admission with one changed assumption per variant. The service divides the requested total node and wall budgets among the primary run and its variants. It reports the retained families, status and node use of each alternative. Use fixed node budgets for repeatable comparisons. Birth and encounter seeds stay paired.

```json
"sensitivity": {
  "cache_gold": [0, 80],
  "practice_cadence_ms": [30000],
  "gear_access": ["owned"]
}
```

Other axes include `challenge_level`, `practice_circuits`, `budget_gold`, `max_nodes` and encounter `horizon_us`. Gear access accepts `owned`, `practical` or `theoretical`. A threshold miss may come from missing resources, a finite schedule or a bounded search. Inspect the route gaps and coverage for the paired seeds before comparing families.

Run `python tools/run_discovery_demonstration.py --output build/discovery-demo` from a checkout with the compiled extensions and package data. It executes the checked-in early discovery request, selects two discovered families with replayed results on both seeds and compares them with the default M1 example and both caster baselines. Each family gets the same cap itinerary and a separate terminal encounter against two Ancient Liches. The output ZIP contains individual workbench archives with complete requests and independently replayed results. Extract a JSON member to import it into the workbench. The JSON report records machine information, counters, checkpoint performance, elapsed time and a separate run of the untouched guided cap preset. Verify every archived request and route using python tools/run_discovery_demonstration.py --output build/discovery-demo --verify.

## Measured Windows comparison

The frozen early workload recorded 659 candidates screened across its passes, counting a candidate once within each pass. It admitted and evaluated 84 distinct families and completed downstream trials for those families and the three references on both birth rolls. Discovery took 2.47 seconds, starting with a validated result at 0.052 seconds, and took 5.00 seconds including replay and archive creation. The larger candidate universe remains bounded. The separate direct cap searches reached their node limits with replayed incumbents.

The unchanged guided creation-to-cap preset also ran on its own. Six of eight admitted families reached level 45 on both birth rolls. The first validated result took 2.03 seconds. Search took 21.15 seconds and independent replay of the 22 retained witnesses brought the total to 33.62 seconds. It used all four million shared nodes.

| Seed 42 family | Birth direct DPS | Level-45 direct DPS | Practice actions | Personal game minutes | Total gold spent |
| --- | ---: | ---: | ---: | ---: | ---: |
| Default M1 legal example | 5.944 | 102.768 | 303,874 | 6,918,864 | 162 |
| Exact INT Breton, seven material bans | 5.944 | 102.768 | 303,980 | 6,918,864 | 162 |
| High Elf reference | 5.944 | 102.768 | 303,980 | 6,918,864 | 162 |
| Discovered Breton, `0944fde7` | 0.752 | 87.062 | 144,907 | 3,986,352 | 148 |
| Discovered Dark Elf, `0594da18` | 6.673 | 87.062 | 150,944 | 4,137,384 | 128 |

All five class documents banned the offered steel dagger. The result marks that copy as excluded by the class restriction. Both discovered classes and both reference caster builds cleared the common cap encounter in 3.52 seconds on both birth rolls. Each removed 320 HP, spent 35 SP and survived. The original M1 example lacks a combat score because its passive health regeneration requires evidence about round timing. In this itinerary both discoveries cut practice by about half, giving up roughly 15% of the reference's cap direct DPS. The Dark Elf had the highest direct DPS at birth among the five on seed 42. The cap comparison panel was selected on early performance, and the separate guided cap run remained bounded. [Frozen request](../examples/build-discovery-demo.json) · [Full measurements and limitations](../benchmarks/results/windows-m8-discovery-demo.json) · [Replayed workbench archives](../benchmarks/results/windows-m8-discovery-demo.zip)

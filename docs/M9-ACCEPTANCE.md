# Beginner spellcaster recommendation qualification

The recommendation fixes one race and one custom class before the player sees a birth roll. Its comparison uses the same creation and combat tapes for every eligible class. Each game file contains the class editor choices. Select the race separately and follow the accompanying creation checklist. The eight scenarios, checkpoint opponents, attack schedules, prices and resource assumptions are documented in [Beginner scenarios](BEGINNER-SCENARIOS.md).

## Two choices from the measured standard search

**Choose Khajiit for the standard recommendation.** Import the [Khajiit class](../benchmarks/results/m9-standard-recommended.dfclass.json) and use its [creation and development checklist](../benchmarks/results/m9-standard-recommended-checklist.txt). It starts with a Broadsword backup, permits nine metals for both plate and a backup weapon, and survived 25% of fights in its weakest scenario group. Its 3.00× advancement setting took 1.42 million practice actions to cap in the declared training itinerary.

**Choose Breton if fast advancement matters more.** The [0.30× Breton class](../benchmarks/results/m9-fast-breton.dfclass.json) and [checklist](../benchmarks/results/m9-fast-breton-checklist.txt) used about one tenth as much practice to reach the cap. It survived a slightly larger share of fights overall, despite losing every fight in its weakest group. Its four compatible metals leave fewer upgrade choices.

| Fixed build | Worst-group survival | Overall survival | Survived and cleared | Plate + backup metals | Advancement | Mean practice to cap | Cap damage/s | Dungeon spell damage/SP |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Standard Khajiit | 25% | 94.1% | 73.4% | 9 | 3.00× | 1,419,715 | 52.91 | 1.50 |
| Fast Breton, forbids ebony | 0% | 94.9% | 63.7% | 4 | 0.30× | 143,035 | 49.71 | 1.79 |
| Manual Breton, forbids adamantium | 0% | 94.9% | 63.7% | 4 | 0.30× | 143,035 | 49.71 | 1.79 |
| Manual High Elf | 0% | 94.4% | 59.7% | 4 | 0.30× | 147,075 | 49.51 | 1.81 |

Every class in this table had at least one group with zero clears. Each group had four common birth/encounter draws. The rates measure these specific fights. The two Breton material choices tied on the offered equipment. The Nord alternative improved mean survival to 96.0% with 63.2% mean survival-with-clear. The Dark Elf alternative delivered 2.22 dungeon spell damage per spell point with 48.1% mean survival-with-clear. Both classes and their checklists are in the [standard demonstration archive](../benchmarks/results/m9-standard-recommendations.zip).

With the same fully evaluated classes, stronger incoming pressure and protected recovery each changed the preferred class compared with its matched baseline scenarios. Owned gear alone and removal of optional spell purchases each preserved the preferred class for the scenarios they affected. Inspect the paired measurements in the [standard report](../benchmarks/results/m9-standard-comparison.json).

Standard admitted 24 generated classes plus two manual baselines and two controlled comparisons. Twenty-two generated classes completed the common panel. One could not reach the required low-SP entry condition through the paid preparation. The time limit stopped another at level 37 during replay. Their incomplete rows did not enter the ranking. Independent replay checked 9,672 outcomes for the 26 fully evaluated classes.

| Standard Khajiit checkpoint | Survived | Survived and cleared | Maximum HP / SP on birth tape 42 |
| --- | ---: | ---: | ---: |
| Creation | 102 / 124 | 55 / 124 | 55 / 237 |
| Level 15 | 124 / 124 | 106 / 124 | 441 / 300 |
| Level 45 | 124 / 124 | 112 / 124 | 1,265 / 300 |

Each checkpoint uses its own declared enemy band. The replayed example kept the Broadsword in its right hand at all three checkpoints. Its compatible plate and weapon metals are iron, steel, silver, elven, dwarven, mithril, ebony, orcish and daedric. Actual item access depends on the play scenario.

## What a longer search found

**The thorough search found a Breton that survived all 372 sampled fights.** It cleared 174 within the declared horizons (46.8%) and had at least one group with zero clears. The default ranking favors its higher weakest-group survival over the standard Khajiit's higher clear rate. Its War Axe provides a backup, seven metals permit both plate and backup weapons, and its 2.69× advancement averaged 1,240,909 practice actions to cap. [Import the thorough Breton class](../benchmarks/results/m9-thorough-recommended.dfclass.json) · [Creation and development checklist](../benchmarks/results/m9-thorough-recommended-checklist.txt)

| Budget | Recommended race | Weakest-group survival | Mean survived and cleared | Advancement | Mean practice to cap | First validated / service time |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| Quick · 30 s | High Elf | 0% | 82.0% | 1.75× | 821,083 | 2.02 / 19.15 s |
| Standard · 120 s | Khajiit | 25% | 73.4% | 3.00× | 1,419,715 | 2.25 / 120.06 s |
| Thorough · 600 s | Breton | 100% | 46.8% | 2.69× | 1,240,909 | 2.75 / 594.37 s |

| Budget | Native class nodes | Screened / legal | Generated classes admitted / fully evaluated | Controls fully evaluated | Outcomes independently replayed | Files |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| Quick | 90,000 | 723 / 263 | 4 / 4 | 4 | 2,976 | [Report](../benchmarks/results/m9-quick-comparison.json) · [Archive](../benchmarks/results/m9-quick-recommendations.zip) |
| Standard | 378,000 | 3,111 / 1,047 | 24 / 22 | 4 | 9,672 | [Report](../benchmarks/results/m9-standard-comparison.json) · [Archive](../benchmarks/results/m9-standard-recommendations.zip) |
| Thorough | 954,000 | 8,091 / 2,761 | 100 / 87 | 4 | 33,852 | [Report](../benchmarks/results/m9-thorough-comparison.json) · [Archive](../benchmarks/results/m9-thorough-recommendations.zip) |

Each Windows run used the same two birth tapes, two encounter seeds and four controls. Quick completed its admitted panel. Standard reached its wall limit. Thirteen thorough classes could not reach the low-SP scenario through the specified paid casts and were ineligible for ranking. Independent replay of the resulting archive ran after the measured service time. A broader set of classes, different enemy schedules, more seeds or different access to gear and training could change the recommendation.

## Reproduce the comparison

```sh
dfo build recommend --output build/beginner.json
dfo build replay --plan build/beginner.json
dfo benchmark --suite beginner --workers 1 --output build/beginner-quality.json
python tools/run_beginner_demonstration.py --output build/beginner-demo
```

The demonstration runs quick, standard and thorough in fresh processes under their respective budgets. Each ZIP includes the complete request, result, independent replay, game class and checklist. Open its `workbench-archive.json` in the Library to inspect the same run. Use `--thoroughness standard` to run one budget. The public class exporter and importer check each exported class against the pinned Create rules.

## What the reduced reference measures

The [frozen qualification domains](../src/dfo_optimizer/data/beginner-qualification-v1.json) each contain eight feasible 30-HP, 3× magery classes. One varies race, the balanced Intelligence/Speed allocation and the Medical/Etiquette slot. The other varies race, adamantium access and buckler access across four legal advancement rates. Independent Cartesian products establish the full sets. The qualification checks that native exhaustive admission returns each set. It then compares the exact downstream winner with native two- and four-candidate panels on the same scenarios and seeds. Manual comparators outside each domain are excluded from its census.

The development scenario uses ordinary melee, physical pressure and multiple targets. All three held-out panels use different birth and fight draws. The first combines hostile casting, low starting spell points and mixed defense under compressed attack schedules. The second runs a multi-room fight with and without a protected recovery opportunity. The third compares later equipment access with owned items against physical, resistant and sustained encounters. Every family must have a replayed outcome for each required combination of checkpoint, scenario, assumption, birth and fight draw. A family missing an observation cannot qualify as an exhaustive reference.

The independent ranking checks weakest survival-with-clear rate, weakest survival rate and mean survival-with-clear rate in that order. It then favors more compatible plate and backup-weapon metals, faster class advancement, fewer practice actions and lower horizon-normalized censored clear time. The class ID breaks ties. The report distinguishes recovery of an equally strong class from recovery of the specific tie-broken class. It records each first lost priority and reports the largest observed gap in the units of that priority. Pareto recall counts distinct vectors across the seven declared axes. These measurements apply to the finite reference classes and policy panel. The broad recommendation remains bounded.

| Generated families retained | Held-out winning metric recovery | Exact tie-broken class recovered | Mean frontier recall | Largest observed primary loss |
| --- | ---: | ---: | ---: | ---: |
| 2 of 8 | 3 / 3 | 1 / 3 | 83.3% | 0 |
| 4 of 8 | 3 / 3 | 2 / 3 | 100% | 0 |

The sealed Windows and Linux wheels returned matching full exhaustive result hashes on all four panels, and matching native work and result identity in the repeated fixed-work check. Individual specialist diagnostics measure the best observed cap damage rate, health floor and dungeon spell efficiency on the retained panel. [Windows quality report](../benchmarks/results/windows-m9-beginner.json) · [Ubuntu quality report](../benchmarks/results/ubuntu-m9-beginner.json)

## Submitted M8 result

The submitted creation-to-cap result evaluated six of eight admitted classes across birth tapes 42 and 43. It spent 4,000,000 nodes, with a first validated result at 1.168 seconds and total service time of 16.231 seconds. Its five pre-birth classes supplied nine Pareto representatives on funded direct spell performance and progression effort. The saved validation counted 22 routes. Independent replay, including the final-checkpoint comparison witnesses, checked 24. The selected M8 Breton forbids plate. This conflicts with the beginner equipment requirement.

Class admission consumed 53,792 nodes and the lifecycle consumed 3,946,208. An instrumented rerun of the same request on the pre-M9 Windows wheel took 33.739 seconds. Python's profiler counted 297,322 calls to `progression_replay.transition` (27.237 seconds cumulative) and 4,196,350 calls to `_tally` (8.965 seconds cumulative). The cumulative times include nested calls. These measurements identified repeated progression replay as the largest cost in this submitted search.

All five M8 frontier classes fail the beginner profile on the original rolls. The two Bretons forbid plate. The Dark Elf, Khajiit and Redguard take a class save vulnerability and lack a trained, equippable starting melee weapon. Every class also fails the sampled starting-kit check for a usable backup and enough carrying capacity for plate. The [original request, paired outcomes, classes, hashes and replay](../benchmarks/results/m9-m8-submitted-origin.json) record those per-class checks. Regenerate that record from the original request and result with the following command.

```sh
python tools/run_beginner_demonstration.py --origin-only --origin-request dfo-request.json --origin-result dfo-result.json --output build/beginner-demo
```

## Platform qualification

The isolated Windows wheel passed 859 tests with one platform skip and 91.68% Python line coverage. Nine source-oracle checks and seven benchmark suites passed. Chromium exercised the recommendation, file export, checklist and replay workflows. These are automated observations of the application. A first-time player's comprehension, actual in-game import and live-server play were outside this test. The serial comparisons preserved the legacy work counters and output quality against [M8 / 0.5.0](../benchmarks/results/windows-m9-release-comparison-0.5.0.json) and the four earlier suites against [0.3.0](../benchmarks/results/windows-m9-release-comparison-0.3.0.json). The Windows warm follow-up measured 3.6–6.5% longer for four legacy encounter workloads, including the pack at 2.00 → 2.07 ms. [Windows qualification](../benchmarks/results/windows-m9-qualification.json) · [Browser timings](../benchmarks/results/windows-m9-browser-timings.json) · [Repeated encounter measurements](../benchmarks/results/windows-m9-encounter-investigation.json)

The Ubuntu 24.04 x86-64 wheel, built with CPython 3.12.3 and GCC 13.3, passed all 860 tests in 451.43 seconds with 91.47% Python line coverage, including Chromium. Installation checks verified 196 files. Source checks included 328 physical blows, 68 swing schedules and the manual class creation fixtures. All seven suites passed. [Ubuntu qualification](../benchmarks/results/ubuntu-m9-qualification.json) · [Browser timings](../benchmarks/results/ubuntu-m9-browser-timings.json)

The separate GCC-instrumented build ran 552 tests and covered 2,810 of 2,890 executable native header lines (97.23%). Each header exceeded 80%. Its first run found that one orchestration test unnecessarily queried installed wheel metadata in the development-only interpreter. The rerun used a test-only correction to stub that lookup. The qualified sources and wheel are identified by the sealed archive and binary hashes. The [qualification record](../benchmarks/results/ubuntu-m9-qualification.json) identifies both test versions. [Per-header line coverage](../benchmarks/results/ubuntu-m9-native-coverage.json)

Linux preserved deterministic work and quality on the [0.5.0 workloads](../benchmarks/results/ubuntu-m9-release-comparison-0.5.0.json) and the [four 0.3.0 suites](../benchmarks/results/ubuntu-m9-release-comparison-0.3.0.json). Three initial 0.5.0 timing flags prompted 101 alternating warm observations per workload on the idle, single-vCPU guest. Their medians were 0.135 → 0.128 ms for the class mechanics batch, 5.45 → 5.13 ms for bounded gear, and 68.17 → 67.42 ms for bounded lifecycle search. [Per-sample timings and identities](../benchmarks/results/ubuntu-m9-latency-followup.json)

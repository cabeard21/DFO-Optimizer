# DFO Optimizer

Offline native class, spellbook, gear, progression and encounter optimization for Daggerfall Online's 2026-11-02 public source snapshot. [Project specification](DFO_Spellcasting_Optimizer_Codex_Handoff.md)

## Install

Use CPython 3.12 x64. Building from source needs MSVC with the C++ desktop build tools on Windows, or a C++17 compiler and Python development headers on Linux. An already-built platform wheel needs only its matching Python runtime.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install .
.\.venv\Scripts\dfo.exe class optimize --top 1 --output build/example.json
```

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install .
.venv/bin/dfo class optimize --top 1 --output build/example.json
```

## Create your first spellcaster

Run `dfo ui` and choose **Recommend My First Spellcaster**. The default comparison has a two-minute budget. Read the recommended race and starting equipment, download the game class, and follow the printable checklist when assigning your bonuses. Race is selected separately in the game. The result also explains what the character gives up and which later choices you can postpone.

The same service can create, check and export the recommendation from the command line.

```sh
dfo build recommend --output build/first-spellcaster.json
dfo build replay --plan build/first-spellcaster.json
dfo class export --result build/first-spellcaster.json --output build/first-spellcaster.dfclass.json
```

Use `--thoroughness quick` for a smaller class panel or `--thoroughness thorough` for a longer search. Each class faces the same declared opportunities, birth rolls and enemy attacks. The comparison includes acquired weapons and armor, spell-point shortages and opportunities to heal.

To start from the measured Standard run, select Khajiit, import the [recommended class](benchmarks/results/m9-standard-recommended.dfclass.json) and follow the [creation checklist](benchmarks/results/m9-standard-recommended-checklist.txt). Its nine compatible plate metals leave room to change equipment later. A [fast-advancing Breton](benchmarks/results/m9-fast-breton.dfclass.json) reached the same cap with about one tenth the practice in the modeled itinerary. The [comparison and qualification record](docs/M9-ACCEPTANCE.md) explains the trade-off and includes both checklists.

## Discover a spellcaster build

Run `dfo ui` and select **Discover Spellcaster Build**. Start with the two-minute Overall PvE search, then compare funded spells, loadouts and progression effort on the same birth rolls. Each preset displays its world assumptions. The practical itinerary assumes specific access to practice, rest and purchases. The theoretical equipment preset supplies a separate finite item pool.

Start with all eight races and an ordered skill assignment that can eventually master all six schools. Lock a permanent choice only if you want it enforced. The seven-material Breton and its High Elf race variant are optional comparison inputs. To compare a custom class, import its game JSON and select its race. Exporting a recommendation downloads the game class document. Save the archive to keep its race, assumptions and replayable route.

The CLI uses the same services. The class command screens creation choices. The build command evaluates their progression and performance.

```sh
dfo class optimize --profile spellcaster_discovery_v1 --top 24 --output build/class-panel.json
dfo build optimize --request examples/build-discovery-demo.json --output build/discovery.json
dfo build replay --plan build/discovery.json
dfo benchmark --suite discovery --workers 1 --output build/discovery-quality.json
```

The result reports class enumeration, admission and downstream completion separately. An early result can be replayed while the search continues. A complete paired comparison covers each listed birth seed. See the [M8 qualification record](docs/M8-ACCEPTANCE.md) for measured recovery, demonstration inputs and platform evidence.

## Use the installed CLI

With the environment activated, the following commands export the first candidate, validate its actual game document, and reproduce a small exact search.

```sh
dfo class optimize --profile dhargo_pve --top 20 --output build/classes.json
dfo class export --result build/classes.json --index 0 --output build/mage.dfclass.json
dfo class validate --class build/mage.dfclass.json --race 1
dfo class import --input build/mage.dfclass.json
dfo class optimize --request examples/max-intelligence.json --output build/int-frontier.json
dfo ruleset coverage
dfo benchmark --suite smoke --workers 1 --output build/smoke.json
```

The default returns examples with 30 HP, 3× INT Magery and −12 difficulty. Inspect the listed equipment prohibitions before using an example in the game. The exact request varies INT and STR across three allocations, two races, and a small explicit trait catalog. Its maximum is an attribute floor within those choices. Practical starting damage, training feasibility and live-server equivalence are still unknown.

The CLI writes JSON. `class import` accepts parseable drafts and reports skipped picks. `class validate` exits 1 if the default profile fails. `class export` emits a creator-legal document. The game file omits race, so retain the search result to preserve the complete candidate identity.

During an active class search, Ctrl+C requests cancellation. The CLI writes the validated incumbents and termination reason to the requested JSON destination and exits with status 130.

### Compare spells and complete loadouts

```sh
dfo evaluate --request examples/spell-fixed.json
dfo spell optimize --request examples/spell-auto.json --output build/spells.json
dfo gear optimize --request examples/gear-owned.json --output build/owned.json
dfo gear optimize --request examples/gear-budget.json --output build/upgrades.json
dfo gear optimize --request examples/gear-catalog.json --output build/catalog.json
dfo gear optimize --request examples/gear-bis.json --output build/theory.json
dfo benchmark --suite combat --workers 1 --output build/combat.json
```

Each point pairs a complete recipe with expected target HP loss per recast second and per actual SP. The scenario assumes one ordinary, stationary PvE foe and one confirmed hit per cast. Read the returned search status, domain, acquisition evidence, and exclusions before comparing points. The theoretical gear example searches a declared roll catalog.

### Plan a character through level 45

```sh
dfo progression plan --request examples/progression-tradeoffs.json --output build/training.json
dfo progression replay --plan build/training.json
dfo progression plan --request examples/progression-mastery.json --output build/mastery.json
dfo spellbook evaluate --request examples/spellbook-fixed.json
dfo spellbook optimize --request examples/spellbook-auto.json
dfo build baselines
dfo build optimize --request examples/build-lifecycle.json --output build/early.json
dfo build replay --plan build/early.json
dfo build optimize --request examples/build-checkpoint-reversal.json --output build/checkpoints.json
dfo build optimize --request examples/build-creation-to-cap.json --output build/capped.json
dfo build replan --request examples/build-replan-current.json --output build/current.json
dfo build replan --request examples/build-replan.json
dfo benchmark --suite progression --output build/progression-benchmark.json
dfo benchmark --suite lifecycle --output build/lifecycle-benchmark.json
```

Start with the small training example to see the price of replacing casts with a guild session. The creation-to-cap examples use declared activity access and a frozen birth roll. The near-cap mastery example starts from a synthetic save. The replan example shows which missing observations prevent a route from being verified. Use `dfo build compare --plans first.json second.json` for compatible lifecycle results. A save's stock spell IDs can be resolved with a locally supplied `SPELLS.STD` via `dfo progression plan --stock-spells PATH --request REQUEST`. Viewing records alone does not grant a spell.

### Compare sustained encounters

```sh
dfo encounter evaluate --request examples/encounter-miss.json --output build/miss.json
dfo encounter optimize --request examples/encounter-pack.json --output build/pack.json
dfo encounter replay --plan build/pack.json
dfo encounter optimize --request examples/encounter-dungeon.json --output build/dungeon.json
dfo build optimize --request examples/build-encounter-reversal.json --output build/route.json
dfo build replay --plan build/route.json
dfo spell curve --request examples/spell-scaling.json --output build/scaling.json
dfo benchmark --suite encounter --workers 1 --output build/encounter-benchmark.json
```

The miss example makes the cost of an unsuccessful projectile visible. The pack compares three policies on the same four seeds. Read the censored clear time alongside the clear probability. A fight that runs out of time contributes the full horizon to the censored mean. The first trial includes an event trace, and replay checks every retained policy and seed. The separate spell scaling command changes one caster input at a time and reports hypothetical fixed-cast results.

The Rat example uses the public enemy definition and explicitly supplies target HP, position and attack times. To read base defenses from local classic data, run `dfo encounter import-enemy --input PATH/TO/MONSTER.BSA --mobile-id 0 --hp 12` with the HP you observed. Check the returned evidence and blockers before using the target.

### Open the local workbench

```sh
dfo ui
```

The command starts a server on the loopback interface and opens its local address in your browser. Use `dfo ui --no-browser` to print the address, and Ctrl+C in that terminal to close the workbench. Open a packaged example in Character Creator, Progression, Spell Lab or Gear & Loadouts. Run it and choose **Save to library** to make the result available in **Compare Builds**. **Export archive** includes the frozen request and result. **Data & Diagnostics** shows the installed ruleset, mechanics coverage and benchmark reports. The library persists on this computer.

To choose where the workbench stores its library, set the `DFO_WORKBENCH_HOME` environment variable to a writable directory before starting `dfo ui`.

### Use a character save

In the game's enhanced Load menu choose **Move saves → Export all saves**. List the slots, select one, then supply it directly to an evaluation or save the portable character JSON for reuse. The commands below replay a synthetic two-slot ZIP produced by the pinned game's normal exporter.

```sh
dfo character slots --input tests/fixtures/character/export.zip
dfo character import --input tests/fixtures/character/export.zip --slot 0 --output build/character.json
dfo evaluate --character build/character.json --request examples/spell-fixed-from-save.json
dfo gear optimize --character tests/fixtures/character/export.zip --slot 0 --request examples/gear-auto-from-save.json
```

Saved SP can omit online bonuses. For automatic searches the example records a separately attributed observation of current SP. Replace that observation with your own value, source and timestamp when using your save. Plain v1 `SaveData.txt`, slot directories, and portable character JSON also work. [Save fixture and schema examples](tests/fixtures/character/README.md)

## Rebuild and verify

Normal search runs offline from the packaged ruleset. For extraction and oracle replay, install Git and Node 22.18, then obtain the pinned reference in the ignored vendor directory.

```sh
git clone --filter=blob:none --no-checkout https://github.com/Lattymoy/daggerfall-js-source.git vendor/dfo-source
git -C vendor/dfo-source sparse-checkout set --no-cone '/src/' '/locales/' '/test/systems/' '/test/modsOff.js' '/test/fixtures/mw/' '/tools/nifWrite.mjs' '/tools/lib/isMain.mjs' '/app/lib/fileStorage.cjs' '/package.json' '/vendor/**/*.json' '/vendor/**/*.js' '/LICENSE' '/README.md'
git -C vendor/dfo-source checkout --detach a3eb1605ea1dc391b691fe314377458a7e63e483
dfo ruleset build --source vendor/dfo-source --commit a3eb1605ea1dc391b691fe314377458a7e63e483 --out build/ruleset
dfo ruleset validate --ruleset build/ruleset
python -m pip install -r requirements-dev.txt
python -m build
python tools/verify_wheel.py --browser
```

Wheel acceptance creates a new environment, regenerates the source fixtures, runs the tests against the installed package from outside the checkout, and records five serial benchmark suites. The browser lane adds Chromium workflow tests. Set `DFO_SOURCE` to use another local checkout. The 14 original Dhargo downloads can also be replayed separately. [Fixture verification](tests/fixtures/dhargo/README.md)

[M0–M1 acceptance](docs/M0-M1-ACCEPTANCE.md) · [M2–M3 acceptance](docs/M2-M3-ACCEPTANCE.md) · [M4–M5 acceptance](docs/M4-M5-ACCEPTANCE.md) · [M6–M7 qualification](docs/M6-M7-ACCEPTANCE.md) · [Architecture](docs/ARCHITECTURE.md) · [Mechanics and open questions](docs/MECHANICS.md) · [Search guarantees](docs/OPTIMIZATION.md) · [Performance measurements](docs/PERFORMANCE.md)

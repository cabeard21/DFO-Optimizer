# DFO Optimizer

Offline native class construction and search for Daggerfall Online's 2026-11-02 public source snapshot. Project specification and milestone gates are in [the handoff](DFO_Spellcasting_Optimizer_Codex_Handoff.md).

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

## Rebuild and verify

Normal search runs offline from the packaged ruleset. For extraction and oracle replay, install Git and Node 22.18, then obtain the pinned reference in the ignored vendor directory.

```sh
git clone --filter=blob:none --no-checkout https://github.com/Lattymoy/daggerfall-js-source.git vendor/dfo-source
git -C vendor/dfo-source sparse-checkout set --no-cone '/src/' '/locales/' '/test/systems/' '/package.json' '/vendor/**/*.json' '/vendor/**/*.js' '/LICENSE' '/README.md'
git -C vendor/dfo-source checkout --detach a3eb1605ea1dc391b691fe314377458a7e63e483
dfo ruleset build --source vendor/dfo-source --commit a3eb1605ea1dc391b691fe314377458a7e63e483 --out build/ruleset
dfo ruleset validate --ruleset build/ruleset
python -m pip install -r requirements-dev.txt
python -m build
python tools/verify_wheel.py
```

Wheel acceptance creates a new environment, invokes the independent Node oracle, runs the tests against the installed package from outside the checkout, and records a smoke benchmark. Set `DFO_SOURCE` to use another local checkout. The 14 original Dhargo downloads can also be replayed separately. [Fixture verification](tests/fixtures/dhargo/README.md)

[M0–M1 acceptance and results](docs/M0-M1-ACCEPTANCE.md) · [Architecture](docs/ARCHITECTURE.md) · [Mechanics and open questions](docs/MECHANICS.md) · [Search guarantees](docs/OPTIMIZATION.md) · [Performance measurements](docs/PERFORMANCE.md)

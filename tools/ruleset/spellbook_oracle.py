"""Compute exact stage-specific spell frontiers against the pinned game and project effect IDs to native goals."""
import argparse
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from dfo_optimizer.ruleset import run_adapter

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DATA = ROOT / "src/dfo_optimizer/data"


def load_source(source):
    closure = json.loads((DATA / "spell-lock.json").read_text())
    outgoing = json.loads((HERE / "spell-extra-lock.json").read_text())
    if closure.keys() & outgoing.keys():
        raise ValueError("Conflicting source hashes in search inputs")
    with TemporaryDirectory() as directory:
        identity = Path(directory) / "lock.json"
        identity.write_text(json.dumps({**closure, **outgoing}))
        return run_adapter(source, identity, HERE / "spellbook_oracle.mjs")


def registry(output):
    shapes = [
        ("spell.disintegrate", "src/systems/effects.js", "applySpell,chanceValue",
         "Native chance-to-kill calculation with the displayed spellmaker settings, chance-before-save order, and the remaining target HP. "
         "The final witness uses a confirmed legal finite cast on a non-player stationary target."),
        ("spell.multi_effect", "src/systems/spell/spellMaker.js", "buildCustomSpell,spellMakerCost,validateSpellPurchase",
         "One to three valid ordered Damage Health or Disintegrate effects on a stationary NPC. "
         "Each cast combines the visible price and health loss from retained effects in the requested order."),
        ("spell.native_spellbook", "src/systems/spell/spellMaker.js", "purchaseSpell",
         "Fixed and stage-specific dynamic policies replay confirmed spell acquisitions and SP costs. "
         "Policies can use the declared fresh-target casts and quote history. Practice, regeneration and equipment-dependent redistribution are outside the proficiency snapshot."),
    ]
    return [{"source_sha":output["source_sha"],"mechanic_id":raw[0],"verification_status":"source_verified",
             "live_verified":False,"implementation_status":"native_spellbook","mode":"online_snapshot",
             "symbol":raw[2],"path":raw[1],"limits":raw[3],"assumptions":["The resolved encounter is one stationary ordinary NPC and a confirmed hit per cast."]}
            for raw in shapes]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    output = load_source(args.source)
    for values, path in ((output, ROOT / "tests/fixtures/spellbook-oracle.json"),
                         (registry(output), DATA / "spellbook-mechanics.json")):
        if args.check:
            if json.loads(path.read_text()) != values:
                raise SystemExit(f"Oracle differs at {path}")
        else:
            path.write_text(json.dumps(values, indent=2) + "\n", encoding="utf-8")
    print(f"{len(output['examples'])} game-derived spellbook scenarios")


if __name__ == "__main__":
    main()

"""Regenerate the encounter fixtures and per-mechanic source status from the pinned game."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
from uuid import uuid4

from dfo_optimizer.ruleset import SOURCE_SHA, materialize_pinned


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DATA = ROOT / "src/dfo_optimizer/data"
BASE = "Ordinary online PvE with explicit cast, equipped-item and target evidence. No mentoring, court, duel or PvP."
PATH_LIMITS = {
    "battlemage": "Spellsteel reads the live positive shield pool. Aegis Bolt grants its power-cast shield from health actually lost and can raise the incumbent shield cap.",
    "trickster": "Slip Away changes enemy targeting after the one-third HP threshold. Both concealment and the Fleeting Hold rider require enemy AI.",
    "riftwalker": "Between Moments adds 20 points of cast speed. Rift Lance arcs also require ordered nearby foe and sharing evidence.",
    "warden": "Steadfast heals a shielded, living player on a magic round. Living Aegis guard carry and guard budget require the signature combat door.",
    "wardwright": "Attuned Wards discounts spells made only of Alteration or Thaumaturgy effects. Prismatic Ward and incoming spell absorption require the defensive spell door.",
    "shadowcaster": "Unseen Strike depends on live concealment. Ordinary unconcealed casts can be resolved. Shadow Bolt and enemy detection need concealment transitions.",
    "spellbreaker": "Sunder reduces the Damage Health save. Unravel restores a third of actual paid magicka on damage, with separate damage and Silence schools and rolls.",
    "bloodmage": "Sanguine Tide derives power from missing health at the landing. The Blood Boil signature has a separate low-health hit.",
    "elementalist": "Conflux grants one stack per damaging cast across targets and uses strict ten-second expiry. Chain Lightning needs ordered secondary target and career evidence.",
    "seer": "Foresight is rolled only at a scheduled hostile blow. Psychic Lance marks and the target-specific timed pierce require the signature.",
    "lightbringer": "Dawn's Ward reads the game-classified undead or daedra target group. Dawnbolt has a separate eligible heal and burn rider.",
    "enchanter": "Glamour's Personality, Etiquette and Streetwise bonuses have no combat input in the fixed encounter. A Mind Bender refund needs a newly calmed hostile AI.",
    "necromancer": "Death's Due restores 5% maximum health and magicka on eligible kills. Siphon Life heals half the HP actually lost, subject to signature identity.",
    "soulbinder": "Soul Well restores 10% maximum magicka on eligible kills, or 20% for the caster's own active Soul Trap. Soul Lance requires the trap and its signature data.",
    "hierophant": "Absolution heals on a nonlethal crossing below 30% with a 180-second recovery. Sanctify's cures and resistance must be present to score its rider.",
}
MARTIAL_LIMITS = {
    "vanguard":"Iron Discipline reduces a marked hostile blow by 10% before Shield and carries the fractional reduction.",
    "bladedancer":"Dancer's Step evades one marked hostile blow in ten before the damage modifiers run.",
    "bloodletter":"Bloodlust heals 5% of maximum HP on an eligible kill through the shared fractional health credit.",
    "juggernaut":"Stand Firm heals 20% on a nonlethal crossing below 30% HP with 180 seconds of recovery.",
    "brawler":"Grit heals 1% of maximum HP per magic round. Fatigue is outside the scored resources.",
    "windrunner":"Windborne adds 10 Speed before the effective Speed cap. Running and Jumping are outside the encounter.",
    "blademaster":"Flowing Steel requires a landed weapon attack.",
    "warblade":"War Rhythm changes weapon swing cadence.",
    "ranger":"Hunter's Instinct affects weapon attacks against beasts.",
    "cutthroat":"Cheap Shot affects weapon strikes against unaware opponents.",
    "assassin":"Opening Strike affects the first weapon attack on each opponent.",
    "shadowdancer":"Light Step changes Agility and Dodging before an observed incoming hit is resolved.",
    "woodsman":"Tireless restores fatigue, which is outside the scored resources.",
    "berserker":"Frenzy changes weapon damage and swing cadence.",
    "crusader":"Purge affects weapon attacks against undead and daedra.",
}


def registry(data):
    def row(id, path, symbol, limits, implementation="native_encounter"):
        return dict(mechanic_id=id, path="src/"+path, symbol=symbol, source_sha=SOURCE_SHA,
                    verification_status="source_verified", implementation_status=implementation,
                    mode="online_snapshot", live_verified=False, limits=limits, assumptions=[BASE])

    rows = [
        row("encounter.damage", "systems/effects.js", "applySpell,effectMagnitude",
            "On confirmed hostile landings, resolve magnitude, ward, immunity and remaining saving throw in source order."),
        row("encounter.healing", "systems/effects.js", "applySpell,runEffectRound",
            "Caster-only Heal Health and Regenerate read the appropriate school's earned climb. Each regeneration tick rolls a fresh magnitude."),
        row("encounter.shield", "systems/effects.js", "applySpell,renewRounds,tickActiveEffects",
            "Caster-only Shield recasts top up the original pool and refresh its remaining rounds; broken pools can be replaced."),
        row("encounter.area", "systems/spellcast.js", "sweepFoes,sphereOverlapsCapsule",
            "Source explosion sweep uses the living foe capsules in order, including the exact rim. Cast origin and friendly-fire eligibility remain encounter inputs."),
        row("encounter.wellspring", "systems/loot/lootPowers.js", "lootKill,wornSum",
            "Worn valid jewellery Wellspring lines sum to at most 10% maximum magicka per eligible kill. The source game shares fractional carry with other magicka gifts."),
        row("encounter.spell_defenses", "systems/effects.js", "applySpell,spellReflectionChance,spellResistanceChance",
            "Per-slot absorption, reflection and resistance use ordered gates. Only the first reflected slot returns the whole spell. The later original slots still resolve."),
        row("encounter.absorption", "systems/absorption.js", "tryAbsorption,effectCastingCost,absorbRefund",
            "Receiver-side Destruction cost and available room precede effect, set, career and item checks. Half the aggregate absorbed spell points, floored, is credited."),
        row("encounter.silence", "systems/effects.js", "applySpell,renewRounds",
            "Silence refreshes an existing duration before testing a new chance. Only new instances receive the non-magnitude saving throw."),
        row("progression.oghma", "systems/artifactEffects.js", "hasArtifactSubtype,OGHMA_BONUS_POOL,SPECIAL_ARTIFACT_HANDLERS",
            "Consumes one observed Oghma copy. The 30-point allocation respects earned attribute caps and clears the level-up latch. Acquiring the artifact is a separate opportunity.",
            "native_progression"),
        row("progression.firmament", "net/firmament/firmamentLaw.js", "treeFault,treeStats,pointsLeft",
            "Additive allocations require a connected sign, observed account access, Renown and profession points. Respecs and future entitlements are outside this domain.",
            "native_progression"),
        row("encounter.firmament", "systems/firmamentPowers.js", "firmamentFold,firmamentSpellPower,firmamentSpellPierce,firmamentCastSpeed",
            "Funded awake trees can supply static spell power, pierce, cast speed and Destruction. Capacity-changing nodes require matching live pool observations. Unprojected keystones block scoring.",
            "native_checkpoint"),
    ]
    if set(PATH_LIMITS) != {p["id"] for p in data["paths"]}:
        raise ValueError("Path roster differs from the audited game snapshot")
    for p in data["paths"]:
        status = "gated_ai" if p["id"] == "trickster" else "scoped_passive"
        rows.append(row("encounter.path."+p["id"], "systems/arcanePowers.js",
                        "awakePathId,pathSpellPower,pathLanded,pathKill,pathHurt",
                        PATH_LIMITS[p["id"]], status))
    if {p["id"] for p in data["martial"]["paths"]} != MARTIAL_LIMITS.keys():
        raise ValueError("Unexpected martial path roster")
    for p in data["martial"]["paths"]:
        status = "scoped_passive" if p["id"] in {
            "vanguard","bladedancer","bloodletter","juggernaut","brawler","windrunner"
        } else "outside_spell_encounter"
        rows.append(row("encounter.martial."+p["id"],"systems/martialPowers.js",
                        "awakeMartialId,martialEvade,martialDamageMod,martialHurt,martialRound,martialKill,martialFold",
                        MARTIAL_LIMITS[p["id"]]+" Weapon techniques and their riders require weapon actions.",
                        status))
    return rows


def generate(source, scratch=ROOT/"build/encounter-oracle"):
    files = {}
    for path in (DATA/"spell-lock.json", HERE/"spell-extra-lock.json"):
        files.update(json.loads(path.read_text()))
    # Python 3.12's Windows mkdtemp creates a private ACL that blocks child
    # processes in restricted build accounts. Inherit the build workspace ACL.
    scratch = scratch.resolve()
    scratch.mkdir(parents=True, exist_ok=True)
    stage = scratch / ("snapshot-" + uuid4().hex)
    stage.mkdir(exist_ok=False)
    try:
        materialize_pinned(source, stage, files)
        script = stage/"adapter.mjs"
        script.write_bytes((HERE/"encounter_oracle.mjs").read_bytes())
        clean = {k:v for k,v in os.environ.items() if k.upper() not in {"NODE_OPTIONS", "NODE_PATH"}}
        run = subprocess.run(["node", str(script)], cwd=stage, env=clean, capture_output=True, timeout=120)
        if run.returncode:
            raise ValueError(run.stderr.decode("utf-8", errors="replace")[:1800])
        result = json.loads(run.stdout)
    finally:
        if stage.resolve().parent != scratch:
            raise ValueError("Encounter scratch directory is outside its workspace")
        shutil.rmtree(stage)
    if result["source_sha"] != SOURCE_SHA:
        raise ValueError("Unexpected encounter source commit")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--scratch", type=Path, default=ROOT/"build/encounter-oracle",
                        help="Place temporary authenticated source files in this writable directory")
    args = parser.parse_args()
    result = generate(args.source, args.scratch)
    for target, value in ((ROOT/"tests/fixtures/encounter-oracle.json", result),
                          (DATA/"encounter-paths.json", result["paths"]),
                          (DATA/"encounter-mechanics.json", registry(result))):
        if args.check:
            if json.loads(target.read_text()) != value:
                raise SystemExit(f"Encounter snapshot differs at {target}")
        else:
            target.write_text(json.dumps(value, indent=2)+"\n", encoding="utf-8")
    print(f"{len(result['effects'])} game effects, {len(result['paths'])} path records, plus area and listener sequences")


if __name__ == "__main__":
    main()

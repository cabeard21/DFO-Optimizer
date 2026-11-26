"""Bind a frozen checkpoint and validate one finite policy on a common draw panel."""

from copy import deepcopy
from dataclasses import dataclass, field
from time import perf_counter

from .beginner_report import retained_size
from .beginner_scenario_catalog import variant_case
from .encounter import _digest
from .encounter_reference import simulate_trial
from .encounter_request import freeze_encounter
from .lifecycle_defenses import career_absorption
from .physical_encounter import PhysicalGap


class ScenarioGap(ValueError):
    """A necessary observed ability or physical state is unavailable."""


class PanelLimit(Exception):
    """The shared event, memory, cancellation or time limit was reached."""


@dataclass
class Budget:
    max_events: int = 0
    memory_bytes: int = 64 << 20
    wall_seconds: float = 0.0
    cancel: object = None
    reference_only: bool = False
    started: float = field(default_factory=perf_counter)
    events: int = 0
    peak_bytes: int = 0
    batches: int = 0
    trials: int = 0
    replayed: int = 0
    retained_bytes: int = 0
    cache_bytes: int = 0
    peak_matrix_bytes: int = 0

    def available(self):
        return self.memory_bytes - self.retained_bytes - self.cache_bytes

    def observe(self, amount):
        if amount > self.available():
            raise PanelLimit("memory_limit")
        self.peak_matrix_bytes = max(
            self.peak_matrix_bytes, self.retained_bytes + self.cache_bytes + amount
        )

    def retain(self, rows):
        # Independent per-batch sizes conservatively count shared scalars across batches.
        amount = retained_size(rows, set()) + len(rows) * 16
        self.observe(amount)
        self.retained_bytes += amount

    def cache(self, value):
        # Includes the receipt key, scalar/receipt, dictionary growth and table slop.
        amount = 256 + retained_size(value, set())
        self.observe(amount)
        self.cache_bytes += amount

    def check(self, *, replay=False):
        if self.cancel and self.cancel.cancelled():
            raise PanelLimit("cancelled")
        if self.wall_seconds and perf_counter() - self.started >= self.wall_seconds:
            raise PanelLimit("time_limit")
        if not replay and self.max_events and self.events >= self.max_events:
            raise PanelLimit("event_limit")

    def evaluate(self, query, report=None):
        """One native batch for the entire draw panel, then independent fixed-policy replay."""
        self.check()
        setup_bytes = retained_size(query, set())
        self.observe(setup_bytes)
        try:
            ctx = freeze_encounter(query)
        except PhysicalGap as error:
            raise ScenarioGap(str(error)) from error
        if ctx["blockers"]:
            raise ScenarioGap("; ".join(ctx["blockers"]))
        setup_bytes += retained_size(ctx, set())
        self.observe(setup_bytes)
        certified = []
        if not self.reference_only:
            from . import _encounter

            seconds = (
                max(1e-12, self.wall_seconds - (perf_counter() - self.started))
                if self.wall_seconds
                else 0
            )
            native = _encounter.evaluate(
                ctx["scenario"],
                ctx["spells"],
                ctx["policies"],
                ctx["seeds"],
                max_events=self.max_events - self.events if self.max_events else 0,
                memory_bytes=max(1, self.available() - setup_bytes),
                wall_seconds=seconds,
                trace=True,
                cancel=getattr(self.cancel, "encounter", self.cancel),
            )
            self.events += native["events"]
            self.peak_bytes = max(self.peak_bytes, native["work_bytes"])
            self.batches += 1
            self.trials += native["trials_completed"]
            if native["termination"] != "exhausted":
                raise PanelLimit(native["termination"])
            self.observe(setup_bytes + native["work_bytes"])
            certified = native["rows"][0]["trials"]
            setup_bytes += retained_size(certified, set())
            self.observe(setup_bytes)
        rows = []
        for i, seed in enumerate(ctx["seeds"]):
            self.check(replay=True)
            try:
                trial = simulate_trial(
                    ctx["scenario"],
                    ctx["spells"],
                    ctx["policies"][0],
                    seed,
                    trace=True,
                    poll=lambda: self.check(replay=True),
                    max_trace_events=(self.available() - setup_bytes) // 512,
                )
            except MemoryError as error:
                raise PanelLimit("memory_limit") from error
            self.observe(setup_bytes + retained_size(trial, set()))
            if certified:
                scalar = {k: v for k, v in trial.items() if k != "trace"}
                native = {k: v for k, v in certified[i].items() if k != "trace"}
                if (
                    native != scalar
                    or i == 0
                    and trial["trace"] != [list(e) for e in certified[i]["trace"]]
                ):
                    differing = sorted(
                        k
                        for k in scalar.keys() | native.keys()
                        if scalar.get(k) != native.get(k)
                    )
                    raise RuntimeError(
                        f"Beginner encounter {query['scenario']['id']} on seed {seed}: "
                        f"native and independent replay differ in {differing or ['event trace']}"
                    )
            self.replayed += 1
            row = report(i, trial) if report else trial
            rows.append(row)
            setup_bytes += retained_size(row, set()) + 16
            self.observe(setup_bytes)
        return rows


def _school_spell(spells, effect, ranges):
    return [
        s
        for s in spells
        if s["range_type"] in ranges
        and any(e["effect_id"] == effect for e in s["effects"])
    ]


def casting_policy(spells, multiple=False):
    """The rule is fixed at entry. It reads HP, shield, legal reach and affordable SP."""
    # Keep materialized book order as the last tie-breaker. Expensive optional
    # casts naturally fall through to an affordable starter or actual melee.
    rules = []
    for effect, key, threshold in (
        ("10,8", "hp_below_pct", 60),
        ("35,255", "shield_below", 1),
        ("18,255", "hp_below_pct", 65),
    ):
        for s in _school_spell(spells, effect, (0,)):
            rules.append({"spell": s["id"], key: threshold})
    for reach in ((3,), (1,), (2,), (4,)) if multiple else ((1,), (2,), (3,), (4,)):
        for s in spells:
            if s["range_type"] in reach and any(
                e["effect_id"] in ("4,0", "5,255") for e in s["effects"]
            ):
                rules.append({"spell": s["id"]})
    return {"id": "prepared-health-shield-attack-v1", "rules": rules}


def prepare_low_sp(stage, seed, budget=None):
    """Real cast clicks, releases and SP payments in a declared safe practice period."""
    actor = _actor_with_wards(stage, "darkness", 120_000_000)
    if actor["current_sp"] <= actor["max_sp"] // 4:
        return {
            "spell": None,
            "seed": seed,
            "casts": 0,
            "spent_sp": 0,
            "restored_sp": 0,
            "initial_sp": actor["current_sp"],
            "ending_sp": actor["current_sp"],
            "elapsed_us": 0,
            "trace_hash": _digest([]),
        }
    if actor.get("path") not in (None, "none") or actor.get("martial_path") not in (
        None,
        "none",
    ):
        raise ScenarioGap(
            "Active specialization requires carried timers from the depletion prelude"
        )
    book = _school_spell(stage["spells"], "4,0", (1, 2, 3)) or _school_spell(
        stage["spells"], "10,8", (0,)
    )
    if not book:
        raise ScenarioGap(
            "No owned direct damage or immediate heal for the paid low-SP prelude"
        )
    spell = {
        k: v
        for k, v in book[0].items()
        if k in ("id", "range_type", "effects", "element", "evidence")
    }
    scene = {
        "id": "paid-casting-prelude",
        "horizon_us": 120_000_000,
        "evidence": "Hypothetical stationary, harmless high-HP practice target in reach for two minutes. "
        "Cast this owned spell until funds run out. No advancement, on-kill rewards or rest.",
        "enemies": [
            {
                "id": "practice target",
                "hp": 1_000_000,
                "willpower": 50,
                "x_mm": 900,
                "z_mm": 0,
            }
        ],
    }
    query = {
        "actor": actor,
        "scenario": scene,
        "spells": [spell],
        "seeds": [seed],
        "policies": [{"id": "repeat-paid-cast", "rules": [{"spell": spell["id"]}]}],
    }
    outcome = (budget or Budget()).evaluate(query)[0]
    if outcome["kills"] or outcome["end_hp"] != actor["hp"]:
        raise ScenarioGap("Practice prelude ended with a changed HP or dead target")
    if outcome["end_sp"] > actor["max_sp"] // 4:
        raise ScenarioGap(
            "The common paid prelude did not reach the declared low-SP threshold"
        )
    return {
        "spell": spell["id"],
        "seed": seed,
        "casts": outcome["casts"],
        "spent_sp": outcome["spent_sp"],
        "restored_sp": outcome["restored_sp"],
        "initial_sp": outcome["initial_sp"],
        "ending_sp": outcome["end_sp"],
        "elapsed_us": outcome["end_us"],
        "trace_hash": _digest(outcome["trace"]),
    }


def _actor_with_wards(stage, environment, horizon):
    actor = deepcopy(stage["actor"])
    if career_absorption({"spellAbsorptionFlags": 0, **stage["career"]}, environment):
        actor["wards"] = {
            **actor.get("wards", {}),
            "career_absorbs": True,
            "active_through_us": horizon,
            "evidence": "Authenticated effective career and declared stable lighting throughout this scene.",
        }
    return actor


def make_request(stage, case, variant, seeds, initial_sp=None):
    actor = _actor_with_wards(stage, case["environment"], case["scene"]["horizon_us"])
    if initial_sp is not None:
        actor["current_sp"] = initial_sp
    scene = variant_case(case, variant, stage)
    band = case["threat_by_stage"][stage["stage"]]
    career = stage["career"]
    # passiveSpecials.js checks (absolute magic round % 4 == 0). These
    # short rooms start 5 s before round one. The first fourth round is at 20 s.
    if (
        scene["first_round_us"]
        + ((4 - case["first_absolute_round"]) % 4) * scene["round_period_us"]
        <= scene["horizon_us"]
    ):
        flag = career.get("regeneration", 0)
        if flag in (2, 8) and scene["incoming"]:
            raise ScenarioGap(
                "An active career regeneration tick requires its ordinary combat implementation"
            )
    if career.get("abilityFlagsAndSpellPointsBitfield", 0) & 0x3C0:
        raise ScenarioGap(
            "Environmental magery needs a verified spell pool through the complete scenario"
        )
    book = [
        {
            k: v
            for k, v in s.items()
            if k in ("id", "signature", "range_type", "effects", "element", "evidence")
        }
        for s in stage["spells"]
    ]
    policy = casting_policy(book, case["id"] == "multiple")
    if case["physical"]:
        from .beginner_equipment import bind_physical_player
        from .physical_encounter import ordinary_combat, ordinary_foe

        try:
            actor["physical"] = stage.get("physical_player") or bind_physical_player(
                stage
            )
        except PhysicalGap as error:
            raise ScenarioGap(str(error)) from error
        weapon = {
            "templateIndex": band["weapon_template"],
            "material": band["weapon_material"],
            "group": "Weapons",
            "currentCondition": 50,
            "maxCondition": 50,
        }
        foes = []
        for enemy in scene["enemies"]:
            foe = ordinary_foe(
                level=enemy["level"], skill=band["melee_skill"], weapon=weapon
            )
            foe["attributes"][2] = enemy["willpower"]
            foes.append(foe)
        scene["physical"] = ordinary_combat(
            foes,
            evidence="Active ordinary PCAAO/RRI. Hypothetical awake humanoids, stage-specific weapon copies, swing timing and short reach.",
        )
    elif not policy["rules"]:
        if stage.get("unsupported_spells"):
            raise ScenarioGap(
                "An unresolved owned spell may affect the out-of-melee-reach fight"
            )
        scene["allow_wait"] = True
    hostile = deepcopy(case["hostile_spells"])
    for spell in hostile:
        slot = spell["effects"][0]
        slot.update(
            zip(
                ("base_low", "base_high", "plus_low", "plus_high"),
                band["hostile_magnitude"],
                strict=True,
            )
        )
    return {
        "schema_version": 1,
        "actor": actor,
        "spells": [*book, *hostile],
        "scenario": scene,
        "policies": [policy],
        "seeds": list(seeds),
    }

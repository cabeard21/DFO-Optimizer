"""Exercise the public parsers independently of the chosen encounter fixture."""
from pathlib import Path

import pytest

from dfo_optimizer.cli import _parser


@pytest.mark.parametrize("action,flag", [
    ("evaluate", "--request"), ("optimize", "--request"), ("replay", "--plan"),
])
def test_encounter_commands(action, flag):
    args = _parser().parse_args(["encounter", action, flag, "fight.json"])
    assert args.action == action
    assert getattr(args, flag[2:]) == Path("fight.json")


def test_workbench_chooses_a_loopback_port_and_can_run_without_launching():
    args = _parser().parse_args(["ui", "--no-browser"])
    assert args.port == 0
    assert args.no_browser


def test_encounter_benchmark_entry_point():
    args = _parser().parse_args(["benchmark", "--suite", "encounter"])
    assert args.workers == 1

"""End-to-end game ZIP to scored spell, owned loadout, and joint Pareto results."""
import json
from pathlib import Path

import pytest

from dfo_optimizer.cli import main

ROOT = Path(__file__).resolve().parents[1]
EXPORT = ROOT / "tests/fixtures/character/export.zip"


@pytest.mark.parametrize(("command", "example"), [
    (["evaluate"], "spell-fixed"), (["spell", "optimize"], "spell-auto"),
    (["gear", "evaluate"], "gear-fixed"), (["gear", "optimize"], "gear-auto"),
])
def test_replay_upstream_export(command, example, tmp_path):
    result_file = tmp_path / "result.json"
    saved = EXPORT.read_bytes()
    assert main([*command, "--character", str(EXPORT), "--slot", "0", "--request",
                 str(ROOT / f"examples/{example}-from-save.json"), "--output", str(result_file)]) == 0
    result = json.loads(result_file.read_text(encoding="utf-8"))
    if example.startswith("gear"):
        candidate = result["candidates"][0]
        assert len(candidate["loadout"]) == 27
        assert candidate["metrics"]["dps"] > 0
        ids = set(candidate["loadout"].values())
        if example == "gear-auto":
            assert "uid:0000000000000002" in ids
        else:
            assert "uid:0000000000000001" in ids
    else:
        assert result["candidates"][0]["metrics"]["dps"] > 0
        assert result["proof_scope"]["caster_snapshot_hash"]
    assert EXPORT.read_bytes() == saved


def test_autospell_needs_actual_resources_from_save(tmp_path):
    request = json.loads((ROOT / "examples/spell-auto-from-save.json").read_text(encoding="utf-8"))
    del request["live_observations"]
    path = tmp_path / "request.json"
    path.write_text(json.dumps(request), encoding="utf-8")
    output = tmp_path / "result.json"
    assert main(["spell", "optimize", "--character", str(EXPORT), "--slot", "0",
                 "--request", str(path), "--output", str(output)]) == 0
    result = json.loads(output.read_text(encoding="utf-8"))
    assert result["status"] == "unsupported"
    assert result["candidates"] == []
    assert any("current_sp" in msg for msg in result["unsupported_mechanics"])

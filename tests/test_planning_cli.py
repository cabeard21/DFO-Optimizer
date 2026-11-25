import json

import pytest

from dfo_optimizer.cli import main


@pytest.mark.parametrize("command", [
    ["progression", "plan"], ["build", "optimize"], ["build", "replan"],
    ["spellbook", "evaluate"], ["spellbook", "optimize"],
])
def test_planning_commands_require_an_object(command, tmp_path, capsys):
    path = tmp_path / "request.json"
    path.write_text("[]", encoding="utf-8")
    assert main([*command, "--request", str(path)]) == 2
    assert "object" in json.loads(capsys.readouterr().err)["error"]


def test_save_referenced_inside_request_is_protected(tmp_path, capsys):
    slot = tmp_path / "slot0"
    slot.mkdir()
    save = slot / "SaveData.txt"
    save.write_bytes(b"original game save")
    request = tmp_path / "request.json"
    request.write_text(json.dumps({"start": {"type": "current_character", "character_file": "slot0"}}))
    assert main(["progression", "plan", "--request", str(request), "--output", str(save)]) == 2
    assert save.read_bytes() == b"original game save"
    assert "input game save" in json.loads(capsys.readouterr().err)["error"]


def test_progression_cannot_overwrite_stock_or_game_data(tmp_path, capsys):
    source = tmp_path / "SPELLS.STD"
    source.write_bytes(bytes(89))
    assert main(["progression", "plan", "--request", "-", "--stock-spells", str(source),
                 "--output", str(source)]) == 2
    assert json.loads(capsys.readouterr().err)["error"]
    assert source.read_bytes() == bytes(89)


def test_build_protects_dependencies_of_linked_progression_file(tmp_path, capsys):
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    save = inputs / "character.json"
    save.write_bytes(b"frozen character")
    progression = inputs / "schedule.json"
    progression.write_text(json.dumps({"start": {"character_file": "character.json"}}))
    request = tmp_path / "build.json"
    request.write_text(json.dumps({"progression_file": "inputs/schedule.json"}))
    for path in (save, progression):
        before = path.read_bytes()
        assert main(["build", "optimize", "--request", str(request), "--output", str(path)]) == 2
        assert "input" in json.loads(capsys.readouterr().err)["error"]
        assert path.read_bytes() == before

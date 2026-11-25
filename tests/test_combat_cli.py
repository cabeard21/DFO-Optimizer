"""Exercise installed entry points and the boundary between save data and requests."""
import json
from pathlib import Path

import pytest

from dfo_optimizer.cli import main


EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


@pytest.mark.parametrize("argv", [
    ["spell", "optimize"], ["gear", "optimize"], ["gear", "evaluate"], ["evaluate"],
])
def test_combat_commands_reject_nonobject_requests(argv, tmp_path, capsys):
    request = tmp_path / "bad.json"
    request.write_text("[]", encoding="utf8")
    assert main([*argv, "--request", str(request)]) == 2
    assert "object" in json.loads(capsys.readouterr().err)["error"]


def test_import_cannot_overwrite_its_game_export(tmp_path, capsys):
    archive = tmp_path / "save.zip"
    original = (Path(__file__).parent / "fixtures/character/export.zip").read_bytes()
    archive.write_bytes(original)
    assert main(["character", "import", "--input", str(archive), "--slot", "0",
                 "--output", str(archive)]) == 2
    assert archive.read_bytes() == original
    assert "save" in json.loads(capsys.readouterr().err)["error"].lower()


def test_character_import_reports_missing_file(tmp_path, capsys):
    assert main(["character", "import", "--input", str(tmp_path / "absent.zip")]) == 2
    assert json.loads(capsys.readouterr().err)["error"]


def test_raw_save_output_preserves_mixed_case_slot_metadata(tmp_path, capsys):
    source = tmp_path / "SaveData.txt"
    source.write_text("{}")
    card = tmp_path / "saveINFO.Txt"
    card.write_text("original metadata")
    assert main(["character", "import", "--input", str(source), "--output", str(card)]) == 2
    assert "replace a game save" in json.loads(capsys.readouterr().err)["error"]
    assert card.read_text() == "original metadata"

import struct
import json
import os
from pathlib import Path

import pytest

from dfo_optimizer.enemy_career import import_enemy_career


def career():
    data = bytearray(74)
    data[:4] = bytes([2, 4, 8, 16])
    struct.pack_into("<H", data, 62, 63)
    return bytes(data)


def test_local_bsa_and_extracted_record_agree_without_distributing_game_data(tmp_path):
    payload = career()
    record = tmp_path / "ENEMY000.CFG"
    record.write_bytes(payload)
    archive = tmp_path / "MONSTER.BSA"
    entry = struct.pack("<14si", b"ENEMY000.CFG", len(payload))
    archive.write_bytes(struct.pack("<hH", 1, 0x100) + payload + entry)
    direct = import_enemy_career(record, 0, 12)
    packed = import_enemy_career(archive, 0, 12)
    assert direct["target"] == packed["target"] == {
        "id": "mobile-0", "hp": 12, "willpower": 63, "resistant": 2, "immune": 4,
        "low_tolerance": 8, "critical_weakness": 16,
    }
    assert packed["record_sha256"] == direct["record_sha256"]
    assert packed["record"] == "ENEMY000.CFG"


def test_mismatched_career_and_incomplete_archive_are_errors(tmp_path):
    wrong = tmp_path / "CLASS00.CFG"
    wrong.write_bytes(career())
    with pytest.raises(ValueError, match="ENEMY"):
        import_enemy_career(wrong, 1, 10)
    archive = tmp_path / "MONSTER.BSA"
    archive.write_bytes(struct.pack("<hH", 1, 0x100) + bytes(18))
    with pytest.raises(ValueError):
        import_enemy_career(archive, 0, 10)


def test_absorption_needs_an_explicit_encounter_model(tmp_path):
    row = bytearray(career())
    row[9] = 1
    file = tmp_path / "CLASS00.CFG"
    file.write_bytes(row)
    out = import_enemy_career(file, 128, 120)
    assert out["record"] == "CLASS00.CFG"
    assert out["blockers"] and out["target"] is None


def test_classic_readers_and_rat_scenario_against_the_pinned_game(tmp_path):
    from dfo_optimizer.ruleset import DATA, run_adapter
    root = Path(__file__).resolve().parents[1]
    oracle = run_adapter(os.environ.get("DFO_SOURCE", root / "vendor/dfo-source"), DATA / "spell-lock.json",
                         root / "tools/ruleset/enemy_oracle.mjs", scratch_dir=tmp_path)
    path = tmp_path / "ENEMY000.CFG"
    path.write_bytes(career())
    row = import_enemy_career(path, 0, 12)["target"]
    assert {key:row[key] for key in oracle["career"]} == oracle["career"]
    req = json.loads((root / "examples/encounter-rat.json").read_text(encoding="utf8"))
    rat = oracle["rat"]
    assert rat["level"] == 1
    assert rat["min_hp"] <= req["scenario"]["enemies"][0]["hp"] <= rat["max_hp"]
    assert all(rat["min_damage"] <= hit["damage"] <= rat["max_damage"] for hit in req["scenario"]["incoming"])

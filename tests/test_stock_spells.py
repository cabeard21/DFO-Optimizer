import hashlib
import json
import os
from pathlib import Path

import pytest

from dfo_optimizer.cli import main
from dfo_optimizer.ruleset import run_adapter
from dfo_optimizer.stock_spells import stock_records


def spell_bytes(index, name, kind=4, subtype=0):
    raw = bytearray(range(89))
    raw[:6] = bytes((kind, subtype, 255, 255, 255, 255))
    raw[6:10] = bytes((4, 2, 7, 1))
    raw[47:72] = name.encode("latin1").ljust(25, b"\0")
    raw[73] = index
    return raw


def test_stock_parser_matches_authenticated_game_reader(tmp_path):
    path = tmp_path / "SPELLS.STD"
    raw = b"".join((spell_bytes(58, "Frost"), spell_bytes(58, "Second"),
                    spell_bytes(10, "Frée", 3, 2), spell_bytes(9, "Empty", 255, 255)))
    path.write_bytes(raw)
    root = Path(__file__).resolve().parents[1]
    tools = root / "tools/ruleset"
    source = os.environ.get("DFO_SOURCE", str(root / "vendor/dfo-source"))
    oracle = run_adapter(source, tools / "stock-lock.json", tools / "stock_oracle.mjs", [raw.hex()])
    got = stock_records(path)
    assert {k: v["record"] for k, v in got.items()} == oracle
    assert set(got) == {"58", "10"}
    assert got["10"]["record"]["effects"][0]["type"] == 26
    assert got["58"]["source_sha256"] == hashlib.sha256(raw).hexdigest()
    assert got["58"]["record"]["name"] == "Frost"
    assert stock_records(path, [58]) == {"58": got["58"]}
    with pytest.raises(ValueError, match="absent"):
        stock_records(path, [9])


def test_stock_cli_preserves_source_and_rejects_truncation(tmp_path, capsys):
    path = tmp_path / "SPELLS.STD"
    raw = spell_bytes(4, "Spell")
    path.write_bytes(raw)
    assert main(["spell", "stock", "--input", str(path), "--index", "4"]) == 0
    assert json.loads(capsys.readouterr().out)["spell_records"]["4"]["record"]["index"] == 4
    assert main(["spell", "stock", "--input", str(path), "--output", str(path)]) == 2
    assert path.read_bytes() == raw
    path.write_bytes(raw[:-1])
    with pytest.raises(ValueError, match="89"):
        stock_records(path)

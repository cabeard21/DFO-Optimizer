"""Read a local classic career's spell defenses for a user-observed enemy HP value."""
from hashlib import sha256
from pathlib import Path
import struct

from .ruleset import SOURCE_SHA


def _from_archive(stream, wanted):
    size = stream.seek(0, 2)
    stream.seek(0)
    header = stream.read(4)
    if len(header) != 4:
        raise ValueError("Incomplete MONSTER.BSA header")
    count, kind = struct.unpack("<hH", header)
    directory = size - 18 * count
    if kind != 0x0100 or count < 1 or directory < 4:
        raise ValueError("Expected a classic name-record BSA directory")
    stream.seek(directory)
    offset = 4
    record = None
    for name, length in struct.iter_unpack("<14si", stream.read(18 * count)):
        if length < 0 or offset + length > directory:
            raise ValueError("Invalid MONSTER.BSA record size")
        if record is None and name.partition(b"\0")[0] == wanted.encode("ascii"):
            record = offset, length
        offset += length
    if offset != directory or record is None:
        raise ValueError(f"Invalid directory or missing {wanted} in MONSTER.BSA")
    start, length = record
    if length < 74 or length > 65536:
        raise ValueError("Unexpected DFO career record size")
    stream.seek(start)
    return stream.read(length)


def import_enemy_career(path, mobile_id, observed_hp):
    if type(mobile_id) is not int or not (0 <= mobile_id <= 42 or 128 <= mobile_id <= 146):
        raise ValueError("Use a classic monster ID 0–42 or class enemy ID 128–146")
    if type(observed_hp) is not int or not 1 <= observed_hp <= 2**30:
        raise ValueError("Supply the positive HP observed on this target")
    path = Path(path)
    monster = mobile_id < 128
    name = f"ENEMY{mobile_id:03}.CFG" if monster else f"CLASS{mobile_id - 128:02}.CFG"
    with path.open("rb") as stream:
        if monster and path.name.upper() == "MONSTER.BSA":
            data = _from_archive(stream, name)
        elif path.name.upper() == name:
            data = stream.read(65537)
        else:
            raise ValueError(f"Expected {name}" + (" or MONSTER.BSA" if monster else ""))
    if not 74 <= len(data) <= 65536:
        raise ValueError("Unexpected DFO career record size")
    willpower = struct.unpack_from("<H", data, 62)[0]
    if willpower > 100 or any(mask > 127 for mask in data[:4]):
        raise ValueError("Career attributes or tolerance masks exceed the supported target domain")
    blockers = []
    if data[9]:
        blockers.append("Career spell absorption requires the target's current SP, capacity and active conditions")
    if data[7]:
        blockers.append("Career regeneration requires its live activation and round schedule")
    return {
        "kind": "enemy_career", "source_sha": SOURCE_SHA, "record": name, "mobile_id": mobile_id,
        "record_sha256": sha256(data).hexdigest(), "observed_hp": observed_hp, "blockers": blockers,
        "target": None if blockers else {
            "id": f"mobile-{mobile_id}", "hp": observed_hp, "willpower": willpower,
            **dict(zip(("resistant", "immune", "low_tolerance", "critical_weakness"), data[:4], strict=True)),
        },
        "scope": "Career-base defenses and supplied HP. Add the observed overlay, positions and attacks for an encounter.",
    }

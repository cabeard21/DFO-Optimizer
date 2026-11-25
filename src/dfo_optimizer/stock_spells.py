"""Resolve stock spell IDs against a player's local classic SPELLS.STD."""

from hashlib import sha256
import json
from pathlib import Path


RECORD_SIZE = 89
_DURATION = ("durationBase", "durationMod", "durationPerLevel")
_CHANCE = ("chanceBase", "chanceMod", "chancePerLevel")
_MAGNITUDE = ("magnitudeBaseLow", "magnitudeBaseHigh", "magnitudeLevelBase",
              "magnitudeLevelHigh", "magnitudePerLevel")


def _signed_byte(n):
    return n if n < 128 else n - 256


def _record(raw):
    effects = [{"type": _signed_byte(raw[i]), "subType": _signed_byte(raw[i + 1])}
               for i in (0, 2, 4)]
    if all(e["type"] < 0 for e in effects):
        return None
    offset = 14
    for fields in (_DURATION, _CHANCE, _MAGNITUDE):
        for effect in effects:
            effect.update(zip(fields, raw[offset:offset + len(fields)], strict=True))
            offset += len(fields)
    index = raw[73]
    if index == 10 and (effects[0]["type"], effects[0]["subType"]) == (3, 2):
        effects[0].update(type=26, subType=-1)
    return {"effects": effects, "element": raw[6], "rangeType": raw[7],
            "cost": int.from_bytes(raw[8:10], "little"),
            "name": raw[47:72].split(b"\0", 1)[0].decode("latin1"), "icon": raw[72], "index": index}


def stock_records(path, indices=None):
    """Return indexed stock records with file and record provenance, independent of ownership."""
    with Path(path).open("rb") as stream:
        raw = stream.read(2_000_001)
    if len(raw) > 2_000_000 or not raw or len(raw) % RECORD_SIZE:
        raise ValueError("SPELLS.STD requires complete 89-byte records within 2 MB.")
    wanted = None if indices is None else set(indices)
    if wanted is not None and any(type(i) is not int or not 0 <= i <= 255 for i in wanted):
        raise ValueError("Stock spell indices must be integers from 0 through 255.")
    file_hash = sha256(raw).hexdigest()
    records = {}
    for offset in range(0, len(raw), RECORD_SIZE):
        record = _record(raw[offset:offset + RECORD_SIZE])
        if record is None:
            continue
        index = record["index"]
        if index in records or (wanted is not None and index not in wanted):
            continue
        canonical = json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        records[index] = {"record": record, "source_format": "SPELLS.STD",
                          "source_sha256": file_hash, "record_sha256": sha256(canonical.encode()).hexdigest()}
    if wanted is not None and (missing := wanted - records.keys()):
        raise ValueError(f"Stock spell indices absent from supplied file: {sorted(missing)}")
    return {str(i): records[i] for i in sorted(records)}

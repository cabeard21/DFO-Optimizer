"""Read-only DFO v1 export framing and slot selection."""
import json
from pathlib import Path
import re
from zipfile import BadZipFile, ZipFile

MAX_SAVE_BYTES = 64 * 1024 * 1024
MAX_ZIP_BYTES = 256 * 1024 * 1024
CARD_BYTES = 256 * 1024
SLOT_MEMBER = re.compile(r"(?:Saves/)?SAVE(0|[1-9][0-9]{0,8})/(SaveData\.txt|SaveInfo\.txt)")


def _no_duplicates(pairs):
    result = {}
    for name, value in pairs:
        if name in result:
            raise ValueError(f"Duplicate JSON field {name!r}")
        result[name] = value
    return result


def _nonfinite(token):
    raise ValueError(f"Invalid JSON number {token}")


def read_json(stream, limit, label):
    payload = stream.read(limit + 1)
    if len(payload) > limit:
        raise ValueError(f"{label} exceeds the {limit}-byte import limit")
    try:
        value = json.loads(payload.decode("utf-8-sig"), object_pairs_hook=_no_duplicates,
                           parse_constant=_nonfinite)
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ValueError(f"{label} must be a UTF-8 JSON object") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def _card_fields(card, slot):
    when = card.get("dateAndTime", {})
    if not isinstance(when, dict):
        raise ValueError("Invalid slot dateAndTime")
    for key in ("realTime", "gameTime"):
        if when.get(key) is not None and (type(when[key]) is not int or when[key] < 0):
            raise ValueError("Invalid slot time")
    for key in ("saveName", "characterName", "dfuVersion", "characterId"):
        if card.get(key) is not None and not isinstance(card[key], str):
            raise ValueError(f"Invalid slot {key}")
    version = card.get("saveVersion")
    if version is not None and (type(version) is not int or version < 1):
        raise ValueError("Invalid save slot version")
    return {"slot": slot, "save_version": version, "character_name": card.get("characterName"),
            "character_id": card.get("characterId"), "save_name": card.get("saveName"),
            "observed_at_ms": when.get("realTime"), "game_minutes": when.get("gameTime"),
            "build_tag": card.get("dfuVersion")}


def _members(archive):
    slots = {}
    entries = archive.infolist()
    if len(entries) > 20000:
        raise ValueError("Too many ZIP members")
    for entry in entries:
        match = SLOT_MEMBER.fullmatch(entry.filename)
        if match is None:
            continue
        number, name = int(match[1]), match[2]
        group = slots.setdefault(number, {})
        if name in group:
            raise ValueError(f"Duplicate {name} for slot {number}")
        if entry.flag_bits & 1:
            raise ValueError("Encrypted save slots are unsupported")
        limit = CARD_BYTES if name == "SaveInfo.txt" else MAX_SAVE_BYTES
        if entry.file_size > limit:
            raise ValueError(f"{name} exceeds its import size limit")
        group[name] = entry
    valid = {slot: members for slot, members in slots.items() if len(members) == 2}
    if not valid:
        raise ValueError("No complete save slot in ZIP")
    return valid


def _zip_input(path, slot, list_only):
    with path.open("rb") as stream:
        return read_zip_stream(stream, slot, list_only)


def read_zip_stream(stream, slot=None, list_only=False):
    """Read a seekable ZIP without extracting or trusting member paths."""
    if slot is not None and (type(slot) is not int or slot < 0):
        raise ValueError("A slot must be a nonnegative integer")
    stream.seek(0, 2)
    if stream.tell() > MAX_ZIP_BYTES:
        raise ValueError("ZIP exceeds its import size limit")
    stream.seek(0)
    try:
        with ZipFile(stream) as archive:
            slots = _members(archive)
            if list_only:
                if sum(s["SaveInfo.txt"].file_size for s in slots.values()) > MAX_SAVE_BYTES:
                    raise ValueError("Combined slot cards exceed their import size limit")
                return [_zip_card(archive, slots[n], n) for n in sorted(slots)]
            if slot is None and len(slots) != 1:
                raise ValueError(f"Choose --slot from {sorted(slots)}")
            selected = next(iter(slots)) if slot is None else slot
            if selected not in slots:
                raise ValueError(f"Unknown save slot {selected}")
            group = slots[selected]
            card = _zip_card(archive, group, selected)
            with archive.open(group["SaveData.txt"]) as stream:
                return read_json(stream, MAX_SAVE_BYTES, "SaveData.txt"), card
    except (BadZipFile, NotImplementedError, RuntimeError, EOFError) as exc:
        raise ValueError("Unreadable or unsupported save ZIP") from exc


def _zip_card(archive, group, number):
    with archive.open(group["SaveInfo.txt"]) as stream:
        return _card_fields(read_json(stream, CARD_BYTES, "SaveInfo.txt"), number)


def read_input(path, slot=None, list_only=False):
    path = Path(path)
    if slot is not None and (type(slot) is not int or slot < 0):
        raise ValueError("A slot must be a nonnegative integer")
    if path.suffix.lower() == ".zip":
        return _zip_input(path, slot, list_only)
    if slot is not None:
        raise ValueError("Select --slot only for a save ZIP")
    if path.is_dir():
        path = path / "SaveData.txt"
    card = {}
    if path.name == "SaveData.txt" and path.with_name("SaveInfo.txt").is_file():
        with path.with_name("SaveInfo.txt").open("rb") as stream:
            match = re.fullmatch(r"SAVE(0|[1-9][0-9]{0,8})", path.parent.name)
            card = _card_fields(read_json(stream, CARD_BYTES, "SaveInfo.txt"), int(match[1]) if match else None)
    if list_only:
        if not card:
            raise ValueError("Supply a game export ZIP or a slot folder with SaveInfo.txt")
        return [card]
    with path.open("rb") as stream:
        return read_json(stream, MAX_SAVE_BYTES, path.name), card

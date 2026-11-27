"""Versioned local Firmament profiles with revision-checked updates."""
import re
from uuid import uuid4

from .character import normalize_character
from .workbench_files import Library


class ProfileChanged(ValueError):
    pass


def public_profile(profile, *, include_character=False):
    if include_character:
        return profile
    return {key: value for key, value in profile.items() if key != "character"}


class FirmamentProfiles(Library):
    def __init__(self, directory):
        super().__init__(directory)
        self.file = self.file.with_name("firmament.json")

    def update(self, edit, *, character=None):
        from .firmament import validate_allocation

        fields = {"id", "revision", "label", "tree", "stars", "craft", "spell", "spell_index", "target"}
        if not isinstance(edit, dict) or set(edit) - fields:
            raise ValueError("Invalid Firmament profile fields")
        key = edit.get("id")
        revision = edit.get("revision")
        if key is None:
            if character is None or revision is not None:
                raise ValueError("Import a character to create a Firmament profile")
        elif not isinstance(key, str) or not re.fullmatch(r"[0-9a-f]{32}", key) or type(revision) is not int:
            raise ValueError("Provide a Firmament profile ID and revision")
        with self._writing():
            document = self._read()
            items = document["items"]
            if key is None:
                previous = {"id": uuid4().hex, "revision": 0,
                            "tree": {"start": None, "keys": []}, "stars": 0, "craft": 0}
            else:
                previous = next((p for p in items if p["id"] == key), None)
                if previous is None:
                    raise KeyError("Unknown Firmament profile")
                if revision != previous["revision"]:
                    raise ProfileChanged("Firmament profile changed. Reload it and try again.")
            updates = {k: v for k, v in edit.items() if k not in {"id", "revision"}}
            if "spell" in updates and "spell_index" not in updates:
                updates["spell_index"] = None
            if "spell_index" in updates and "spell" not in updates:
                updates["spell"] = None
            profile = {**previous, **updates, "revision": previous["revision"] + 1}
            if character is not None:
                snapshot = normalize_character(character)
                name = snapshot.get("observations", {}).get("name") or "Imported character"
                if previous.get("character_hash") != snapshot["snapshot_hash"] and "spell_index" not in updates:
                    profile["spell_index"] = None
                profile = {"label": name, **profile, "character": snapshot, "character_name": name,
                           "character_hash": snapshot["snapshot_hash"]}
            if not isinstance(profile["label"], str) or not 1 <= len(profile["label"].strip()) <= 255:
                raise ValueError("Choose a profile label of 1..255 characters")
            for field in ("spell", "target"):
                if profile.get(field) is not None and not isinstance(profile[field], dict):
                    raise ValueError(f"{field} must be an object")
            index = profile.get("spell_index")
            if index is not None and (type(index) is not int or not 0 <= index < 2**31):
                raise ValueError("Invalid saved spell index")
            if index is not None and profile.get("spell") is not None:
                raise ValueError("Choose a saved spell or provide a recipe")
            profile["tree"] = validate_allocation(profile["tree"], profile["stars"], profile["craft"])["tree"]
            self._write({**document, "items": [profile, *(p for p in items if p["id"] != profile["id"])]})
        return profile


def search_request(profile):
    keys = ("character", "tree", "stars", "craft", "target", "spell", "spell_index", "revision")
    return {**{k: profile[k] for k in keys if profile.get(k) is not None}, "profile_id": profile["id"]}

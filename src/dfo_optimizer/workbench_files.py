"""Local library, browser uploads and reproducible downloadable artifacts."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile, SpooledTemporaryFile
from threading import Lock

from .character import normalize_character
from .character_files import MAX_SAVE_BYTES, read_json, read_zip_stream
from .classes import export_class, import_class
from .workbench_jobs import digest
from .workbench_services import ACTIONS, inline_only


def default_library():
    override = os.environ.get("DFO_WORKBENCH_HOME")
    if override:
        return Path(override)
    if os.name == "nt":
        return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local")) / "DFO Optimizer"
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "dfo-optimizer"


class Library:
    def __init__(self, directory):
        self.file = Path(directory) / "library.json"
        self.lock = Lock()

    @staticmethod
    def _validate(value):
        if (not isinstance(value,dict) or set(value) != {"version","preferences","items"}
                or type(value["version"]) is not int or value["version"] != 1
                or not isinstance(value["preferences"],dict) or not isinstance(value["items"],list)
                or len(value["items"]) > 100 or any(not isinstance(item,dict) for item in value["items"])):
            raise ValueError("Expected library version 1, preferences, and up to 100 item objects")
        return value

    def get(self):
        with self.lock:
            return self._read()

    def _read(self):
        if not self.file.exists():
            return {"version":1, "items":[], "preferences":{}}
        with self.file.open("rb") as stream:
            return self._validate(read_json(stream, MAX_SAVE_BYTES, "local workbench library"))

    def save(self, value):
        with self._writing():
            return self._write(value)

    @contextmanager
    def _writing(self):
        # Distinct launches can share this library while serving different
        # ephemeral ports. Lock a stable sibling inode across atomic replaces.
        with self.lock:
            self.file.parent.mkdir(parents=True,exist_ok=True)
            with self.file.with_suffix(".lock").open("a+b") as stream:
                stream.seek(0)
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(stream.fileno(),msvcrt.LK_LOCK,1)
                else:
                    import fcntl
                    fcntl.flock(stream,fcntl.LOCK_EX)
                yield  # Closing the descriptor releases either platform's lock.

    def store_item(self, envelope):
        item = envelope.get("item", {})
        preferences = envelope.get("preferences", {})
        if not isinstance(item,dict) or not isinstance(item.get("id"),str) or not item["id"]:
            raise ValueError("Each saved item needs a stable ID")
        if not isinstance(preferences,dict):
            raise ValueError("Preferences must be an object")
        with self._writing():
            previous = self._read()
            return self._write({"version":1, "items":[item,*(x for x in previous["items"] if x.get("id") != item["id"])],
                                "preferences":{**previous["preferences"],**preferences}})

    def item(self, identifier):
        item = next((item for item in self.get()["items"] if item.get("id") == identifier),None)
        if item is None:
            raise KeyError("Unknown saved item")
        return item

    def _write(self, value):
        payload = json.dumps(self._validate(value),ensure_ascii=False,allow_nan=False,separators=(",",":")).encode()
        if len(payload) > MAX_SAVE_BYTES:
            raise ValueError("Library exceeds the local storage limit")
        temp = NamedTemporaryFile(dir=self.file.parent,delete=False)
        try:
            with temp:
                temp.write(payload)
                temp.flush()
                os.fsync(temp.fileno())
            os.replace(temp.name,self.file)
        finally:
            Path(temp.name).unlink(missing_ok=True)
        return value


def upload_save(stream, length, kind, slot, zip_format):
    # Small uploads stay in memory. Larger ones spill into a temporary file
    # automatically removed on close. Client filenames never reach the filesystem.
    first = stream.read(min(length,4))
    zipped = zip_format or first.startswith(b"PK")
    if not zipped and length > MAX_SAVE_BYTES:
        raise ValueError("JSON save exceeds its import limit")
    with SpooledTemporaryFile(max_size=8<<20) as file:
        file.write(first)
        remaining = length-len(first)
        while remaining:
            chunk = stream.read(min(remaining,65536))
            if not chunk:
                raise ValueError("Incomplete character upload")
            file.write(chunk)
            remaining -= len(chunk)
        file.seek(0)
        if zipped:
            result = read_zip_stream(file,slot,list_only=kind=="slots")
            if kind == "slots":
                return result
            document,card = result
        else:
            if slot is not None or kind == "slots":
                raise ValueError("Select a slot from a game export ZIP")
            document,card = read_json(file,MAX_SAVE_BYTES,"character"),{}
        return normalize_character(document,card=card)


def imported(kind, value, ruleset_hash):
    if kind == "class":
        value = import_class(value)
    elif kind == "request":
        inline_only(value)
    elif kind == "archive":
        if (value.get("format") != "dfo-workbench-archive" or type(value.get("version")) is not int
                or value["version"] != 1 or value.get("action") not in ACTIONS
                or not isinstance(value.get("request"),dict) or not isinstance(value.get("result"),dict)
                or value.get("request_hash") != digest(value["request"])
                or value["result"].get("ruleset_hash",value.get("ruleset_hash")) != value.get("ruleset_hash")
                or value.get("archive_sha256") != digest({k:v for k,v in value.items() if k != "archive_sha256"})):
            raise ValueError("Invalid workbench archive or checksum")
        inline_only(value["request"])
    elif kind not in ("result","character","slots","inventory","benchmark"):
        raise ValueError("Unsupported upload type")
    warnings = []
    if isinstance(value,dict) and value.get("ruleset_hash") not in (None,ruleset_hash):
        warnings.append("Ruleset mismatch. This document uses a different snapshot.")
    return {"kind":kind, "value":value, "warnings":warnings}


def library_item(kind, value, label):
    if not isinstance(label,str) or not 1 <= len(label) <= 255:
        raise ValueError("Choose a library label of 1..255 characters")
    if kind == "archive":
        payload = {**value, "isArchive":True}
        identifier = value["result"].get("result_hash")
    elif kind == "result":
        action = {"progression_plan":"progression plan","spell_curve":"spell curve",
                  "lifecycle":"build optimize"}.get(value.get("kind"))
        if value.get("kind") == "encounter_result" and value.get("mode") in ("evaluate","optimize"):
            action = "encounter " + value["mode"]
        payload = {"result":value,"action":action,"request":value.get("frozen_request"),
                   "ruleset_hash":value.get("ruleset_hash")}
        identifier = value.get("result_hash")
    elif kind == "character":
        payload, identifier = {"kind":kind,"value":value}, value.get("snapshot_hash")
    else:
        raise ValueError("Select a result, archive or character to save")
    return {**payload,"id":identifier or digest(value),"label":label}


def export_job(job, query):
    preview = query.get("preview") == "1"
    result = job["incumbent"] if preview else job["result"]
    if result is None:
        raise ValueError("This job has no final service result. Save a checked preview separately.")
    if query.get("archive") == "1":
        request = job["incumbent_request"] if preview else job["request"]
        archive = {"format":"dfo-workbench-archive","version":1,"action":job["action"],
                   "mode":"request" if preview else job["mode"],"request":request,"request_hash":digest(request),
                   "ruleset_hash":job["ruleset_hash"],"result":result,"preview":preview}
        return {**archive,"archive_sha256":digest(archive)}, "workbench-archive.json"
    if job["action"] == "build recommend" and ("family" in query or "checklist" in query):
        if (set(query) - {"family", "checklist", "preview"} or "family" not in query or
                query.get("checklist", "1") != "1" or query.get("preview", "1") != "1"):
            raise ValueError("Choose one published recommendation")
        rows = [result.get("recommendation"), *result.get("alternatives", [])]
        selected = next((r for r in rows if isinstance(r,dict) and r.get("id") == query["family"]), None)
        if not selected:
            raise ValueError("Unknown published recommendation")
        if "checklist" in query:
            return selected["guide"]["text"].encode("utf-8"), "spellcaster-checklist.txt"
        return export_class(selected["class"]), "spellcaster.dfclass.json"
    if "family" in query:
        if job["action"] != "build optimize" or query.keys() - {"family", "preview"}:
            raise ValueError("Select one family from a build result")
        family_id = query["family"]
        witnesses = (*result["candidates"], *result.get("comparison_witnesses", ()))
        if not any(row.get("family") == family_id and row.get("validated") for row in witnesses):
            raise ValueError("Unknown validated build family")
        frozen = result["frozen_request"]
        families = [*frozen.get("families", []), *frozen.get("class_admission", {}).get("families", [])]
        family = next((row for row in families if row["id"] == family_id), {})
        start = family.get("start")
        if "baseline_id" in family:
            from .build_baselines import resolve_family_baseline
            from .ruleset import load_ruleset
            start = resolve_family_baseline(family["baseline_id"], load_ruleset())
        if not start or start.get("type") != "new_character":
            raise ValueError("This build family has no game class document")
        return export_class(start["class"]), "dfo-class.json"
    if "index" in query or "class_id" in query:
        if job["action"] != "class optimize" or ("index" in query and "class_id" in query):
            raise ValueError("Select one class from a completed class search")
        candidates = result["candidates"]
        if "class_id" in query:
            selected = next((r for r in candidates if r["class_id"] == query["class_id"]), None)
        else:
            index = int(query["index"])
            selected = candidates[index] if 0 <= index < len(candidates) else None
        if selected is None:
            raise ValueError("Unknown class candidate")
        return export_class(selected["class_doc"]), "dfo-class.json"
    return result, "dfo-validated-preview.json" if preview else "dfo-result.json"

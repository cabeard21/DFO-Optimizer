"""Pinned offline ruleset and deterministic extraction from authenticated Git blobs."""
import hashlib
from functools import lru_cache
import json
import os
from pathlib import Path
import subprocess
import tempfile

SOURCE_SHA = "a3eb1605ea1dc391b691fe314377458a7e63e483"
SOURCE_URL = "https://github.com/Lattymoy/daggerfall-js-source"
DATA = Path(__file__).with_name("data")
BUNDLE_HASH = "e8d974f193cc266b6fdbaaae73f35bc5e1bb446fe8cfa22a65da3c21269ca886"
COMBAT_BUNDLE_HASH = "b8755e71e6c87e3efcf582325d49230a68db49910930127e72b0b12eff2bf183"
CLASS_BUNDLE_HASH = "293f927a36e9bdbc9504e8ed3f16582e326c9bcc5f7a8b84a241a81ae069a27d"
MAX_BUNDLE_BYTES = 2_000_000


def _json_bytes(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _digest(bundle):
    return hashlib.sha256(_json_bytes({k: v for k, v in bundle.items() if k != "content_hash"})).hexdigest()


def _authenticate(bundle):
    if not isinstance(bundle, dict) or bundle.get("source_sha") != SOURCE_SHA or bundle.get("schema_version") != 1:
        raise ValueError("Unsupported ruleset schema or source revision")
    identity = bundle.get("content_hash")
    body = _json_bytes({k: v for k, v in bundle.items() if k != "content_hash"})
    if identity not in (BUNDLE_HASH, COMBAT_BUNDLE_HASH, CLASS_BUNDLE_HASH) or hashlib.sha256(body).hexdigest() != identity:
        raise ValueError("Ruleset does not match the reviewed content hash")
    return body, identity


def validate_ruleset(bundle: dict) -> dict:
    """Only the exact reviewed schema and contents may become a native search input."""
    _authenticate(bundle)
    return bundle


def freeze_ruleset(bundle):
    """Detach from the caller using the same canonical bytes that passed authentication."""
    body, identity = _authenticate(bundle)
    snapshot = json.loads(body)
    snapshot["content_hash"] = identity
    return snapshot


def validate_combat_ruleset(bundle):
    validate_ruleset(bundle)
    if bundle["content_hash"] == CLASS_BUNDLE_HASH:
        raise ValueError("Spell and gear evaluation require a ruleset with combat mechanics.")
    return bundle


@lru_cache(maxsize=1)
def _installed_combat_rules():
    """Read-only service snapshot owned by the installed package."""
    return validate_combat_ruleset(load_ruleset())


def validate_progression_ruleset(bundle):
    validate_ruleset(bundle)
    if bundle.get("extraction_version") != 3:
        raise ValueError("Progression and spellbook evaluation require the lifecycle ruleset.")
    return bundle


def _bundle_path(path):
    candidate = Path(path)
    if candidate.is_dir() or candidate.suffix.lower() != ".json":
        return candidate / "ruleset.json"
    return candidate


def load_ruleset(path=None) -> dict:
    """Return a detached JSON snapshot. Every call authenticates its complete contents."""
    source = _bundle_path(path) if path is not None else DATA / "ruleset.json"
    with source.open("rb") as stream:
        raw = stream.read(MAX_BUNDLE_BYTES + 1)
    if len(raw) > MAX_BUNDLE_BYTES:
        raise ValueError("Ruleset exceeds the supported bundle size")
    return validate_ruleset(json.loads(raw))


def coverage(bundle: dict) -> dict:
    validate_ruleset(bundle)
    registry = bundle["mechanics"]
    return {
        "source_sha": SOURCE_SHA, "content_hash": bundle["content_hash"],
        "snapshot_verified": [r["mechanic_id"] for r in registry if r["verification_status"] == "source_verified"],
        "live_verified": [r["mechanic_id"] for r in registry if r["live_verified"]],
        "unsupported": [r["mechanic_id"] for r in registry if r["verification_status"] == "unsupported"],
        "mechanics": registry,
    }


def materialize_pinned(source, destination: Path, lock: dict) -> None:
    """Stage regular-file data from an internal allowlist, never worktree contents.

    Each record's object ID AND its serialized Git blob digest must match our lock.
    A corrupt/replaced object cannot cause execution of modified JavaScript.
    """
    requests = "".join(f"{SOURCE_SHA}:{name}\n" for name in lock).encode()
    env = {**os.environ, "GIT_NO_REPLACE_OBJECTS": "1", "GIT_NO_LAZY_FETCH": "1", "GIT_TERMINAL_PROMPT": "0"}
    cmd = ["git", "-C", str(Path(source).resolve()), "cat-file", "--batch"]
    proc = subprocess.run(cmd, input=requests, capture_output=True, timeout=120, env=env)
    if proc.returncode:
        raise ValueError("Cannot read the pinned Git objects from the supplied source")
    offset = 0
    for name, expected in lock.items():
        end = proc.stdout.index(b"\n", offset)
        header = proc.stdout[offset:end].split()
        if len(header) != 3 or header[:2] != [expected.encode("ascii"), b"blob"]:
            raise ValueError(f"Missing or mismatched pinned source blob: {name}")
        size = int(header[2])
        payload = proc.stdout[end + 1:end + 1 + size]
        digest = hashlib.sha1(b"blob " + header[2] + b"\0" + payload, usedforsecurity=False).hexdigest()
        if len(payload) != size or digest != expected:
            raise ValueError(f"Corrupted pinned source blob: {name}")
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
        offset = end + size + 2
    (destination / "package.json").write_text('{"type":"module"}', encoding="ascii")


def run_adapter(source, lock_file: Path, adapter: Path, args=()):
    lock = json.loads(lock_file.read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory(prefix="dfo-source-") as scratch:
        stage = Path(scratch)
        materialize_pinned(source, stage, lock)
        script = stage / "adapter.mjs"
        script.write_bytes(adapter.read_bytes())
        env = {k: v for k, v in os.environ.items() if k.upper() not in {"NODE_OPTIONS", "NODE_PATH"}}
        proc = subprocess.run(
            ["node", str(script), *args], capture_output=True, cwd=stage, env=env, timeout=120,
        )
        if proc.returncode:
            raise ValueError(f"Node source adapter failed: {proc.stderr.decode('utf-8', errors='replace')[:1200]}")
        return json.loads(proc.stdout)


def _extract(source):
    catalog = run_adapter(source, DATA / "source-lock.json", DATA / "extract.mjs")
    def data(name):
        return json.loads((DATA / name).read_text(encoding="utf-8"))

    registry = {row["mechanic_id"]: row for row in data("mechanics.json")}
    for name in ("spell-mechanics.json", "equipment-mechanics.json",
                 "progression-mechanics.json", "spellbook-mechanics.json"):
        registry.update((row["mechanic_id"], row) for row in data(name))
    spell_rules = run_adapter(source, DATA / "spell-lock.json", DATA / "spell-rules.mjs")
    equipment = {"source_sha": SOURCE_SHA, **run_adapter(source, DATA / "equipment-lock.json", DATA / "equipment.mjs")}
    progression = run_adapter(source, DATA / "progression-lock.json", DATA / "progression-rules.mjs")
    if (spell_rules != data("spell-rules.json") or equipment != data("equipment.json")
            or progression != data("progression-rules.json")):
        raise ValueError("Extracted catalogs differ from the reviewed data shipped in this package.")
    bundle = {
        **catalog, "schema_version": 1, "extraction_version": 3, "engine_version": "lifecycle-v1",
        "mode": "online_snapshot", "source_url": SOURCE_URL, "source_sha": SOURCE_SHA,
        "snapshot_date": "2026-11-02", "supported_live_version": None,
        "mechanics": list(registry.values()), "spell_rules": spell_rules,
        "equipment_hash": hashlib.sha256(_json_bytes(equipment)).hexdigest(),
        "progression_rules": progression,
    }
    return {**bundle, "content_hash": _digest(bundle)}


def build_ruleset(source, commit: str, out) -> dict:
    if commit != SOURCE_SHA:
        raise ValueError(f"Only supported commit is {SOURCE_SHA}")
    target = _bundle_path(out).resolve()
    if target.is_relative_to(Path(source).resolve()):
        raise ValueError("Write the ruleset outside the reference checkout")
    bundle = validate_ruleset(_extract(source))
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as temp:
        staged = Path(temp.name)
    try:
        staged.write_bytes((json.dumps(bundle, sort_keys=True, indent=2) + "\n").encode("utf-8"))
        staged.replace(target)
    finally:
        staged.unlink(missing_ok=True)
    return bundle

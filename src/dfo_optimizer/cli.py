"""Installed DFO optimizer CLI. Every successful command produces JSON."""

import argparse
import json
import os
from pathlib import Path
from subprocess import SubprocessError
import sys
from tempfile import NamedTemporaryFile


def _invalid_json_number(token):
    raise ValueError(f"{token} is not a JSON number.")


def _input(path):
    if str(path) == "-":
        return json.load(sys.stdin, parse_constant=_invalid_json_number)
    return json.loads(Path(path).read_text(encoding="utf-8-sig"), parse_constant=_invalid_json_number)


def _write(value, destination):
    document = json.dumps(value, ensure_ascii=True, allow_nan=False, indent=2) + "\n"
    if destination is None or str(destination) == "-":
        sys.stdout.write(document)
        return
    target = Path(destination)
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = NamedTemporaryFile("w", encoding="utf-8", newline="\n", dir=target.parent, delete=False)
    try:
        with temp:
            temp.write(document)
        os.replace(temp.name, target)
    finally:
        Path(temp.name).unlink(missing_ok=True)


def _command(subcommands, name, description, *, ruleset=True):
    cmd = subcommands.add_parser(name, help=description, description=description)
    if ruleset:
        cmd.add_argument("--ruleset", type=Path, help="bundle directory or ruleset.json")
    cmd.add_argument("--output", type=Path, help="JSON output file (default: stdout)")
    return cmd


def _parser():
    parser = argparse.ArgumentParser(prog="dfo", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    rules = commands.add_parser("ruleset").add_subparsers(dest="action", required=True)
    build = rules.add_parser("build", help="extract the supported source revision")
    build.add_argument("--source", required=True, type=Path)
    build.add_argument("--commit", required=True)
    build.add_argument("--out", required=True, type=Path)
    _command(rules, "validate", "Check bundle integrity and schema")
    _command(rules, "coverage", "List supported mechanics and evidence")

    classes = commands.add_parser("class").add_subparsers(dest="action", required=True)
    for action in ("import", "validate"):
        cmd = _command(classes, action, "Inspect a game class file and its creation and profile checks")
        cmd.add_argument("--class", "--input", dest="document", required=True, type=Path)
        cmd.add_argument("--race", type=int, help="external race ID")
    export = _command(classes, "export", "Write a validated v1 game class document")
    source = export.add_mutually_exclusive_group(required=True)
    source.add_argument("--result", type=Path, help="class optimize result file")
    source.add_argument("--class", "--input", dest="document", type=Path, help="game class document")
    selection = export.add_mutually_exclusive_group()
    selection.add_argument("--class-id", help="stable candidate ID in the result")
    selection.add_argument("--index", type=int, help="zero-based candidate index (default: 0)")
    optimize = _command(classes, "optimize", "Search a frozen class request")
    optimize.epilog = (
        "Ctrl+C requests cancellation. A cancelled search writes its checked incumbents "
        "to the selected output with status cancelled and exits with code 130."
    )
    optimize.add_argument("--request", type=Path, help="request JSON, or - for stdin")
    optimize.add_argument("--profile", choices=["dhargo_pve"])
    optimize.add_argument("--top", type=int, help="override the requested number of results")
    characters = commands.add_parser("character").add_subparsers(dest="action", required=True)
    for action in ("slots", "import"):
        cmd = _command(characters, action, "Read a local character snapshot or DFO save export", ruleset=False)
        cmd.add_argument("--input", type=Path, required=True)
        if action == "import":
            cmd.add_argument("--slot", type=int, help="DFO save slot number in a multi-slot export")
    spell = commands.add_parser("spell").add_subparsers(dest="action", required=True)
    gear = commands.add_parser("gear").add_subparsers(dest="action", required=True)
    for parent, action, help_text in (
        (commands, "evaluate", "Evaluate one fixed direct spell"),
        (spell, "optimize", "Search legal Damage Health settings"),
        (gear, "evaluate", "Evaluate a complete loadout"),
        (gear, "optimize", "Search complete loadouts and spell settings"),
    ):
        cmd = _command(parent, action, help_text)
        cmd.add_argument("--request", type=Path, required=True, help="frozen JSON request, or - for stdin")
        cmd.add_argument("--character", type=Path, help="supply the character from an exported save or portable snapshot")
        cmd.add_argument("--slot", type=int, help="save slot in --character")
    bench = _command(commands, "benchmark", "Run the serial native benchmark suite", ruleset=False)
    bench.add_argument("--suite", choices=["foundation", "smoke", "combat"], default="smoke")
    bench.add_argument("--workers", type=int, choices=[1], default=1)
    return parser


def _export_source(args, bundle):
    if args.document is not None:
        if args.class_id is not None or args.index is not None:
            raise ValueError("Candidate selection requires --result.")
        return _input(args.document)
    result = _input(args.result)
    if not isinstance(result, dict) or result.get("ruleset_hash") != bundle["content_hash"]:
        raise ValueError("The search result must use the selected ruleset.")
    candidates = result.get("candidates")
    if not isinstance(candidates, list) or any(not isinstance(c, dict) for c in candidates):
        raise ValueError("Malformed search result candidate list.")
    if args.class_id is not None:
        matches = [c for c in candidates if c.get("class_id") == args.class_id]
        if len(matches) != 1:
            raise ValueError("Expected one candidate with the requested class ID.")
        candidate = matches[0]
    else:
        index = args.index or 0
        if index < 0 or index >= len(candidates):
            raise ValueError("Candidate index is outside the result.")
        candidate = candidates[index]
    if not isinstance(candidate.get("class_doc"), dict):
        raise ValueError("Missing candidate class document.")
    from .search import class_identity
    race = candidate.get("race_id")
    if (type(race) is not int or race not in {r["id"] for r in bundle["races"]}
            or candidate.get("class_id") != class_identity(bundle["content_hash"], race, candidate["class_doc"])):
        raise ValueError("Candidate identity does not match its race, ruleset and class document.")
    return candidate["class_doc"]


def _interruptible_search(service, token_factory, request, bundle):
    from concurrent.futures import ThreadPoolExecutor, wait
    import signal
    import threading

    # Only the main interpreter thread can receive SIGINT. Keep it available
    # while the serial native worker searches with the GIL released.
    if threading.current_thread() is not threading.main_thread():
        return service(request, ruleset=bundle)
    token = token_factory()
    previous = signal.getsignal(signal.SIGINT)
    try:
        if previous != signal.SIG_IGN:
            signal.signal(signal.SIGINT, lambda _signum, _frame: token.cancel())
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(service, request, ruleset=bundle, cancel=token)
            while not future.done():
                # A finite wait lets Windows dispatch pending Python signals.
                # Normal completion wakes this wait immediately.
                wait((future,), timeout=0.05)
            return future.result()
    finally:
        signal.signal(signal.SIGINT, previous)


def _combat(args, bundle):
    request = _input(args.request)
    if not isinstance(request, dict):
        raise ValueError("Combat request must be a JSON object.")
    if args.character is not None:
        if "caster" in request or "character" in request:
            raise ValueError("Specify the character once, in the request or with --character.")
        from .character import import_character
        request = {**request, "character": import_character(args.character, slot=args.slot)}
    elif args.slot is not None:
        raise ValueError("--slot requires --character.")
    if args.command == "gear":
        from . import _gear, gear
        service = gear.optimize_gear if args.action == "optimize" else gear.evaluate_gear
        factory = _gear.CancelToken
    else:
        from . import _spells, spells
        service = spells.evaluate_spell if args.command == "evaluate" else spells.optimize_spells
        factory = _spells.CancelToken
    result = _interruptible_search(service, factory, request, bundle)
    return result, 130 if result.get("termination") == "cancelled" else 0


def _dispatch(args):
    from . import ruleset

    if args.command == "benchmark":
        if args.suite == "combat":
            from .combat_benchmark import run_combat_benchmark
            return run_combat_benchmark(), 0
        from .benchmark import run_benchmark
        return run_benchmark(args.suite), 0
    if args.command == "ruleset" and args.action == "build":
        bundle = ruleset.build_ruleset(args.source, args.commit, args.out)
        return {"ruleset_hash": bundle["content_hash"], "source_sha": bundle["source_sha"], "out": str(args.out)}, 0
    if args.command == "character":
        from .character import import_character, list_character_slots
        if args.action == "slots":
            return list_character_slots(args.input), 0
        return import_character(args.input, slot=args.slot), 0
    bundle = ruleset.load_ruleset(args.ruleset)
    if args.command in ("evaluate", "gear", "spell"):
        return _combat(args, bundle)
    if args.command == "ruleset":
        if args.action == "coverage":
            return ruleset.coverage(bundle), 0
        ruleset.validate_ruleset(bundle)
        return {"valid": True, "ruleset_hash": bundle["content_hash"], "source_sha": bundle["source_sha"]}, 0
    if args.action == "optimize":
        from .native import require_native
        from .search import optimize_classes
        request = _input(args.request) if args.request is not None else {}
        if not isinstance(request, dict):
            raise ValueError("Search request must be a JSON object.")
        overrides = {"profile": args.profile, "top_k": args.top}
        request = {**request, **{k: v for k, v in overrides.items() if v is not None}}
        result = _interruptible_search(optimize_classes, require_native().CancelToken, request, bundle)
        return result, 130 if result["termination"] == "cancelled" else 0
    from . import classes
    if args.action == "export":
        return classes.export_class(_export_source(args, bundle), ruleset=bundle), 0
    report = classes.validate_class(_input(args.document), ruleset=bundle, race=args.race)
    valid = report["parsed"] if args.action == "import" else report["profile_legal"] and not report["skipped"]
    return report, 0 if valid else 1


def _protect_save(args):
    if getattr(args, "output", None) is None or str(args.output) == "-":
        return
    source = args.input if args.command == "character" else getattr(args, "character", None)
    if source is None:
        return
    path = source.resolve()
    destination = args.output.resolve()
    if path == destination or (path.is_dir() and destination.is_relative_to(path)):
        raise ValueError("Choose an output path outside the input game save.")
    slot_files = {"savedata.txt", "saveinfo.txt"}
    if path.name.casefold() in slot_files and destination.parent == path.parent:
        if destination.name.casefold() in slot_files:
            raise ValueError("The output would replace a game save file.")


def main(argv=None):
    args = _parser().parse_args(argv)
    try:
        _protect_save(args)
        result, status = _dispatch(args)
        _write(result, getattr(args, "output", None))
        return status
    except (ValueError, OSError, RuntimeError, ImportError, SubprocessError) as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print(json.dumps({"error": "Cancelled."}), file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())

from importlib.util import module_from_spec, spec_from_file_location
import json
from pathlib import Path
from zipfile import ZipFile

from dfo_optimizer import beginner
from dfo_optimizer.beginner_classes import manual_classes


def test_standard_publishes_the_actual_replayed_class_and_checklist(tmp_path, monkeypatch):
    spec = spec_from_file_location(
        "beginner_demo", Path(__file__).parents[1] / "tools/run_beginner_demonstration.py"
    )
    demo = module_from_spec(spec)
    spec.loader.exec_module(demo)
    family = manual_classes()[0]
    winner = {
        "id": family["id"],
        "role": "Recommended spellcaster",
        "race": "Breton",
        "race_id": family["start"]["race_id"],
        "class": family["start"]["class"],
        "metrics": {},
        "guide": {"text": "Choose Breton.\n"},
        "origin": "manual",
        "status": "replayed",
    }
    result = {
        "status": "best_found_bounded",
        "termination": "panel_complete",
        "ruleset_hash": "rules",
        "source_sha": "src",
        "result_hash": "digest",
        "recommendation": winner,
        "alternatives": [],
        "timings": {"elapsed_seconds": 1, "first_validated_seconds": 1},
        "diagnostics": {"admission": {"counts": {"legal": 1, "manual": 1, "admitted": 0}}},
        "sensitivity": [],
        "assumptions": [],
        "limitations": [],
        "comparisons": [winner],
    }
    monkeypatch.setattr(beginner, "recommend_build", lambda request: result)
    monkeypatch.setattr(beginner, "replay_recommendation", lambda plan: {"verified": plan == result})
    summary = demo.save_run(tmp_path, "standard")
    with ZipFile(tmp_path / summary["archive"]) as archive:
        saved = json.loads(archive.read("workbench-archive.json"))
        assert saved["result"] == result and saved["request"] == {"thoroughness": "standard"}
        for member in ("recommended.dfclass.json", "recommended-checklist.txt"):
            assert (tmp_path / ("m9-standard-" + member)).read_bytes() == archive.read(member)
    assert summary["fully_evaluated_by_origin"] == {"manual": 1}

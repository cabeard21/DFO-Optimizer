import json

import pytest

from dfo_optimizer import cli


@pytest.fixture
def requests(monkeypatch):
    seen = []

    def run(_fn, _cancel, request, _rules):
        seen.append(request)
        return {"termination": "panel_complete"}

    monkeypatch.setattr(cli, "_interruptible_search", run)
    return seen


def test_new_cli_requests_use_strict_profile_and_preserve_legacy_file(tmp_path, requests):
    parser = cli._parser()
    cli._planning(parser.parse_args(["build", "recommend"]), None)
    path = tmp_path / "legacy.json"
    path.write_text('{"thoroughness":"quick"}', encoding="utf-8")
    cli._planning(parser.parse_args(["build", "recommend", "--request", str(path)]), None)
    assert requests == [{"schema_version": 2}, {"thoroughness": "quick"}]


def test_compare_slower_reads_checked_strict_incumbent(tmp_path, requests):
    parser = cli._parser()
    path = tmp_path / "archive.json"
    selected = {"class": {"name": "Test Mage"}, "race_id": 1, "status": "replayed",
                "metrics": {"advancement_multiplier": 0.30}}
    result = {"kind": "beginner_recommendation", "recommendation": selected,
              "frozen_request": {"thoroughness": "quick"}}
    path.write_text(json.dumps({"format": "dfo-workbench-archive", "result": result}), encoding="utf-8")
    cli._planning(parser.parse_args(["build", "recommend", "--compare-slower", str(path)]), None)
    assert requests == [{"schema_version": 2, "thoroughness": "quick",
                         "compare_slower": {"class": selected["class"], "race_id": 1}}]


def test_compare_slower_cannot_overwrite_the_input_archive(tmp_path):
    archive = tmp_path / "archive.json"
    archive.write_text('{}', encoding="utf-8")
    args = cli._parser().parse_args([
        "build", "recommend", "--compare-slower", str(archive), "--output", str(archive)
    ])
    with pytest.raises(ValueError, match="distinct"):
        cli._protect_save(args)

import json
import subprocess
import sys

import pytest

from dfo_optimizer.cli import main


def test_ruleset_summary_is_json(capsys):
    assert main(["ruleset", "coverage"]) == 0
    assert json.loads(capsys.readouterr().out)


def test_invalid_request_does_not_overwrite_output(tmp_path, capsys):
    request = tmp_path / "broken.json"
    request.write_text("[", encoding="utf-8")
    output = tmp_path / "out.json"
    output.write_bytes(b"previous output")
    assert main(["class", "optimize", "--request", str(request), "--output", str(output)]) == 2
    assert output.read_bytes() == b"previous output"
    assert json.loads(capsys.readouterr().err)["error"]


def test_installed_bundle_validation_and_export_by_id(capsys, tmp_path):
    assert main(["ruleset", "validate"]) == 0
    assert json.loads(capsys.readouterr().out)["valid"] is True
    output = tmp_path / "nested" / "result.json"
    assert main(["class", "optimize", "--profile", "dhargo_pve", "--top", "1", "--output", str(output)]) == 0
    result = json.loads(output.read_text())
    class_id = result["candidates"][0]["class_id"]
    assert main(["class", "export", "--result", str(output), "--class-id", class_id]) == 0
    exported = json.loads(capsys.readouterr().out)
    assert exported == result["candidates"][0]["class_doc"]
    assert main(["class", "export", "--result", str(output), "--class-id", "absent"]) == 2
    assert main(["class", "export", "--result", str(output), "--index", "-1"]) == 2
    result["ruleset_hash"] = "mismatched"
    output.write_text(json.dumps(result))
    assert main(["class", "export", "--result", str(output)]) == 2


@pytest.mark.parametrize("field", ["name", "skills", "race"])
def test_result_export_rejects_tampered_identity(tmp_path, field, capsys):
    path = tmp_path / "result.json"
    assert main(["class", "optimize", "--top", "1", "--output", str(path)]) == 0
    result = json.loads(path.read_text())
    candidate = result["candidates"][0]
    if field == "name":
        candidate["class_doc"]["name"] = "Altered class"
    elif field == "skills":
        candidate["class_doc"]["skills"]["primary"].reverse()
    else:
        candidate["race_id"] = 1 if candidate["race_id"] != 1 else 2
    path.write_text(json.dumps(result))
    for selector in (["--class-id", candidate["class_id"]], ["--index", "0"]):
        assert main(["class", "export", "--result", str(path), *selector]) == 2
        assert "identity" in json.loads(capsys.readouterr().err)["error"].lower()


def test_drafts_can_be_imported_and_do_not_pass_create(tmp_path, capsys):
    path = tmp_path / "results.json"
    assert main(["class", "optimize", "--top", "1", "--output", str(path)]) == 0
    document = json.loads(path.read_text())["candidates"][0]["class_doc"]
    document["skills"]["primary"][0] = None
    path.write_text(json.dumps(document))
    assert main(["class", "import", "--class", str(path)]) == 0
    imported = json.loads(capsys.readouterr().out)
    assert imported["parsed"] and not imported["create_legal"]
    assert main(["class", "validate", "--class", str(path)]) == 1
    assert main(["class", "export", "--class", str(path)]) == 2


def test_stdout_request_and_error_for_non_object(monkeypatch, capsys):
    import io
    monkeypatch.setattr(sys, "stdin", io.StringIO("[]"))
    assert main(["class", "optimize", "--request", "-"]) == 2
    assert "object" in json.loads(capsys.readouterr().err)["error"]


def test_nonfinite_numbers_are_rejected_even_in_ignored_fields(tmp_path, capsys):
    path = tmp_path / "malformed.json"
    path.write_text('{"extra": NaN}')
    assert main(["class", "import", "--input", str(path)]) == 2
    assert "NaN" in json.loads(capsys.readouterr().err)["error"]


def test_ruleset_build_failures_use_cli_error_response(tmp_path, monkeypatch, capsys):
    from dfo_optimizer import ruleset

    def source_timeout(*args):
        raise subprocess.TimeoutExpired("git", 120)

    monkeypatch.setattr(ruleset, "build_ruleset", source_timeout)
    assert main(["ruleset", "build", "--source", str(tmp_path), "--commit", ruleset.SOURCE_SHA,
                 "--out", str(tmp_path / "out")]) == 2
    assert "timed out" in json.loads(capsys.readouterr().err)["error"]


@pytest.mark.parametrize("workers", ["0", "2"])
def test_benchmark_workers_are_serial(workers):
    with pytest.raises(SystemExit) as error:
        main(["benchmark", "--workers", workers])
    assert error.value.code == 2


def test_installed_cli_search_export_validate(tmp_path):
    def call(*args):
        return subprocess.run(
            [sys.executable, "-I", "-m", "dfo_optimizer.cli", *map(str, args)],
            cwd=tmp_path, capture_output=True, text=True, check=True,
        )

    results = tmp_path / "results.json"
    game = tmp_path / "my-class.json"
    call("class", "optimize", "--top", 1, "--output", results)
    call("class", "export", "--result", results, "--index", 0, "--output", game)
    assert json.loads(game.read_text(encoding="utf-8"))["format"] == "daggerfall-enhanced/custom-class"
    report = json.loads(call("class", "validate", "--class", game).stdout)
    assert report["create_legal"] and report["profile_legal"]
    assert report["difficulty_points"] == -12
    assert report["advancement_multiplier"] == 0.30
    imported = json.loads(call("class", "import", "--input", game).stdout)
    assert imported["normalized"] == json.loads(game.read_text(encoding="utf-8"))

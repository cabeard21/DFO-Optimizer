"""Exercise the actual loopback HTTP transport and the public service boundary."""
from http.client import HTTPConnection
import json
from pathlib import Path
from threading import Thread
from time import monotonic, sleep

import pytest

from dfo_optimizer.workbench import create_server


@pytest.fixture
def site(tmp_path):
    with create_server(library_dir=tmp_path / "library") as server:
        thread = Thread(target=server.serve_forever, kwargs={"poll_interval": .02})
        thread.start()
        try:
            yield server
        finally:
            server.shutdown()
            thread.join()


def call(site, path, body=None, *, headers=None):
    client = HTTPConnection(*site.server_address, timeout=10)
    if body is not None and not isinstance(body, bytes):
        body = json.dumps(body).encode()
    client.request("GET" if body is None else "POST", path, body,
                   {"Content-Type":"application/json", **(headers or {})})
    reply = client.getresponse()
    data = reply.read()
    client.close()
    return reply.status, json.loads(data) if "json" in (reply.getheader("Content-Type") or "") else data


def finish(site, job_id, predicate=None):
    until = monotonic()+15
    while monotonic()<until:
        code, result = call(site,"/api/jobs/"+job_id)
        assert code == 200
        ready = predicate(result) if predicate else result["state"] in {"completed","cancelled","failed"}
        if ready:
            return result
        sleep(.005)
    pytest.fail("Job timed out")


def test_service_examples_exports_and_reopened_archive(site):
    from dfo_optimizer.gear import optimize_gear
    _, meta = call(site, "/api/meta")
    assert {"gear-bis","gear-owned","gear-budget"} <= set(meta["examples"])
    _, request = call(site, "/api/examples/gear-budget")
    code, job = call(site, "/api/jobs", {"action":"gear optimize","request":request, "mode":"request"})
    assert code == 202
    done = finish(site,job["id"])
    assert done["state"] == "completed", done["error"]
    assert done["result"]["result_hash"] == optimize_gear(request)["result_hash"]
    assert call(site, "/api/jobs/"+job["id"]+"/export")[1] == done["result"]
    _, archive = call(site, "/api/jobs/"+job["id"]+"/export?archive=1")
    assert archive["request"] == request and archive["result"] == done["result"]
    assert call(site, "/api/import/archive", archive)[1]["value"] == archive
    archive["action"] = "class optimize"
    assert call(site, "/api/import/archive", archive)[0] == 400


def test_class_export_and_real_zip_import(site):
    _, req = call(site,"/api/examples/max-intelligence")
    _, job = call(site,"/api/jobs",{"action":"class optimize","request":req})
    final = finish(site,job["id"])
    candidate = final["result"]["candidates"][0]
    _, doc = call(site,"/api/jobs/"+job["id"]+"/export?class_id="+candidate["class_id"])
    assert doc == candidate["class_doc"]
    assert call(site,"/api/import/class",doc)[1]["value"]["create_legal"]
    blob = (Path(__file__).parent/"fixtures/character/export.zip").read_bytes()
    slots = call(site, "/api/import/slots", blob)[1]["value"]
    _, selected = call(site, "/api/import/character?slot="+str(slots[0]["slot"]), blob)
    assert selected["value"]["kind"] == "character"
    assert selected["value"]["schema_version"] == 2


def test_discovery_presets_and_export_of_selected_lifecycle_family(site):
    _, meta = call(site, "/api/meta")
    assert "early" in {row["id"] for row in meta["discovery_presets"]}
    _, practical = call(site, "/api/examples/discovery-early")
    assert practical["class_search"]["profile"] == "spellcaster_discovery_v1"
    assert call(site, "/api/examples/discovery-unknown")[0] == 404
    _, job = call(site, "/api/jobs", {"action":"build optimize", "source":{"example":"build-lifecycle"}})
    result = finish(site, job["id"])["result"]
    selected = result["candidates"][0]["family"]
    from urllib.parse import urlencode
    url = "/api/jobs/"+job["id"]+"/export?"
    status, document = call(site, url+urlencode({"family":selected}))
    assert status == 200 and document == meta["catalog"]["caster_classes"]["m1-breton-caster"]
    assert call(site, url+"family=unknown")[0] == 400
    assert call(site, url+"family=unknown&index=0")[0] == 400
    _, saved = call(site,"/api/library/item",{"job_id":job["id"],"label":"Paired casters"})
    saved_url = "/api/library/export?"+urlencode({"id":saved["items"][0]["id"],"family":selected})
    assert call(site,saved_url) == (200,document)


def test_discovery_incumbent_uses_one_budget(site, monkeypatch):
    from threading import Event
    from dfo_optimizer import workbench_jobs

    _, request = call(site, "/api/examples/discovery-early")
    released = Event()
    calls = []
    def execute(action, frozen, token, *, on_incumbent):
        calls.append(frozen)
        checked = {"kind":"lifecycle", "status":"best_found_bounded", "candidates":[{"validated":True}]}
        on_incumbent(checked)
        assert released.wait(5)
        return {**checked, "status":"cancelled" if token.cancelled() else "best_found_bounded"}

    monkeypatch.setattr(workbench_jobs,"execute",execute)
    try:
        _, job = call(site, "/api/jobs", {"action":"build optimize","request":request})
        partial = finish(site, job["id"], lambda r: r["incumbent"] is not None)
        assert partial["incumbent_request"] == request
        assert partial["progress"]["preview_nodes"] == partial["progress"]["preview_runs"] == 0
        call(site, "/api/jobs/"+job["id"]+"/cancel", {})
    finally:
        released.set()
    done = finish(site, job["id"])
    assert calls == [request] and done["state"] == "cancelled" and done["result"]["candidates"]


def test_upload_and_archive_preserve_exact_json_values(site):
    from dfo_optimizer.workbench_jobs import digest
    raw = b'{"large":9007199254740993,"weight":1.0}'
    _, uploaded = call(site, "/api/import/request", raw)
    identifier = uploaded["upload_id"]
    _, frozen = call(site, "/api/uploads/" + identifier)
    assert frozen["large"] == 9_007_199_254_740_993 and type(frozen["weight"]) is float
    _, job = call(site, "/api/jobs", {"action":"class validate","source":{"upload":identifier}})
    assert type(job["request"]["weight"]) is float and job["request_hash"] == digest(frozen)
    _, plan = call(site, "/api/jobs", {"action":"progression plan","source":{"example":"progression-tradeoffs"}})
    result = finish(site, plan["id"])["result"]
    _, archive = call(site, "/api/jobs/"+plan["id"]+"/export?archive=1")
    _, stored = call(site, "/api/library/item", {"job_id":plan["id"],"label":"First plan"})
    saved_id = stored["items"][0]["id"]
    assert call(site, "/api/library/export?id="+saved_id)[1] == result
    _, replay = call(site, "/api/jobs", {"action":"progression replay","source":{"library_result":saved_id}})
    assert finish(site, replay["id"])["result"]["valid"]
    # Both checks detect mixed identities even if the outer container checksum
    # is recomputed by an archive writer.
    for patch in ({"request_hash":"wrong"}, {"result":{**result,"ruleset_hash":"old"}}):
        mixed = {k:v for k,v in {**archive,**patch}.items() if k != "archive_sha256"}
        assert call(site, "/api/import/archive", {**mixed,"archive_sha256":digest(mixed)})[0] == 400


def test_path_isolation_and_ruleset_mismatch(site):
    code, error = call(site, "/api/jobs", {"action":"progression plan","request":{"start":{"character_file":"local.json"}}})
    assert code == 400 and "upload" in error["error"].lower()
    code, err = call(site, "/api/jobs", {"action":"gear optimize","request":{},"ruleset_hash":"old"})
    assert code == 409 and "ruleset" in err["error"].lower()
    assert call(site, "/api/meta", headers={"Host":"unrelated.invalid"})[0] == 403
    assert call(site, "/api/jobs", {},headers={"Origin":"https://unrelated.invalid"})[0] == 403
    assert call(site, "/api/examples/unknown")[0] == 404
    assert call(site, "/api/import/result", {"ruleset_hash":"old","result_hash":"x"})[1]["warnings"]
    for name in ("build-creation-to-cap","build-replan","progression-legacy-gap"):
        code, doc = call(site, "/api/examples/"+name)
        assert code == 200 and "_file\"" not in json.dumps(doc)


@pytest.mark.parametrize(("raw","expected"),[
    ({"kind":"spell_curve"}, "spell curve"),
    ({"kind":"encounter_result","mode":"evaluate"}, "encounter evaluate"),
    ({"kind":"encounter_result","mode":"optimize"}, "encounter optimize"),
])
def test_saved_standalone_results_keep_their_operation(site,raw,expected):
    _, receipt = call(site, "/api/import/result?save_as=test.json", raw)
    stored = call(site, "/api/library")[1]["items"][0]
    assert stored["id"] == receipt["saved_id"]
    assert stored["action"] == expected


def test_running_native_job_exposes_replayed_preview_and_keeps_it_on_cancel(site):
    request = {"exact":True,"top_k":1,"max_nodes":0,"wall_seconds":20,
               "skill_domains":[[22]]+[list(range(35)) for _ in range(11)]}
    _, job = call(site,"/api/jobs",{"action":"class optimize","request":request})
    partial = finish(site,job["id"],lambda r:r["incumbent"] is not None)
    assert partial["incumbent"]["validation"]["finalists_checked"] == 1
    assert partial["progress"]["preview_runs"] >= 1
    call(site,"/api/jobs/"+job["id"]+"/cancel",{})
    cancelled = finish(site,job["id"])
    assert cancelled["state"] == "cancelled"
    assert cancelled["incumbent"]["candidates"]
    assert cancelled["request"] == request


def test_library_survives_another_port_and_rejects_invalid_writes(site):
    directory = site.library.file.parent
    assert call(site, "/api/library")[1] == {"version":1,"items":[],"preferences":{}}
    assert not directory.exists()
    document = {"version":1,"items":[{"id":"local","title":"My Breton"}],"preferences":{"workspace":"gear"}}
    assert call(site, "/api/library", document) == (200,document)
    assert call(site, "/api/library", {**document,"items":[42]})[0] == 400
    with create_server(library_dir=directory) as reopened:
        assert reopened.server_port != site.server_port
        assert reopened.library.get() == document


@pytest.mark.parametrize(("action","sample","argv"), [
    ("class optimize","max-intelligence",["class","optimize"]),
    ("progression plan","progression-tradeoffs",["progression","plan"]),
    ("spell evaluate","spell-fixed",["evaluate"]),
    ("spellbook optimize","spellbook-auto",["spellbook","optimize"]),
    ("build optimize","build-lifecycle",["build","optimize"]),
    ("encounter optimize","encounter-pack",["encounter","optimize"]),
    ("gear optimize","gear-owned",["gear","optimize"]),
    ("gear optimize","gear-bis",["gear","optimize"]),
])
def test_http_results_match_cli_and_replay(site,tmp_path,action,sample,argv):
    from dfo_optimizer.cli import main
    _, request = call(site,"/api/examples/"+sample)
    _, job = call(site,"/api/jobs",{"action":action, "request":request})
    final = finish(site,job["id"])
    assert final["state"] == "completed", final["error"]
    input_file, result_file = tmp_path / "request.json", tmp_path / "result.json"
    input_file.write_text(json.dumps(request),encoding="utf-8")
    assert main([*argv,"--request",str(input_file),"--output",str(result_file)]) == 0
    cli_result = json.loads(result_file.read_bytes())
    assert final["result"]["result_hash"] == cli_result["result_hash"]
    if action in ("build optimize","progression plan","encounter optimize"):
        _, replay = call(site,"/api/jobs",{"action":action.split()[0]+" replay", "request":cli_result})
        assert finish(site,replay["id"])["state"] == "completed"


def test_request_validation_and_bounded_modes(site):
    def submit(**kwargs):
        return call(site,"/api/jobs",kwargs)
    _, result = submit(action="class optimize",request={"max_nodes":3},mode="quick")
    assert result["request"] == {"max_nodes":3,"wall_seconds":1}
    assert finish(site,result["id"])["result"]["counters"]["nodes"] <= 3
    assert submit(action="unknown",request={})[0] == 400
    assert submit(action="class optimize",request={},mode="invented")[0] == 400
    assert submit(action="class optimize",request={},extra=True)[0] == 400
    assert call(site,"/api/import/request",b'{"x":1,"x":2}')[0] == 400
    assert call(site,"/api/import/slots",b"invalid",headers={"Content-Type":"text/plain"})[0] == 415
    assert call(site,"/api/jobs/"+"a"*32)[0] == 404
    _, job = submit(action="spell evaluate",request={})
    failed = finish(site,job["id"])
    assert failed["state"] == "failed" and failed["error"]
    assert call(site,"/api/jobs/"+job["id"]+"/export")[0] == 400


def test_job_elapsed_uses_the_high_resolution_clock(monkeypatch):
    from dfo_optimizer import workbench_jobs
    job = workbench_jobs.Job("class optimize","quick",{},"request","rules",created=1.0)
    monkeypatch.setattr(workbench_jobs,"perf_counter",lambda:1.00035)
    assert job.snapshot()["progress"]["elapsed_seconds"] == pytest.approx(.00035)

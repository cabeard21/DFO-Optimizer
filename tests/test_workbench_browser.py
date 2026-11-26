"""Real Chromium acceptance. Enable using DFO_BROWSER_TEST=1 with Playwright installed."""
import json
import os
from pathlib import Path
import platform
import re
from threading import Thread

import pytest

from dfo_optimizer.workbench import create_server


pytestmark = pytest.mark.skipif(os.environ.get("DFO_BROWSER_TEST") != "1",
                                reason="explicit installed-wheel Chromium lane")
LONG = {"exact":True,"top_k":1,"max_nodes":0,"wall_seconds":40,
        "skill_domains":[[22]]+[list(range(35)) for _ in range(11)]}


@pytest.fixture(scope="module")
def observations():
    entries = []
    yield entries
    destination = os.environ.get("DFO_BROWSER_REPORT")
    if destination:
        from dfo_optimizer import workbench
        from dfo_optimizer.ruleset import load_ruleset
        report = {"platform":platform.platform(),"python":platform.python_version(),"service_module":workbench.__file__,
                  "ruleset_hash":load_ruleset()["content_hash"],"observations":entries}
        path = Path(destination)
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(json.dumps(report,indent=2)+"\n",encoding="utf-8")


def observe_search(page):
    page.evaluate("""() => {
      const times = window.dfoSearchTiming = {start:null,preview_ms:null,final_ms:null};
      document.getElementById("content").dataset.timingComplete="false";
      function click(event){
        if (!event.target.closest("button")?.textContent.startsWith("Run ")) return;
        times.start=performance.now(); document.removeEventListener("click",click,true);
      }
      document.addEventListener("click",click,true);
      const changes=new MutationObserver(()=>{
        if(times.start===null)return;
        const area=document.getElementById("result-area");
        if(times.preview_ms===null && area?.textContent.includes("First validated result."))
          times.preview_ms=performance.now()-times.start;
        if(["completed","failed","cancelled"].includes(area?.querySelector(".state")?.textContent)){
          times.final_ms=performance.now()-times.start; changes.disconnect();
          document.getElementById("content").dataset.timingComplete="true";
        }
      });
      changes.observe(document.getElementById("content"),{subtree:true,childList:true});
    }""")


def record(entries,page,name,result):
    from playwright.sync_api import expect
    expect(page.locator("#content")).to_have_attribute("data-timing-complete","true")
    timings = page.evaluate("window.dfoSearchTiming")
    entries.append({"workload":name,"visible_preview_ms":timings["preview_ms"],"visible_final_ms":timings["final_ms"],
                    "result_hash":result.get("result_hash"),"status":result.get("status"),
                    "counters":result.get("counters"),"service_timings":result.get("timings"),
                    "service_elapsed_seconds":result.get("elapsed_seconds")})


@pytest.fixture(scope="module")
def browser():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        opts = {"executable_path":os.environ["DFO_BROWSER_EXECUTABLE"]} if "DFO_BROWSER_EXECUTABLE" in os.environ else {}
        instance = p.chromium.launch(headless=True,**opts)
        try:
            yield instance
        finally:
            instance.close()


@pytest.fixture
def desktop(browser,tmp_path):
    from playwright.sync_api import expect
    with create_server(library_dir=tmp_path/"library") as server:
        worker = Thread(target=server.serve_forever,kwargs={"poll_interval":.03})
        worker.start()
        context = browser.new_context(accept_downloads=True)
        page = context.new_page()
        page.set_default_timeout(12_000)
        external = []
        errors = []
        page.on("pageerror",lambda err:errors.append(str(err)))
        page.on("request",lambda req:external.append(req.url) if req.url.startswith(("http:","https:"))
                and not req.url.startswith(server.url+"/") else None)
        try:
            page.goto(server.url)
            expect(page.get_by_role("button",name="Recommend My First Spellcaster")).to_be_visible()
            yield page, server.url
            assert errors == []
            assert external == []
        finally:
            context.close()
            server.shutdown()
            worker.join()
        assert errors == [], "Unhandled browser errors"
        assert external == [], "The workbench contacted an external origin"


def download(page,button):
    with page.expect_download() as event:
        page.get_by_role("button",name=button,exact=True).click()
    return json.loads(event.value.path().read_bytes())


def upload(page,button,file):
    with page.expect_file_chooser() as event:
        page.get_by_role("button",name=button,exact=True).click()
    event.value.set_files(file)


def json_file(name,value):
    return {"name":name,"mimeType":"application/json","buffer":json.dumps(value).encode()}


def test_recommend_first_spellcaster_download_and_reopen(desktop):
    from playwright.sync_api import expect
    page, url = desktop
    expect(page.get_by_label("Search thoroughness")).to_have_value("standard")
    advancement = page.get_by_label("Require 0.30× advancement")
    expect(advancement).not_to_be_checked()
    advancement.check()
    page.get_by_label("Search thoroughness").select_option("quick")
    with page.expect_response(lambda r: r.url == url+"/api/jobs" and r.request.method == "POST") as submitted:
        page.get_by_role("button", name="Recommend My First Spellcaster").click()
    identifier = submitted.value.json()["id"]
    area = page.locator(f'#result-area[data-job-id="{identifier}"]')
    expect(area).to_have_attribute("data-state", re.compile("completed|failed|cancelled"), timeout=300_000)
    assert area.get_attribute("data-state") == "completed", area.inner_text()
    result = page.request.get(url+"/api/jobs/"+identifier+"/export").json()
    lead = result["recommendation"]
    assert result["frozen_request"]["require_fast_advancement"]
    assert lead["metrics"]["advancement_multiplier"] == 0.30
    assert all(row["permanent"]["advancement_multiplier"] == 0.30 for row in result["comparisons"])
    expect(area.get_by_role("heading", name="Your creation checklist")).to_be_visible()
    expect(area.get_by_text("Choose your race", exact=True)).to_be_visible()
    with page.expect_download() as event:
        area.get_by_role("button", name="Download game class").click()
    assert event.value.suggested_filename.endswith(".dfclass.json")
    assert json.loads(event.value.path().read_bytes()) == lead["class"]
    with page.expect_download() as event:
        area.get_by_role("button", name="Download checklist").click()
    assert event.value.path().read_text(encoding="utf-8") == lead["guide"]["text"]
    # Intercept only the native print dialog, then inspect the exact document sent to print.
    page.evaluate("window.print=()=>{}")
    area.get_by_role("button", name="Print checklist").click()
    page.emulate_media(media="print")
    expect(page.locator("#print-checklist")).to_be_visible()
    expect(page.locator("#navigation")).to_be_hidden()
    page.evaluate("window.dispatchEvent(new Event('afterprint'))")
    page.emulate_media(media="screen")
    if result["alternatives"]:
        area.get_by_label("View a build").select_option("1")
        alternate=result["alternatives"][0]
        assert download(page,"Download game class") == alternate["class"]
        with page.expect_download() as selected:
            area.get_by_role("button",name="Download checklist").click()
        assert selected.value.path().read_text(encoding="utf-8") == alternate["guide"]["text"]
    if result["sensitivity"]:
        expect(area.get_by_role("heading",name="How the choice changes")).to_be_visible()
    area.get_by_role("button", name="Replay result").click()
    expect(page.get_by_role("dialog").get_by_text("verified",exact=True)).to_be_visible(timeout=180_000)
    page.get_by_role("button", name="Close dialog").click()
    area.get_by_role("button", name="Save to library").click()
    page.get_by_role("button", name="Open library").click()
    page.get_by_role("button", name="Inspect").first.click()
    expect(page.get_by_role("dialog").get_by_role("button", name="Download checklist")).to_be_visible()


def test_guided_spellcaster_discovery_and_class_comparison(desktop):
    from playwright.sync_api import expect
    page, url = desktop
    def discover():
        with page.expect_response(lambda r:r.url==url+"/api/jobs" and r.request.method=="POST") as submitted:
            page.get_by_role("button", name="Discover builds", exact=True).click()
        identifier = submitted.value.json()["id"]
        result_area = page.locator(f'#result-area[data-job-id="{identifier}"]')
        expect(result_area).to_have_attribute("data-state", re.compile("completed|failed|cancelled"),timeout=150_000)
        assert result_area.get_attribute("data-state") == "completed", page.locator("#status").inner_text()
    page.get_by_role("link", name="Discover Spellcaster Build", exact=True).click()
    expect(page.get_by_label("Optimization objective")).to_be_visible()
    page.get_by_label("Scenario preset").select_option("discovery-theoretical_endgame")
    expect(page.get_by_role("status")).to_have_text("Loaded discovery-theoretical_endgame.")
    page.get_by_label("Scenario preset").select_option("discovery-early")
    expect(page.get_by_role("status")).to_have_text("Loaded discovery-early.")
    original = download(page, "Export request")
    effort = page.get_by_label("Search thoroughness")
    expect(effort).to_have_value("standard")
    effort.select_option("quick")
    quick = download(page,"Export request")
    assert quick["search"]["wall_seconds"] == 30 and quick["search"]["max_nodes"] < original["search"]["max_nodes"]
    assert quick["class_search"]["top_k"] < original["class_search"]["top_k"]
    assert quick["class_admission_strategy"] == original["class_admission_strategy"]
    effort.select_option("thorough")
    thorough = download(page,"Export request")
    assert thorough["search"]["wall_seconds"] == 600 and thorough["search"]["max_nodes"] > original["search"]["max_nodes"]
    assert thorough["class_search"]["top_k"] > original["class_search"]["top_k"]
    effort.select_option("standard")
    assert download(page,"Export request") == original
    page.get_by_text("Class decisions", exact=True).click()
    page.get_by_label("Required class health").fill("30")
    page.get_by_label("Required class health").press("Tab")
    discover()
    result = download(page, "Export result")
    assert result["kind"] == "lifecycle" and result["candidates"], result.get("gaps")
    doc = download(page, "Export game class")
    assert page.request.post(url+"/api/import/class", data=doc).json()["value"]["create_legal"]
    archive = download(page, "Export archive")
    assert archive["request"]["class_search"]["profile"] == "spellcaster_discovery_v1"
    page.get_by_role("button", name="Replay result", exact=True).click()
    page.wait_for_function("""() => document.querySelector('#status[data-error=true]') ||
        document.querySelector('#drawer[open] #dialog-title')?.textContent==='Replay verification'""", timeout=120_000)
    assert page.locator("#status").get_attribute("data-error") != "true", page.locator("#status").inner_text()
    page.get_by_role("button", name="Close dialog").click()
    upload(page, "Compare a game class", json_file("discovered.json", doc))
    page.get_by_label("Race for imported class").select_option(label="Breton")
    page.get_by_role("button", name="Add comparison", exact=True).click()
    page.get_by_text("Progression assumptions", exact=True).click()
    page.get_by_label("Hypothetical gold cache after birth").fill("165")
    page.get_by_label("Hypothetical gold cache after birth").press("Tab")
    frozen = download(page, "Export request")
    assert frozen["progression"]["itinerary"]["cache_gold"] == 165
    assert any(f.get("start", {}).get("class") == doc for f in frozen["families"])
    page.get_by_text("Comparison classes", exact=True).click()
    page.get_by_label("High Elf caster", exact=True).check()
    page.get_by_label("Optimization objective").select_option("damage_per_sp")
    discover()
    result_area = page.locator("#result-area")
    imported = next(f["id"] for f in frozen["families"] if f.get("start", {}).get("class")==doc)
    comparison_row = result_area.get_by_role("row").filter(has_text=imported)
    expect(comparison_row.first).to_be_visible(timeout=150_000)
    expect(result_area.get_by_text("comparison-high-elf-caster", exact=True).first).to_be_visible()
    comparison_row.first.get_by_role("button", name=re.compile("^Seed ")).first.click()
    assert download(page, "Export game class") == doc


def test_navigation_search_export_library_and_mismatch(desktop,observations):
    from playwright.sync_api import expect
    from dfo_optimizer.search import optimize_classes
    page, url = desktop
    for name in ("Progression","Spell Lab","Gear & Loadouts","Compare Builds","Data & Diagnostics","Character Creator"):
        page.get_by_role("link",name=name,exact=True).click()
        expect(page.get_by_role("heading",name=name,exact=True,level=1)).to_be_visible()
    expected = optimize_classes(page.request.get(url+"/api/examples/max-intelligence").json())
    observe_search(page)
    page.get_by_role("button",name="Run class search").click()
    result = download(page,"Export result")
    record(observations,page,"class",result)
    assert result["result_hash"] == expected["result_hash"]
    assert download(page,"Export game class") == result["candidates"][0]["class_doc"]
    archive = download(page,"Export archive")
    page.get_by_role("button",name="Open library").click()
    upload(page,"Open archive",json_file("caster-archive.json",archive))
    expect(page.get_by_text("caster-archive.json",exact=True)).to_be_visible()
    page.get_by_role("button",name="Inspect").first.click()
    expect(page.get_by_role("button",name="Open frozen request")).to_be_visible()
    page.get_by_role("button",name="Close dialog").click()
    page.get_by_role("button",name="Open library").click()
    upload(page,"Open result",json_file("old.json",{**result,"ruleset_hash":"old","result_hash":"old"}))
    expect(page.get_by_text("old.json",exact=True)).to_be_visible()
    page.locator(".library-item").filter(has_text="old.json").get_by_role("button",name="Inspect").click()
    expect(page.get_by_text("This result uses a different ruleset.",exact=False)).to_be_visible()
    page.get_by_role("button",name="Close dialog").click()
    page.reload()
    page.get_by_role("link",name="Compare Builds").click()
    expect(page.get_by_text("Re-run both with matching inputs",exact=False)).to_be_visible()
    # The exact same saved class and frozen inputs can be inspected and compared.
    page.get_by_role("combobox",name="First search",exact=True).select_option(label="caster-archive.json")
    page.get_by_role("combobox",name="Second search",exact=True).select_option(label="caster-archive.json")
    expect(page.get_by_role("heading",name="Frontier comparison")).to_be_visible()


@pytest.mark.parametrize(("operation","example"),[
    ("Best owned","gear-owned"),("Budget upgrades","gear-budget"),("Theoretical BIS","gear-bis")])
def test_gear_modes_match_the_service(desktop,operation,example,observations):
    from playwright.sync_api import expect
    from dfo_optimizer.gear import optimize_gear
    page,url = desktop
    page.get_by_role("link",name="Gear & Loadouts").click()
    control = page.get_by_role("combobox",name="Operation",exact=True)
    if control.locator("option:checked").text_content() != operation:
        control.select_option(label=operation)
    expect(page.get_by_role("combobox",name="Example",exact=True)).to_have_value(example)
    expect(page.get_by_role("status")).to_have_text("Loaded "+example+".")
    expected = optimize_gear(page.request.get(url+"/api/examples/"+example).json())
    observe_search(page)
    page.get_by_role("button",name="Run gear search").click()
    result = download(page,"Export result")
    assert result["result_hash"] == expected["result_hash"]
    record(observations,page,example,result)


def test_progression_replay_and_game_export_import(desktop):
    from playwright.sync_api import expect
    page,url = desktop
    page.get_by_role("link",name="Progression",exact=True).click()
    page.get_by_role("button",name="Run plan training").click()
    page.get_by_role("button",name="Replay result").click()
    expect(page.get_by_role("heading",name="Replay verification")).to_be_visible()
    page.get_by_role("button",name="Close dialog").click()
    path = Path(__file__).parent/"fixtures/character/export.zip"
    upload(page,"Import character",path)
    slots = page.request.post(url+"/api/import/slots?format=zip",data=path.read_bytes(),
                              headers={"Content-Type":"application/octet-stream"}).json()["value"]
    if len(slots)>1:
        page.get_by_role("button",name=f"Slot {slots[0]['slot']} ·",exact=False).click()
    expect(page.get_by_role("status")).to_contain_text("Saved")
    page.get_by_text("Full request JSON",exact=True).click()
    imported = json.loads(page.get_by_label("Frozen request inputs").input_value())
    assert imported["start"]["character"]["kind"] == "character"


def test_edit_uploaded_request_saved_character_and_reopened_archive(desktop):
    from playwright.sync_api import expect
    from dfo_optimizer.character import normalize_character
    from dfo_optimizer.workbench_jobs import digest

    page, url = desktop
    request = {**page.request.get(url+"/api/examples/spell-fixed").json(), "price_factor":1.0}
    snapshot = normalize_character({
        "kind":"character", "schema_version":1,
        "caster":{**request["caster"], **dict.fromkeys(("focus_pct","power_pct","pierce","cast_speed_pct"),0)},
        "observations":{"external_sequence":9_007_199_254_740_993, "weight":2.0},
    })
    page.get_by_role("link",name="Spell Lab").click()
    page.get_by_label("Operation").select_option(label="Evaluate spell")
    expect(page.get_by_role("button",name="Run evaluate spell")).to_be_visible()
    upload(page,"Open request",json_file("authored.json",request))
    expect(page.get_by_label("Example")).to_have_value("authored.json")
    page.get_by_role("button",name="Open library").click()
    with page.expect_file_chooser() as choice:
        page.get_by_role("dialog").get_by_role("button",name="Import character").click()
    choice.value.set_files(json_file("observed.json",snapshot))
    page.get_by_role("button",name="Use character").click()
    page.get_by_label("Target HP").fill("62")
    page.get_by_label("Target HP").press("Tab")
    expected = {k:v for k,v in request.items() if k != "caster"}
    expected.update(character=snapshot,target={**request["target"],"hp":62})
    assert digest(download(page,"Export request")) == digest(expected)
    page.get_by_role("button",name="Run evaluate spell").click()
    archive = download(page,"Export archive")
    assert archive["request_hash"] == digest(expected)
    page.get_by_role("button",name="Open library").click()
    upload(page,"Open archive",json_file("authored-archive.json",archive))
    page.locator(".library-item").filter(has_text="authored-archive.json").get_by_role("button",name="Inspect").click()
    page.get_by_role("button",name="Open frozen request").click()
    page.get_by_text("Full request JSON",exact=True).click()
    editor = page.get_by_label("Frozen request inputs")
    raw = editor.input_value()
    assert '"price_factor": 1.0' in raw and '"external_sequence": 9007199254740993' in raw
    editor.fill(raw.replace('"hp": 62','"hp": 63'))
    editor.press("Tab")
    amended = {**expected,"target":{**expected["target"],"hp":63}}
    assert digest(download(page,"Export request")) == digest(amended)


def test_cancel_before_feasibility_and_after_replayed_incumbent(desktop,observations):
    from playwright.sync_api import expect
    page,url = desktop
    page.get_by_role("link", name="Character Creator", exact=True).click()
    # A real native worker occupies the only slot, making pre-feasible
    # cancellation of the visible job independent of host execution speed.
    running = page.request.post(url+"/api/jobs",data={"action":"class optimize","request":LONG}).json()
    try:
        page.get_by_role("button",name="Run class search").click()
        page.get_by_role("button",name="Cancel search").click()
        expect(page.get_by_role("status")).to_have_text("cancelled")
        expect(page.get_by_role("button",name="Export result")).to_have_count(0)
    finally:
        page.request.post(url+"/api/jobs/"+running["id"]+"/cancel",data={})
    upload(page,"Open request",json_file("long.json",LONG))
    page.get_by_text("Full request JSON",exact=True).click()
    expect(page.get_by_label("Frozen request inputs")).to_have_value(re.compile('"wall_seconds": 40'))
    observe_search(page)
    page.get_by_role("button",name="Run class search").click()
    expect(page.get_by_text("First validated result.",exact=False)).to_be_visible(timeout=20_000)
    editor = page.get_by_label("Frozen request inputs")
    editor.fill(json.dumps({**LONG,"top_k":2}))
    editor.press("Tab")
    expect(page.get_by_text("Inputs have changed since this search was submitted.")).to_be_visible()
    page.get_by_role("button",name="Cancel search").click()
    expect(page.get_by_role("status")).to_have_text("cancelled")
    expect(page.get_by_role("heading",name="Selected option")).to_be_visible()
    if page.get_by_role("button",name="Export archive",exact=True).count():
        frozen = download(page,"Export archive")
    else:
        frozen = download(page,"Export validated preview")
    assert frozen["request"]["top_k"] == LONG["top_k"] == 1
    assert json.loads(editor.input_value())["top_k"] == 2
    result = frozen["result"]
    record(observations,page,"class-cancelled",result)
    assert page.evaluate("window.dfoSearchTiming.preview_ms") is not None

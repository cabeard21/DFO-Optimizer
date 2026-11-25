"""Run the same numeric-preserving workbench edit adapter as the browser."""
import base64
import json
from importlib.resources import files
import subprocess

import pytest


@pytest.mark.parametrize("modern", [True, False])
def test_node_admission_after_edit_preserves_exact_numbers_and_frozen_subtrees(modern):
    asset = files("dfo_optimizer").joinpath("data/workbench/exact-json.js").read_bytes()
    module = "data:text/javascript;base64," + base64.b64encode(asset).decode("ascii")
    script = """
        import {parseDocument, stringifyDocument, retainNumbers} from MODULE;
        const parse=JSON.parse;
        if (!MODERN) JSON.parse=(s,reviver)=>parse(s,reviver&&function(k,v){return reviver.call(this,k,v);});
        const req=parseDocument('{"wide":9007199254740993,"dec":1.0,"n":1,"rows":[2.0,9007199254740995],"arg":"1.0","goal":0}');
        const archive=parseDocument('{"items":[{"value":{"id":9007199254740997,"n":3.0,"observed":2.5}}]}');
        const attached=retainNumbers(req,{...req,character:archive.items[0].value});
        const edited=retainNumbers(attached,{...attached,rows:[...attached.rows],goal:3});
        const override=parseDocument('{"id":9007199254740996,"n":3,"observed":2.5}');
        const amended=retainNumbers(edited,{...edited,character:override});
        const first=parseDocument('{"source":9007199254740993,"context":{"second":2.0,"first":1}}');
        const same=parseDocument('{"context":{"first":1,"second":2.0},"source":9007199254740993}');
        const different=parseDocument('{"context":{"first":1,"second":2},"source":9007199254740992}');
        const key=r=>stringifyDocument(retainNumbers(r,{context:r.context,source:r.source}),0,true);
        if(key(first)!==key(same)||key(first)===key(different))throw Error("Invalid comparison of frozen inputs");
        if(!key(first).includes('9007199254740993'))throw Error("Lost projected integer");
        console.log(stringifyDocument({request:edited,amended},2));
    """.replace("MODULE",json.dumps(module)).replace("MODERN","true" if modern else "false")
    out=subprocess.run(["node","--input-type=module","--eval",script],capture_output=True,text=True,check=True)
    result=json.loads(out.stdout)
    request=result["request"]
    assert request["wide"]==9007199254740993 and type(request["dec"]) is float and type(request["n"]) is int
    assert type(request["rows"][0]) is float and request["rows"][1]==9007199254740995
    assert request["goal"]==3 and request["arg"]=="1.0"
    assert request["character"]["id"]==9007199254740997 and type(request["character"]["n"]) is float
    assert result["amended"]["character"]["id"]==9007199254740996
    assert type(result["amended"]["character"]["n"]) is int

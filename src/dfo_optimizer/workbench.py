"""Local-only HTTP workbench for the installed DFO optimizer."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
import json
import re
from threading import Lock
from urllib.parse import parse_qsl, urlsplit
import webbrowser

from .character_files import MAX_SAVE_BYTES, MAX_ZIP_BYTES, read_json
from .firmament_profiles import FirmamentProfiles, ProfileChanged, public_profile, search_request
from .ruleset import DATA, load_ruleset
from .workbench_files import Library, default_library, export_job, imported, library_item, upload_save
from .workbench_jobs import Jobs, QueueFull, RulesetMismatch, digest
from .workbench_services import metadata, read_example


ASSETS = DATA / "workbench"
MEDIA = {".html":"text/html; charset=utf-8", ".js":"text/javascript; charset=utf-8",
         ".css":"text/css; charset=utf-8", ".svg":"image/svg+xml", ".png":"image/png",
         ".webp":"image/webp", ".woff2":"font/woff2", ".woff":"font/woff", ".ico":"image/x-icon"}
JOB_PATH = re.compile(r"/api/jobs/([0-9a-f]{32})(?:/(export|cancel))?")


class HttpIssue(ValueError):
    def __init__(self, status, message):
        self.status = status
        super().__init__(message)


class WorkbenchServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, port, library_dir):
        super().__init__(("127.0.0.1",port), Handler)
        self.url = f"http://127.0.0.1:{self.server_port}"
        self.jobs = Jobs(load_ruleset()["content_hash"])
        self.library = Library(library_dir)
        self.firmament_profiles = FirmamentProfiles(library_dir)
        self.uploads = {}
        self.upload_lock = Lock()

    def remember_request(self, value):
        identifier = digest(value)
        # Keep sufficient raw JSON for recently opened requests. A browser
        # round trip through Number cannot preserve all int64 values.
        encoded = json.dumps(value,separators=(",",":"),ensure_ascii=False,allow_nan=False).encode()
        with self.upload_lock:
            self.uploads.pop(identifier,None)
            while self.uploads and (len(self.uploads) >= 16 or
                    sum(len(raw) for raw in self.uploads.values())+len(encoded) > MAX_SAVE_BYTES):
                del self.uploads[next(iter(self.uploads))]
            self.uploads[identifier] = encoded
        return identifier

    def request_upload(self, identifier):
        with self.upload_lock:
            payload = self.uploads[identifier]
        return json.loads(payload)

    def get_request(self):
        sock, address = super().get_request()
        sock.settimeout(30)
        return sock,address

    def server_close(self):
        if hasattr(self,"jobs"):
            self.jobs.close()
        super().server_close()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        # Uploaded characters and job identifiers belong to the local session.
        pass

    def _reply(self, code, value, *, media="application/json", filename=None):
        data = value if isinstance(value,bytes) else json.dumps(value,ensure_ascii=True,allow_nan=False).encode()
        self.send_response(code)
        self.send_header("Content-Type",media)
        self.send_header("Content-Length",str(len(data)))
        self.send_header("Cache-Control","no-store")
        self.send_header("X-Content-Type-Options","nosniff")
        self.send_header("X-Frame-Options","DENY")
        self.send_header("Referrer-Policy","no-referrer")
        self.send_header("Content-Security-Policy","default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
                         "img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
        if filename:
            self.send_header("Content-Disposition",f'attachment; filename="{filename}"')
        self.end_headers()
        self.wfile.write(data)

    def _length(self, limit):
        values = self.headers.get_all("Content-Length",[])
        if len(values) != 1 or not re.fullmatch(r"[0-9]{1,10}",values[0]) or "Transfer-Encoding" in self.headers:
            raise HttpIssue(400,"A single Content-Length is required")
        length = int(values[0])
        if length > limit:
            raise HttpIssue(413,"Upload exceeds the size limit")
        return length

    def _json(self):
        length = self._length(MAX_SAVE_BYTES)
        data = self.rfile.read(length)
        if len(data) != length:
            raise HttpIssue(400,"Incomplete request")
        return read_json(BytesIO(data),MAX_SAVE_BYTES,"request")

    def _guard(self):
        host = self.server.url.removeprefix("http://")
        if self.headers.get_all("Host",[]) != [host]:
            raise HttpIssue(403,"Use the local workbench address")
        if self.headers.get_all("Origin",[]) not in ([],[self.server.url]):
            raise HttpIssue(403,"Use the workbench from its own window")
        if self.headers.get("Sec-Fetch-Site") == "cross-site":
            raise HttpIssue(403,"Cross-site requests are disabled")
        url = urlsplit(self.path)
        if url.scheme or url.netloc or not self.path.startswith("/") or self.path.startswith("//"):
            raise HttpIssue(400,"Expected a local workbench path")
        params = parse_qsl(url.query,keep_blank_values=True,max_num_fields=10)
        if len(dict(params)) != len(params):
            raise HttpIssue(400,"Repeated query parameter")
        return url.path,dict(params)

    def _get(self,path,query):
        if path == "/api/meta":
            return self._reply(200,metadata())
        if path == "/api/firmament/catalog":
            from .firmament import firmament_catalog
            return self._reply(200, firmament_catalog())
        if path == "/api/firmament/profiles":
            profiles = self.server.firmament_profiles.get()["items"]
            return self._reply(200, {"profiles": [public_profile(p) for p in profiles]})
        if path == "/api/firmament/profile":
            return self._reply(200, self.server.firmament_profiles.item(query.get("id")))
        if path == "/api/library":
            return self._reply(200,self.server.library.get())
        if path == "/api/library/export":
            item = self.server.library.item(query.get("id"))
            if "family" in query:
                if (set(query) - {"id", "family", "checklist"} or
                        item.get("ruleset_hash") != self.server.jobs.ruleset_hash):
                    raise ValueError("Choose a family from a build saved with the installed ruleset")
                value,name = export_job(item,{k:v for k,v in query.items() if k != "id"})
                return self._reply(200,value,filename=name,media="text/plain; charset=utf-8" if name.endswith(".txt") else "application/json")
            key = "request" if query.get("request") == "1" else "result"
            if not isinstance(item.get(key),dict):
                raise ValueError("This item has no "+key)
            return self._reply(200,item[key],filename="dfo-"+key+".json")
        if path.startswith("/api/examples/"):
            return self._reply(200,read_example(path.removeprefix("/api/examples/")),
                               filename="dfo-request.json" if query.get("download") == "1" else None)
        if path.startswith("/api/uploads/"):
            return self._reply(200,self.server.request_upload(path.removeprefix("/api/uploads/")),filename="dfo-request.json")
        job = JOB_PATH.fullmatch(path)
        if job:
            value = self.server.jobs.get(job[1])
            if job[2] == "export":
                value,name = export_job(value,query)
                return self._reply(200,value,filename=name,media="text/plain; charset=utf-8" if name.endswith(".txt") else "application/json")
            if job[2] is None:
                return self._reply(200,value)
        name = "index.html" if path == "/" else path[1:]
        if not re.fullmatch(r"[A-Za-z0-9_-]+(?:/[A-Za-z0-9_-]+)*/?[A-Za-z0-9_.-]*\.[A-Za-z0-9]+",name):
            raise HttpIssue(404,"Unknown workbench resource")
        target = (ASSETS/name).resolve()
        if not target.is_relative_to(ASSETS.resolve()) or target.suffix not in MEDIA or not target.is_file():
            raise HttpIssue(404,"Unknown workbench resource")
        return self._reply(200,target.read_bytes(),media=MEDIA[target.suffix])

    def _post(self,path,query):
        kind = path.removeprefix("/api/import/") if path.startswith("/api/import/") else None
        media = self.headers.get("Content-Type","").partition(";")[0].strip().lower()
        if media != "application/json" and not (kind and media == "application/octet-stream"):
            raise HttpIssue(415,"Use application/json or a binary file upload")
        if kind in ("slots","character"):
            if set(query) - {"slot","format","save_as"} or query.get("format") not in (None,"json","zip"):
                raise ValueError("Invalid character upload options")
            slot = int(query["slot"]) if "slot" in query else None
            value = upload_save(self.rfile,self._length(MAX_ZIP_BYTES),kind,slot,query.get("format")=="zip")
            return self._import(kind,value,query)
        data = self._json()
        if not isinstance(data, dict):
            raise ValueError("Expected a JSON object")
        if path == "/api/firmament/profile":
            upload = data.pop("character_upload", None)
            if upload is not None and not isinstance(upload, str):
                raise ValueError("Choose an imported character")
            character = self.server.request_upload(upload) if upload is not None else None
            return self._reply(200, public_profile(self.server.firmament_profiles.update(data, character=character)))
        if path == "/api/firmament/adopt":
            return self._reply(200, public_profile(self._adopt_firmament(data)))
        if path == "/api/jobs":
            # JavaScript numbers cannot preserve all JSON integer widths or
            # the distinction between integral floats and integers. Replay and
            # unedited inputs select the authoritative server-side document.
            if "source" in data:
                data = self._source_job(data)
            if "firmament_profile" in data:
                data = self._firmament_job(data)
            return self._reply(202,self.server.jobs.submit(data))
        if path == "/api/library":
            return self._reply(200,self.server.library.save(data))
        if path == "/api/library/item":
            if "job_id" in data:
                job = self.server.jobs.get(data["job_id"])
                archive, _ = export_job(job,{"archive":"1"})
                data = {"item":library_item("archive",archive,data.get("label")),
                        "preferences":data.get("preferences",{})}
            return self._reply(200,self.server.library.store_item(data))
        if kind:
            return self._import(kind,data,query)
        job = JOB_PATH.fullmatch(path)
        if job and job[2] == "cancel":
            return self._reply(200,self.server.jobs.cancel(job[1]))
        raise HttpIssue(404,"Unknown workbench resource")

    def _import(self,kind,value,query):
        response = imported(kind,value,self.server.jobs.ruleset_hash)
        if kind == "request":
            response["upload_id"] = self.server.remember_request(value)
        if kind == "character":
            response["upload_id"] = self.server.remember_request(response["value"])
        if "save_as" in query:
            item = library_item(kind,response["value"],query["save_as"])
            self.server.library.store_item({"item":item})
            response["saved_id"] = item["id"]
        return self._reply(200,response)

    def _firmament_job(self, data):
        selector = data.pop("firmament_profile")
        if (not isinstance(selector, dict) or set(selector) != {"id", "revision"} or
                not isinstance(selector["id"], str) or type(selector["revision"]) is not int):
            raise ValueError("Select a Firmament profile and revision")
        profile = self.server.firmament_profiles.item(selector["id"])
        if profile["revision"] != selector["revision"]:
            raise ProfileChanged("Firmament profile changed. Reload it and try again.")
        frozen = search_request(profile)
        from .firmament import firmament_catalog
        catalog_hash = firmament_catalog()["content_hash"]
        if data.get("action") == "firmament optimize" and "request" not in data:
            return {**data, "request": {**frozen, "catalog_hash": catalog_hash,
                                       "ruleset_hash": self.server.jobs.ruleset_hash}}
        request = data.get("request")
        if (data.get("action") not in {"gear optimize", "gear evaluate"} or
                not isinstance(request, dict) or "firmament_projection" in request or "encounter" in request):
            raise ValueError("Attach a Firmament profile to a standard Gear request")
        character = request.get("character")
        if not isinstance(character, dict) or character.get("snapshot_hash") != profile["character_hash"]:
            raise ValueError("Use the same character snapshot in Gear and Firmament")
        fields = ("tree", "stars", "craft", "profile_id", "revision")
        projection = {**{key: frozen[key] for key in fields}, "snapshot_hash": profile["character_hash"],
                      "ruleset_hash": self.server.jobs.ruleset_hash, "catalog_hash": catalog_hash}
        return {**data, "request": {**request, "character": frozen["character"],
                                   "firmament_projection": projection}}

    def _adopt_firmament(self, data):
        if set(data) != {"id", "revision", "job_id", "candidate_index"}:
            raise ValueError("Select a completed Firmament recommendation")
        key, revision, job_id, index = (data[k] for k in ("id", "revision", "job_id", "candidate_index"))
        if not isinstance(key, str) or type(revision) is not int or not isinstance(job_id, str) or type(index) is not int:
            raise ValueError("Invalid Firmament recommendation selection")
        job = self.server.jobs.get(job_id)
        request = job["request"]
        if job["action"] != "firmament optimize" or job["state"] != "completed" or request.get("profile_id") != key:
            raise ValueError("Select a completed recommendation for this profile")
        if request.get("revision") != revision:
            raise ProfileChanged("Firmament profile changed. Run a fresh recommendation.")
        profile = self.server.firmament_profiles.item(key)
        if profile["revision"] != revision:
            raise ProfileChanged("Firmament profile changed. Run a fresh recommendation.")
        submitted = {k: v for k, v in request.items() if k not in {"search", "ruleset_hash", "catalog_hash"}}
        if submitted != search_request(profile):
            raise ValueError("Recommendation was calculated for different profile inputs")
        candidates = job["result"].get("candidates", [])
        if not 0 <= index < len(candidates):
            raise ValueError("Unknown Firmament recommendation")
        tree = candidates[index]["tree"]
        tracked = profile["tree"]
        if tracked["start"] is not None and (tree["start"] != tracked["start"] or
                                             not set(tracked["keys"]).issubset(tree["keys"])):
            raise ValueError("Recommendation must extend the tracked tree")
        return self.server.firmament_profiles.update({"id": key, "revision": revision, "tree": tree})

    def _source_job(self,data):
        source = data["source"]
        if not isinstance(source,dict) or len(source) != 1 or "request" in data:
            raise ValueError("Select either an original document or an inline request")
        selector, identifier = next(iter(source.items()))
        if not isinstance(identifier,str):
            raise ValueError("A source ID must be a string")
        if selector == "example":
            value = read_example(identifier)
        elif selector == "upload":
            value = self.server.request_upload(identifier)
        elif selector in ("job_result","library_result","library_request"):
            entry = self.server.jobs.get(identifier) if selector == "job_result" else self.server.library.item(identifier)
            if selector != "library_request" and data.get("action") not in ("progression replay","build replay","encounter replay"):
                raise ValueError("Use the replay action for a retained result")
            value = entry.get("request" if selector == "library_request" else "result")
        else:
            raise ValueError("Unknown original document type")
        return {**{k:v for k,v in data.items() if k != "source"},"request":value}

    def _handle(self,route):
        try:
            route(*self._guard())
        except HttpIssue as exc:
            self._reply(exc.status,{"error":str(exc)})
        except (RulesetMismatch,QueueFull) as exc:
            self._reply(409 if isinstance(exc,RulesetMismatch) else 429,{"error":str(exc)})
        except ProfileChanged as exc:
            self._reply(409, {"error": str(exc)})
        except KeyError:
            self._reply(404,{"error":"Unknown job or packaged example"})
        except (ValueError,TypeError,RecursionError) as exc:
            self._reply(400,{"error":str(exc)})
        except (ConnectionError,TimeoutError):
            return
        except OSError:
            self._reply(500,{"error":"Local workbench storage is unavailable"})

    def do_GET(self):
        self._handle(self._get)

    def do_POST(self):
        self._handle(self._post)


def create_server(port=0, *, library_dir=None):
    if type(port) is not int or not 0 <= port <= 65535:
        raise ValueError("port must be an integer in 0..65535")
    return WorkbenchServer(port,library_dir if library_dir is not None else default_library())


def serve(port=0, open_browser=True):
    with create_server(port) as server:
        print(server.url,flush=True)
        if open_browser:
            webbrowser.open(server.url)
        try:
            server.serve_forever(poll_interval=.1)
        except KeyboardInterrupt:
            pass
    return 0

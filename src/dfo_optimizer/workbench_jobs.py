"""One native worker, immutable submitted inputs, replayed previews and cooperative cancellation."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from hashlib import sha256
import json
import logging
from threading import Event, RLock
from time import perf_counter
from uuid import uuid4

from .workbench_services import ACTIONS, MODES, execute, inline_only, limited_request, searchable, search_token


def digest(value):
    return sha256(json.dumps(value,sort_keys=True,separators=(",",":"),allow_nan=False).encode()).hexdigest()


class RulesetMismatch(ValueError):
    pass


class QueueFull(ValueError):
    pass


@dataclass
class Job:
    action: str
    mode: str
    request: dict
    request_hash: str
    ruleset_hash: str
    id: str = field(default_factory=lambda: uuid4().hex)
    created: float = field(default_factory=perf_counter)
    finished: float | None = None
    state: str = "queued"
    phase: str = "queued"
    preview_runs: int = 0
    preview_nodes: int = 0
    incumbent: dict | None = None
    incumbent_request: dict | None = None
    result: dict | None = None
    error: str | None = None
    token: object = None
    stop: Event = field(default_factory=Event)

    def snapshot(self):
        end = self.finished if self.finished is not None else perf_counter()
        return {"id":self.id, "action":self.action, "state":self.state, "mode":self.mode,
                "ruleset_hash":self.ruleset_hash, "request_hash":self.request_hash, "request":self.request,
                "progress":{"phase":self.phase,"elapsed_seconds":end-self.created,
                            "preview_runs":self.preview_runs,"preview_nodes":self.preview_nodes},
                "result":self.result,"incumbent":self.incumbent,"incumbent_request":self.incumbent_request,
                "error":self.error}


class Jobs:
    def __init__(self, ruleset_hash, *, retain=32, queue_size=8):
        self.ruleset_hash = ruleset_hash
        self.retain = retain
        self.queue_size = queue_size
        self.entries = {}
        self.lock = RLock()
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="dfo-search")
        self.closed = False

    def submit(self, raw):
        if set(raw) - {"action","request","mode","ruleset_hash"}:
            raise ValueError("Unknown workbench job fields")
        action, req, mode = raw.get("action"), raw.get("request"), raw.get("mode","request")
        if not isinstance(action,str) or action not in ACTIONS or not isinstance(req,dict):
            raise ValueError("Supply a supported action and a JSON request object")
        if not isinstance(mode,str) or mode not in MODES:
            raise ValueError("Unknown search mode")
        if any(v != self.ruleset_hash for v in (raw.get("ruleset_hash",self.ruleset_hash),
                                                 req.get("ruleset_hash",self.ruleset_hash))):
            raise RulesetMismatch("Ruleset mismatch. Select inputs for the installed ruleset.")
        inline_only(req)
        frozen = limited_request(action,req,MODES[mode])
        job = Job(action,mode,frozen,digest(frozen),self.ruleset_hash)
        with self.lock:
            if self.closed or sum(entry.finished is None for entry in self.entries.values()) >= self.queue_size:
                raise QueueFull("The search queue is full. Wait for a job or cancel one.")
            if len(self.entries) >= self.retain:
                old = next((key for key, value in self.entries.items() if value.finished is not None), None)
                if old is None:
                    raise QueueFull("All retained jobs are active")
                del self.entries[old]
            self.entries[job.id] = job
            self.pool.submit(self._work, job)
            return job.snapshot()

    def get(self, job_id):
        with self.lock:
            return self.entries[job_id].snapshot()

    def cancel(self, job_id):
        with self.lock:
            job = self.entries[job_id]
            if job.finished is None:
                job.stop.set()
                if job.state == "queued":
                    self._end(job,"cancelled")
                else:
                    job.state = "cancelling"
                    if job.token is not None:
                        job.token.cancel()
            return job.snapshot()

    def _end(self, job, state):
        job.state = job.phase = state
        job.finished = perf_counter()
        job.token = None

    def _previews(self, job):
        # These are independent shorter requests over the same feasible domain.
        # Never splice their results into the final service result or its proof.
        if not searchable(job.action):
            return
        for budget in (512, 8192):
            controls = job.request if job.action == "class optimize" else job.request.get("search",{})
            key = "max_events" if job.action.startswith("encounter ") else "max_nodes"
            limit = controls.get(key,0) if isinstance(controls,dict) else None
            if type(limit) is not int or (limit > 0 and limit <= budget) or job.stop.is_set():
                return
            query = limited_request(job.action,job.request,{"max_nodes":budget,"wall_seconds":.2})
            partial = execute(job.action,query,job.token)
            stats = partial.get("counters",{})
            with self.lock:
                job.preview_runs += 1
                job.preview_nodes += stats.get("nodes",stats.get("events",0))
                if any(partial.get(k) for k in ("routes","candidates","frontier")):
                    job.incumbent = partial
                    job.incumbent_request = query
            if partial.get("termination") in ("exhausted","constraint_conflict","top_k"):
                return

    def _work(self, job):
        try:
            with self.lock:
                if job.stop.is_set():
                    return
                job.token = search_token(job.action, job.request)
                job.state, job.phase = "running", "preview" if searchable(job.action) else "evaluate"
            self._previews(job)
            with self.lock:
                job.phase = "final_search"
                if job.stop.is_set():
                    self._end(job,"cancelled")
                    return
            result = execute(job.action,job.request,job.token)
            with self.lock:
                job.result = result
                cancelled = result.get("status") == "cancelled" or result.get("termination") == "cancelled"
                self._end(job,"cancelled" if cancelled else "completed")
        except Exception as exc:
            if not isinstance(exc,(ValueError, RuntimeError, ImportError)):
                logging.getLogger(__name__).exception("Workbench service failed for %s",job.action)
            with self.lock:
                job.error = str(exc) if isinstance(exc,(ValueError, RuntimeError, ImportError)) else "Unable to complete the requested operation"
                self._end(job,"failed")

    def close(self):
        with self.lock:
            self.closed = True
            for job in self.entries.values():
                self.cancel(job.id)
        self.pool.shutdown(wait=True)

"""Exercise the CLI's signal boundary separately from kernel cancellation tests."""

import _thread
import json
import os
import signal
import subprocess
import sys
from threading import Thread
import time

import pytest

from dfo_optimizer.cli import main


LONG_SEARCH = {
    "exact": True, "top_k": 1, "max_nodes": 0, "wall_seconds": 60,
    "skill_domains": [[22]] + [list(range(35)) for _ in range(11)],
}


def _assert_preserved(result):
    assert result["termination"] == result["status"] == "cancelled"
    assert result["counters"]["leaves"] > 0
    assert result["validation"]["finalists_checked"] == len(result["candidates"]) == 1


def test_cli_interrupt_returns_a_result(monkeypatch, tmp_path):
    from dfo_optimizer import search

    original = search.optimize_classes
    previous = signal.getsignal(signal.SIGINT)

    def interrupt_during_search(*args, **kwargs):
        token = kwargs["cancel"]

        def interrupt_after_incumbent():
            deadline = time.monotonic() + 20
            while not token.has_incumbent() and time.monotonic() < deadline:
                time.sleep(0.005)
            _thread.interrupt_main()

        sender = Thread(target=interrupt_after_incumbent)
        sender.start()
        try:
            return original(*args, **kwargs)
        finally:
            sender.join()

    monkeypatch.setattr(search, "optimize_classes", interrupt_during_search)
    request, output = tmp_path / "request.json", tmp_path / "result.json"
    request.write_text(json.dumps(LONG_SEARCH))
    assert main(["class", "optimize", "--request", str(request), "--output", str(output)]) == 130
    assert signal.getsignal(signal.SIGINT) is previous
    _assert_preserved(json.loads(output.read_text()))


@pytest.mark.skipif(os.name != "posix", reason="POSIX subprocess SIGINT delivery")
def test_running_cli_handles_posix_sigint(tmp_path):
    request = tmp_path / "request.json"
    request.write_text(json.dumps(LONG_SEARCH))
    # Emit the readiness marker only after the worker publishes a native
    # incumbent, even under virtualized hardware or heavy concurrent CI work.
    script = """
import sys, threading, time
from dfo_optimizer import search, cli
original = search.optimize_classes
def ready(*args, **kwargs):
    def announce():
        while not kwargs['cancel'].has_incumbent():
            time.sleep(0.005)
        print('ready', file=sys.stderr, flush=True)
    threading.Thread(target=announce, daemon=True).start()
    return original(*args, **kwargs)
search.optimize_classes = ready
sys.exit(cli.main(['class', 'optimize', '--request', sys.argv[1]]))
"""
    cmd = [sys.executable, "-I", "-c", script, str(request)]
    with subprocess.Popen(cmd, cwd=tmp_path, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) as child:
        try:
            import select
            assert select.select([child.stderr], [], [], 30)[0], "Child did not report a native incumbent"
            assert child.stderr.readline().strip() == "ready"
            child.send_signal(signal.SIGINT)
            output, error = child.communicate(timeout=20)
            result = json.loads(output)
            assert child.returncode == 130, (error, result["termination"], result["counters"])
            _assert_preserved(result)
        finally:
            if child.poll() is None:
                child.kill()

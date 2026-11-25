"""Sampling helpers for a single local benchmark process."""

from hashlib import sha256
from importlib import metadata
from importlib.machinery import EXTENSION_SUFFIXES
import math
import os
from pathlib import Path
import platform
import statistics
import sys
from time import perf_counter, process_time


def measure(call):
    wall = perf_counter()
    cpu = process_time()
    result = call()
    return result, {"wall_seconds": perf_counter() - wall, "cpu_seconds": process_time() - cpu}


def summarize(samples):
    ordered = sorted(row["wall_seconds"] for row in samples)
    return {
        "samples": samples,
        "p50_seconds": statistics.median(ordered),
        "p95_seconds": ordered[math.ceil(0.95 * len(ordered)) - 1],
    }


def cpu_name():
    if sys.platform == "win32":
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0") as key:
            return winreg.QueryValueEx(key, "ProcessorNameString")[0].strip()
    if sys.platform.startswith("linux"):
        for line in Path("/proc/cpuinfo").read_text().splitlines():
            if line.startswith("model name"):
                return line.partition(":")[2].strip()
    return platform.processor() or platform.machine()


def host():
    return {
        "os": platform.platform(), "architecture": platform.machine(),
        "cpu": cpu_name(), "logical_cpus": os.cpu_count(),
        "python": platform.python_version(), "python_compiler": platform.python_compiler(),
    }


def engine(native):
    filename = Path(native.__file__)
    if not filename.name.endswith(tuple(EXTENSION_SUFFIXES)):
        raise RuntimeError("The benchmark requires the installed native extension.")
    return {
        **native.build_info(), "native": True, "extension": filename.name,
        "binary_sha256": sha256(filename.read_bytes()).hexdigest(),
        "version": metadata.version("dfo-optimizer"),
    }


def peak_rss_bytes():
    if sys.platform != "win32":
        from resource import getrusage, RUSAGE_SELF
        scale = 1 if sys.platform == "darwin" else 1024
        return getrusage(RUSAGE_SELF).ru_maxrss * scale
    import ctypes as ct
    from ctypes import wintypes as win

    class ProcessMemoryCounters(ct.Structure):
        _fields_ = [("cb", win.DWORD), ("PageFaultCount", win.DWORD)] + [
            (name, ct.c_size_t) for name in (
                "PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage", "QuotaPagedPoolUsage",
                "QuotaPeakNonPagedPoolUsage", "QuotaNonPagedPoolUsage", "PagefileUsage", "PeakPagefileUsage",
            )
        ]

    read_counters = ct.WinDLL("psapi", use_last_error=True).GetProcessMemoryInfo
    read_counters.argtypes = [win.HANDLE, ct.POINTER(ProcessMemoryCounters), win.DWORD]
    read_counters.restype = win.BOOL
    counters = ProcessMemoryCounters()
    counters.cb = ct.sizeof(counters)
    if not read_counters(win.HANDLE(-1), ct.byref(counters), counters.cb):
        raise ct.WinError(ct.get_last_error())
    return counters.PeakWorkingSetSize

"""Small structured phase reports shared by sync, export and discovery processes."""
from __future__ import annotations

import contextvars
import functools
import json
import math
import os
import re
import sys
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

_CURRENT = contextvars.ContextVar("sync_metrics", default=None)


def process_memory() -> dict:
    try:
        if os.name == "nt":
            import ctypes
            from ctypes import wintypes
            class Counters(ctypes.Structure):
                _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                            *[(name, ctypes.c_size_t) for name in ("PeakWorkingSetSize", "WorkingSetSize",
                                "QuotaPeakPagedPoolUsage", "QuotaPagedPoolUsage", "QuotaPeakNonPagedPoolUsage",
                                "QuotaNonPagedPoolUsage", "PagefileUsage", "PeakPagefileUsage")]]
            counters = Counters()
            counters.cb = ctypes.sizeof(counters)
            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel.GetCurrentProcess.restype = wintypes.HANDLE
            psapi = ctypes.WinDLL("psapi", use_last_error=True)
            psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
            if not psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
                raise OSError(ctypes.get_last_error())
            return {"peakWorkingSetBytes": counters.PeakWorkingSetSize,
                    "workingSetBytes": counters.WorkingSetSize, "source": "GetProcessMemoryInfo"}
        import resource
        import sys
        value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return {"peakRssBytes": int(value * (1 if sys.platform == "darwin" else 1024)), "source": "getrusage"}
    except (ImportError, OSError, AttributeError):
        return {"source": "unavailable"}


class RunMetrics:
    def __init__(self, directory: Path, lane: str = "sync", run_id: str | None = None):
        self.directory = Path(directory)
        self.run_id = run_id if isinstance(run_id, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,80}", run_id) else uuid.uuid4().hex
        self.path = self.directory / f"{self.run_id}.{lane}.json"
        self.report = {"schema": 1, "runId": self.run_id, "lane": lane, "pid": os.getpid(),
                       "startedUnixSeconds": time.time(), "phases": {}, "counters": {}}
        self.started = time.perf_counter()

    def __enter__(self):
        self.token = _CURRENT.set(self)
        return self

    def __exit__(self, error_type, error, traceback):
        temporary = None
        try:
            self.report.update(status="failed" if error_type else "passed",
                               durationSeconds=time.perf_counter() - self.started, memory=process_memory())
            if error_type:
                self.report["errorType"] = error_type.__name__
                self.report["errorMessage"] = str(error)[:1024]
            self.report["workerReports"] = [str(path.resolve()) for path in self.directory.glob(self.run_id + ".*.json")
                                            if path != self.path]
            temporary = self.path.with_suffix(".json." + uuid.uuid4().hex + ".tmp")
            self.directory.mkdir(parents=True, exist_ok=True)
            temporary.write_text(json.dumps(self.report, indent=2, allow_nan=False), encoding="utf-8")
            os.replace(temporary, self.path)
        except Exception:
            # Every measurement operation is best effort, including metadata
            # collection. Preserve the original sync result or exception.
            self.path = None
        finally:
            try:
                if temporary is not None:
                    temporary.unlink(missing_ok=True)
            except Exception:
                pass
            finally:
                _CURRENT.reset(self.token)

    def environment(self) -> dict:
        return {"TIXL_SYNC_RUN_ID": self.run_id, "TIXL_SYNC_METRICS_DIR": str(self.directory.resolve()),
                "TIXL_SYNC_WORKER_STARTED_AT": str(time.time())}


def current_run():
    return _CURRENT.get()


def count(name: str, amount: int | float = 1) -> None:
    run = current_run()
    if run is not None:
        run.report["counters"][name] = run.report["counters"].get(name, 0) + amount


@contextmanager
def phase(name: str):
    run = current_run()
    started = time.perf_counter()
    failed = False
    try:
        yield
    except BaseException:
        failed = True
        raise
    finally:
        if run is not None:
            duration = time.perf_counter() - started
            row = run.report["phases"].setdefault(name, {"calls": 0, "totalSeconds": 0.0,
                  "minSeconds": duration, "maxSeconds": 0.0, "failures": 0})
            row["calls"] += 1
            row["totalSeconds"] += duration
            row["minSeconds"] = min(row["minSeconds"], duration)
            row["maxSeconds"] = max(row["maxSeconds"], duration)
            row["failures"] += int(failed)


def timed(name: str):
    def decorate(function):
        @functools.wraps(function)
        def wrapped(*args, **kwargs):
            with phase(name):
                return function(*args, **kwargs)
        return wrapped
    return decorate


def measured_sync(function):
    @functools.wraps(function)
    def wrapped(blend, requested_profile, requested_cache, blender, force, install):
        cache = Path(requested_cache) if requested_cache is not None else Path(blend).parent / ".tixl_cache" / Path(blend).stem
        run_id = os.environ.get("TIXL_SYNC_RUN_ID")
        run = RunMetrics(cache / "sync_metrics", run_id=run_id)
        try:
            with run:
                queued = os.environ.get("TIXL_SYNC_QUEUED_AT")
                if queued:
                    try:
                        value = float(queued)
                        if math.isfinite(value):
                            run.report["queueDelaySeconds"] = max(0, time.time() - value)
                    except ValueError:
                        pass
                result = function(blend, requested_profile, requested_cache, blender, force, install)
                run.report["resultStatus"] = result.get("status")
        except BaseException as error:
            path = None
            try:
                path = str(run.path.resolve()) if run.path else None
                error.metrics_path = path
            except Exception:
                pass
            try:
                print("SYNC_METRICS_REPORT " + json.dumps({"runId": run.run_id, "path": path, "status": "failed"}), file=sys.stderr, flush=True)
            except Exception:
                pass
            raise
        result["metrics"] = str(run.path.resolve()) if run.path else None
        return result
    return wrapped


@contextmanager
def worker_metrics(lane: str = "worker"):
    directory = os.environ.get("TIXL_SYNC_METRICS_DIR")
    if not directory:
        yield None
        return
    with RunMetrics(Path(directory), lane, os.environ.get("TIXL_SYNC_RUN_ID")) as run:
        started = os.environ.get("TIXL_SYNC_WORKER_STARTED_AT")
        if started:
            try:
                value = float(started)
                if math.isfinite(value):
                    run.report["startupSeconds"] = max(0, time.time() - value)
            except ValueError:
                pass
        yield run

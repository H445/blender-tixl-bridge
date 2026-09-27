"""Measure the bundled example through TiXL's debug protocol, restoring all state."""
from __future__ import annotations

import argparse
import json
import math
import shutil
import struct
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "blender_tixl_bridge" / "source"))
from cache_bindings import PATH_INPUTS, _managed_relative
from cache_publication import publish_generation, verify_generation
from cache_validation import validate_export_payload
from tixl_bridge import call

_CUMULATIVE_STATS = (
    "Blender cumulative scene loads",
    "Blender cumulative scene load us",
    "Blender cumulative morph uploads",
    "Blender cumulative material uploads",
    "Blender cumulative upload bytes",
)
_HELD_FRAME_STATS = (
    "Blender morph uploads",
    "Blender material uploads",
    "Blender upload bytes",
)
_INT32_MAX = 2**31 - 1


def percentiles(values):
    rows = sorted(value for value in values if math.isfinite(value))
    if not rows:
        return None
    def at(percentile):
        position = (len(rows) - 1) * percentile
        lower = int(position)
        upper = min(lower + 1, len(rows) - 1)
        return rows[lower] + (rows[upper] - rows[lower]) * (position - lower)
    return {"count": len(rows), "p50": at(.50), "p95": at(.95), "p99": at(.99)}


def _validate_cumulative_metrics(snapshots):
    previous = None
    for label, metrics in snapshots:
        if not isinstance(metrics, dict) or not isinstance(metrics.get("renderStats"), dict):
            raise ValueError(f"Metrics snapshot {label} has no renderStats")
        stats = metrics["renderStats"]
        current = {}
        for key in _CUMULATIVE_STATS:
            value = stats.get(key)
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError(f"Cumulative metric {key} is missing or invalid at {label}")
            if value < 0 or value >= _INT32_MAX:
                raise ValueError(f"Cumulative metric {key} is saturated or invalid at {label}")
            current[key] = value
            if previous is not None and value < previous[key]:
                raise ValueError(f"Cumulative metric {key} decreased at {label}")
        previous = current


def _validate_held_frame_metrics(metrics):
    if not isinstance(metrics, dict) or not isinstance(metrics.get("renderStats"), dict):
        raise ValueError("Held-frame metrics have no renderStats")
    stats = metrics["renderStats"]
    frame_stats = {}
    for key in _HELD_FRAME_STATS:
        value = stats.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"Held-frame metric {key} is missing or invalid")
        if value != 0:
            raise AssertionError(f"Unchanged source frame reported {value} for {key}")
        frame_stats[key] = value
    return frame_stats


def _restore_state(protocol_call, port, context, before, applied, report):
    """Attempt every cleanup action and retain per-call restoration evidence."""
    evidence = {"attempts": [], "graphMatchesOriginal": None,
                "contextMatchesOriginal": None, "verified": False}

    def attempt(name, method, **params):
        row = {"step": name, "method": method, "params": params}
        evidence["attempts"].append(row)
        try:
            result = protocol_call(method, port, **params)
        except BaseException as error:
            row.update(status="failed", errorType=type(error).__name__, error=str(error))
            return False, None
        row["status"] = "passed"
        return True, result

    for index in range(applied):
        attempt(f"undo_{index + 1}", "undo")
    attempt("restore_time", "setTime", timeInSecs=context["time"]["timeInSecs"])
    attempt("pump_after_time_restore", "pumpFrames", count=3)
    graph_ok, restored = attempt("readback_graph", "getGraphState", includeDefaults=True)

    attempt("restore_playback_state", "setPlayback", playing=context["time"]["isPlaying"])
    # The protocol maps a playing-only command to speed 1 or 0, so set the
    # requested speed last to preserve non-default and negative playback rates.
    attempt("restore_playback_speed", "setPlayback", speed=context["time"]["playbackSpeed"])
    context_ok, restored_context = attempt("readback_context", "getContext")

    if graph_ok:
        evidence["graphMatchesOriginal"] = restored == before
        if restored != before:
            evidence["attempts"].append({"step": "verify_graph", "status": "failed",
                                         "errorType": "AssertionError",
                                         "error": "Benchmark failed to restore original graph"})
    if context_ok:
        try:
            static_context = lambda row: {key: value for key, value in row.items() if key != "time"}
            time_state = restored_context.get("time", {}) if isinstance(restored_context, dict) else {}
            expected_time = context["time"]
            context_matches = (
                isinstance(restored_context, dict)
                and static_context(restored_context) == static_context(context)
                and time_state.get("playbackSpeed") == expected_time["playbackSpeed"]
                and time_state.get("isPlaying") == expected_time["isPlaying"]
            )
            if not expected_time["isPlaying"]:
                context_matches = context_matches and time_state == expected_time
            evidence["contextMatchesOriginal"] = context_matches
            if not context_matches:
                raise AssertionError("Benchmark failed to restore original context")
        except BaseException as error:
            evidence["contextMatchesOriginal"] = False
            evidence["attempts"].append({"step": "verify_context", "status": "failed",
                                         "errorType": type(error).__name__, "error": str(error)})

    evidence["verified"] = (
        all(row["status"] == "passed" for row in evidence["attempts"])
        and evidence["graphMatchesOriginal"] is True
        and evidence["contextMatchesOriginal"] is True
    )
    report["restoration"] = evidence
    report["stateRestored"] = evidence["verified"]
    report["cleanupFailures"] = [row for row in evidence["attempts"] if row["status"] != "passed"]
    return evidence


def _persist_report(folder: Path, report: dict) -> Path:
    path = folder / "runtime_report.json"
    path.write_text(json.dumps(report, indent=2, allow_nan=False), encoding="utf-8")
    return path


def benchmark(cache: Path, folder: Path, port: int, samples: int, project: str):
    folder.mkdir(parents=True)
    context = call("getContext", port)
    if context.get("compositionName") != project:
        raise ValueError(f"Open {project} before benchmarking; the current project was preserved")
    before = call("getGraphState", port, includeDefaults=True)
    if before.get("missingChildren") or before.get("missingConnections"):
        raise ValueError("Repair unresolved graph structure before benchmarking")
    # Clone the known example payload to exercise a fresh path load without
    # modifying its files or the editable project on disk.
    from cache_publication import active_root
    try:
        data = active_root(cache)
    except ValueError:
        data = cache  # Bundled example can predate generation publication.
    stage = folder / "stage"
    stage.mkdir()
    shutil.copytree(data / "worlds", stage / "worlds")
    for name in ("camera_60hz.bin", "camera_timeline.json"):
        shutil.copy2(data / name, stage / name)
    manifest = json.loads((stage / "worlds" / "manifest.json").read_text(encoding="utf-8"))
    validate_export_payload(stage, manifest)
    private_cache = folder / "cache"
    published = publish_generation(stage, private_cache, manifest, "generic")
    root = verify_generation(private_cache, published["generation"])
    changes = []
    for child in before["children"]:
        slots = PATH_INPUTS.get(child.get("symbolName", "").split(".")[-1], set())
        for item in child.get("inputs", []):
            if item["id"] not in slots or not isinstance(item.get("value"), str):
                continue
            relative = _managed_relative(item["value"], cache)
            if relative is not None:
                target = root / relative
                if not target.exists():
                    raise ValueError("Benchmark payload lacks " + str(relative))
                changes.append((child["childId"], item["id"], str(target)))
    if not changes:
        raise ValueError("No managed example data paths found")
    report = {"schema": 1, "project": project, "editorVersion": call("getVersion", port),
              "scope": "paused deterministic source-time steps; debug-reported editor frame intervals, not GPU timestamps",
              "samples": [], "dataGeneration": root.name, "bindings": len(changes)}
    applied = 0
    benchmark_error = None
    benchmark_traceback = None
    try:
        call("setPlayback", port, playing=False)
        initial = call("getMetrics", port)
        if "Blender cumulative upload bytes" not in initial.get("renderStats", {}):
            raise ValueError("Install the runtime statistics update before benchmarking")
        started = time.perf_counter()
        for child, slot, value in changes:
            call("setInput", port, childId=child, inputId=slot, value=value)
            applied += 1
        call("pumpFrames", port, count=3)
        report["freshPathLoadWallSeconds"] = time.perf_counter() - started
        loaded = call("getMetrics", port)
        report["initialMetrics"] = initial
        report["loadedMetrics"] = loaded
        total_seconds = (max(world["active_clip"][1] for world in manifest["worlds"]) - 1) / manifest["fps"]
        for index in range(samples):
            source_time = total_seconds * index / samples
            started = time.perf_counter()
            call("setTime", port, timeInSecs=source_time)
            call("pumpFrames", port, count=1)
            metrics = call("getMetrics", port)
            report["samples"].append({"sourceSeconds": source_time,
                                      "roundTripSeconds": time.perf_counter() - started,
                                      "metrics": metrics})
        # With the source frame unchanged, successful upload counters must stop.
        held_before = call("getMetrics", port)
        call("pumpFrames", port, count=10)
        held_after = call("getMetrics", port)
        metric_series = [("initial", initial), ("loaded", loaded)]
        metric_series.extend((f"sample_{index + 1}", row["metrics"])
                             for index, row in enumerate(report["samples"]))
        metric_series.extend((("held_before", held_before), ("held_after", held_after)))
        _validate_cumulative_metrics(metric_series)
        report["heldFrameStats"] = _validate_held_frame_metrics(held_after)
        report["heldFrameUploadBytes"] = (held_after["renderStats"]["Blender cumulative upload bytes"]
                                           - held_before["renderStats"]["Blender cumulative upload bytes"])
        if report["heldFrameUploadBytes"] != 0:
            raise AssertionError("Unchanged source frame uploaded bridge buffers")
        call("setTime", port, timeInSecs=0)
        call("pumpFrames", port, count=3)
        screenshot = folder / "output.png"
        call("screenshot", port, path=str(screenshot), target="output")
        with screenshot.open("rb") as stream:
            stream.seek(16)
            report["outputResolution"] = list(struct.unpack(">II", stream.read(8)))
        report["screenshot"] = str(screenshot)
        report["frameDeltaMilliseconds"] = percentiles([row["metrics"]["frameDeltaSeconds"] * 1000 for row in report["samples"]])
        report["debugRoundTripMilliseconds"] = percentiles([row["roundTripSeconds"] * 1000 for row in report["samples"]])
        final = held_after["renderStats"]
        report["uploads"] = {key: final[key] - initial["renderStats"][key] for key in
                              ("Blender cumulative morph uploads", "Blender cumulative material uploads", "Blender cumulative upload bytes")}
        report["sceneLoadMicroseconds"] = (loaded["renderStats"]["Blender cumulative scene load us"]
                                            - initial["renderStats"]["Blender cumulative scene load us"])
        report["peakManagedMemoryMb"] = max(row["metrics"]["gcTotalMemoryMb"] for row in report["samples"])
        gpu = [row["metrics"].get("gpuMemory", {}).get("currentUsageMb") for row in report["samples"]
               if isinstance(row["metrics"].get("gpuMemory"), dict)]
        report["peakGpuUsageMb"] = max((value for value in gpu if value is not None), default=None)
        report["status"] = "passed"
    except BaseException as error:
        benchmark_error = error
        benchmark_traceback = error.__traceback__
        report["status"] = "failed"
        report["benchmarkFailure"] = {"errorType": type(error).__name__, "error": str(error)}

    restoration = _restore_state(call, port, context, before, applied, report)
    if not restoration["verified"]:
        report["status"] = "failed"
    path = _persist_report(folder, report)
    if benchmark_error is not None:
        raise benchmark_error.with_traceback(benchmark_traceback)
    if not restoration["verified"]:
        raise AssertionError(f"Benchmark failed to restore original graph/context; see {path}")
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=9042)
    parser.add_argument("--samples", type=int, default=120)
    parser.add_argument("--project", default="BlendShapeExample")
    parser.add_argument("--cache", type=Path, default=ROOT / "examples" / ".tixl_cache" / "BlendShapeExample")
    parser.add_argument("--output", type=Path, default=ROOT / "examples" / ".tixl_cache" / "benchmarks" / ("tixl_" + uuid.uuid4().hex))
    options = parser.parse_args()
    if options.samples < 10 or options.samples > 10000:
        parser.error("samples must be between 10 and 10000")
    print(benchmark(options.cache.resolve(), options.output.resolve(), options.port, options.samples, options.project))


if __name__ == "__main__":
    main()

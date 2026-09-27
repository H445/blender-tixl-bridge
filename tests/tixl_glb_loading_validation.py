"""Repeat paused example loads and verify shared-cache bounds and output equality."""
from __future__ import annotations

import argparse
import hashlib
import json
import uuid
from pathlib import Path

from tixl_runtime_benchmark import ROOT, benchmark, call, percentiles


def validate(folder: Path, baseline: Path, repetitions: int, port: int):
    folder.mkdir(parents=True, exist_ok=False)
    baseline_report = json.loads((baseline / "runtime_report.json").read_text())
    if baseline_report.get("stateRestored") is not True:
        raise ValueError("Baseline did not verify restoration")
    expected_image = hashlib.sha256((baseline / "output.png").read_bytes()).hexdigest()
    report = {"schema": 1, "status": "running", "runs": [],
              "scope": "paused unchanged export copied to distinct generation paths; "
                       "accounted shared track memory and whole-editor memory reported separately"}
    report_path = folder / "loading_report.json"
    try:
        for index in range(repetitions):
            path = benchmark(ROOT / "examples/.tixl_cache/BlendShapeExample",
                             folder / f"run_{index:02d}", port, 10, "BlendShapeExample")
            run = json.loads(path.read_text())
            first = run["initialMetrics"]["renderStats"]
            last = run["loadedMetrics"]["renderStats"]
            reads = last["Blender cumulative GLB reads"] - first["Blender cumulative GLB reads"]
            parses = last["Blender cumulative GLB JSON parses"] - first["Blender cumulative GLB JSON parses"]
            loads = last["Blender cumulative scene loads"] - first["Blender cumulative scene loads"]
            if not (reads == parses == loads and reads > 0):
                raise AssertionError(f"Expected one GLB read/parse per scene initialization: {reads}/{parses}/{loads}")
            image_hash = hashlib.sha256((path.parent / "output.png").read_bytes()).hexdigest()
            if image_hash != expected_image:
                raise AssertionError("Rendered PNG differs from the pre-change baseline")
            restored = call("getMetrics", port)
            stats = restored["renderStats"]
            entries = stats["Blender shared animation cache entries"]
            accounted = stats["Blender shared animation cache accounted bytes"]
            if not (0 <= entries <= 16 and 0 <= accounted <= 64 * 1024 * 1024):
                raise AssertionError("Shared animation cache exceeded its entry or byte budget")
            report["runs"].append({"index": index, "sceneLoadMicroseconds": run["sceneLoadMicroseconds"],
                                   "glbReads": reads, "jsonParses": parses, "sceneLoads": loads,
                                   "cacheEntriesAfterRestoration": entries,
                                   "cacheAccountedBytesAfterRestoration": accounted,
                                   "editorManagedMemoryMbAfterRestoration": restored["gcTotalMemoryMb"],
                                   "editorGpuMemoryAfterRestoration": restored.get("gpuMemory"),
                                   "baselinePngMatches": True, "stateRestored": run["stateRestored"],
                                   "heldFrameUploadBytes": run["heldFrameUploadBytes"],
                                   "runtimeReport": str(path.relative_to(ROOT))})
            report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        tail = report["runs"][-4:]
        if any(row["cacheEntriesAfterRestoration"] != 16 for row in tail):
            raise AssertionError("Repeated generations did not exercise the cache entry limit")
        if len({row["cacheAccountedBytesAfterRestoration"] for row in tail}) != 1:
            raise AssertionError("Identical-size generation loads did not reach a shared-cache memory plateau")
        report["sceneLoadMicroseconds"] = percentiles([row["sceneLoadMicroseconds"] for row in report["runs"]])
        report["cacheTailAccountedBytes"] = [row["cacheAccountedBytesAfterRestoration"] for row in tail]
        gpu = [row["editorGpuMemoryAfterRestoration"].get("currentUsageMb")
               for row in report["runs"] if isinstance(row["editorGpuMemoryAfterRestoration"], dict)]
        if len(gpu) == repetitions and all(isinstance(value, (int, float)) for value in gpu):
            report["gpuMemoryRangeMb"] = [min(gpu), max(gpu)]
            report["gpuMemoryFirstToLastChangeMb"] = gpu[-1] - gpu[0]
        report["status"] = "passed"
    except BaseException as error:
        report["status"] = "failed"
        report["error"] = {"type": type(error).__name__, "message": str(error)}
        raise
    finally:
        report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report_path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", required=True, type=Path)
    parser.add_argument("--port", type=int, default=9042)
    parser.add_argument("--repetitions", type=int, default=8)
    parser.add_argument("--output", type=Path, default=ROOT / "examples/.tixl_cache/benchmarks" / ("glb_" + uuid.uuid4().hex))
    options = parser.parse_args()
    if options.repetitions < 8 or options.repetitions > 100:
        parser.error("repetitions must be between 8 and 100")
    print(validate(options.output.resolve(), options.baseline.resolve(), options.repetitions, options.port))


if __name__ == "__main__":
    main()

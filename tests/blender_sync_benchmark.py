"""Reproducible bridge sync workload benchmark.

Run from a disposable Blender ``--background --factory-startup`` process,
preferably through the official Blender MCP launcher. This script creates all
fixtures itself, calls the no-install sync path, and writes artifacts only to
``examples/.tixl_cache/benchmarks/<run id>``.
"""
from __future__ import annotations

import json
import math
import os
import re
import subprocess
import sys
import time
import traceback
import uuid
from pathlib import Path

import bpy

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "blender_tixl_bridge" / "source"
sys.path.insert(0, str(SOURCE))
import blend_sync
import cache_publication

# This harness writes only private caches and always requests no-install. The
# production sync guard is for writes visible to a running TiXL editor; bypass
# that unrelated check here so the benchmark never probes or contacts TiXL.
blend_sync.wait_for_editor_pause = lambda: None


def cache_bytes(path: Path) -> int:
    return sum(file.stat().st_size for file in path.rglob("*") if file.is_file())


def load_metrics(result: dict) -> dict | None:
    raw = result.get("metrics") or result.get("metrics_path")
    if not raw:
        return None
    path = Path(raw)
    if not path.is_file():
        return {"path": str(path), "unavailable": True}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        return {"path": str(path), "unavailable": True, "error": str(error)}
    data["path"] = str(path.resolve())
    return data


def reset_scene(name: str, start: int = 1, end: int = 60):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.name = name
    scene.frame_start, scene.frame_end = start, end
    scene.render.fps = 60
    scene.render.fps_base = 1.0
    scene.render.resolution_x, scene.render.resolution_y = 320, 240
    scene.render.resolution_percentage = 100
    scene["tixl_project_name"] = "Benchmark_" + re.sub(r"[^A-Za-z0-9_]", "_", name)
    return scene


def material(name="BenchmarkMaterial", color=(0.2, 0.45, 0.8, 1.0)):
    value = bpy.data.materials.new(name)
    value.diffuse_color = color
    value.use_nodes = True
    shader = value.node_tree.nodes.get("Principled BSDF")
    shader.inputs["Base Color"].default_value = color
    shader.inputs["Roughness"].default_value = 0.42
    return value


def setup_camera_and_light(scene, collection=None):
    camera_data = bpy.data.cameras.new("BenchmarkCameraData")
    camera = bpy.data.objects.new("BenchmarkCamera", camera_data)
    camera.location = (4.2, -6.0, 3.4)
    camera.rotation_euler = (-camera.location).to_track_quat("-Z", "Y").to_euler()
    camera_data.lens = 50
    (collection or scene.collection).objects.link(camera)
    scene.camera = camera
    light_data = bpy.data.lights.new("BenchmarkKeyData", "AREA")
    light_data.energy = 900
    light = bpy.data.objects.new("BenchmarkKey", light_data)
    light.location = (3.5, -4.0, 5.0)
    light.rotation_euler = (-light.location).to_track_quat("-Z", "Y").to_euler()
    (collection or scene.collection).objects.link(light)


def add_cube(scene, name="AnimatedCube", collection=None, size=2.0, mat=None):
    mesh = bpy.data.meshes.new(name + "Mesh")
    h = size / 2
    vertices = [(-h, -h, -h), (-h, -h, h), (-h, h, -h), (-h, h, h),
                (h, -h, -h), (h, -h, h), (h, h, -h), (h, h, h)]
    faces = [(0, 4, 6, 2), (1, 3, 7, 5), (0, 1, 5, 4),
             (2, 6, 7, 3), (0, 2, 3, 1), (4, 5, 7, 6)]
    mesh.from_pydata(vertices, [], faces)
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    (collection or scene.collection).objects.link(obj)
    obj.data.materials.append(mat or material())
    return obj


def save_fixture(path: Path, scene):
    setup_camera_and_light(scene)
    scene.frame_set(scene.frame_start)
    bpy.ops.wm.save_as_mainfile(filepath=str(path), check_existing=False, compress=True)
    return path


def sync_once(blend: Path, cache: Path, label: str, fixture: dict, run: dict):
    started = time.perf_counter()
    result = blend_sync.sync(blend, "generic", cache, Path(bpy.app.binary_path), False, False)
    elapsed = time.perf_counter() - started
    metric = load_metrics(result)
    record = {"label": label, "blend": str(blend), "cache": str(cache),
              "wallSeconds": elapsed, "status": result["status"],
              "sourceSha256": blend_sync.digest(blend), "metrics": metric,
              "cacheBytes": cache_bytes(cache), "fixture": fixture}
    run["syncs"].append(record)
    return result


def fixture_simple(folder: Path):
    scene = reset_scene("simple_baseline")
    cube = add_cube(scene)
    cube.location.z = 0.1
    blend = save_fixture(folder / "simple.blend", scene)
    return blend, {"objects": 3, "frames": 60, "fps": 60, "worlds": 1,
                   "mesh": "one static cube", "cameraAndLight": True}


def fixture_long(folder: Path):
    scene = reset_scene("long_timeline", 1, 600)
    cube = add_cube(scene, size=1.5)
    for frame, location, rotation in ((1, (0, 0, 0), (0, 0, 0)),
                                      (300, (2, 0, 1), (0, 0, math.pi)),
                                      (600, (0, 0, 0), (0, 0, math.tau))):
        cube.location = location
        cube.rotation_euler = rotation
        cube.keyframe_insert(data_path="location", frame=frame)
        cube.keyframe_insert(data_path="rotation_euler", frame=frame)
    blend = save_fixture(folder / "long_timeline.blend", scene)
    return blend, {"objects": 3, "frames": 600, "fps": 60, "worlds": 1,
                   "mesh": "one cube with keyed translation and rotation at 1, 300, 600"}


def fixture_multi_world(folder: Path):
    scene = reset_scene("multiple_worlds", 1, 181)
    worlds = []
    palette = ((0.8, 0.2, 0.1, 1), (0.15, 0.7, 0.25, 1), (0.2, 0.35, 0.9, 1))
    for index, world_name in enumerate(("amber", "green", "blue")):
        collection = bpy.data.collections.new(world_name.title())
        scene.collection.children.link(collection)
        obj = add_cube(scene, world_name.title() + "Cube", collection, 1.2,
                       material(world_name.title() + "Material", palette[index]))
        obj.location.x = index * 0.15
        worlds.append({"name": world_name, "collection": collection.name,
                       "start_seconds": index, "end_seconds": index + 1})
    scene["tixl_worlds"] = json.dumps(worlds, separators=(",", ":"))
    setup_camera_and_light(scene)
    scene.frame_set(1)
    blend = folder / "multiple_worlds.blend"
    bpy.ops.wm.save_as_mainfile(filepath=str(blend), check_existing=False, compress=True)
    return blend, {"objects": 5, "frames": 181, "fps": 60, "worlds": 3,
                   "worldRangesSeconds": [[0, 1], [1, 2], [2, 3]],
                   "collections": ["Amber", "Green", "Blue"]}


def fixture_morph(folder: Path):
    scene = reset_scene("morph_heavy", 1, 60)
    obj = add_cube(scene, "MorphCube", size=1.5)
    basis = obj.shape_key_add(name="Basis")
    keys = []
    for key_index in range(8):
        key = obj.shape_key_add(name=f"Morph{key_index + 1:02d}")
        for vertex_index, point in enumerate(key.data):
            phase = (vertex_index + key_index) * math.pi / 4
            point.co.z += math.sin(phase) * (0.08 + key_index * 0.01)
            point.co.x += math.cos(phase) * 0.04
        keys.append(key)
    for frame in range(1, 61):
        for index, key in enumerate(keys):
            key.value = 1.0 if frame == (index * 7 + 1) else 0.0
            key.keyframe_insert(data_path="value", frame=frame)
    blend = save_fixture(folder / "morph_heavy.blend", scene)
    return blend, {"objects": 3, "frames": 60, "fps": 60, "worlds": 1,
                   "mesh": "one cube, Basis plus 8 shape keys, all keyed on frames 1..60"}


def python_executable():
    version = f"{bpy.app.version[0]}.{bpy.app.version[1]}"
    filename = "python.exe" if os.name == "nt" else "python3"
    path = Path(bpy.app.binary_path).parent / version / "python" / "bin" / filename
    if not path.is_file():
        raise RuntimeError("Could not locate a Python executable for rapid-save CLI requests")
    return path


def rapid_save_benchmark(folder: Path, run: dict):
    from sync_queue import LatestRequestQueue
    scene = reset_scene("rapid_saves", 1, 180)
    cube = add_cube(scene)
    for frame, x in ((1, 0), (180, 1)):
        cube.location.x = x
        cube.keyframe_insert(data_path="location", frame=frame)
    blend = save_fixture(folder / "rapid_saves.blend", scene)
    cache = folder / "cache"
    cli_bootstrap = ("import sys; sys.path.insert(0, " + repr(str(SOURCE)) + "); "
                     "import blend_sync; blend_sync.wait_for_editor_pause=lambda: None; "
                     "blend_sync.main()")
    command = [str(python_executable()), "-c", cli_bootstrap, "sync",
               "--blend", str(blend), "--profile", "generic", "--cache-root", str(cache),
               "--blender", str(Path(bpy.app.binary_path)), "--no-install"]
    launched = []
    peak_active = 0
    def launch(request):
        nonlocal peak_active
        log = folder / (request["runId"] + ".cli.log")
        with log.open("w", encoding="utf-8") as output:
            process = subprocess.Popen(command, cwd=str(ROOT), stdout=output,
                                       stderr=subprocess.STDOUT, env=request["env"],
                                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        launched.append({"request": request, "process": process, "log": log,
                         "started": time.perf_counter()})
        peak_active = max(peak_active, sum(row["process"].poll() is None for row in launched))
        return process
    queue = LatestRequestQueue(launch)
    snapshots = []
    for index in range(5):
        cube.location.y = index * .125
        cube.keyframe_insert(data_path="location", frame=1 + index)
        bpy.ops.wm.save_as_mainfile(filepath=str(blend), check_existing=False, compress=True)
        saved_sha = blend_sync.digest(blend)
        snapshots.append(saved_sha)
        run_id = uuid.uuid4().hex
        queue.submit({"source": str(blend), "index": index + 1,
                      "sourceSha256": saved_sha, "runId": run_id, "queuedAt": time.time(),
                      "statusPath": str(cache / "sync_status.json"),
                      "env": dict(os.environ, TIXL_SYNC_RUN_ID=run_id)})
        if index == 0:
            # Change subsequent saves only after the first request is actively
            # exporting. This exercises a pending save across worker failure.
            deadline = time.monotonic() + 30
            while not list((cache / ".staging").glob("*/export.log")):
                queue.poll()
                if not queue.has_work or time.monotonic() >= deadline:
                    raise AssertionError("First rapid-save export did not start")
                time.sleep(.05)
    deadline = time.monotonic() + 300
    while queue.has_work:
        queue.poll()
        if time.monotonic() >= deadline:
            raise TimeoutError("Rapid-save queue did not drain")
        time.sleep(.05)
    results = []
    rejected = []
    for row in launched:
        request, process = row["request"], row["process"]
        output = row["log"].read_text(encoding="utf-8", errors="replace")
        record = {"request": request["index"], "submittedSourceSha256": request["sourceSha256"],
                  "returnCode": process.returncode,
                  "wallSeconds": time.perf_counter() - row["started"], "stdoutTail": output[-1600:],
                  "metrics": load_metrics({"metrics": str(cache / "sync_metrics" / (request["runId"] + ".sync.json"))})}
        results.append(record)
        if process.returncode:
            rejected.append({"request": request["index"], "returnCode": process.returncode})
    latest_sha = blend_sync.digest(blend)
    manifest = cache_publication.read_manifest(cache)
    verified_sha = manifest.get("source_sha256")
    report = {"blend": str(blend), "cache": str(cache), "requests": results,
              "savedSourceSha256": snapshots, "latestSourceSha256": latest_sha,
              "verifiedCacheSourceSha256": verified_sha,
              "latestSourceAccepted": verified_sha == latest_sha,
              "rejectedSaveCount": len(rejected), "rejectedSaves": rejected,
              "cacheBytes": cache_bytes(cache), "submittedRequestCount": len(snapshots),
              "cliProcessCount": len(launched), "peakActiveCliProcesses": peak_active,
              "coalescedRequestCount": len(snapshots) - len(launched),
              "queueStatus": queue.snapshot(str(blend)),
              "workerProcessCount": sum((item["metrics"] or {}).get("counters", {}).get("blenderProcesses", 0)
                                        for item in results)}
    run["rapidSaves"] = report
    if not report["latestSourceAccepted"]:
        raise AssertionError("Rapid-save queue lost the final saved source")
    if peak_active != 1 or len(launched) > 2:
        raise AssertionError("Rapid-save queue exceeded one active plus one latest pending request")


def main():
    run_id = time.strftime("%Y%m%dT%H%M%S") + "_" + uuid.uuid4().hex[:8]
    folder = ROOT / "examples" / ".tixl_cache" / "benchmarks" / run_id
    folder.mkdir(parents=True, exist_ok=False)
    run = {"schema": 1, "runId": run_id, "status": "running", "lane": "benchmark",
           "measurementScope": "export-only no-install; TiXL transport, installation, and live rendering excluded",
           "startedUtc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "runtime": {"blenderVersion": bpy.app.version_string,
                       "blenderBuildHash": getattr(bpy.app, "build_hash", b"").decode(errors="replace")
                       if isinstance(getattr(bpy.app, "build_hash", b""), bytes)
                       else str(getattr(bpy.app, "build_hash", "")),
                       "pythonVersion": sys.version, "platform": sys.platform,
                       "blenderExecutable": str(Path(bpy.app.binary_path).resolve()),
                       "pythonExecutable": str(python_executable().resolve())},
           "fixtureDefinitions": {}, "syncs": [], "errors": []}
    started = time.perf_counter()
    try:
        blend, fixture = fixture_simple(folder)
        cache = folder / "simple_cache"
        run["fixtureDefinitions"]["simple"] = fixture
        sync_once(blend, cache, "simple_baseline", fixture, run)
        sync_once(blend, cache, "simple_unchanged", fixture, run)
        # Make and save one deterministic edit before measuring the rebuild.
        cube = bpy.data.objects.get("AnimatedCube")
        if cube:
            cube.location.x = 0.75
        else:
            # The saved file is still loaded unless the next fixture was created.
            cube = next((item for item in bpy.context.scene.objects if item.type == "MESH"), None)
            cube.location.x = 0.75
        bpy.ops.wm.save_as_mainfile(filepath=str(blend), check_existing=False, compress=True)
        sync_once(blend, cache, "simple_edited", fixture, run)

        for key, creator in (("longTimeline", fixture_long),
                             ("multipleWorlds", fixture_multi_world),
                             ("morphHeavy", fixture_morph)):
            blend, fixture = creator(folder)
            run["fixtureDefinitions"][key] = fixture
            sync_once(blend, folder / (key + "_cache"), key, fixture, run)

        rapid_save_benchmark(folder, run)
        run["status"] = "passed"
    except Exception:
        run["status"] = "failed"
        run["errors"].append(traceback.format_exc())
    run["durationSeconds"] = time.perf_counter() - started
    run["endedUtc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    run["processCounts"] = {
        "directSyncRequests": len(run["syncs"]),
        "syncWorkerProcesses": sum((item.get("metrics") or {}).get("counters", {}).get("blenderProcesses", 0)
                                   for item in run["syncs"]),
        "rapidSaveCliProcesses": (run.get("rapidSaves") or {}).get("cliProcessCount", 0),
        "rapidSaveWorkerProcesses": (run.get("rapidSaves") or {}).get("workerProcessCount", 0),
    }
    run["aggregateMetrics"] = [item["metrics"] for item in run["syncs"] if item.get("metrics")]
    run["aggregateMetrics"].extend(
        item["metrics"] for item in (run.get("rapidSaves") or {}).get("requests", [])
        if item.get("metrics"))
    report_path = folder / "benchmark_report.json"
    report_path.write_text(json.dumps(run, indent=2, default=str), encoding="utf-8")
    print("BLENDER_SYNC_BENCHMARK " + json.dumps({"status": run["status"],
          "report": str(report_path), "durationSeconds": run["durationSeconds"],
          "processCounts": run["processCounts"]}), flush=True)
    if run["status"] != "passed":
        raise RuntimeError("Benchmark failed; see " + str(report_path))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        sys.stdout.flush()
        os._exit(1)

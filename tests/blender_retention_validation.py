"""Disposable Blender-background acceptance run for cache retention.

Run through Blender MCP with ``--background --factory-startup --python``.
This creates a unique ignored scope under ``examples/.tixl_cache`` and never
opens or contacts a TiXL installation. The closed-editor override applies only
to this private, unloaded fixture cache; it is not a live TiXL performance or
editor-safety claim.
"""
from __future__ import annotations

import json
import os
import sys
import time
import traceback
import uuid
from pathlib import Path

import bpy

ROOT = Path(__file__).resolve().parents[1]
SCOPE = ROOT / "examples" / ".tixl_cache" / "issue8_validation" / uuid.uuid4().hex
CACHE = SCOPE / "c"
BLEND = SCOPE / "R.blend"
TEMPLATE = SCOPE / "p" / "O"
EDITOR = SCOPE / "e"
PROJECTS = SCOPE / "p"
REPORT = SCOPE / "r.json"


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def tree_bytes(path: Path, *, exclude: set[str] | None = None) -> int:
    exclude = exclude or set()
    if not path.exists():
        return 0
    return sum(file.stat().st_size for file in path.rglob("*")
               if file.is_file() and file.name not in exclude)


def current_and_previous(cache_publication, cache: Path) -> dict:
    pointer_path = cache / cache_publication.POINTER
    pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
    active = pointer.get("generation")
    previous = pointer.get("previous")
    if not active:
        raise AssertionError("Current-generation pointer has no active generation")
    verified = {active: str(cache_publication.verify_generation(cache, active))}
    if previous:
        verified[previous] = str(cache_publication.verify_generation(cache, previous))
    return {"active": active, "previous": previous, "verified": verified}


def make_fixture(bench) -> None:
    scene = bench.reset_scene("R", 1, 13)
    scene["tixl_project_name"] = "R"
    scene.render.fps = 60
    cube = bench.add_cube(scene, "RetentionCube", size=1.25)
    cube.location.x = 0.0
    cube.keyframe_insert(data_path="location", frame=1)
    cube.location.x = 0.4
    cube.keyframe_insert(data_path="location", frame=13)
    bench.setup_camera_and_light(scene)
    bpy.ops.wm.save_as_mainfile(filepath=str(BLEND), check_existing=False, compress=True)


def save_fixture() -> None:
    bpy.ops.wm.save_as_mainfile(filepath=str(BLEND), check_existing=False, compress=True)


def make_policy() -> dict:
    return {
        "generations": {"max_count": 2, "max_bytes": 4 * 1024**3, "max_age_days": 30},
        "backups": {"max_count": 1, "max_bytes": 1024**3, "max_age_days": 30},
        "staging": {"max_count": 1, "max_bytes": 1024**3, "max_age_days": 30},
        "reports": {"max_count": 8, "max_bytes": 128 * 1024**2, "max_age_days": 30},
        "logs": {"max_count": 4, "max_bytes": 128 * 1024**2, "max_age_days": 30},
    }


def make_fake_template() -> None:
    PROJECTS.mkdir(parents=True, exist_ok=False)
    TEMPLATE.mkdir(parents=True, exist_ok=False)
    EDITOR.mkdir(parents=True, exist_ok=False)
    (TEMPLATE / "Operators.csproj").write_text(
        "<Project><PropertyGroup><RootNamespace>Template</RootNamespace>"
        "<HomeGuid>00000000-0000-0000-0000-000000000001</HomeGuid>"
        "<PackageId>00000000-0000-0000-0000-000000000002</PackageId>"
        "</PropertyGroup></Project>", encoding="utf-8")


def editable_timing(home: dict) -> list[dict]:
    result = []
    for child in home.get("Children", []):
        if not child.get("SymbolName", "").endswith("BlenderSourceClip"):
            continue
        for output in child.get("Outputs", []):
            clip = output.get("OutputData", {}).get("TimeClip")
            if clip:
                result.append({"id": child["Id"], "name": child.get("Name"),
                               "timeClip": clip})
    if not result:
        raise AssertionError("Generated editable Home graph has no source TimeClips")
    return result


def create_user_evidence(project: Path, cache: Path) -> tuple[Path, bytes, Path, bytes]:
    import retention_lifecycle

    symbols = project / "Symbols"
    home_path = symbols / (project.name + ".t3")
    home = json.loads(home_path.read_text(encoding="utf-8"))
    clips = editable_timing(home)
    # This edit represents user-owned timing and metadata. Later binds must
    # change managed data paths while preserving both values exactly.
    for row in clips:
        timing = row["timeClip"].get("TimeRange", {})
        timing["Start"] = float(timing.get("Start", 0.0)) + 0.03125
        timing["End"] = float(timing.get("End", 0.0)) - 0.03125
    home["Issue8UserFlag"] = {"keep": True, "label": "user-owned"}
    write_json(home_path, home)

    user_graph = symbols / "UserTimeClips.t3"
    write_json(user_graph, {"Id": str(uuid.uuid4()), "Children": [], "Connections": [],
                            "TimeClips": [{"StartTime": 7, "Duration": 23}],
                            "Issue8UserGraph": True})

    # It has no bridge ownership marker and must remain outside retention scope.
    legacy = cache / "project_backups" / "legacy_user_backup"
    legacy.mkdir(parents=True, exist_ok=False)
    write_json(legacy / "UserGraph.t3", {"Id": str(uuid.uuid4()), "Children": [],
                                         "Connections": [],
                                         "TimeClips": [{"StartTime": 9, "Duration": 17}]})
    return user_graph, user_graph.read_bytes(), legacy, (legacy / "UserGraph.t3").read_bytes()


def check_user_evidence(project: Path, user_graph: Path, user_graph_bytes: bytes,
                        legacy: Path, legacy_bytes: bytes, expected_timing: list[dict]) -> None:
    home_path = project / "Symbols" / (project.name + ".t3")
    home = json.loads(home_path.read_text(encoding="utf-8"))
    if editable_timing(home) != expected_timing:
        raise AssertionError("A real project bind changed user-edited Home TimeClips")
    if home.get("Issue8UserFlag") != {"keep": True, "label": "user-owned"}:
        raise AssertionError("A real project bind changed a custom Home user flag")
    if user_graph.read_bytes() != user_graph_bytes:
        raise AssertionError("A real project bind changed the user-owned graph TimeClips")
    if (legacy / "UserGraph.t3").read_bytes() != legacy_bytes:
        raise AssertionError("Retention changed an unmarked legacy backup graph")
    if not legacy.is_dir():
        raise AssertionError("Retention removed an unmarked legacy backup")


def main() -> None:
    SCOPE.mkdir(parents=True, exist_ok=False)
    CACHE.mkdir(parents=True, exist_ok=False)
    make_fake_template()
    write_json(CACHE / "retention_policy.json", make_policy())

    # All overrides are confined to this disposable runner and private cache.
    os.environ["TIXL_BRIDGE_OPERATOR_PROJECT"] = str(TEMPLATE)
    os.environ["TIXL_BRIDGE_EDITOR"] = str(EDITOR)
    os.environ["TIXL_BRIDGE_MODE"] = "offline"
    sys.path.insert(0, str(ROOT / "tests"))
    sys.path.insert(0, str(ROOT / "blender_tixl_bridge" / "source"))
    import blender_sync_benchmark as bench
    import blend_sync
    import blend_sync_graph
    import cache_publication
    from retention_lifecycle import cleanup

    blend_sync.TIXL_PROJECT = TEMPLATE
    blend_sync.TIXL_EDITOR = EDITOR
    blend_sync.wait_for_editor_pause = lambda: None
    blend_sync.editor_running = lambda: False

    run = {"schema": 1, "scope": str(SCOPE.resolve()), "privateCache": str(CACHE.resolve()),
           "measurementScope": "private unloaded cache; TiXL editor closure is simulated; no live TiXL claim",
           "blenderVersion": bpy.app.version_string, "startedUtc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "status": "running", "attempts": [], "cleanupPasses": [], "assertions": {}}
    try:
        make_fixture(bench)
        scene = bpy.context.scene
        camera = scene.camera
        project = None
        expected_timing = None
        user_graph = legacy = None
        user_graph_bytes = legacy_bytes = None
        successes = 0
        failure_record = None

        # Five successful forced exports; a sixth worker run is the deliberate
        # no-camera failure between successful exports 2 and 3.
        for index in range(1, 6):
            if index == 3:
                scene.camera = None
                save_fixture()
                try:
                    blend_sync.sync(BLEND, "generic", CACHE, Path(bpy.app.binary_path), True, False)
                except RuntimeError as error:
                    failed_metrics = getattr(error, "metrics_path", None)
                    failure_record = {"status": "failed-as-expected", "error": str(error),
                                      "metrics": failed_metrics}
                else:
                    raise AssertionError("No-camera worker unexpectedly succeeded")
                scene.camera = camera
                save_fixture()
                failed_summary_path = CACHE / "sync_logs" / "failed_run.json"
                failed_summary = json.loads(failed_summary_path.read_text(encoding="utf-8"))
                stage = CACHE / ".staging" / failed_summary["stage"]
                export_log = stage / "export.log"
                failed_run_id = failed_summary["runId"]
                parent_metrics = CACHE / "sync_metrics" / (failed_run_id + ".sync.json")
                worker_metrics = CACHE / "sync_metrics" / (failed_run_id + ".worker.json")
                if not stage.is_dir() or not export_log.is_file() or export_log.stat().st_size < 32:
                    raise AssertionError("Failed export stage or useful worker log was not retained")
                if "camera" not in export_log.read_text(encoding="utf-8", errors="replace").lower():
                    raise AssertionError("Retained worker log does not explain the camera failure")
                if not parent_metrics.is_file() or not worker_metrics.is_file():
                    raise AssertionError("Failed export parent/worker metrics were not retained")
                failure_record.update({"runId": failed_run_id, "stage": str(stage.resolve()),
                                       "exportLog": str(export_log.resolve()),
                                       "parentMetrics": str(parent_metrics.resolve()),
                                       "workerMetrics": str(worker_metrics.resolve()),
                                       "exportLogBytes": export_log.stat().st_size})
                run["failure"] = failure_record

            # Every successful iteration must launch and validate a real Blender worker.
            scene.frame_set(1)
            cube = bpy.data.objects.get("RetentionCube")
            cube.location.y = index * 0.03
            cube.keyframe_insert(data_path="location", frame=1)
            save_fixture()
            started = time.perf_counter()
            result = blend_sync.sync(BLEND, "generic", CACHE, Path(bpy.app.binary_path), True, False)
            elapsed = time.perf_counter() - started
            if result.get("status") != "rebuilt":
                raise AssertionError(f"Forced export {index} did not rebuild: {result.get('status')}")
            successes += 1
            manifest = cache_publication.read_manifest(CACHE)
            files = blend_sync_graph.generate(BLEND, CACHE, manifest)
            # Exercise the real generated-project populate and path rebinding
            # with a fake parent csproj located inside this unique run scope.
            blend_sync.ensure_generic_project(BLEND, CACHE, files, build=False, manifest=manifest)
            marker = json.loads((CACHE / "tixl_project.json").read_text(encoding="utf-8"))
            project = Path(marker["path"])
            if index == 1:
                user_graph, user_graph_bytes, legacy, legacy_bytes = create_user_evidence(project, CACHE)
                home = json.loads((project / "Symbols" / (project.name + ".t3")).read_text(encoding="utf-8"))
                expected_timing = editable_timing(home)
            else:
                check_user_evidence(project, user_graph, user_graph_bytes, legacy, legacy_bytes,
                                    expected_timing)

            cleanup_report = cleanup(CACHE, editor_is_running=False)
            run["cleanupPasses"].append({"afterExport": index,
                                        "status": cleanup_report.get("categories", {}).get("generations", {}).get("status"),
                                        "generationCount": len(list((CACHE / "generations").glob("[0-9a-f]" * 32))),
                                        "backupCount": len([p for p in (CACHE / "project_backups").iterdir() if p.is_dir()]),
                                        "stagingCount": len(list((CACHE / ".staging").iterdir())) if (CACHE / ".staging").exists() else 0})
            run["attempts"].append({"successfulExport": index, "resultStatus": result["status"],
                                    "wallSeconds": elapsed, "generation": manifest["generation"],
                                    "metrics": result.get("metrics"),
                                    "privateCacheBytes": tree_bytes(CACHE, exclude={"retention.json"})})

        pointer_evidence = current_and_previous(cache_publication, CACHE)
        if pointer_evidence["previous"] is None:
            raise AssertionError("No previous generation is recorded for recovery")
        if len(pointer_evidence["verified"]) != 2:
            raise AssertionError("Current and previous generations were not both fully verified")
        if failure_record is None:
            raise AssertionError("The deliberate failed worker run was not recorded")
        if successes != 5:
            raise AssertionError(f"Expected five successful forced exports, got {successes}")
        check_user_evidence(project, user_graph, user_graph_bytes, legacy, legacy_bytes,
                            expected_timing)

        # The first pass can conservatively pin generations through backups it
        # prunes. Confirm the next passes converge, then check every generation
        # still referenced by the current/previous pointers.
        convergence = []
        for pass_number in (1, 2, 3):
            report = cleanup(CACHE, editor_is_running=False)
            generation_root = CACHE / "generations"
            convergence.append({"pass": pass_number,
                                "generationBytes": tree_bytes(generation_root),
                                "backupBytes": tree_bytes(CACHE / "project_backups"),
                                "generationCount": len(list(generation_root.iterdir())),
                                "backupCount": len(list((CACHE / "project_backups").iterdir())),
                                "retentionStatus": report.get("categories", {}).get("generations", {}).get("status")})
        if convergence[1]["generationBytes"] != convergence[2]["generationBytes"]:
            raise AssertionError("Generated storage did not converge after two cleanup passes")
        if convergence[1]["backupBytes"] != convergence[2]["backupBytes"]:
            raise AssertionError("Backup storage did not converge after two cleanup passes")
        pointer_evidence = current_and_previous(cache_publication, CACHE)
        if len(list((CACHE / "generations").iterdir())) > 2:
            raise AssertionError("Generation retention exceeded its configured count")
        if len([p for p in (CACHE / "project_backups").iterdir()
                if p.is_dir() and (p / "bridge_backup.json").is_file()]) > 1:
            raise AssertionError("Backup retention exceeded its configured count")
        if not (CACHE / ".staging" / Path(failure_record["stage"]).name).is_dir():
            raise AssertionError("Latest failed stage was pruned")

        # Verify that the harness confined every generated artifact to its run scope.
        artifacts = [CACHE / "generations", CACHE / ".staging", CACHE / "project_backups",
                     CACHE / "sync_metrics", CACHE / "sync_logs", project,
                     TEMPLATE, EDITOR, BLEND]
        escaped = [str(path) for path in artifacts if not path.resolve().is_relative_to(SCOPE.resolve())]
        if escaped:
            raise AssertionError("Artifacts escaped the disposable validation scope: " + repr(escaped))

        run["assertions"] = {
            "fiveForcedExports": successes == 5,
            "realNoCameraFailureRecovered": failure_record["status"] == "failed-as-expected",
            "currentAndPreviousInventoriesValid": len(pointer_evidence["verified"]) == 2,
            "latestFailedEvidenceRetained": True,
            "homeTimingAndCustomFlagPreserved": True,
            "unmarkedLegacyBackupAndUserGraphPreserved": True,
            "generationCountWithinLimit": True,
            "backupCountWithinLimit": True,
            "storageConvergedAfterTwoCleanupPasses": True,
            "artifactsConfinedToUniqueScope": True,
        }
        run["generationPointers"] = pointer_evidence
        run["convergence"] = convergence
        run["artifacts"] = {"scope": str(SCOPE.resolve()), "privateCache": str(CACHE.resolve()),
                            "blend": str(BLEND.resolve()), "project": str(project.resolve()),
                            "homeGraph": str((project / "Symbols" / (project.name + ".t3")).resolve()),
                            "userGraph": str(user_graph.resolve()), "legacyBackup": str(legacy.resolve()),
                            "failedStage": failure_record["stage"], "failedExportLog": failure_record["exportLog"],
                            "failedParentMetrics": failure_record["parentMetrics"],
                            "failedWorkerMetrics": failure_record["workerMetrics"]}
        run["status"] = "passed"
    except Exception:
        run["status"] = "failed"
        run["error"] = traceback.format_exc()
    finally:
        run["endedUtc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        run["report"] = str(REPORT.resolve())
        write_json(REPORT, run)
        print("BLENDER_RETENTION_VALIDATION " + json.dumps({"status": run["status"],
              "report": str(REPORT.resolve()), "scope": str(SCOPE.resolve()),
              "successfulExports": sum(1 for row in run.get("attempts", []) if row.get("resultStatus") == "rebuilt")}),
              flush=True)
    if run["status"] != "passed":
        raise RuntimeError("Retention validation failed; see " + str(REPORT))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        sys.stdout.flush()
        os._exit(1)

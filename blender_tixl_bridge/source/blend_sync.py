"""Keep TiXL runtime caches in sync with a saved Blender project.

Examples:
  python source/blend_sync.py sync --blend path/to/project.blend
  python source/blend_sync.py watch --blend path/to/project.blend

The only authoring input is the .blend. Generated GLB/animation files are a
private cache. Blender runs out of process and never blocks a TiXL frame.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import struct
import subprocess
import time
import uuid
from contextlib import contextmanager
from collections import Counter
from pathlib import Path
from cache_publication import active_root, generation_root, read_manifest, publish_generation
from sync_metrics import count, current_run, measured_sync, phase, timed

ROOT = Path(__file__).resolve().parents[1]
BLENDER = Path(os.environ.get("TIXL_BRIDGE_BLENDER", shutil.which("blender") or "blender"))
TIXL_PROJECT = Path(os.environ.get("TIXL_BRIDGE_OPERATOR_PROJECT", ""))
TIXL_EDITOR = Path(os.environ.get("TIXL_BRIDGE_EDITOR", ""))
MODE = os.environ.get("TIXL_BRIDGE_MODE", "auto").lower()
BRIDGE_PORT = int(os.environ.get("TIXL_BRIDGE_PORT", "9042"))
if MODE not in {"auto", "offline", "debug"}:
    raise ValueError(f"Unknown TiXL bridge mode: {MODE}")


@timed("hashing")
def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
            count("hashBytes", len(block))
    return h.hexdigest()


@contextmanager
def export_lock(cache: Path):
    from process_lock import process_lock
    with phase("queue_wait"):
        lock = process_lock(cache / ".blend_sync.process.lock")
        lock.__enter__()
    try:
        if (cache / ".blend_sync.lock").exists():
            raise RuntimeError("An older-version sync lock remains. Wait for that sync to finish; "
                               "if it has exited, remove .blend_sync.lock before retrying.")
        yield
    finally:
        lock.__exit__(None, None, None)


def profile_for(blend: Path, requested: str) -> str:
    return "generic"


def cache_for(blend: Path, profile: str, requested: Path | None) -> Path:
    if requested:
        return requested.resolve()
    return blend.parent / ".tixl_cache" / blend.stem


@timed("cache_validation")
def cached_manifest(cache: Path, sha: str, blender: Path | None = None) -> dict | None:
    from export_contract import valid_contract
    try:
        data = active_root(cache)
        manifest = json.loads((data / "worlds" / "manifest.json").read_text(encoding="utf-8"))
        if not isinstance(manifest, dict) or manifest.get("generation") != data.name:
            return None
        if manifest.get("source_sha256") != sha:
            return None
        if not valid_contract(manifest.get("export_contract"), blender or BLENDER):
            return None
        for world in manifest["worlds"]:
            name = world["world"]
            for suffix in ("animation.bin", "animation.json", "channels.json", "manifest.json"):
                if not (data / "worlds" / f"{name}_{suffix}").is_file():
                    return None
            for pass_name in world["glbs"]:
                if not (data / "worlds" / f"{name}_{pass_name}.glb").is_file():
                    return None
        count("cacheBytes", sum(p.stat().st_size for p in data.rglob("*") if p.is_file()))
        return manifest
    except (ValueError, KeyError, OSError, TypeError):
        return None


def valid_cache(cache: Path, sha: str, blender: Path | None = None) -> bool:
    return cached_manifest(cache, sha, blender) is not None

@timed("validation")
def validate_stage(stage: Path, sha: str, blender: Path | None = None) -> dict:
    from export_contract import valid_contract
    from cache_validation import validate_export_payload
    worlds = stage / "worlds"
    manifest = json.loads((worlds / "manifest.json").read_text(encoding="utf-8"))
    if manifest["source_sha256"] != sha or not manifest["worlds"]:
        raise ValueError("The staged export does not match the saved Blender file")
    if not valid_contract(manifest.get("export_contract"), blender or BLENDER, require_reusable=False):
        raise ValueError("The staged export contract is stale or invalid")
    for world in manifest["worlds"]:
        name = world["world"]
        binary = worlds / f"{name}_animation.bin"
        with binary.open("rb") as stream:
            if stream.read(9) != b"TIXLANIM\x01":
                raise ValueError(f"Invalid animation cache for {name}")
            count = struct.unpack("<I", stream.read(4))[0]
        if count != world["object_count"]:
            raise ValueError(f"Object count mismatch for {name}")
        metadata = json.loads((worlds / f"{name}_animation.json").read_text(encoding="utf-8"))
        channels = json.loads((worlds / f"{name}_channels.json").read_text(encoding="utf-8"))
        for suffix in ("animation.json", "channels.json", "manifest.json"):
            json.loads((worlds / f"{name}_{suffix}").read_text(encoding="utf-8"))
        nodes, materials = set(), set()
        for part in world["glbs"]:
            with (worlds / f"{name}_{part}.glb").open("rb") as stream:
                if stream.read(4) != b"glTF":
                    raise ValueError(f"Invalid GLB for {name}/{part}")
                stream.seek(12)
                length, chunk_type = struct.unpack("<I4s", stream.read(8))
                if chunk_type != b"JSON":
                    raise ValueError(f"Missing GLB JSON for {name}/{part}")
                gltf = json.loads(stream.read(length))
                nodes.update(node["name"] for node in gltf.get("nodes", []) if "mesh" in node)
                materials.update(material["name"] for material in gltf.get("materials", []) if "name" in material)
        expected = {row["export_name"] for row in metadata["records"]}
        if nodes != expected:
            raise ValueError(f"GLB and animation node names differ for {name}")
        if any(track["export_name"] not in materials for track in channels["materials"]):
            raise ValueError(f"Animated material is missing from GLB for {name}")
    with (stage / "camera_60hz.bin").open("rb") as stream:
        samples = struct.unpack("<i", stream.read(4))[0]
        if samples < 2 or stream.seek(0, os.SEEK_END) != 4 + samples * 48:
            raise ValueError("Invalid camera rail")
    validate_export_payload(stage, manifest)
    return manifest


@timed("publication")
def publish(stage: Path, cache: Path, manifest: dict, profile: str,
            source: Path | None = None, expected_sha: str | None = None) -> dict:
    return publish_generation(stage, cache, manifest, profile, source, expected_sha)


def editor_running() -> bool:
    result = subprocess.run(["powershell", "-NoProfile", "-Command",
                             "[bool](Get-Process TiXL -ErrorAction SilentlyContinue)"],
                            capture_output=True, text=True, check=True)
    return result.stdout.strip().lower() == "true"


def require_editor_closed() -> None:
    """Defer installation rather than closing an editor with unknown save state.

    The debug protocol cannot confirm that all editor work has been saved.
    A paused transport or a successful CloseMainWindow is not that evidence.
    The user closes TiXL after saving; the next sync resumes installation.
    """
    if editor_running():
        raise RuntimeError(
            "TiXL installation deferred: save your editor work, close TiXL manually, "
            "then retry sync. The bridge will not close or terminate TiXL.")


@timed("application_start")
def start_editor(debug: bool = False) -> bool:
    if os.environ.get("TIXL_BRIDGE_LAUNCH_EDITOR", "1") == "0":
        return False
    command = [str(TIXL_EDITOR / "TiXL.exe"), "--window", "1600x900", "--no-splash"]
    if debug:
        command += ["--debug-server", str(BRIDGE_PORT)]
    subprocess.Popen(command,
                     cwd=str(TIXL_EDITOR), creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return True


def bridge_call(method: str, timeout: float = 120, **params):
    from tixl_bridge import call
    return call(method, BRIDGE_PORT, timeout=timeout, **params)


def bridge_available() -> bool:
    try:
        result = bridge_call("getVersion", timeout=5)
        return isinstance(result, dict) and result.get("protocolVersion") == 1
    except TimeoutError as error:
        raise RuntimeError("TiXL's debug bridge is busy; retry the save after the editor responds") from error
    except (OSError, ValueError, RuntimeError):
        return False


@timed("transport_wait")
def wait_for_editor_pause() -> None:
    """Keep changed cache files and symbols off TiXL's realtime path."""
    if not editor_running():
        return
    if not bridge_available():
        raise RuntimeError(f"Save your editor work and close TiXL manually, or launch it with --debug-server {BRIDGE_PORT}, before publishing a Blender cache")
    announced = False
    while True:
        try:
            context = bridge_call("getContext", timeout=10)
        except (OSError, ConnectionError):
            if not editor_running():
                return
            raise
        if not context.get("time", {}).get("isPlaying", False):
            return
        if not announced:
            print("TiXL is playing; waiting for a paused frame before publishing Blender changes", flush=True)
            announced = True
        time.sleep(0.5)


def pin_home_output(name: str) -> None:
    from blend_sync_project import _read_tixl_json
    home_path = TIXL_PROJECT.parent / name / "Symbols" / f"{name}.t3"
    if not home_path.is_file():
        return
    home = _read_tixl_json(home_path)
    if home.get("Inputs") or home.get("Outputs"):
        return
    target = next((child for child in home["Children"]
                   if child["Name"] == "Output target"
                   and child["SymbolName"].endswith(".RenderTarget")), None)
    if target:
        bridge_call("pin", childId=target["Id"])


def open_project(name: str) -> None:
    bridge_call("openProject", name=name)
    pin_home_output(name)


@timed("activation")
def open_project_when_ready(name: str) -> None:
    last_error = None
    for _ in range(45):
        try:
            open_project(name)
            verify_project_graph(name)
            return
        except (OSError, ValueError, RuntimeError) as error:
            last_error = error
            time.sleep(1)
    raise RuntimeError(f"TiXL started but could not open generated project {name}: {last_error}")


def _connection_routes(rows: list[dict], pascal_case: bool) -> dict:
    """Preserve ordering within each target's multi-input connection list."""
    fields = ("SourceParentOrChildId", "SourceSlotId", "TargetParentOrChildId", "TargetSlotId")
    if not pascal_case:
        fields = tuple(field[0].lower() + field[1:] for field in fields)
    routes = {}
    for row in rows:
        edge = tuple(row[field].lower() for field in fields)
        routes.setdefault(edge[2:], []).append(edge)
    return routes


def capture_project_graph(name: str) -> dict:
    """Snapshot reachable local symbols before a live reload, including edits."""
    from blend_sync_project import _read_tixl_json
    symbols = TIXL_PROJECT.parent / name / "Symbols"
    local = {_read_tixl_json(path)["Id"].lower(): path for path in symbols.rglob("*.t3")}
    pending = [_read_tixl_json(symbols / f"{name}.t3")["Id"].lower()]
    states = {}
    for symbol_id in pending:
        if symbol_id in states:
            continue
        state = bridge_call("getGraphState", compositionId=symbol_id, includeDefaults=False)
        if state.get("symbolId", "").lower() != symbol_id or state.get("missingChildren") or state.get("missingConnections"):
            raise RuntimeError("TiXL graph is unresolved before refresh; repair editor work before retrying sync")
        states[symbol_id] = state
        pending.extend(row["symbolId"].lower() for row in state.get("children", []) if row["symbolId"].lower() in local)
    return states


def verify_project_graph(name: str, home_state: dict | None = None, live_states: dict | None = None) -> None:
    """Read back saved home/import structure before reporting activation success.

    This never repairs user graphs or saves editor work. A mismatch requires
    a saved-work restart rather than another optimistic reload.
    """
    from blend_sync_project import _read_tixl_json
    symbols = TIXL_PROJECT.parent / name / "Symbols"
    home = symbols / f"{name}.t3"
    # Old imports can remain archived in Symbols after a project migration.
    # Validate the active home and locally defined symbols it references,
    # rather than treating every unused historical import as active output.
    local_symbols = {_read_tixl_json(path)["Id"].lower(): path for path in sorted(symbols.rglob("*.t3"))}
    expected_files = [home]
    visited = set()
    with phase("first_evaluation"):
        bridge_call("pumpFrames", count=3)
    for path in expected_files:
        expected = _read_tixl_json(path)
        symbol_id = expected["Id"].lower()
        if symbol_id in visited:
            continue
        visited.add(symbol_id)
        actual = bridge_call("getGraphState", compositionId=expected["Id"], includeDefaults=False)
        child_key = lambda row: (row["Id"].lower(), row["SymbolId"].lower())
        expected_children = Counter(child_key(row) for row in expected.get("Children", []))
        actual_children = Counter((row["childId"].lower(), row["symbolId"].lower()) for row in actual.get("children", []))
        expected_edges = _connection_routes(expected.get("Connections", []), True)
        actual_edges = _connection_routes(actual.get("connections", []), False)
        baseline = home_state if path == home else None
        generated = symbols / "PrismalLabs" / "BlenderExport" / "Generated"
        if live_states is not None and not path.is_relative_to(generated):
            baseline = live_states.get(symbol_id)
            if baseline is None:
                raise RuntimeError("TiXL live refresh introduced an unexpected user symbol; save editor work and restart before retrying sync")
        if baseline is not None:
            # Compare a live refresh against the pre-refresh editor state,
            # including unsaved user additions, routes and input overrides.
            # Only generated imports must agree with generated files on disk.
            expected_children = Counter((row["childId"].lower(), row["symbolId"].lower())
                                        for row in baseline.get("children", []))
            expected_edges = _connection_routes(baseline.get("connections", []), False)
            if (baseline.get("symbolId", "").lower() != expected["Id"].lower()
                    or baseline.get("missingChildren") or baseline.get("missingConnections")):
                raise RuntimeError("TiXL home graph is unresolved before refresh; save and repair editor work before retrying sync")
            expected_rows = Counter(json.dumps(row, sort_keys=True) for row in baseline.get("children", []))
            actual_rows = Counter(json.dumps(row, sort_keys=True) for row in actual.get("children", []))
            if expected_rows != actual_rows:
                raise RuntimeError("TiXL live refresh changed user graph state; save editor work and restart before retrying sync")
        if (actual.get("symbolId", "").lower() != expected["Id"].lower()
                or actual.get("missingChildren") or actual.get("missingConnections")
                or expected_children != actual_children or expected_edges != actual_edges):
            raise RuntimeError(
                f"TiXL graph activation failed for {path.name}: loaded structure differs "
                "from saved structure or has unresolved connections. Save editor work, "
                f"close TiXL manually, and restart with --debug-server {BRIDGE_PORT} before retrying sync.")
        for row in actual.get("children", []):
            referenced = row["symbolId"].lower()
            if referenced in local_symbols and referenced not in visited:
                expected_files.append(local_symbols[referenced])


@timed("graph_installation")
def generic_finish(blend: Path, cache: Path, manifest: dict, install: bool, refresh_runtime: bool = False) -> None:
    from blend_sync_graph import generate
    # A parent TiXL project can watch generated C# inside this checkout.
    # Keep all graph/source writes off the active transport.
    wait_for_editor_pause()
    files = generate(blend, cache, manifest)
    if not install:
        return
    if not os.environ.get("TIXL_BRIDGE_OPERATOR_PROJECT") or not os.environ.get("TIXL_BRIDGE_EDITOR"):
        raise ValueError("Set TiXL operator project and editor paths in the Blender add-on preferences")
    if not TIXL_PROJECT.is_dir() or not TIXL_EDITOR.is_dir():
        raise FileNotFoundError("TiXL operator project or editor directory not found")
    csproj = next(TIXL_PROJECT.glob("*.csproj"), None)
    if csproj is None:
        raise FileNotFoundError(f"No TiXL .csproj in {TIXL_PROJECT}")
    target = TIXL_PROJECT / "Symbols"
    operator_files = sorted((ROOT / "operators").glob("Blender*.*"))
    for stem in ("BlenderAnimationScene", "BlenderCameraTimeline", "BlenderExportLights",
                 "BlenderWorldPreload", "BlenderWorldClipTime",
                 "BlenderSourceClip", "BlenderClipSequence", "BlenderMeshSelect",
                 "BlenderMeshReplace", "BlenderTextureSelect", "BlenderTextureReplace"):
        if any(not (ROOT / "operators" / f"{stem}{suffix}").is_file()
               for suffix in (".cs", ".t3", ".t3ui")):
            raise FileNotFoundError(f"Incomplete TiXL operator: {stem}")
    install_files = operator_files
    operator_target = target / "PrismalLabs" / "BlenderExport"
    changed_operators = [file for file in install_files
                         if not (operator_target / file.name).is_file()
                         or digest(operator_target / file.name) != digest(file)
                         or (target / file.name).is_file()]
    needs_copy = bool(changed_operators)
    operator_structure_changed = any(file.suffix in {".t3", ".t3ui"}
                                     or (target / file.name).is_file()
                                     for file in changed_operators)
    def install_operators() -> None:
        operator_target.mkdir(parents=True, exist_ok=True)
        backup = cache / "project_backups" / ("operator_root_duplicates_" + uuid.uuid4().hex[:8])
        for file in install_files:
            legacy = target / file.name
            if legacy.is_file():
                backup.mkdir(parents=True, exist_ok=True)
                shutil.copy2(legacy, backup / file.name)
                legacy.unlink()
            destination = operator_target / file.name
            if not destination.is_file() or digest(destination) != digest(file):
                shutil.copy2(file, destination)
    marker = cache / "tixl_project.json"
    graph_sha = hashlib.sha256(("world-clip-lanes-v6|" + "|".join(digest(file) for file in files)).encode()).hexdigest()
    project_state = json.loads(marker.read_text(encoding="utf-8")) if marker.is_file() else {}
    needs_project = (project_state.get("graph_sha256") != graph_sha
                     or not Path(project_state.get("path", "")).is_dir())
    live = MODE != "offline" and bridge_available()
    wants_debug = MODE == "debug" or live
    # A graph written on disk cannot be safely activated by reload. Even a
    # live paused editor may contain unsaved user edits. Defer BEFORE copying
    # operators or populating the installed project; manual close/retry then
    # builds with no stale graph left in memory. Code-only reload remains live.
    if needs_project or operator_structure_changed:
        require_editor_closed()
    if not needs_copy and not needs_project and not refresh_runtime:
        if live and project_state.get("name"):
            before = capture_project_graph(project_state["name"])
            verify_project_graph(project_state["name"], live_states=before)
        return
    wait_for_editor_pause()
    # Probe the destination before interrupting an open TiXL session. In a
    # restricted caller the cache can still be built, but installation waits.
    probe = target / (".blend_sync_probe_" + uuid.uuid4().hex)
    try:
        probe.write_text("probe", encoding="utf-8")
    finally:
        probe.unlink(missing_ok=True)
    if live and project_state.get("name") and Path(project_state.get("path", "")).is_dir():
        before = capture_project_graph(project_state["name"])
        if needs_copy:
            install_operators()
            with phase("activation"):
                bridge_call("reload", project=csproj.stem)
        ensure_generic_project(blend, cache, files, build=False, manifest=manifest)
        with phase("activation"):
            bridge_call("reload", project=project_state["name"])
        # Reload must preserve the current composition, selection and output
        # pin. Reopening can discard unsaved graph edits, even on a data sync.
        verify_project_graph(project_state["name"], live_states=before)
        return
    require_editor_closed()
    success = False
    try:
        if needs_copy:
            install_operators()
            build_project(csproj)
        ensure_generic_project(blend, cache, files, manifest=manifest)
        success = True
    finally:
        if success and (needs_project or wants_debug):
            started = start_editor(debug=wants_debug)
            if started and success and wants_debug:
                project = json.loads((cache / "tixl_project.json").read_text(encoding="utf-8"))
                open_project_when_ready(project["name"])


@timed("build")
def build_project(csproj: Path) -> None:
    count("buildProcesses")
    subprocess.run(["dotnet", "build", str(csproj),
                    f"-p:T3_ASSEMBLY_PATH={TIXL_EDITOR}", "--nologo"], check=True)


def ensure_generic_project(blend: Path, cache: Path, files: list[Path], build: bool = True,
                           manifest: dict | None = None) -> None:
    from blend_sync_project import create_scaffold, populate, project_name_for
    marker = cache / "tixl_project.json"
    graph_sha = hashlib.sha256(("world-clip-lanes-v6|" + "|".join(digest(file) for file in files)).encode()).hexdigest()
    existing = None
    if marker.is_file():
        state = json.loads(marker.read_text(encoding="utf-8"))
        if Path(state["path"]).is_dir():
            if state.get("graph_sha256") == graph_sha:
                return
            existing = state
    requested = json.loads(files[3].read_text(encoding="utf-8")).get("project_name", "")
    name = existing["name"] if existing else project_name_for(blend, requested)
    path = Path(existing["path"]) if existing else TIXL_PROJECT.parent / name
    if not existing and path.exists() and any(path.iterdir()):
        raise FileExistsError(f"Requested TiXL project already exists: {path}")
    create_scaffold(path, name, TIXL_PROJECT, blend)
    probe = path / "Symbols" / (".blend_sync_probe_" + uuid.uuid4().hex)
    try:
        probe.write_text("probe", encoding="utf-8")
    finally:
        probe.unlink(missing_ok=True)
    populate(path, files, cache / "project_backups", TIXL_EDITOR, build=False)
    manifest = read_manifest(cache) if manifest is None else manifest
    from cache_bindings import rebind_project_paths
    rebind_project_paths(path, cache, manifest["generation"])
    if build:
        build_project(next(path.glob("*.csproj")))
    marker.write_text(json.dumps({"name": name, "path": str(path), "source_blend": str(blend),
                                  "graph_sha256": graph_sha}, indent=2), encoding="utf-8")


@measured_sync
def sync(blend: Path, requested_profile: str, requested_cache: Path | None,
         blender: Path, force: bool, install: bool) -> dict:
    blend = blend.resolve()
    if not blend.is_file() or blend.suffix.lower() != ".blend":
        raise FileNotFoundError(f"Saved .blend file not found: {blend}")
    profile = profile_for(blend, requested_profile)
    cache = cache_for(blend, profile, requested_cache)
    stat_before = (blend.stat().st_size, blend.stat().st_mtime_ns)
    sha = digest(blend)
    if stat_before != (blend.stat().st_size, blend.stat().st_mtime_ns):
        raise RuntimeError("Blender save was still changing; retry sync shortly")
    reusable = None if force else cached_manifest(cache, sha, blender)
    if reusable is not None:
        generic_finish(blend, cache, reusable, install)
        return {"status": "up_to_date", "blend": str(blend), "cache": str(cache), "profile": profile}
    if not blender.is_file():
        raise FileNotFoundError(f"Blender executable not found: {blender}")
    wait_for_editor_pause()
    with export_lock(cache):
        stable = (blend.stat().st_size, blend.stat().st_mtime_ns)
        sha = digest(blend)
        if stable != (blend.stat().st_size, blend.stat().st_mtime_ns):
            raise RuntimeError("Blender save changed during sync; retry on the next save")
        reusable = None if force else cached_manifest(cache, sha, blender)
        if reusable is not None:
            generic_finish(blend, cache, reusable, install)
            return {"status": "up_to_date", "blend": str(blend), "cache": str(cache), "profile": profile}
        stage = cache / ".staging" / uuid.uuid4().hex
        stage.mkdir(parents=True)
        cmd = [str(blender), "--background", str(blend), "--python", str(ROOT / "source" / "blend_sync_worker.py"),
               "--", "--staging", str(stage)]
        log = stage / "export.log"
        env = dict(os.environ)
        env.update(current_run().environment())
        count("blenderProcesses")
        with phase("blender_process"):
            with log.open("w", encoding="utf-8") as output:
                completed = subprocess.run(cmd, stdout=output, stderr=subprocess.STDOUT, env=env)
            if completed.returncode or "BLEND_SYNC_STAGE_COMPLETE" not in log.read_text(encoding="utf-8", errors="replace"):
                raise RuntimeError(f"Blender export failed; prior cache retained. See {log}")
        manifest = validate_stage(stage, sha, blender)
        wait_for_editor_pause()
        manifest = publish(stage, cache, manifest, profile, blend, sha)
        data = generation_root(cache, manifest["generation"])
        log = data / "export.log"
        count("cacheBytes", sum(p.stat().st_size for p in data.rglob("*") if p.is_file()))
        generic_finish(blend, cache, manifest, install, refresh_runtime=True)
        return {"status": "rebuilt", "blend": str(blend), "cache": str(cache),
                "profile": profile, "worlds": len(manifest["worlds"]), "log": str(log)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("sync", "watch", "status", "install"))
    parser.add_argument("--blend", required=True, type=Path)
    parser.add_argument("--profile", choices=("auto", "generic"), default="auto")
    parser.add_argument("--cache-root", type=Path)
    parser.add_argument("--blender", type=Path, default=BLENDER)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--no-install", action="store_true", help="Build cache and graph without installing into TiXL")
    parser.add_argument("--interval", type=float, default=4.0, help="Watch poll interval in seconds")
    options = parser.parse_args()
    if options.action == "status":
        blend = options.blend.resolve()
        profile = profile_for(blend, options.profile)
        cache = cache_for(blend, profile, options.cache_root)
        result = {"status": "up_to_date" if valid_cache(cache, digest(blend), options.blender) else "stale",
                  "blend": str(blend), "cache": str(cache), "profile": profile}
        print(json.dumps(result, indent=2))
        return
    if options.action == "install":
        blend = options.blend.resolve()
        profile = profile_for(blend, options.profile)
        cache = cache_for(blend, profile, options.cache_root)
        manifest = cached_manifest(cache, digest(blend), options.blender)
        if profile != "generic" or manifest is None:
            raise ValueError("Install requires an up-to-date generic Blender cache")
        generic_finish(blend, cache, manifest, True)
        print(json.dumps({"status": "installed", "blend": str(blend)}))
        return
    if options.action == "sync":
        print(json.dumps(sync(options.blend, options.profile, options.cache_root,
                              options.blender, options.force, not options.no_install), indent=2))
        return
    last_error = None
    while True:
        try:
            # Wait until a save has settled; never read a partially written blend.
            before = (options.blend.stat().st_size, options.blend.stat().st_mtime_ns)
            time.sleep(2)
            after = (options.blend.stat().st_size, options.blend.stat().st_mtime_ns)
            if before == after:
                result = sync(options.blend, options.profile, options.cache_root,
                              options.blender, False, not options.no_install)
                if result["status"] != "up_to_date":
                    print(json.dumps(result), flush=True)
            last_error = None
        except Exception as error:
            message = str(error)
            if message != last_error:
                print(json.dumps({"status": "error", "message": message}), flush=True)
                last_error = message
        time.sleep(max(1.0, options.interval))


if __name__ == "__main__":
    main()

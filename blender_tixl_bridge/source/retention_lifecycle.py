"""Retention evidence and safe cleanup at the serialized sync boundary."""
from __future__ import annotations

import contextvars
import json
import os
import re
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

from cache_retention import RetentionPolicy, prune_directories, prune_files, _has_reparse_ancestor, _is_reparse

_RUN = contextvars.ContextVar("retention_run", default=None)
GENERATION = r"[0-9a-f]{32}"
BACKUP = r"(?:[A-Za-z0-9_]+_)?[0-9a-f]{32}"
DEFAULTS = {
    "generations": {"max_count": 3, "max_bytes": 1024 * 1024 * 1024, "max_age_days": 30},
    "backups": {"max_count": 10, "max_bytes": 256 * 1024 * 1024, "max_age_days": 30},
    "staging": {"max_count": 2, "max_bytes": 512 * 1024 * 1024, "max_age_days": 7},
    "reports": {"max_count": 80, "max_bytes": 16 * 1024 * 1024, "max_age_days": 30},
    "logs": {"max_count": 20, "max_bytes": 64 * 1024 * 1024, "max_age_days": 30},
}


def atomic_json(path: Path, value: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    # Keep temporary names shorter than their payloads on Windows paths close
    # to MAX_PATH, including Blender's embedded Python runtime.
    temporary = path.with_name(".r_" + uuid.uuid4().hex[:16] + ".tmp")
    try:
        temporary.write_text(json.dumps(value, indent=2, allow_nan=False), encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def new_backup(root: Path, prefix: str = "backup") -> Path:
    """Identify newly generated backups; legacy and unmarked directories stay untouched."""
    path = root / (prefix + "_" + uuid.uuid4().hex)
    path.mkdir(parents=True, exist_ok=False)
    run = _RUN.get()
    atomic_json(path / "bridge_backup.json", {"schema": 1, "name": path.name,
                                               "runId": run["runId"] if run else None})
    if run is not None:
        run["backups"].append(path.name)
    return path


def track_stage(stage: Path):
    run = _RUN.get()
    if run is not None:
        run["stage"] = stage.name
        run["exportLog"] = str(stage / "export.log")
        atomic_json(stage / "bridge_stage.json", {"schema": 1, "stage": stage.name,
                                                   "cache": str(stage.parent.parent.resolve()),
                                                   "runId": run["runId"]})


def track_generation(generation: str):
    run = _RUN.get()
    if run is not None:
        run["generation"] = generation
        run.pop("stage", None)
        run["exportLog"] = str(Path(run["cache"]) / "generations" / generation / "export.log")


def _read(path: Path):
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("Expected retention evidence object")
    return value


def _existing(root: Path, names):
    return {name for name in names if isinstance(name, str) and (root / name).exists()}


def _checked_graphs(root: Path):
    if _has_reparse_ancestor(root):
        raise ValueError("Graph evidence has a reparse ancestor")
    if not root.exists():
        return []
    found, pending = [], [root]
    while pending:
        directory = pending.pop()
        with os.scandir(directory) as rows:
            for row in rows:
                path = Path(row.path)
                if _is_reparse(path):
                    raise ValueError("Graph evidence contains a reparse entry")
                if row.is_dir(follow_symlinks=False):
                    pending.append(path)
                elif row.is_file(follow_symlinks=False):
                    if path.suffix.lower() == ".t3":
                        found.append(path)
                else:
                    raise ValueError("Graph evidence contains a non-regular entry")
    return found


def _validate_summary(summary: dict, cache: Path):
    if (summary.get("schema") != 1 or summary.get("status") not in {"running", "passed", "failed"} or
            not isinstance(summary.get("runId"), str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", summary["runId"])):
        raise ValueError("Malformed run summary")
    backups = summary.get("backups")
    if not isinstance(backups, list) or any(not isinstance(x, str) or not re.fullmatch(BACKUP, x) for x in backups):
        raise ValueError("Malformed backup pin evidence")
    for name in backups:
        if not (cache / "project_backups" / name).is_dir():
            raise ValueError("Required recovery backup is missing")
    for key, folder in (("stage", ".staging"), ("generation", "generations")):
        value = summary.get(key)
        if value is not None:
            if not isinstance(value, str) or not re.fullmatch(GENERATION, value) or not (cache / folder / value).is_dir():
                raise ValueError("Invalid or missing recovery generation/stage")
    return summary


def _generation_pins(cache: Path):
    pins = set()
    for name in ("current_generation.json", "previous_generation.json"):
        path = cache / name
        if not path.exists():
            continue
        pointer = _read(path)
        if pointer.get("schema") != 1 or not isinstance(pointer.get("generation"), str):
            raise ValueError("Malformed generation pointer")
        for key in ("generation", "previous"):
            value = pointer.get(key)
            if value is not None:
                if not isinstance(value, str) or not re.fullmatch(GENERATION, value) or not (cache / "generations" / value).is_dir():
                    raise ValueError("Invalid or missing generation pointer target")
                pins.add(value)
    return pins


@contextmanager
def _log_lease(folder: Path):
    from process_lock import process_lock
    # The output wrapper already holds this lease in the parent process.
    if os.environ.get("TIXL_LOG_GROUP_LOCK") == str(folder.resolve()):
        yield
    else:
        with process_lock(folder / ".logging.process.lock", timeout=0):
            yield


def _references(cache: Path, project: Path | None, backups: Path):
    """Scan saved graphs and retained recovery copies; unreadable evidence blocks pruning."""
    from blend_sync_project import _read_tixl_json
    references = set()
    paths = _checked_graphs(backups)
    if project is not None:
        symbols = project / "Symbols"
        if not symbols.is_dir():
            raise ValueError("Saved project graph directory is unavailable")
        paths.extend(_checked_graphs(symbols))
    paths.extend(_checked_graphs(cache / "native_source"))
    def visit(value):
        if isinstance(value, str):
            # Values outside this cache are not adopted or removed.
            path = Path(value).resolve(strict=False)
            try:
                parts = path.relative_to(cache.resolve()).parts
            except ValueError:
                if not Path(value).is_absolute() and re.search(r"generations[/\\][0-9a-f]{32}", value):
                    raise ValueError("Relative generation reference cannot be safely assigned to this cache")
                return
            if len(parts) >= 2 and parts[0] == "generations":
                if not re.fullmatch(GENERATION, parts[1]):
                    raise ValueError("Malformed generation reference")
                references.add(parts[1])
        elif isinstance(value, dict):
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)
    for path in paths:
        if path.is_symlink() or path.resolve().is_relative_to(path.parent.resolve()) is False:
            raise ValueError("Unsafe graph evidence path")
        graph = _read_tixl_json(path)
        if not isinstance(graph, dict):
            raise ValueError("Graph evidence must be an object")
        visit(graph)
    return references


def cleanup(cache: Path, *, editor_is_running: bool, pinned_run: dict | None = None):
    """Caller holds the process lock; cleanup trouble never alters the sync outcome."""
    if _has_reparse_ancestor(cache):
        raise ValueError("Cache has a reparse ancestor; cleanup is deferred")
    cache = cache.resolve()
    config = _read(cache / "retention_policy.json") if (cache / "retention_policy.json").exists() else {}
    if set(config) - (set(DEFAULTS) | {"protected_generations", "max_log_bytes"}):
        raise ValueError("Unknown retention policy key")
    log_limit = config.get("max_log_bytes", 4 * 1024 * 1024)
    if isinstance(log_limit, bool) or not isinstance(log_limit, int) or log_limit < 1024:
        raise ValueError("max_log_bytes must be an integer of at least 1024")
    policies = {key: RetentionPolicy(**(defaults | config.get(key, {}))) for key, defaults in DEFAULTS.items()}
    protected = config.get("protected_generations", [])
    if not isinstance(protected, list) or any(not isinstance(x, str) or not re.fullmatch(GENERATION, x) for x in protected):
        raise ValueError("Invalid protected generation list")
    summaries = []
    for name in ("latest_run.json", "last_successful_run.json", "failed_run.json"):
        path = cache / "sync_logs" / name
        if path.exists():
            summaries.append(_validate_summary(_read(path), cache))
    if pinned_run:
        summaries.append(_validate_summary(pinned_run, cache))
    generation_pins = _generation_pins(cache) | set(protected)
    if any(not (cache / "generations" / name).is_dir() for name in protected):
        raise ValueError("Configured protected generation is missing")
    project = None
    if (cache / "tixl_project.json").exists():
        project = Path(_read(cache / "tixl_project.json")["path"])
    # Validate all graph evidence before any mutation. References from backups
    # removed in this pass remain conservatively pinned until the next pass.
    references = _references(cache, project, cache / "project_backups")
    generations = cache / "generations"
    for path in generations.iterdir() if generations.exists() else []:
        if not re.fullmatch(GENERATION, path.name):
            continue
        marker = _read(path / "generation_commit.json")
        manifest = _read(path / "worlds" / "manifest.json")
        if (marker.get("schema") != 1 or marker.get("generation") != path.name or
                not isinstance(marker.get("files"), dict) or not marker["files"] or manifest.get("generation") != path.name):
            raise ValueError("Malformed generated cache ownership evidence")
    report = {"schema": 1, "completedUnixSeconds": time.time(), "categories": {}}
    backups = cache / "project_backups"
    # Ownership is established only for new backups, not inferred from legacy names.
    owned_backups = []
    for path in backups.iterdir() if backups.exists() else []:
        marker = path / "bridge_backup.json"
        if re.fullmatch(BACKUP, path.name) and marker.is_file():
            evidence = _read(marker)
            if evidence.get("schema") != 1 or evidence.get("name") != path.name:
                raise ValueError("Malformed backup ownership evidence")
            owned_backups.append(path.name)
    owned_pattern = "(?:" + "|".join(re.escape(x) for x in owned_backups) + ")" if owned_backups else r"(?!)"
    backup_pins = _existing(backups, [x for summary in summaries for x in summary.get("backups", [])])
    if backups.exists():
        report["categories"]["backups"] = prune_directories(backups, cache, policies["backups"],
            name_pattern=owned_pattern, pinned_names=backup_pins, dry_run=False)
    stages = cache / ".staging"
    owned_stages = []
    for path in stages.iterdir() if stages.exists() else []:
        marker = path / "bridge_stage.json"
        if re.fullmatch(GENERATION, path.name) and marker.is_file():
            evidence = _read(marker)
            if evidence.get("schema") != 1 or evidence.get("stage") != path.name or evidence.get("cache") != str(cache):
                raise ValueError("Malformed stage ownership evidence")
            owned_stages.append(path.name)
    if stages.exists():
        report["categories"]["staging"] = prune_directories(stages, cache, policies["staging"],
            name_pattern="(?:" + "|".join(owned_stages) + ")" if owned_stages else r"(?!)",
            pinned_names=_existing(stages, [s.get("stage") for s in summaries]), dry_run=False)
    generation_pins.update(s.get("generation") for s in summaries if s.get("generation"))
    if generations.exists():
        if editor_is_running:
            report["categories"]["generations"] = {"status": "deferred", "reason": "TiXL is open; unsaved and undo references cannot be exhaustively enumerated"}
        else:
            generation_pins.update(references)
            report["categories"]["generations"] = prune_directories(generations, cache, policies["generations"],
                name_pattern=GENERATION, pinned_names=generation_pins, dry_run=False)
    run_ids = {s.get("runId") for s in summaries if s.get("runId")}
    for category, folder, pattern in (("reports", cache / "sync_metrics", r"[A-Za-z0-9_-]{1,80}\.[A-Za-z0-9_-]+\.json"),
                                      ("logs", cache / "sync_logs", r"[0-9a-f]{32}\.log(?:\.meta\.json)?")):
        if folder.exists():
            pins = {p.name for p in folder.iterdir() if any(p.name.startswith(run_id + ".") for run_id in run_ids)}
            if category == "logs":
                if (folder / "latest_failed.json").exists():
                    name = _read(folder / "latest_failed.json")["log"]
                    if not isinstance(name, str) or not re.fullmatch(r"[0-9a-f]{32}\.log", name):
                        raise ValueError("Invalid failed-log ownership evidence")
                    pins.update(_existing(folder, [name, name + ".meta.json"]))
                try:
                    with _log_lease(folder):
                        report["categories"][category] = prune_files(folder, cache, policies[category],
                            name_pattern=pattern, pinned_names=pins, dry_run=False)
                except TimeoutError:
                    report["categories"][category] = {"status": "deferred", "reason": "A child output writer still owns the log group"}
            else:
                report["categories"][category] = prune_files(folder, cache, policies[category],
                    name_pattern=pattern, pinned_names=pins, dry_run=False)
    atomic_json(cache / "sync_logs" / "retention.json", report)
    return report


@contextmanager
def retention_run(cache: Path, run_id: str, *, editor_is_running):
    lexical_cache = cache
    cache = cache.resolve()
    started = time.time()
    run = {"schema": 1, "runId": run_id, "cache": str(cache), "status": "running", "backups": [], "startedUnixSeconds": started,
           "metrics": str(cache / "sync_metrics" / (run_id + ".sync.json")),
           "log": os.environ.get("TIXL_SYNC_LOG")}
    token = _RUN.set(run)
    try:
        yield run
    except BaseException as error:
        run.update(status="failed", errorType=type(error).__name__, errorMessage=str(error)[:1024])
        raise
    else:
        run["status"] = "passed"
    finally:
        _RUN.reset(token)
        run["durationSeconds"] = time.time() - started
        try:
            if run.get("exportLog") and not Path(run["exportLog"]).is_file():
                run["exportLog"] = None
            folder = cache / "sync_logs"
            atomic_json(folder / "latest_run.json", run)
            atomic_json(folder / ("failed_run.json" if run["status"] == "failed" else "last_successful_run.json"), run)
            try:
                cleanup(lexical_cache, editor_is_running=editor_is_running(), pinned_run=run)
            except Exception as error:
                atomic_json(folder / "retention.json", {"schema": 1, "status": "deferred",
                    "reason": f"{type(error).__name__}: {error}"[:1024]})
        except Exception:
            pass  # Evidence and cleanup cannot replace a sync failure or result.

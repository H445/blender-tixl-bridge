"""Publish immutable export generations through one atomic commit pointer."""
from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import uuid
from pathlib import Path
from sync_metrics import count, timed

SCHEMA = 1
POINTER = "current_generation.json"
RECOVERY = "previous_generation.json"
MARKER = "generation_commit.json"


@timed("hashing")
def _hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
            count("hashBytes", len(block))
    return digest.hexdigest()


def _json(path: Path, value: dict) -> None:
    with path.open("w", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, allow_nan=False)
        stream.flush()
        os.fsync(stream.fileno())


def _atomic_json(path: Path, value: dict) -> None:
    temp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        _json(temp, value)
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def generation_root(cache: Path, generation: str) -> Path:
    if not isinstance(generation, str) or not re.fullmatch(r"[0-9a-f]{32}", generation):
        raise ValueError("Invalid export generation identity")
    root = cache / "generations" / generation
    if root.resolve().parent != (cache / "generations").resolve():
        raise ValueError("Export generation escapes cache directory")
    return root


def verify_generation(cache: Path, generation: str) -> Path:
    root = generation_root(cache, generation)
    marker = json.loads((root / MARKER).read_text(encoding="utf-8"))
    if not isinstance(marker, dict) or marker.get("schema") != SCHEMA or marker.get("generation") != generation:
        raise ValueError("Invalid export generation commit marker")
    inventory = marker["files"]
    if not isinstance(inventory, dict) or not inventory:
        raise ValueError("Empty export generation inventory")
    expected = {path.relative_to(root).as_posix() for path in root.rglob("*")
                if path.is_file() and path.name != MARKER}
    if set(inventory) != expected:
        raise ValueError("Export generation file membership changed")
    for relative, evidence in inventory.items():
        if not isinstance(relative, str) or not isinstance(evidence, dict):
            raise ValueError("Invalid export generation file evidence")
        path = root / relative
        if path.resolve().is_relative_to(root.resolve()) is False:
            raise ValueError("Export generation file escapes its directory")
        if path.stat().st_size != evidence["size"] or _hash(path) != evidence["sha256"]:
            raise ValueError("Export generation file changed: " + relative)
    for required in ("worlds/manifest.json", "camera_60hz.bin", "camera_timeline.json", "blend_sync_state.json"):
        if required not in inventory:
            raise ValueError("Incomplete export generation: " + required)
    return root


def active_root(cache: Path) -> Path:
    """Read one pointer snapshot; fall back only to a previously committed root."""
    for pointer_path in (cache / POINTER, cache / RECOVERY):
        try:
            pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
            if not isinstance(pointer, dict) or pointer.get("schema") != SCHEMA:
                continue
            for generation in (pointer.get("generation"), pointer.get("previous")):
                if generation is None:
                    continue
                try:
                    return verify_generation(cache, generation)
                except (OSError, ValueError, KeyError, TypeError):
                    pass
        except (OSError, ValueError, KeyError, TypeError):
            pass
    raise ValueError("No verified committed export generation; rebuild the cache")


def read_manifest(cache: Path) -> dict:
    root = active_root(cache)
    manifest = json.loads((root / "worlds" / "manifest.json").read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or manifest.get("generation") != root.name:
        raise ValueError("Export manifest generation differs from commit marker")
    return manifest


def publish_generation(stage: Path, cache: Path, manifest: dict, profile: str,
                       source: Path | None = None, expected_sha: str | None = None) -> dict:
    """Seal every payload before changing visibility; never modify published files."""
    generation = uuid.uuid4().hex
    root = generation_root(cache, generation)
    root.parent.mkdir(parents=True, exist_ok=True)
    try:
        previous = active_root(cache).name
    except ValueError:
        previous = None
    result = copy.deepcopy(manifest)
    result["generation"] = generation
    for world in result["worlds"]:
        world["glbs"] = {part: str(root / "worlds" / f'{world["world"]}_{part}.glb')
                         for part in world["glbs"]}
    _json(stage / "worlds" / "manifest.json", result)
    _json(stage / "blend_sync_state.json", {
        "generation": generation, "source_blend": result["source_blend"],
        "source_sha256": result["source_sha256"], "profile": profile,
        "worlds": [world["world"] for world in result["worlds"]],
        "camera_rail": str(root / "camera_60hz.bin"),
    })
    files = {path.relative_to(stage).as_posix(): {"size": path.stat().st_size, "sha256": _hash(path)}
             for path in sorted(stage.rglob("*")) if path.is_file() and path.name != MARKER}
    _json(stage / MARKER, {"schema": SCHEMA, "generation": generation, "files": files})
    # This rename is preparation, not publication. Readers never scan orphan roots.
    stage.replace(root)
    verify_generation(cache, generation)
    if previous is not None:
        _atomic_json(cache / RECOVERY, {"schema": SCHEMA, "generation": previous})
    if source is not None:
        before = source.stat()
        actual_sha = _hash(source)
        after = source.stat()
        if (actual_sha != expected_sha or
                (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns)):
            raise RuntimeError("Saved Blender source changed during export; prior generation retained")
    _atomic_json(cache / POINTER, {"schema": SCHEMA, "generation": generation, "previous": previous})
    return result

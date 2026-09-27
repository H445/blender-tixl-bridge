"""Migrate only bridge data-path inputs in editable, closed-editor projects."""
from __future__ import annotations

import json
import os
import uuid
from pathlib import Path

from cache_publication import generation_root, verify_generation

PATH_INPUTS = {
    "LoadGltfScene": {"292e80cf-ba31-4a50-9bf4-83712430f811"},
    "BlenderAnimationScene": {"ca02f7a3-a03a-4db0-a05d-3a66b0c9ab11", "3a4c36f9-e8c1-4ab7-b370-0f548b054933"},
    "BlenderCameraTimeline": {"0713a026-3b7b-5ddf-ac49-e585d8248fa6", "70bceb8e-15a0-592f-a01b-ff73dfac2a59"},
    "BlenderExportLights": {"e0a26c9d-fc85-59a7-88b5-1d1b0d8c5c3f"},
}


def _managed_relative(value: str, cache: Path) -> Path | None:
    # Lexical comparison retains declared aliases and does not adopt outside files.
    path = Path(os.path.abspath(value))
    try:
        relative = path.relative_to(Path(os.path.abspath(cache)))
    except ValueError:
        return None
    parts = relative.parts
    if parts and parts[0] == "generations" and len(parts) >= 3:
        try:
            generation_root(cache, parts[1])
        except ValueError:
            return None
        relative = Path(*parts[2:])
    if relative.parts and relative.parts[0] == "worlds":
        return relative
    if relative.as_posix() in {"camera_60hz.bin", "camera_timeline.json"}:
        return relative
    return None


def rebind_project_paths(project: Path, cache: Path, generation: str) -> int:
    """Preflight all bindings, then replace with rollback; caller closes TiXL first."""
    from blend_sync_project import _read_tixl_json
    root = verify_generation(cache, generation)
    changes = []
    for path in sorted((project / "Symbols").rglob("*.t3")):
        if path.relative_to(project / "Symbols").parts[:3] == ("PrismalLabs", "BlenderExport", "Generated"):
            continue
        graph = _read_tixl_json(path)
        changed = False
        for child in graph.get("Children", []):
            slots = PATH_INPUTS.get(child.get("SymbolName", "").split(".")[-1], set())
            for item in child.get("InputValues", []):
                value = item.get("Value")
                if item.get("Id") not in slots or not isinstance(value, str):
                    continue
                relative = _managed_relative(value, cache)
                if relative is None:
                    continue
                target = root / relative
                if not target.exists():
                    raise ValueError(f"New export lacks editable graph data binding: {relative}")
                if target.resolve().is_relative_to(root.resolve()) is False:
                    raise ValueError("Editable graph binding escapes export generation")
                if value != str(target):
                    item["Value"] = str(target)
                    changed = True
        if changed:
            changes.append((path, path.read_bytes(), json.dumps(graph, indent=2).encode("utf-8")))
    prepared = []
    try:
        if changes:
            backup = cache / "project_backups" / ("generation_bindings_" + uuid.uuid4().hex)
            for path, original, _ in changes:
                destination = backup / path.relative_to(project)
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(original)
        for path, original, content in changes:
            temp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
            temp.write_bytes(content)
            prepared.append((path, temp, original))
        applied = []
        try:
            for path, temp, original in prepared:
                os.replace(temp, path)
                applied.append((path, original))
        except Exception:
            for path, original in reversed(applied):
                path.write_bytes(original)
            raise
    finally:
        for _, temp, _ in prepared:
            temp.unlink(missing_ok=True)
    return len(changes)

"""Deterministic evidence for deciding whether a Blender export cache is reusable."""
from __future__ import annotations

import glob
import hashlib
import json
from pathlib import Path
from typing import Any
from sync_metrics import count, timed

EXPORT_SCHEMA = 1
SAMPLE_RATE = 60
PROFILE = "generic"
_CHUNK_SIZE = 1024 * 1024
_EXPORT_SOURCES = (
    "export_contract.py",
    "blend_sync_worker.py",
    "tixl_animation_export.py",
)


@timed("hashing")
def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(_CHUNK_SIZE), b""):
            digest.update(block)
            count("hashBytes", len(block))
    return digest.hexdigest()


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def _resolved_file(path: Path) -> tuple[str, str] | None:
    try:
        resolved = path.resolve(strict=True)
        if not resolved.is_file():
            return None
        return str(resolved), _sha256_file(resolved)
    except (OSError, RuntimeError, ValueError):
        return None


def _source_evidence(source_dir: Path | None) -> dict:
    root = (Path(source_dir) if source_dir is not None
            else Path(__file__).resolve().parent).resolve()
    files = []
    reusable = True
    for name in _EXPORT_SOURCES:
        evidence = _resolved_file(root / name)
        if evidence is None:
            reusable = False
            files.append({"path": str((root / name).resolve()), "sha256": None})
        else:
            files.append({"path": evidence[0], "sha256": evidence[1]})
    return {"root": str(root), "files": files, "reusable": reusable}


def _python_tree(root: Path) -> dict:
    """Hash a .py tree by relative name and contents, including membership."""
    # Keep the declared location so later validation follows its current target.
    root = root.absolute()
    rows = []
    reusable = root.is_dir()
    if reusable:
        try:
            for path in sorted(root.rglob("*.py"), key=lambda item: item.relative_to(root).as_posix()):
                if not path.is_file():
                    continue
                rows.append({"path": path.relative_to(root).as_posix(),
                             "sha256": _sha256_file(path)})
        except (OSError, RuntimeError, ValueError):
            reusable = False
            rows = []
    return {"root": str(root), "files": rows, "reusable": reusable and bool(rows)}


def dependency_evidence(specs: list[dict]) -> dict:
    """Return sorted, content-hashed evidence for declared external inputs."""
    evidence = []
    reusable = True
    if not isinstance(specs, list):
        return {"specs": [], "reusable": False}

    for spec in specs:
        if not isinstance(spec, dict):
            evidence.append({"kind": None, "path": None, "files": [], "reusable": False})
            reusable = False
            continue
        kind, raw_path = spec.get("kind"), spec.get("path")
        row = {"kind": kind, "path": raw_path, "files": [], "reusable": False}
        if kind not in {"file", "glob"} or not isinstance(raw_path, str):
            evidence.append(row)
            reusable = False
            continue
        try:
            declared = Path(raw_path)
            if not declared.is_absolute():
                evidence.append(row)
                reusable = False
                continue
            if kind == "file":
                matches = [declared] if declared.is_file() else []
            else:
                matches = [Path(item) for item in glob.glob(raw_path, recursive=True)]
                matches = [item for item in matches if item.is_file()]
            files = []
            for item in matches:
                pair = _resolved_file(item)
                if pair is None:
                    continue
                files.append({"declaredPath": str(item), "path": pair[0], "sha256": pair[1]})
            files.sort(key=lambda item: item["declaredPath"])
            row["files"] = files
            row["reusable"] = bool(files) and len(files) == len(matches)
        except (OSError, RuntimeError, ValueError):
            row["files"] = []
        evidence.append(row)
        reusable = reusable and row["reusable"]

    evidence.sort(key=lambda item: _canonical_bytes(item).decode("utf-8"))
    return {"specs": evidence, "reusable": reusable}


def _settings_evidence(settings: dict) -> tuple[dict, bool]:
    if not isinstance(settings, dict):
        return {"values": None, "sha256": None}, False
    values = dict(settings)
    reusable = values.get("sampleRate", SAMPLE_RATE) == SAMPLE_RATE
    reusable = reusable and values.get("profile", PROFILE) == PROFILE
    values["sampleRate"] = SAMPLE_RATE
    values["profile"] = PROFILE
    try:
        raw = _canonical_bytes(values)
    except (TypeError, ValueError, OverflowError):
        return {"values": None, "sha256": None}, False
    return {"values": values, "sha256": hashlib.sha256(raw).hexdigest()}, reusable


def build_contract(blender: Path, gltf_root: Path, settings: dict,
                   dependency_specs: list[dict], source_dir: Path | None = None) -> dict:
    """Build a fail-closed export fingerprint from the current toolchain."""
    blender_path = Path(blender)
    blender_evidence = _resolved_file(blender_path)
    blender_row = ({"path": blender_evidence[0], "sha256": blender_evidence[1]}
                   if blender_evidence else {"path": str(blender_path.resolve()), "sha256": None})
    source = _source_evidence(source_dir)
    gltf = _python_tree(Path(gltf_root))
    dependencies = dependency_evidence(dependency_specs)
    settings_row, settings_reusable = _settings_evidence(settings)
    reusable = bool(blender_evidence and source["reusable"] and gltf["reusable"]
                    and dependencies["reusable"] and settings_reusable)
    contract = {
        "schema": EXPORT_SCHEMA,
        "sampleRate": SAMPLE_RATE,
        "profile": PROFILE,
        "settings": settings_row,
        "blender": blender_row,
        "exporterSources": source,
        "gltfExporter": gltf,
        "dependencies": dependencies,
        "reusable": reusable,
    }
    return contract


def valid_contract(contract: dict, blender: Path,
                   source_dir: Path | None = None, *, require_reusable: bool = True) -> bool:
    """Re-evaluate recorded evidence. Invalid or unknown data always fails closed."""
    try:
        if not isinstance(contract, dict) or contract.get("schema") != EXPORT_SCHEMA:
            return False
        if contract.get("sampleRate") != SAMPLE_RATE or contract.get("profile") != PROFILE:
            return False
        if not isinstance(contract.get("reusable"), bool):
            return False
        settings = contract.get("settings")
        if not isinstance(settings, dict) or not isinstance(settings.get("values"), dict):
            return False
        if settings["values"].get("sampleRate") != SAMPLE_RATE:
            return False
        if settings["values"].get("profile") != PROFILE:
            return False
        expected_settings_hash = hashlib.sha256(_canonical_bytes(settings["values"])).hexdigest()
        if settings.get("sha256") != expected_settings_hash:
            return False

        blender_row = contract.get("blender")
        if not isinstance(blender_row, dict):
            return False
        current_blender = _resolved_file(Path(blender))
        if current_blender is None or blender_row != {
                "path": current_blender[0], "sha256": current_blender[1]}:
            return False

        exporter_sources = contract.get("exporterSources")
        if not isinstance(exporter_sources, dict) or exporter_sources.get("reusable") is not True:
            return False
        current_source = _source_evidence(source_dir)
        if not current_source["reusable"] or exporter_sources != current_source:
            return False

        gltf = contract.get("gltfExporter")
        if not isinstance(gltf, dict) or gltf.get("reusable") is not True:
            return False
        current_gltf = _python_tree(Path(gltf.get("root", "")))
        if not current_gltf["reusable"] or gltf != current_gltf:
            return False

        dependencies = contract.get("dependencies")
        if not isinstance(dependencies, dict) or not isinstance(dependencies.get("specs"), list):
            return False
        specs = [{"kind": row.get("kind"), "path": row.get("path")}
                 for row in dependencies.get("specs", []) if isinstance(row, dict)]
        if len(specs) != len(dependencies.get("specs", [])):
            return False
        current_dependencies = dependency_evidence(specs)
        if dependencies != current_dependencies:
            return False
        expected_reusable = current_dependencies["reusable"]
        if contract["reusable"] is not expected_reusable:
            return False
        return not require_reusable or expected_reusable
    except (OSError, RuntimeError, TypeError, ValueError, KeyError, OverflowError):
        return False

"""Validate staged Blender export payloads against the runtime file formats."""
from __future__ import annotations

import json
import math
import struct
from pathlib import Path

_ANIMATION_MAGIC = b"TIXLANIM\x01"
_ANIMATION_META_MAGIC = r"TIXLANIM\x01"
_ANIMATION_HEADER_SIZE = len(_ANIMATION_MAGIC) + 4
_RECORD_HEADER_SIZE = 12
_MATRIX_SIZE = 64
_CAMERA_RECORD_SIZE = 12 * 4
_MAX_SAMPLES = 1_000_000
_FPS = 60


def _fail(message: str) -> None:
    raise ValueError(message)


def _read_json(path: Path, description: str) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"Invalid {description}: {path.name}") from error
    if not isinstance(value, dict):
        _fail(f"Invalid {description}: {path.name} must contain an object")
    return value


def _integer(value, description: str, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        _fail(f"Invalid {description}")
    return value


def _finite_number(value, description: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _fail(f"Invalid {description}")
    number = float(value)
    if not math.isfinite(number):
        _fail(f"Non-finite {description}")
    return number


def _validate_animation(world_dir: Path, world: dict, fps: int) -> None:
    name = world.get("world")
    if not isinstance(name, str) or not name or "/" in name or "\\" in name:
        _fail("Invalid world name in export manifest")
    binary_path = world_dir / f"{name}_animation.bin"
    metadata_path = world_dir / f"{name}_animation.json"
    channels_path = world_dir / f"{name}_channels.json"
    world_manifest_path = world_dir / f"{name}_manifest.json"
    metadata = _read_json(metadata_path, "animation metadata")
    channels = _read_json(channels_path, "animation channels")
    world_manifest = _read_json(world_manifest_path, "world manifest")

    if metadata.get("magic") != _ANIMATION_META_MAGIC or metadata.get("fps") != fps:
        _fail(f"Animation metadata contract mismatch for {name}")
    if channels.get("world") != name or channels.get("fps") != fps:
        _fail(f"Animation channels contract mismatch for {name}")
    if world_manifest.get("world") != name or world_manifest.get("fps") != fps:
        _fail(f"World manifest contract mismatch for {name}")

    object_count = _integer(world.get("object_count"), f"object count for {name}")
    if world_manifest.get("object_count") != object_count:
        _fail(f"Object count differs between manifests for {name}")
    active_clip = world.get("active_clip")
    if (not isinstance(active_clip, list) or len(active_clip) != 2
            or any(isinstance(value, bool) or not isinstance(value, int) for value in active_clip)):
        _fail(f"Invalid active clip for {name}")
    clip_start, clip_end = active_clip
    if clip_start < 1 or clip_end <= clip_start:
        _fail(f"Invalid active clip range for {name}")
    if world_manifest.get("active_clip") != active_clip:
        _fail(f"Active clip differs between manifests for {name}")

    records = metadata.get("records")
    if not isinstance(records, list) or len(records) != object_count:
        _fail(f"Animation metadata record count mismatch for {name}")
    names = []
    normalized = []
    for row in records:
        if not isinstance(row, dict):
            _fail(f"Invalid animation record for {name}")
        export_name = row.get("export_name")
        if not isinstance(export_name, str) or not export_name:
            _fail(f"Invalid animation record name for {name}")
        start = _integer(row.get("start"), f"animation start frame for {name}", 1)
        count = _integer(row.get("count"), f"animation sample count for {name}", 1)
        animated = row.get("animated")
        if not isinstance(animated, bool):
            _fail(f"Invalid animation flag for {name}")
        end = start + count - 1
        if count > _MAX_SAMPLES or start < clip_start or end > clip_end:
            _fail(f"Animation record range is outside active clip for {name}")
        if not animated and count != 1:
            _fail(f"Static animation record has multiple samples for {name}")
        names.append(export_name)
        normalized.append((start, count))
    if len(set(names)) != len(names):
        _fail(f"Duplicate animation record name for {name}")

    try:
        with binary_path.open("rb") as stream:
            if stream.read(len(_ANIMATION_MAGIC)) != _ANIMATION_MAGIC:
                _fail(f"Invalid animation cache header for {name}")
            raw_count = stream.read(4)
            if len(raw_count) != 4:
                _fail(f"Truncated animation cache header for {name}")
            (binary_count,) = struct.unpack("<I", raw_count)
            if binary_count != object_count:
                _fail(f"Animation cache record count mismatch for {name}")
            for expected_index, (expected_start, expected_count) in enumerate(normalized):
                raw_header = stream.read(_RECORD_HEADER_SIZE)
                if len(raw_header) != _RECORD_HEADER_SIZE:
                    _fail(f"Truncated animation record header for {name}")
                index, start, count = struct.unpack("<III", raw_header)
                if index != expected_index or (start, count) != (expected_start, expected_count):
                    _fail(f"Animation record index or range differs from metadata for {name}")
                remaining = count * _MATRIX_SIZE
                while remaining:
                    requested = min(remaining, 64 * 1024)
                    block = stream.read(requested)
                    if len(block) != requested:
                        _fail(f"Truncated animation matrices for {name}")
                    values = struct.unpack("<" + "f" * (len(block) // 4), block)
                    if not all(math.isfinite(value) for value in values):
                        _fail(f"Non-finite animation matrix for {name}")
                    if any(values[offset + 15] != 1.0 for offset in range(0, len(values), 16)):
                        _fail(f"Invalid affine animation matrix for {name}")
                    remaining -= len(block)
            if stream.read(1):
                _fail(f"Trailing bytes in animation cache for {name}")
    except OSError as error:
        raise ValueError(f"Missing or unreadable animation cache for {name}") from error


def _validate_glb(path: Path, description: str) -> dict:
    try:
        with path.open("rb") as stream:
            header = stream.read(12)
            if len(header) != 12:
                _fail(f"Truncated GLB header for {description}")
            magic, version, declared_length = struct.unpack("<4sII", header)
            actual_length = path.stat().st_size
            if magic != b"glTF" or version != 2 or declared_length != actual_length:
                _fail(f"Invalid GLB header or declared length for {description}")
            offset = 12
            json_document = None
            chunk_index = 0
            while offset < declared_length:
                chunk_header = stream.read(8)
                if len(chunk_header) != 8:
                    _fail(f"Truncated GLB chunk header for {description}")
                chunk_length, chunk_type = struct.unpack("<I4s", chunk_header)
                offset += 8
                if chunk_length % 4 or chunk_length > declared_length - offset:
                    _fail(f"Invalid GLB chunk length for {description}")
                chunk = stream.read(chunk_length)
                if len(chunk) != chunk_length:
                    _fail(f"Truncated GLB chunk for {description}")
                if chunk_index == 0:
                    if chunk_type != b"JSON":
                        _fail(f"GLB JSON chunk is missing for {description}")
                    try:
                        json_document = json.loads(chunk.decode("utf-8"))
                    except (UnicodeError, json.JSONDecodeError) as error:
                        raise ValueError(f"Invalid GLB JSON chunk for {description}") from error
                elif chunk_type == b"JSON":
                    _fail(f"Duplicate GLB JSON chunk for {description}")
                offset += chunk_length
                chunk_index += 1
            if offset != declared_length or chunk_index == 0 or not isinstance(json_document, dict):
                _fail(f"Incomplete GLB chunks for {description}")
            return json_document
    except OSError as error:
        raise ValueError(f"Missing or unreadable GLB for {description}") from error


def _validate_camera(stage: Path, manifest: dict, camera_count: int) -> None:
    fps = manifest.get("fps")
    if fps != _FPS:
        _fail(f"Export FPS must be {_FPS}")
    timeline = _read_json(stage / "camera_timeline.json", "camera timeline")
    shots = timeline.get("shots")
    passages = timeline.get("passages")
    if not isinstance(shots, list) or not shots or not isinstance(passages, list):
        _fail("Camera timeline requires shots and passages arrays")
    duration = camera_count / fps
    previous_start = -math.inf
    for index, shot in enumerate(shots):
        if not isinstance(shot, dict):
            _fail("Invalid camera timeline shot")
        if shot.get("id") != index + 1:
            _fail("Camera timeline shot IDs are not sequential")
        start = _finite_number(shot.get("start"), "camera shot start")
        if start < 0 or start >= duration or start <= previous_start:
            _fail("Camera timeline shots are unordered or outside the camera rail")
        if not isinstance(shot.get("label"), str) or not shot["label"]:
            _fail("Camera timeline shot label is missing")
        if not isinstance(shot.get("camera"), str) or not shot["camera"]:
            _fail("Camera timeline camera name is missing")
        previous_start = start
    if _finite_number(shots[0].get("start"), "first camera shot start") != 0:
        _fail("Camera timeline does not begin at time zero")

    worlds = manifest.get("worlds")
    if not isinstance(worlds, list) or not worlds:
        _fail("Export manifest contains no worlds")
    ranges = []
    for world in worlds:
        if not isinstance(world, dict) or world.get("fps") != fps:
            _fail("World FPS differs from camera rail FPS")
        active_clip = world.get("active_clip")
        if not isinstance(active_clip, list) or len(active_clip) != 2:
            _fail("Invalid world clip in export manifest")
        start = _integer(active_clip[0], "world clip start", 1)
        end = _integer(active_clip[1], "world clip end", 1)
        if end <= start or end > camera_count + 1:
            _fail("World clip lies outside the camera rail")
        ranges.append((start, end))
    if ranges != sorted(ranges):
        _fail("World manifests are not ordered by active clip start")
    if ranges[0][0] != 1:
        _fail("World clips do not begin at source frame one")
    for previous, current in zip(ranges, ranges[1:]):
        if current[0] > previous[1] + 1:
            _fail("Gap between ordered world clips")


def validate_export_payload(stage: Path, manifest: dict) -> bool:
    """Raise ValueError for incomplete/corrupt payloads; return True when valid."""
    stage = Path(stage)
    if not isinstance(manifest, dict) or not isinstance(manifest.get("worlds"), list):
        _fail("Invalid export manifest")
    worlds = manifest["worlds"]
    if not worlds:
        _fail("Export manifest contains no worlds")
    fps = manifest.get("fps")
    if isinstance(fps, bool) or fps != _FPS:
        _fail(f"Export FPS must be {_FPS}")
    names = [world.get("world") if isinstance(world, dict) else None for world in worlds]
    if any(not isinstance(name, str) or not name for name in names) or len(set(names)) != len(names):
        _fail("Export manifest contains invalid or duplicate world names")

    world_dir = stage / "worlds"
    for world in worlds:
        _validate_animation(world_dir, world, fps)
        name = world["world"]
        metadata = _read_json(world_dir / f"{name}_animation.json", "animation metadata")
        expected_nodes = {row["export_name"] for row in metadata["records"]}
        sdf_fields = world.get("sdf_fields", [])
        if not isinstance(sdf_fields, list) or len(sdf_fields) > 32:
            _fail(f"Invalid SDF field list for {name}")
        sdf_names = set()
        for field in sdf_fields:
            if not isinstance(field, dict) or field.get("kind") not in {"sphere", "box", "torus"}:
                _fail(f"Invalid SDF field for {name}")
            label = field.get("name")
            if not isinstance(label, str) or not label or label in sdf_names:
                _fail(f"Invalid or duplicate SDF name for {name}")
            sdf_names.add(label)
            for vector_name, keys in (("center", "XYZ"), ("color", "XYZW")):
                vector = field.get(vector_name)
                if not isinstance(vector, dict) or any(
                    key not in vector or isinstance(vector[key], bool)
                    or not isinstance(vector[key], (int, float))
                    or not math.isfinite(vector[key]) for key in keys
                ):
                    _fail(f"Invalid SDF {vector_name} for {name}/{label}")
            if field["kind"] == "box":
                size = field.get("size")
                if not isinstance(size, dict) or any(
                    key not in size or isinstance(size[key], bool)
                    or not isinstance(size[key], (int, float))
                    or not math.isfinite(size[key]) or size[key] <= 0 for key in "XYZ"
                ):
                    _fail(f"Invalid SDF box size for {name}/{label}")
            else:
                for key in (("radius", "thickness") if field["kind"] == "torus" else ("radius",)):
                    number = field.get(key)
                    if isinstance(number, bool) or not isinstance(number, (int, float)) or not math.isfinite(number) or number <= 0:
                        _fail(f"Invalid SDF {key} for {name}/{label}")
                if field["kind"] == "torus" and field.get("axis") not in (0, 1, 2):
                    _fail(f"Invalid SDF axis for {name}/{label}")
        glbs = world.get("glbs")
        if not isinstance(glbs, dict) or (not glbs and not sdf_fields):
            _fail(f"World has no GLB passes: {name}")
        nodes = set()
        for part in glbs:
            if not isinstance(part, str) or not part:
                _fail(f"Invalid GLB pass for {name}")
            gltf = _validate_glb(world_dir / f"{name}_{part}.glb", f"{name}/{part}")
            for node in gltf.get("nodes", []):
                if isinstance(node, dict) and "mesh" in node and isinstance(node.get("name"), str):
                    nodes.add(node["name"])
        if nodes != expected_nodes:
            _fail(f"GLB and animation node names differ for {name}")

    camera_path = stage / "camera_60hz.bin"
    try:
        with camera_path.open("rb") as stream:
            raw_count = stream.read(4)
            if len(raw_count) != 4:
                _fail("Truncated camera rail header")
            (camera_count,) = struct.unpack("<i", raw_count)
            if camera_count < 2 or camera_count > _MAX_SAMPLES:
                _fail("Invalid camera rail sample count")
            expected_size = 4 + camera_count * _CAMERA_RECORD_SIZE
            if camera_path.stat().st_size != expected_size:
                _fail("Camera rail length does not match its sample count")
            remaining = camera_count * _CAMERA_RECORD_SIZE
            while remaining:
                block = stream.read(min(remaining, 64 * 1024))
                if not block or len(block) % 4:
                    _fail("Truncated camera rail samples")
                values = struct.unpack("<" + "f" * (len(block) // 4), block)
                if not all(math.isfinite(value) for value in values):
                    _fail("Camera rail contains non-finite samples")
                remaining -= len(block)
    except OSError as error:
        raise ValueError("Missing or unreadable camera rail") from error
    _validate_camera(stage, manifest, camera_count)
    return True

"""Describe static Blender SDF proxies for native TiXL field operators.

Set ``object['tixl_sdf']`` to sphere, box, or torus. The object may be a mesh
or an Empty; its rendered Blender mesh is replaced by TiXL's analytic field.
Arbitrary Geometry Nodes SDF grids remain evaluated meshes when converted to
mesh in Blender, since TiXL has no compatible grid loader in this bridge.
"""

from __future__ import annotations

import math


SUPPORTED = {"sphere", "box", "torus"}
MAX_FIELDS_PER_WORLD = 32


def kind(obj):
    raw = obj.get("tixl_sdf")
    if raw is None or str(raw).strip() == "":
        return None
    result = str(raw).strip().lower()
    if result not in SUPPORTED:
        raise ValueError(f"{obj.name}: unsupported tixl_sdf {raw!r}; use sphere, box, or torus")
    return result


def _xyz(vector):
    # Match the bridge's C * Blender matrix * C^-1 coordinate conversion.
    return {"X": round(float(vector.x), 6), "Y": round(float(vector.z), 6),
            "Z": round(-float(vector.y), 6)}


def _static(obj):
    def animated(item):
        data = item.animation_data
        return bool(data and (data.action or data.drivers or
                              any(track.strips for track in data.nla_tracks)))
    if animated(obj):
        raise ValueError(f"{obj.name}: animated native SDF proxies are not supported")
    if obj.constraints:
        raise ValueError(f"{obj.name}: constrained native SDF proxies are not supported")
    parent = obj.parent
    while parent:
        if animated(parent) or parent.constraints:
            raise ValueError(f"{obj.name}: animated or constrained SDF parent is not supported")
        parent = parent.parent


def describe(obj):
    shape = kind(obj)
    if shape is None:
        return None
    _static(obj)
    from mathutils import Vector
    position = _xyz(obj.matrix_world.translation)
    scale = obj.matrix_world.to_scale()
    if any(not math.isfinite(float(v)) or float(v) <= 0 for v in scale):
        raise ValueError(f"{obj.name}: SDF scale must be positive and finite")
    if shape in {"sphere", "torus"} and max(scale) - min(scale) > 1e-4:
        raise ValueError(f"{obj.name}: {shape} SDF requires uniform scale")
    if shape == "box":
        rotation = obj.matrix_world.to_quaternion()
        if abs(rotation.w) < 1 - 1e-5 or any(abs(v) > 1e-5 for v in (rotation.x, rotation.y, rotation.z)):
            raise ValueError(f"{obj.name}: box SDF rotation is not supported by TiXL BoxSDF")
        size = [float(v) for v in obj.dimensions]
        if min(size) <= 0:
            size = [2 * float(v) for v in scale]
        # A Blender unit cube's scaled dimensions are the full width.
        result = {"name": obj.name, "kind": shape, "center": position,
                  "size": {"X": round(size[0], 6), "Y": round(size[2], 6),
                           "Z": round(size[1], 6)}}
    elif shape == "sphere":
        radius = float(obj.get("tixl_sdf_radius", 0.5)) * float(scale.x)
        if not math.isfinite(radius) or radius <= 0:
            raise ValueError(f"{obj.name}: SDF radius must be positive")
        result = {"name": obj.name, "kind": shape, "center": position,
                  "radius": round(radius, 6)}
    else:
        radius = float(obj.get("tixl_sdf_radius", 0.5)) * float(scale.x)
        thickness = float(obj.get("tixl_sdf_thickness", 0.08)) * float(scale.x)
        if not all(math.isfinite(v) and v > 0 for v in (radius, thickness)):
            raise ValueError(f"{obj.name}: SDF torus radii must be positive")
        normal = obj.matrix_world.to_3x3() @ Vector((0, 0, 1))
        converted = Vector((normal.x, normal.z, -normal.y)).normalized()
        axis = max(range(3), key=lambda i: abs(converted[i]))
        if abs(converted[axis]) < 1 - 1e-4:
            raise ValueError(f"{obj.name}: torus SDF axis must align with X, Y, or Z")
        result = {"name": obj.name, "kind": shape, "center": position,
                  "radius": round(radius, 6), "thickness": round(thickness, 6),
                  "axis": axis}
    raw_color = obj.get("tixl_sdf_color", (0.4, 0.8, 1.0, 1.0))
    if len(raw_color) != 4 or any(not math.isfinite(float(v)) for v in raw_color):
        raise ValueError(f"{obj.name}: tixl_sdf_color must have four finite components")
    result["color"] = {key: float(v) for key, v in zip("XYZW", raw_color)}
    return result


def collect(collection):
    fields = [describe(obj) for obj in collection.all_objects
              if kind(obj) is not None and not obj.hide_render]
    fields.sort(key=lambda item: item["name"])
    if len(fields) > MAX_FIELDS_PER_WORLD:
        raise ValueError(f"Too many native SDF fields ({len(fields)}); limit is {MAX_FIELDS_PER_WORLD}")
    return fields

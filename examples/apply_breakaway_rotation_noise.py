"""Add reproducible, scene-driven tumbling to Blender mesh breakups.

Execute through Blender MCP. ``apply_rotation_noise`` accepts any collection
of animated mesh objects and frame windows; the Asterion recipe at the bottom
uses its tagged reusable craft parts. The bridge samples these F-curve
modifiers at 60 Hz when it exports object transforms to TiXL.
"""

from __future__ import annotations

import hashlib
from collections import Counter

import bpy


PREFIX = "Bridge breakup rotation | "
ASTERION_WINDOWS = (
    ("combat to explorer", 1441, 2161),
    ("explorer to hauler", 3601, 4321),
    ("hauler to combat", 5761, 6481),
)


def random_unit(*values: object) -> float:
    token = "|".join(map(str, values)).encode("utf-8")
    return int.from_bytes(hashlib.blake2b(token, digest_size=8).digest(), "big") / 2**64


def rotation_curves(obj: bpy.types.Object):
    animation = obj.animation_data
    if animation is None or animation.action is None:
        raise ValueError(f"{obj.name} has no animation action")
    action = animation.action
    if hasattr(action, "fcurves"):
        curves = action.fcurves
    else:
        if animation.action_slot is None:
            raise ValueError(f"{obj.name} has no action slot")
        curves = [curve
                  for layer in action.layers
                  for strip in layer.strips
                  for bag in [strip.channelbag(animation.action_slot)]
                  if bag is not None
                  for curve in bag.fcurves]
    result = {curve.array_index: curve for curve in curves
              if curve.data_path == "rotation_euler"}
    if set(result) != {0, 1, 2}:
        raise ValueError(f"{obj.name} needs keyed XYZ Euler rotations")
    return result


def apply_rotation_noise(objects, windows, *, seed="bridge-breakup-v1") -> dict:
    """Animate every supplied mesh, leaving poses outside the windows intact."""
    windows = tuple(windows)
    if not windows or any(end <= start + 180 for _, start, end in windows):
        raise ValueError("Breakup windows must have at least 180 frames")
    if any(windows[i][2] >= windows[i+1][1] for i in range(len(windows)-1)):
        raise ValueError("Breakup windows must be ordered and nonoverlapping")
    objects = sorted(objects, key=lambda obj: obj.name)
    if not objects or any(obj.type != "MESH" for obj in objects):
        raise ValueError("Supply animated mesh objects")
    if len({obj.name for obj in objects}) != len(objects):
        raise ValueError("Mesh object names must be unique")

    # Resolve every action first, so a missing rotation channel cannot leave
    # half the scene updated. Reapplying replaces only our own modifiers.
    targets = [(obj, rotation_curves(obj)) for obj in objects]
    counts = Counter()
    for obj, curves in targets:
        size = max(obj.dimensions.length, 0.01)
        mass_factor = max(0.45, min(1.35, 1.35 / (0.6 + size * 0.45)))
        for axis, curve in curves.items():
            for modifier in list(curve.modifiers):
                if modifier.name.startswith(PREFIX):
                    curve.modifiers.remove(modifier)
            for label, start, end in windows:
                modifier = curve.modifiers.new("NOISE")
                modifier.name = f"{PREFIX}{label} | XYZ"[0:63]
                modifier.blend_type = "ADD"
                modifier.use_restricted_range = True
                modifier.frame_start = start
                modifier.frame_end = end
                modifier.blend_in = 42
                modifier.blend_out = 90
                modifier.scale = 145 + 105 * random_unit(seed, obj.name, label, axis, "speed")
                modifier.strength = (0.62 + 0.62 * random_unit(
                    seed, obj.name, label, axis, "strength")) * mass_factor
                modifier.phase = 1000 * random_unit(seed, obj.name, label, axis, "phase")
                modifier.depth = 2
                modifier.roughness = 0.45
                modifier.lacunarity = 2.0
                counts[label] += 1
    return {"objects": len(objects), "windows": len(windows),
            "rotationModifiers": sum(counts.values()), "perWindow": dict(counts)}


if __name__ == "__main__":
    scene = bpy.context.scene
    result = apply_rotation_noise(
        (obj for obj in scene.objects if obj.get("asterion_part", False)),
        ASTERION_WINDOWS,
    )
    scene["breakup_rotation_noise"] = (
        "Per-part seeded XYZ F-curve noise in three breakup windows; "
        "smooth blend to each assembled ship"
    )
    print("ASTERION_ROTATION_NOISE", result)

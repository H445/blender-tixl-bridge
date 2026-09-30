"""Keyframe HDR thruster emission against the existing flight and 120 BPM clock.

Execute through the official Blender MCP TCP extension on AsterionBreakaway.blend.
The TiXL animation exporter samples these material values at 60 Hz. The TiXL
Home graph then blooms the HDR render before tone mapping.
"""

import math

import bpy


scene = bpy.context.scene
fps = scene.render.fps / scene.render.fps_base
assert abs(fps - 60.0) < 1e-6 and scene.frame_end == 6481
core_objects = sorted((obj for obj in bpy.data.objects
                       if obj.name.startswith("THRUST | core ")), key=lambda o: o.name)
assert len(core_objects) == 6

materials = {
    "core": bpy.data.materials["STORY | ice-blue exhaust core"],
    "plasma": bpy.data.materials["STORY | cobalt exhaust"],
}
sockets = {
    "core": materials["core"].node_tree.nodes["Emission"].inputs["Strength"],
    "plasma": materials["plasma"].node_tree.nodes["Principled BSDF"].inputs["Emission Strength"],
}
materials["core"].node_tree.nodes["Emission"].inputs["Color"].default_value = (
    .22, .72, 1.0, 1.0)
for material in materials.values():
    tree = material.node_tree
    if tree.animation_data:
        if not material.get("asterion_hdr_pulse_v1"):
            raise RuntimeError(f"Preserving unrelated material animation: {material.name}")
        tree.animation_data_clear()


def pulse_at(second):
    # One low-amplitude, smooth onset per 120 BPM quarter note. The exact
    # 108-second endpoint matches zero, including pulse phase.
    phase = (second * 2.0) % 1.0
    return 1.0 + .07 * ((1.0 + math.cos(math.tau * phase)) * .5) ** 6


before = (scene.frame_current, scene.frame_subframe)
samples = []
try:
    for frame in range(1, scene.frame_end + 1, 3):
        scene.frame_set(frame)
        second = (frame - 1) / fps
        length = sum(max(obj.scale.y, 0.0) for obj in core_objects) / 6.0
        width = sum(max(obj.scale.x, 0.0) for obj in core_objects) / 6.0
        # Transform scale already encodes speed, steering, warp and breakaway.
        # Shared material strength follows average throttle; individual engine
        # lengths keep their differential steering response.
        visible = min(1.0, width / .4)
        beat = pulse_at(second)
        core = min(7.0, 2.5 + .38 * length) * visible * beat
        plasma = min(3.0, .85 + .17 * length) * visible * beat
        for name, value in (("core", core), ("plasma", plasma)):
            socket = sockets[name]
            socket.default_value = value
            socket.keyframe_insert(data_path="default_value", frame=frame)
        if frame in (1, 781, 1621, 4021, 5221, 6481):
            samples.append((round(second, 3), round(core, 3), round(plasma, 3)))
finally:
    scene.frame_set(before[0], subframe=before[1])

for material in materials.values():
    material["asterion_hdr_pulse_v1"] = True
    action = material.node_tree.animation_data.action
    curves = (list(action.fcurves) if hasattr(action, "fcurves") else
              [curve for layer in action.layers for strip in layer.strips
               for bag in strip.channelbags for curve in bag.fcurves])
    for curve in curves:
        for key in curve.keyframe_points:
            key.interpolation = "LINEAR"

assert abs(samples[0][1] - samples[-1][1]) < .002
assert abs(samples[0][2] - samples[-1][2]) < .002
scene["thruster_hdr"] = (
    "Six reused exhaust assemblies carry material emission keyed from flight "
    "throttle, warp and breakaway, with a restrained 120 BPM brightness pulse. "
    "TiXL blooms their HDR light before tone mapping."
)
print("ASTERION_THRUSTER_HDR", {"keyframesPerMaterial": 2161, "samples": samples})

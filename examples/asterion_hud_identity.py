"""Add restrained Prismal Labs / H445 identity to Asterion's camera HUD.

Run ``add_identity()`` through Blender MCP after the mission HUD exists. The
function replaces only its own objects, so it can update an authored .blend
without rebuilding telemetry or changing TiXL Home graph edits.
"""

from __future__ import annotations

import bpy


HUD_COLLECTION = "05 HUD | mission telemetry"
PREFIX = "HUD | identity"
SAFE = .80
FLASH_SECONDS = (8.0, 12.0, 24.0, 36.0, 43.0, 58.0, 72.0, 84.0, 90.0, 104.0)


def _material(name: str, color: tuple[float, float, float], strength: float):
    material = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    material.use_nodes = True
    nodes = material.node_tree.nodes
    nodes.clear()
    output = nodes.new("ShaderNodeOutputMaterial")
    emission = nodes.new("ShaderNodeEmission")
    emission.inputs["Color"].default_value = (*color, 1.0)
    emission.inputs["Strength"].default_value = strength
    material.node_tree.links.new(emission.outputs[0], output.inputs["Surface"])
    return material


def _text(hud, camera, name, label, x, y, size, material, *, right=False, depth=-1.982):
    curve = bpy.data.curves.new(name, "FONT")
    curve.body = label
    curve.size = size * SAFE
    curve.align_x = "RIGHT" if right else "LEFT"
    curve.space_character = 1.12
    obj = bpy.data.objects.new(name, curve)
    hud.objects.link(obj)
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.convert(target="MESH")
    obj = bpy.context.view_layer.objects.active
    obj.data.materials.append(material)
    obj.parent = camera
    obj.location = (x * SAFE, y * SAFE, depth)
    obj["asterion_hud"] = True
    obj["asterion_identity"] = True
    obj["hud_text"] = label
    return obj


def _plate(hud, camera, name, x, y, width, height, material, depth=-1.987):
    mesh = bpy.data.meshes.new(name)
    w, h = width * SAFE, height * SAFE
    mesh.from_pydata([(0, 0, 0), (w, 0, 0), (w, h, 0), (0, h, 0)],
                     [], [(0, 1, 2, 3)])
    mesh.materials.append(material)
    obj = bpy.data.objects.new(name, mesh)
    hud.objects.link(obj)
    obj.parent = camera
    obj.location = (x * SAFE, y * SAFE, depth)
    obj["asterion_hud"] = True
    obj["asterion_identity"] = True
    return obj


def _flash(obj, times, fps: float, final_frame: int, start_offset=0, duration=7):
    obj.scale = (0, 0, 0)
    obj.keyframe_insert("scale", frame=1)
    for seconds in times:
        first = round(seconds * fps) + 1 + start_offset
        last = min(final_frame - 1, first + duration)
        obj.scale = (0, 0, 0)
        obj.keyframe_insert("scale", frame=first - 1)
        obj.scale = (1, 1, 1)
        obj.keyframe_insert("scale", frame=first)
        obj.scale = (0, 0, 0)
        obj.keyframe_insert("scale", frame=last)
    obj.scale = (0, 0, 0)
    obj.keyframe_insert("scale", frame=final_frame)
    action = obj.animation_data.action
    curves = (action.fcurves if hasattr(action, "fcurves") else
              [curve for layer in action.layers for strip in layer.strips
               for bag in strip.channelbags for curve in bag.fcurves])
    for curve in curves:
        for key in curve.keyframe_points:
            key.interpolation = "CONSTANT"


def add_identity() -> dict:
    scene = bpy.context.scene
    camera = scene.camera
    hud = bpy.data.collections.get(HUD_COLLECTION)
    if hud is None or camera is None or not bpy.data.filepath:
        raise RuntimeError("Open the saved Asterion scene with its camera-mounted HUD")
    if scene.frame_end != 6481 or scene.render.fps / scene.render.fps_base != 60:
        raise RuntimeError("Asterion's 108-second, 60 Hz loop changed")
    selected = tuple(bpy.context.selected_objects)
    active = bpy.context.view_layer.objects.active
    frame = scene.frame_current
    for obj in list(hud.objects):
        if obj.get("asterion_identity") or obj.name.startswith(PREFIX):
            bpy.data.objects.remove(obj, do_unlink=True)
    for datablocks in (bpy.data.meshes, bpy.data.curves):
        for block in list(datablocks):
            if block.users == 0 and block.name.startswith(PREFIX):
                datablocks.remove(block)
    ice = bpy.data.materials.get("HUD | ice-white typography")
    cyan = bpy.data.materials.get("HUD | signal cyan")
    if ice is None or cyan is None:
        raise RuntimeError("Mission HUD materials are missing")
    dark = _material("HUD | identity negative plate", (.002, .007, .012), 1.0)
    pale = _material("HUD | identity low-key credit", (.19, .48, .60), 1.25)
    try:
        # A persistent systems credit, aligned with the existing lower HUD rail.
        _plate(hud, camera, f"{PREFIX} Prismal Labs backing",
               .545, -.559, .426, .041, dark, depth=-1.984)
        _text(hud, camera, f"{PREFIX} Prismal Labs credit",
              "PRISMAL LABS  /  MISSION SYSTEMS", .96, -.547, .023,
              pale, right=True)
        # The callsign is an inverse-video telemetry fault, not a title card.
        plate = _plate(hud, camera, f"{PREFIX} H445 reverse plate",
                       -.089, .462, .178, .043, dark)
        label = _text(hud, camera, f"{PREFIX} H445 callsign",
                      "H445", -.047, .468, .027, ice)
        ghost = _text(hud, camera, f"{PREFIX} H445 displaced signal",
                      "H445", -.043, .471, .027, cyan, depth=-1.979)
        fps = scene.render.fps / scene.render.fps_base
        _flash(plate, FLASH_SECONDS, fps, scene.frame_end, duration=8)
        _flash(label, FLASH_SECONDS, fps, scene.frame_end, duration=7)
        _flash(ghost, FLASH_SECONDS, fps, scene.frame_end, start_offset=2, duration=3)
        scene["mission_hud_identity"] = (
            "Prismal Labs systems credit in the lower HUD; H445 inverse-video "
            "call sign flickers on ten mission beats and vanishes at the loop seam")
        return {"identityObjects": 5, "flashes": len(FLASH_SECONDS),
                "staticCredit": "PRISMAL LABS  /  MISSION SYSTEMS"}
    finally:
        bpy.ops.object.select_all(action="DESELECT")
        for obj in selected:
            if obj.name in bpy.data.objects:
                obj.select_set(True)
        if active and active.name in bpy.data.objects:
            bpy.context.view_layer.objects.active = active
        scene.frame_set(frame)

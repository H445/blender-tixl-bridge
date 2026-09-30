"""Add opening and closing Prismal Labs / H445 credits to Asterion's HUD.

Run ``add_identity()`` through Blender MCP after the mission HUD exists. The
function replaces only its own objects, so it can update an authored .blend
without rebuilding telemetry or changing TiXL Home graph edits.
"""

from __future__ import annotations

import bpy


HUD_COLLECTION = "05 HUD | mission telemetry"
PREFIX = "HUD | identity"
SAFE = .88
OPENING_SECONDS = (0.45,)
ENDING_SECONDS = (104.35,)


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


def _reveal(obj, times, fps, final_frame, *, phase=0, echo=False):
    """Key a fragmented entrance and geometric fade without material animation."""
    base = obj.location.copy()
    obj.scale = (0, 0, 0)
    obj.keyframe_insert("scale", frame=1)
    obj.keyframe_insert("location", frame=1)
    if echo:
        shape = ((-1, 0, 0, 0), (0, 1, -.018, .007),
                 (3, 0, .012, -.004), (6, 1, .009, .003),
                 (13, 0, 0, 0), (125, 0, 0, 0),
                 (129, .75, -.012, .005), (137, 0, 0, 0))
    else:
        shape = ((-2, 0, 0, 0), (0, .08, -.075, 0),
                 (3, 1.18, .018, 0), (5, 0, 0, 0),
                 (8, .85, -.009, 0), (12, 1, 0, 0),
                 (125, 1, 0, 0), (136, .85, .009, 0),
                 (151, .48, .026, 0), (167, .12, .052, 0),
                 (178, 0, .075, 0))
    for seconds in times:
        first = round(seconds*fps)+1+phase
        for offset, magnitude, dx, dy in shape:
            frame = min(final_frame-1, first+offset)
            obj.scale = (magnitude, magnitude, magnitude)
            obj.location = (base.x+dx, base.y+dy, base.z)
            obj.keyframe_insert("scale", frame=frame)
            obj.keyframe_insert("location", frame=frame)
    obj.scale = (0, 0, 0)
    obj.location = base
    obj.keyframe_insert("scale", frame=final_frame)
    obj.keyframe_insert("location", frame=final_frame)
    action = obj.animation_data.action
    curves = (action.fcurves if hasattr(action, "fcurves") else
              [curve for layer in action.layers for strip in layer.strips
               for bag in strip.channelbags for curve in bag.fcurves])
    for curve in curves:
        for key in curve.keyframe_points:
            key.interpolation = "LINEAR"


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
    pale = _material("HUD | identity low-key credit", (.19, .48, .60), 1.25)
    try:
        # A persistent systems credit, aligned with the existing lower HUD rail.
        _text(hud, camera, f"{PREFIX} Prismal Labs credit",
              "PRISMAL LABS  /  MISSION SYSTEMS", .96, -.547, .023,
              pale, right=True)
        red = _material("HUD | identity magenta echo", (.70, .025, .42), 1.5)
        fps = scene.render.fps / scene.render.fps_base
        credits = (
            ("opening", "H445 / Prismal Labs", OPENING_SECONDS,
             -.36, .065, .069, -.39, .045, .78),
            ("ending", "H445", ENDING_SECONDS,
             -.115, .065, .11, -.16, .045, .34),
        )
        for credit_name, wording, times, x, y, size, plate_x, plate_y, width in credits:
            label = _text(hud, camera, f"{PREFIX} {credit_name} title",
                          wording, x, y, size, ice)
            ghost = _text(hud, camera, f"{PREFIX} {credit_name} cyan echo",
                          wording, x+.006, y+.004, size, cyan,
                          depth=-1.979)
            magenta_ghost = _text(
                hud, camera, f"{PREFIX} {credit_name} magenta echo",
                wording, x-.006, y-.004, size, red, depth=-1.977)
            _reveal(label, times, fps, scene.frame_end, phase=4)
            _reveal(ghost, times, fps, scene.frame_end, phase=1, echo=True)
            _reveal(magenta_ghost, times, fps, scene.frame_end,
                    phase=3, echo=True)
            for index in range(10):
                bar = _plate(hud, camera,
                             f"{PREFIX} {credit_name} scan fragment {index:02d}",
                             plate_x-.02+(index % 3)*.036,
                             plate_y+index*.014,
                             width*.80-(index % 4)*.06, .0035,
                             cyan if index % 2 else red, depth=-1.976)
                _flash(bar, times, fps, scene.frame_end,
                       start_offset=(index*3) % 13, duration=9+index % 4)
        scene["mission_hud_identity"] = (
            "Prismal Labs systems credit in the lower HUD; an opening "
            "H445 / Prismal Labs title and closing H445 title use layered "
            "glitch reveals and clear before the 108-second loop seam")
        return {"identityObjects": 1 + len(credits)*13,
                "credits": ("H445 / Prismal Labs", "H445"),
                "staticCredit": "PRISMAL LABS  /  MISSION SYSTEMS"}
    finally:
        bpy.ops.object.select_all(action="DESELECT")
        for obj in selected:
            if obj.name in bpy.data.objects:
                obj.select_set(True)
        if active and active.name in bpy.data.objects:
            bpy.context.view_layer.objects.active = active
        scene.frame_set(frame)

"""Add an animated, camera-mounted mission HUD to AsterionBreakaway.

Run through Blender MCP after ``add_asterion_story.py``. Text is converted to
mesh so the standard Blender-to-TiXL export carries it without custom nodes.
The overlay has the same pose at 0 and 108 seconds for the project loop.
"""

import math

import bpy
from mathutils import Vector


scene = bpy.context.scene
camera = scene.camera
assert camera and scene.render.fps == 60 and scene.frame_end == 6481

old = bpy.data.collections.get("05 HUD | mission telemetry")
if old:
    for obj in list(old.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    bpy.data.collections.remove(old)
hud = bpy.data.collections.new("05 HUD | mission telemetry")
scene.collection.children.link(hud)


def glow(name, color, strength):
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    nodes.clear()
    out = nodes.new("ShaderNodeOutputMaterial")
    emission = nodes.new("ShaderNodeEmission")
    emission.inputs["Color"].default_value = (*color, 1)
    emission.inputs["Strength"].default_value = strength
    mat.node_tree.links.new(emission.outputs[0], out.inputs["Surface"])
    return mat


white = glow("HUD | ice-white typography", (.67, .82, .91), 1.8)
cyan = glow("HUD | signal cyan", (.05, .62, .85), 2.4)
amber = glow("HUD | cargo amber", (1.0, .38, .08), 2.0)
dim = glow("HUD | graphite rails", (.018, .055, .075), 1.0)


def text_mesh(name, label, x, y, size, material, right=False):
    curve = bpy.data.curves.new(name, "FONT")
    curve.body = label
    curve.size = size
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
    obj.location = (x, y, -2.0)
    obj["asterion_hud"] = True
    obj["hud_text"] = label
    return obj


def rectangle(name, x, y, width, height, material, depth=-2.005):
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata([(0, 0, 0), (width, 0, 0),
                      (width, height, 0), (0, height, 0)],
                     [], [(0, 1, 2, 3)])
    mesh.materials.append(material)
    obj = bpy.data.objects.new(name, mesh)
    hud.objects.link(obj)
    obj.parent = camera
    obj.location = (x, y, depth)
    obj["asterion_hud"] = True
    return obj


def animation_curves(obj):
    action = obj.animation_data.action if obj.animation_data else None
    if action is None:
        return []
    if hasattr(action, "fcurves"):
        return list(action.fcurves)
    return [curve for layer in action.layers for strip in layer.strips
            for bag in strip.channelbags for curve in bag.fcurves]


def key_scale(obj, keys):
    for second, value in keys:
        obj.scale = (value, value, value)
        obj.keyframe_insert("scale", frame=round(second*60)+1)
    for curve in animation_curves(obj):
        for point in curve.keyframe_points:
            point.interpolation = "BEZIER"


def interval_keys(start, end):
    keys = [(0, 0)]
    if start == 0:
        keys = [(0, 1)]
    else:
        keys += [(max(0, start-.35), 0), (start+.3, 1)]
    keys += [(max(start+.3, end-.55), 1), (min(108, end+.15), 0)]
    if end < 108:
        keys.append((108, 0))
    return keys


# Sparse, fixed corner furniture frames each mission caption without covering
# the spacecraft or the two planets. The cyan bar is a looping route indicator.
text_mesh("HUD | mission identifier", "ASTERION / RESCUE VECTOR", -.96, .49,
          .039, white)
text_mesh("HUD | navigation label", "DEEP SPACE / LIVE MISSION", -.96, .434,
          .024, cyan)
text_mesh("HUD | core heading", "MOON CORE STATUS", .96, .49,
          .028, white, right=True)
rectangle("HUD | upper left rule", -.96, .416, .46, .004, cyan)
rectangle("HUD | upper right rule", .57, .416, .39, .004, amber)
rectangle("HUD | route rail", -.96, -.574, 1.92, .004, dim)
progress = rectangle("HUD | route progress", -.96, -.574, 1.92, .004, cyan,
                     depth=-1.999)
for fraction in (0, .25, .5, .75, 1):
    rectangle(f"HUD | route tick {fraction:.2f}", -.96+1.92*fraction,
              -.579, .003, .014, white)
for second, amount in ((0, .003), (11, .10), (24, .22), (36, .33),
                       (60, .55), (72, .66), (84, .77), (90, .83),
                       (104, .96), (107.5, .99), (108, .003)):
    progress.scale.x = amount
    progress.keyframe_insert("scale", frame=round(second*60)+1)

phases = [
    (0, 11, "01 / SIGNAL INTERCEPT", "ASTEROID RUN  /  COMBAT PROFILE"),
    (11, 16, "02 / WARP TO TETHYS", "JUMP CORRIDOR  /  LUNAR VECTOR"),
    (16, 24, "03 / LUNAR APPROACH", "TETHYS  /  HIGH ORBIT"),
    (24, 36, "04 / EVASIVE BREAKAWAY", "ARMOR RELEASE  /  BULLET TIME"),
    (36, 60, "05 / CORE SURVEY", "EXPLORER  /  SIGNAL TRIANGULATION"),
    (60, 72, "06 / CARGO RECONFIGURE", "HAULER  /  ASSEMBLY IN PROGRESS"),
    (72, 84, "07 / CORE RECOVERY", "CARGO LINK  /  TRANSFER TO PORT POD"),
    (84, 90, "08 / WARP TO EMBER", "JUMP CORRIDOR  /  CORE SECURED"),
    (90, 104, "09 / COPPER GIANT ORBIT", "EMBER RINGS  /  DEBRIS EVASION"),
    (104, 108, "10 / RETURN VECTOR", "LOOP CLOSURE  /  REACQUIRE SIGNAL"),
]
for index, (start, end, title, detail) in enumerate(phases):
    keys = interval_keys(start, end)
    if index == 0:
        # The opening caption reappears at the seam with the same full scale.
        keys[-1] = (107.55, 0)
        keys.append((108, 1))
    for suffix, label, y, size, material in (
        ("title", title, -.455, .043, white),
        ("detail", detail, -.517, .025, cyan),
    ):
        obj = text_mesh(f"HUD | phase {index+1:02d} {suffix}", label,
                        -.96, y, size, material)
        key_scale(obj, keys)

statuses = [
    (0, 36, "SEARCHING", cyan),
    (36, 43, "SIGNAL LOCKED", amber),
    (43, 58, "SPECTRAL SCAN", cyan),
    (58, 73, "CORE VECTOR SOLVED", amber),
    (73, 76, "TRACTOR LOCK", amber),
    (76, 82, "TRANSFER IN PROGRESS", amber),
    (82, 104, "SECURED / PORT POD", cyan),
    (104, 108, "SEARCHING", cyan),
]
for index, (start, end, label, material) in enumerate(statuses):
    keys = interval_keys(start, end)
    if index == 0:
        keys[-1] = (107.55, 0)
        keys.append((108, 1))
    obj = text_mesh(f"HUD | core state {index+1:02d}", label, .96, .444,
                    .030, material, right=True)
    key_scale(obj, keys)


# Numeric telemetry is built from seven-segment mesh digits. Each segment has
# a shared animation channel per visible state, so the standard glTF/TiXL
# route carries live values without a scene-specific TiXL text operator.
SEGMENTS = {
    "0": "abcdef", "1": "bc", "2": "abdeg", "3": "abcdg",
    "4": "bcfg", "5": "acdfg", "6": "acdefg", "7": "abc",
    "8": "abcdefg", "9": "abcdfg",
}


def smooth01(value):
    u = min(1.0, max(0.0, value))
    return u*u*u*(u*(u*6-15)+10)


def metric_samples():
    rig = bpy.data.objects["ASTERION | flight rig"]
    core = bpy.data.objects["SIGNAL | recovered moon core"]
    previous = scene.frame_current
    samples = []
    for frame in range(1, scene.frame_end+1, 30):
        second = (frame-1)/60
        scene.frame_set(frame)
        bpy.context.view_layer.update()
        heading = round(math.degrees(rig.rotation_euler.z)) % 360
        roll = round(math.degrees(rig.rotation_euler.y)) % 360
        sensor = rig.matrix_world @ Vector((0, 3, 1.2))
        distance = min(999, round((core.matrix_world.translation-sensor).length))
        before = max(1, frame-3)
        after = min(scene.frame_end, frame+3)
        scene.frame_set(before)
        first = rig.matrix_world.translation.copy()
        scene.frame_set(after)
        last = rig.matrix_world.translation.copy()
        speed = min(999, round((last-first).length*60/(after-before)))
        reset = 1-smooth01((second-103)/5)
        scan = round(100*smooth01((second-43)/15)*reset)
        cargo = round(100*smooth01((second-73)/9)*reset)
        samples.append((frame, {"speed": speed, "heading": heading,
                                "roll": roll, "range": distance,
                                "scan": scan, "cargo": cargo}))
    samples[-1] = (scene.frame_end, samples[0][1].copy())
    scene.frame_set(previous)
    return samples


telemetry = metric_samples()


def seven_segment_readout(name, x, y, material, metric):
    width, height, line, advance = .025, .044, .0034, .033
    geometry = {
        "a": (line, height-line, width-2*line, line),
        "b": (width-line, height/2, line, height/2-line),
        "c": (width-line, line, line, height/2-line),
        "d": (line, 0, width-2*line, line),
        "e": (0, line, line, height/2-line),
        "f": (0, height/2, line, height/2-line),
        "g": (line, height/2-line/2, width-2*line, line),
    }
    objects = {}
    for digit in range(3):
        for segment, (dx, dy, w, h) in geometry.items():
            obj = rectangle(f"HUD | {name} digit {digit} segment {segment}",
                            x+digit*advance+dx, y+dy, w, h, material,
                            depth=-1.997)
            obj["hud_metric"] = metric
            objects[digit, segment] = obj
    last_states = {}
    for frame, values in telemetry:
        display = f"{values[metric]:03d}"
        for digit, character in enumerate(display):
            for segment in geometry:
                state = segment in SEGMENTS[character]
                key = digit, segment
                if last_states.get(key) == state and frame != scene.frame_end:
                    continue
                obj = objects[key]
                obj.scale = (1.0,)*3 if state else (0.0,)*3
                obj.keyframe_insert("scale", frame=frame)
                last_states[key] = state
    for obj in objects.values():
        for curve in animation_curves(obj):
            for point in curve.keyframe_points:
                point.interpolation = "CONSTANT"


for label, metric, x, y, digits_x, material, unit in (
    ("SPD", "speed", -.96, .354, -.80, cyan, "M/S"),
    ("HDG", "heading", -.96, .305, -.80, white, "DEG"),
    ("ROLL", "roll", -.96, .256, -.80, white, "DEG"),
    ("RANGE", "range", .57, .354, .77, white, "M"),
    ("SCAN", "scan", .57, .292, .77, cyan, "%"),
    ("CARGO", "cargo", .57, .214, .77, amber, "%"),
):
    text_mesh(f"HUD | {metric} label", label, x, y, .022, material)
    seven_segment_readout(metric, digits_x, y-.001, material, metric)
    text_mesh(f"HUD | {metric} unit", unit, digits_x+.105, y, .018, material)

for metric, y, material in (("scan", .278, cyan), ("cargo", .200, amber)):
    rectangle(f"HUD | {metric} meter rail", .57, y, .39, .003, dim)
    meter = rectangle(f"HUD | {metric} meter fill", .57, y, .39, .004,
                      material, depth=-1.996)
    for frame, values in telemetry:
        meter.scale.x = max(.001, values[metric]/100)
        meter.keyframe_insert("scale", frame=frame)
    for curve in animation_curves(meter):
        for point in curve.keyframe_points:
            point.interpolation = "LINEAR"

scene["mission_hud"] = (
    "Camera-mounted mesh typography: ten timed flight chapters, animated route "
    "progress, live speed/heading/roll/range digits, scan/cargo completion "
    "meters, and moon-core search/lock/transfer/secured states; seamless loop"
)
scene.frame_set(1)
print("ASTERION_HUD", {"objects": len(hud.objects), "phases": len(phases),
                       "core_states": len(statuses),
                       "telemetry_samples": len(telemetry)})

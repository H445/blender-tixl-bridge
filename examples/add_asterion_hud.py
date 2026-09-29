"""Add an animated, camera-mounted mission HUD to AsterionBreakaway.

Run through Blender MCP after ``add_asterion_story.py``. Text is converted to
mesh so the standard Blender-to-TiXL export carries it without custom nodes.
The overlay has the same pose at 0 and 108 seconds for the project loop.
"""

import bpy


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


def key_scale(obj, keys):
    for second, value in keys:
        obj.scale = (value, value, value)
        obj.keyframe_insert("scale", frame=round(second*60)+1)
    action = obj.animation_data.action
    if hasattr(action, "fcurves"):
        for curve in action.fcurves:
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

scene["mission_hud"] = (
    "Camera-mounted mesh typography: ten timed flight chapters, animated route "
    "progress, and moon-core search/lock/transfer/secured states; seamless loop"
)
scene.frame_set(1)
print("ASTERION_HUD", {"objects": len(hud.objects), "phases": len(phases),
                       "core_states": len(statuses)})

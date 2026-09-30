"""Add repeatable model-space glitch hits to existing Asterion craft parts.

Run through Blender MCP after ``add_asterion_hud.py``. Existing ship meshes
receive additive delta transforms; no flight, breakup, or rebuild keys change.
Linked echoes reuse source mesh datablocks. Rerunning replaces only this
script's objects and delta channels.
"""

import random

import bpy
from mathutils import Vector


scene = bpy.context.scene
rig = bpy.data.objects.get("ASTERION | flight rig")
assert rig and scene.render.fps / scene.render.fps_base == 60
assert scene.frame_end == 6481 and bpy.data.filepath

COLLECTION = "06 Glitch | model echoes and H445"
PREFIX = "GLITCH |"
randomizer = random.Random(445)
old_frame = scene.frame_current
selected = tuple(obj.name for obj in bpy.context.selected_objects)
active = bpy.context.view_layer.objects.active.name if bpy.context.view_layer.objects.active else None


def curves(obj):
    action = obj.animation_data.action if obj.animation_data else None
    if action is None:
        return []
    if hasattr(action, "fcurves"):
        return [(action.fcurves, curve) for curve in action.fcurves]
    return [(bag.fcurves, curve)
            for layer in action.layers for strip in layer.strips
            for bag in strip.channelbags for curve in bag.fcurves]


# Remove only delta channels previously authored here. Original location,
# rotation, scale, visibility and breakaway animation stay intact.
for obj in bpy.data.objects:
    if not obj.get("asterion_model_glitch"):
        continue
    for owner, curve in curves(obj):
        if curve.data_path in {"delta_location", "delta_rotation_euler"}:
            owner.remove(curve)
    obj.delta_location = (0, 0, 0)
    obj.delta_rotation_euler = (0, 0, 0)
    del obj["asterion_model_glitch"]

old = bpy.data.collections.get(COLLECTION)
if old:
    for obj in tuple(old.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    bpy.data.collections.remove(old)
for mesh in tuple(bpy.data.meshes):
    if mesh.users == 0 and mesh.name.startswith(PREFIX):
        bpy.data.meshes.remove(mesh)
for curve in tuple(bpy.data.curves):
    if curve.users == 0 and curve.name.startswith(PREFIX):
        bpy.data.curves.remove(curve)
glitch = bpy.data.collections.new(COLLECTION)
scene.collection.children.link(glitch)


parts = tuple(obj for obj in bpy.data.collections["01 Asterion | detachable craft"].objects
              if obj.type == "MESH" and obj.parent == rig)
groups = {
    "combat": sorted((obj for obj in parts if obj.name.startswith((
        "ARMOR-", "WING-ARMOR-", "NACELLE-PLATE-", "MICRO-GREEBLE-"))),
                     key=lambda obj: obj.name),
    "explorer": sorted((obj for obj in parts if obj.name.startswith((
        "EXPLORER-SOLAR-CELL-", "EXPLORER-RADIATOR-", "EXPLORER-LIDAR-"))),
                       key=lambda obj: obj.name),
    "hauler": sorted((obj for obj in parts if obj.name.startswith((
        "HAULER-CRADLE-BRACE-", "HAULER-CONTAINER-STRAP-"))),
                     key=lambda obj: obj.name),
}
assert all(len(group) >= 8 for group in groups.values())

hits = (6.25, 8.5, 11.75, 14.25, 20.5, 25.5, 28.5, 32.75,
        38.25, 45.5, 53.25, 61.5, 67.25, 72.75, 78.5,
        84.5, 87.25, 94.5, 100.75, 105.5)
hero_groups = {
    "combat": ("PRIMARY-SWEPT-WING--1", "PRIMARY-SWEPT-WING-+1"),
    "explorer": ("EXPLORER-RADIATOR--1-0", "EXPLORER-RADIATOR-+1-0"),
    "hauler": ("HAULER-CARGO-01-01", "HAULER-CARGO-03-00"),
}
schedules = {}
for hit_index, seconds in enumerate(hits):
    family = "combat" if seconds < 36 or seconds >= 104 else (
        "explorer" if seconds < 60 else "hauler")
    amplitude = .75 if 24 <= seconds <= 36 else .48
    hero = bpy.data.objects[hero_groups[family][hit_index % 2]]
    for obj in (*randomizer.sample(groups[family], 8), hero):
        strength = 2.1 if obj == hero else 1.0
        offset = Vector((randomizer.uniform(-1, 1),
                         randomizer.uniform(-1, 1),
                         randomizer.uniform(-.5, .5))) * amplitude*strength
        turn = Vector((randomizer.uniform(-.22, .22),
                       randomizer.uniform(-.22, .22),
                       randomizer.uniform(-.48, .48)))*strength
        schedules.setdefault(obj, []).append((seconds, offset, turn))

for obj, events in schedules.items():
    obj["asterion_model_glitch"] = True
    obj.delta_location = (0, 0, 0)
    obj.delta_rotation_euler = (0, 0, 0)
    for frame in (1, scene.frame_end):
        obj.keyframe_insert("delta_location", frame=frame)
        obj.keyframe_insert("delta_rotation_euler", frame=frame)
    for seconds, offset, turn in events:
        first = round(seconds*60)+1
        for frame, location, rotation in (
                (first-2, Vector((0, 0, 0)), Vector((0, 0, 0))),
                (first, offset, turn),
                (first+7, -offset*.7, -turn*.7),
                (first+17, Vector((0, 0, 0)), Vector((0, 0, 0)))):
            obj.delta_location = location
            obj.delta_rotation_euler = rotation
            obj.keyframe_insert("delta_location", frame=frame)
            obj.keyframe_insert("delta_rotation_euler", frame=frame)
    for _owner, curve in curves(obj):
        if curve.data_path in {"delta_location", "delta_rotation_euler"}:
            for point in curve.keyframe_points:
                point.interpolation = "CONSTANT"
    obj.delta_location = (0, 0, 0)
    obj.delta_rotation_euler = (0, 0, 0)


def emission(name, color, strength):
    material = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    material.use_nodes = True
    nodes = material.node_tree.nodes
    nodes.clear()
    output = nodes.new("ShaderNodeOutputMaterial")
    glow = nodes.new("ShaderNodeEmission")
    glow.inputs["Color"].default_value = (*color, 1)
    glow.inputs["Strength"].default_value = strength
    material.node_tree.links.new(glow.outputs[0], output.inputs["Surface"])
    return material


cyan = emission("GLITCH | hull cyan", (.03, .54, .78), 2.4)
magenta = emission("GLITCH | hull magenta", (.50, .035, .45), 2.1)

def pulse(obj, times, duration=6):
    obj.scale = (0, 0, 0)
    obj.keyframe_insert("scale", frame=1)
    for seconds in times:
        first = round(seconds*60)+1
        for frame, value in ((first-1, 0), (first, 1), (first+duration, 0)):
            obj.scale = (value, value, value)
            obj.keyframe_insert("scale", frame=frame)
    obj.scale = (0, 0, 0)
    obj.keyframe_insert("scale", frame=scene.frame_end)
    for _owner, curve in curves(obj):
        if curve.data_path == "scale":
            for point in curve.keyframe_points:
                point.interpolation = "CONSTANT"


# A linked echo borrows its host's actual mesh datablock. At each hit it
# flicks off the surface for a few frames while the original part stays in
# the ship. No new part geometry or alternate ship assembly is manufactured.
echo_specs = (
    ("PRIMARY-SWEPT-WING--1", (8.5, 20.5)),
    ("PRIMARY-SWEPT-WING-+1", (11.75, 25.5)),
    ("NACELLE--1-0 | shell", (14.25, 28.5)),
    ("NACELLE-+1-0 | shell", (6.25, 32.75)),
    ("ARMOR-08-+1-+1", (25.5, 28.5)),
    ("EXPLORER-RADIATOR--1-0", (38.25, 53.25)),
    ("EXPLORER-RADIATOR-+1-0", (45.5, 53.25)),
    ("EXPLORER-SOLAR-CELL-+1-0-04", (45.5, 53.25)),
    ("HAULER-CARGO-01-01", (67.25, 78.5)),
    ("HAULER-CARGO-03-00", (72.75, 84.5)),
    ("HAULER-CRADLE-BRACE--1-2", (61.5, 87.25)),
    ("HAULER-CRADLE-BRACE-+1-2", (67.25, 94.5)),
)
for index, (name, times) in enumerate(echo_specs):
    host = bpy.data.objects.get(name)
    if host is None:
        raise RuntimeError(f"Missing linked echo source: {name}")
    echo = bpy.data.objects.new(f"GLITCH | linked model echo {index:02d}",
                                host.data)
    glitch.objects.link(echo)
    echo.parent = host
    echo["asterion_glitch_source"] = name
    for slot in echo.material_slots:
        slot.link = "OBJECT"
        slot.material = cyan if index % 2 == 0 else magenta
    echo.scale = (0, 0, 0)
    echo.keyframe_insert("scale", frame=1)
    echo.location = (0, 0, 0)
    echo.keyframe_insert("location", frame=1)
    for seconds in times:
        first = round(seconds*60)+1
        side = -1 if index % 2 else 1
        for frame, scale, location in (
                (first-1, 0, (0, 0, 0)),
                (first, 1, (side*.85, .26, .18)),
                (first+7, 1, (-side*.65, -.24, -.16)),
                (first+19, 0, (0, 0, 0))):
            echo.scale = (scale, scale, scale)
            echo.location = location
            echo.keyframe_insert("scale", frame=frame)
            echo.keyframe_insert("location", frame=frame)
    echo.scale = (0, 0, 0)
    echo.location = (0, 0, 0)
    echo.keyframe_insert("scale", frame=scene.frame_end)
    echo.keyframe_insert("location", frame=scene.frame_end)
    for _owner, curve in curves(echo):
        if curve.data_path in {"scale", "location"}:
            for point in curve.keyframe_points:
                point.interpolation = "CONSTANT"

# These bars use two shared meshes and sit immediately above their host
# surfaces. They read as brief geometry corruption, not detached ship parts.
bar_meshes = []
for index, material in enumerate((cyan, magenta)):
    mesh = bpy.data.meshes.new(f"GLITCH | shared surface tear {index}")
    mesh.from_pydata(((-1.1, -.05, -.045), (1.1, -.05, -.045),
                      (1.1, .05, -.045), (-1.1, .05, -.045),
                      (-1.1, -.05, .045), (1.1, -.05, .045),
                      (1.1, .05, .045), (-1.1, .05, .045)), (),
                     ((0, 3, 2, 1), (4, 5, 6, 7),
                      (0, 1, 5, 4), (1, 2, 6, 5),
                      (2, 3, 7, 6), (3, 0, 4, 7)))
    mesh.materials.append(material)
    bar_meshes.append(mesh)
tear_hosts = {
    "combat": ("PRIMARY-SWEPT-WING--1", "PRIMARY-SWEPT-WING-+1",
               "NACELLE--1-0 | shell", "NACELLE-+1-0 | shell"),
    "explorer": ("EXPLORER-RADIATOR--1-0", "EXPLORER-RADIATOR-+1-0",
                 "EXPLORER | forward survey head"),
    "hauler": ("HAULER-CARGO-01-01", "HAULER-CARGO-03-00"),
}
for index, seconds in enumerate(hits):
    family = "combat" if seconds < 36 or seconds >= 104 else (
        "explorer" if seconds < 60 else "hauler")
    host = bpy.data.objects[tear_hosts[family][index % len(tear_hosts[family])]]
    bounds = host.bound_box
    center_x = (min(point[0] for point in bounds) +
                max(point[0] for point in bounds))*.5
    center_y = (min(point[1] for point in bounds) +
                max(point[1] for point in bounds))*.5
    top = max(point[2] for point in bounds)
    for trace in range(2):
        obj = bpy.data.objects.new(
            f"GLITCH | surface tear {index:02d}-{trace}",
            bar_meshes[(index+trace) % 2])
        glitch.objects.link(obj)
        obj.parent = host
        obj.location = (center_x, center_y + (trace*2-1)*.16,
                        top+.09+trace*.025)
        obj.rotation_euler.z = randomizer.uniform(-.45, .45)
        pulse(obj, (seconds+trace*.05,), duration=18)

scene["model_glitch"] = (
    "Linked model echoes reuse their host meshes; emissive tears reuse two "
    "solid meshes; selected original armor, wing, radiator and cargo parts "
    "receive additive glitch transforms that reset at the 108-second seam"
)
bpy.ops.object.select_all(action="DESELECT")
for name in selected:
    if name in bpy.data.objects:
        bpy.data.objects[name].select_set(True)
if active in bpy.data.objects:
    bpy.context.view_layer.objects.active = bpy.data.objects[active]
scene.frame_set(old_frame)
print("ASTERION_MODEL_GLITCH", {"parts": len(schedules), "hits": len(hits),
                               "linked_echoes": len(echo_specs),
                               "shared_tear_meshes": len(bar_meshes)})

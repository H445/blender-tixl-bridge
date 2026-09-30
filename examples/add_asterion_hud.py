"""Add an animated, camera-mounted mission HUD to AsterionBreakaway.

Run through Blender MCP after ``add_asterion_story.py``. Text is converted to
mesh so the standard Blender-to-TiXL export carries it without custom nodes.
The overlay has the same pose at 0 and 108 seconds for the project loop.
"""

import math
import sys
from pathlib import Path

import bpy
from mathutils import Vector


scene = bpy.context.scene
camera = scene.camera
assert camera and scene.render.fps == 60 and scene.frame_end == 6481

# The TiXL output may be viewed in a narrower panel than Blender's 16:9
# camera frame. Keep every HUD vertex inside a central safe area; scaling
# only X/Y preserves the camera-facing depth and avoids perspective drift.
HUD_SAFE_SCALE = .88


def hud_xy(x, y):
    return x*HUD_SAFE_SCALE, y*HUD_SAFE_SCALE

old = bpy.data.collections.get("05 HUD | mission telemetry")
if old:
    for obj in list(old.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    bpy.data.collections.remove(old)
for datablocks in (bpy.data.meshes, bpy.data.curves):
    for block in list(datablocks):
        if block.users == 0 and block.name.startswith("HUD |"):
            datablocks.remove(block)
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
    curve.size = size*HUD_SAFE_SCALE
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
    obj.location = (*hud_xy(x, y), -2.0)
    obj["asterion_hud"] = True
    obj["hud_text"] = label
    return obj


def rectangle(name, x, y, width, height, material, depth=-2.005):
    mesh = bpy.data.meshes.new(name)
    width *= HUD_SAFE_SCALE
    height *= HUD_SAFE_SCALE
    mesh.from_pydata([(0, 0, 0), (width, 0, 0),
                      (width, height, 0), (0, height, 0)],
                     [], [(0, 1, 2, 3)])
    mesh.materials.append(material)
    obj = bpy.data.objects.new(name, mesh)
    hud.objects.link(obj)
    obj.parent = camera
    obj.location = (*hud_xy(x, y), depth)
    obj["asterion_hud"] = True
    return obj


def line_mesh(name, points, thickness, material, x=0, y=0,
              depth=-1.994):
    """One camera-facing mesh for an animated scan path or scope arc."""
    points = [hud_xy(*point) for point in points]
    thickness *= HUD_SAFE_SCALE
    vertices, faces = [], []
    for a, b in zip(points, points[1:]):
        dx, dy = b[0]-a[0], b[1]-a[1]
        length = math.hypot(dx, dy)
        if length < 1e-8:
            continue
        nx, ny = -dy/length*thickness/2, dx/length*thickness/2
        start = len(vertices)
        vertices.extend([(a[0]+nx, a[1]+ny, 0),
                         (a[0]-nx, a[1]-ny, 0),
                         (b[0]-nx, b[1]-ny, 0),
                         (b[0]+nx, b[1]+ny, 0)])
        faces.append((start, start+1, start+2, start+3))
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(vertices, [], faces)
    mesh.materials.append(material)
    obj = bpy.data.objects.new(name, mesh)
    hud.objects.link(obj)
    obj.parent = camera
    obj.location = (*hud_xy(x, y), depth)
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
            point.interpolation = "CONSTANT"


def interval_keys(start, end):
    # Fixed-position labels hold for the full chapter. Scaling text through
    # intermediate sizes made it look like the entire HUD was jumping.
    keys = [(0, int(start == 0))]
    if start:
        keys.append((start, 1))
    keys.append((end, 0))
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
    # Sample telemetry twice per second while the primary HUD anchors stay
    # fixed. The faster digits follow the flight without moving their panel.
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


# A camera-space signal scope gives the telemetry its own scan language. The
# short arcs and corner brackets stay below the right-hand readouts, leaving
# the center of the picture clear for the ship and its target.
scope_x, scope_y = .79, -.065
for index, (start, span, radius, material) in enumerate((
    (.15, 1.55*math.pi, .075, cyan),
    (1.15*math.pi, .70*math.pi, .060, white),
    (.34*math.pi, .55*math.pi, .091, amber),
)):
    points = [(radius*math.cos(start+span*i/32),
               radius*math.sin(start+span*i/32)) for i in range(33)]
    arc = line_mesh(f"HUD | signal scope arc {index+1}", points, .0022,
                    material, scope_x, scope_y)
    for second, turns in ((0, 0), (36, 3), (72, 6), (108, 9)):
        arc.rotation_euler.z = 2*math.pi*turns*(1 if index != 1 else -1)
        arc.keyframe_insert("rotation_euler", frame=round(second*60)+1)
    for curve in animation_curves(arc):
        for point in curve.keyframe_points:
            point.interpolation = "LINEAR"

for index in range(12):
    angle = 2*math.pi*index/12
    inner = .087 if index % 3 else .082
    tick = [(inner*math.cos(angle), inner*math.sin(angle)),
            (.101*math.cos(angle), .101*math.sin(angle))]
    line_mesh(f"HUD | scope bearing {index:02d}", tick, .0015, dim,
              scope_x, scope_y)

line_mesh("HUD | scope horizontal axis", [(-.11, 0), (-.025, 0),
          (.025, 0), (.11, 0)], .0011, dim, scope_x, scope_y)
line_mesh("HUD | scope vertical axis", [(0, -.11), (0, -.025),
          (0, .025), (0, .11)], .0011, dim, scope_x, scope_y)
beam = line_mesh("HUD | radial scan beam", [(0, 0), (.072, 0)], .0028,
                 cyan, scope_x, scope_y, depth=-1.991)
for second in range(0, 109, 4):
    beam.rotation_euler.z = 2*math.pi*second/4
    beam.keyframe_insert("rotation_euler", frame=second*60+1)
for curve in animation_curves(beam):
    for point in curve.keyframe_points:
        point.interpolation = "LINEAR"

text_mesh("HUD | scope label", "LUNAR VECTOR / ACTIVE", .57, -.215,
          .018, cyan)
for x, y, dx, dy in ((.61, -.065, .025, .025),
                     (.97, -.065, -.025, .025),
                     (.61, -.065, .025, -.025),
                     (.97, -.065, -.025, -.025)):
    # The brackets deliberately have gaps and unequal arm lengths, like
    # projected target geometry rather than another rectangular panel.
    line_mesh(f"HUD | scope bracket {x:.2f} {y:.2f} {dy:+.2f}",
              [(dx, 0), (0, 0), (0, dy)], .002, cyan, x, y)

# Nested wireforms make the scope read as sampled geometry, while a shallow
# perspective lattice holds scan data in the lower-right HUD quadrant.
for sides, radius, material, direction in ((3, .128, cyan, 1),
                                           (6, .112, amber, -1)):
    poly = [(radius*math.cos(2*math.pi*i/sides+math.pi/6),
             radius*math.sin(2*math.pi*i/sides+math.pi/6))
            for i in range(sides+1)]
    wire = line_mesh(f"HUD | {sides}-sided scan wireform", poly, .0017,
                     material, scope_x, scope_y, depth=-1.992)
    for second in (0, 36, 72, 108):
        wire.rotation_euler.z = direction*2*math.pi*second/36
        wire.keyframe_insert("rotation_euler", frame=second*60+1)
    for curve in animation_curves(wire):
        for point in curve.keyframe_points:
            point.interpolation = "LINEAR"

for row in range(5):
    y = -.305-row*.041
    left = .49+row*.013
    right = .965-row*.011
    line_mesh(f"HUD | depth lattice row {row:02d}",
              [(left, y), (right, y)], .00125, dim)
for column in range(7):
    u = column/6
    line_mesh(f"HUD | depth lattice ray {column:02d}",
              [(.49+.475*u, -.305), (.542+.379*u, -.469)],
              .00125, dim)
text_mesh("HUD | geometry legend", "GEOMETRY / SIGNAL DEPTH", .49,
          -.285, .017, cyan)
grid_scan = line_mesh("HUD | lattice scan blade",
                      [(.49, -.305), (.542, -.469)], .003, cyan,
                      depth=-1.990)
for second in range(0, 109, 2):
    frame = second*60+1
    grid_scan.location.x = hud_xy(0 if second % 4 == 0 else .379, 0)[0]
    grid_scan.keyframe_insert("location", frame=frame)
for curve in animation_curves(grid_scan):
    for point in curve.keyframe_points:
        point.interpolation = "LINEAR"


# Isolated HUD glyph failures follow the same deterministic signal/fill
# events as the 120 BPM audio and TiXL visuals. They never glitch the image
# beneath the HUD, and every fragment is absent at both loop boundaries.
audio_path = Path(bpy.data.filepath).parent / "advanced_spaceship" / "audio"
if str(audio_path) not in sys.path:
    sys.path.insert(0, str(audio_path))
from techno_pattern import events, signal_events

fragment_specs = ((-.94, .393, .085, cyan),
                  (-.69, .393, .048, white),
                  (.64, .393, .095, amber),
                  (.79, .393, .052, cyan),
                  (-.93, -.532, .115, cyan),
                  (.65, -.532, .092, amber),
                  (-.91, .194, .145, white),
                  (.72, .172, .105, cyan),
                  (-.74, -.436, .174, cyan),
                  (.68, -.267, .178, amber))
fragments = []
for index, (x, y, width, material) in enumerate(fragment_specs):
    obj = rectangle(f"HUD | signal fault fragment {index+1:02d}",
                    x, y, width, .0036, material, depth=-1.989)
    obj.scale = (0, 0, 0)
    obj.keyframe_insert("scale", frame=1)
    fragments.append(obj)

fault_events = []
for event in events():
    if event.kind in ("signal", "ghost") and (
            not fault_events or event.time - fault_events[-1].time >= 2):
        fault_events.append(event)
for index, event in enumerate(fault_events):
    fragment = fragments[index % len(fragments)]
    start = max(2, round(event.time*60)+1)
    stop = min(scene.frame_end-1, start+max(2, round(3+5*event.gain)))
    baseline = fragment_specs[index % len(fragments)]
    shift = ((index*7) % 9 - 4)*.004
    fragment.location = (*hud_xy(baseline[0]+shift, baseline[1]), -1.989)
    fragment.keyframe_insert("location", frame=start)
    fragment.scale = (1, 1, 1)
    fragment.keyframe_insert("scale", frame=start)
    fragment.scale = (0, 0, 0)
    fragment.keyframe_insert("scale", frame=stop)

# Short spectral echoes add movement to the text without shifting its
# readable primary layer or moving any HUD anchor.
for ghost_index, (name, label, x, y, size, material, right) in enumerate((
        ("HUD | signal fault title ghost", "ASTERION / RESCUE VECTOR",
         -.96, .49, .039, cyan, False),
        ("HUD | signal fault status ghost", "MOON CORE STATUS",
         .96, .49, .028, amber, True))):
    ghost = text_mesh(name, label, x, y, size, material, right=right)
    ghost.location.z = -1.986
    ghost.scale = (0, 0, 0)
    ghost.keyframe_insert("scale", frame=1)
    for event_index, event in enumerate(fault_events):
        if event_index % 3 != ghost_index:
            continue
        start = max(2, round(event.time*60)+1)
        stop = min(scene.frame_end-1, start+3)
        direction = 1 if event_index % 2 else -1
        ghost.location = (*hud_xy(x+direction*.008, y+direction*.003),
                          -1.986)
        ghost.keyframe_insert("location", frame=start)
        ghost.scale = (1, 1, 1)
        ghost.keyframe_insert("scale", frame=start)
        ghost.scale = (0, 0, 0)
        ghost.keyframe_insert("scale", frame=stop)
    ghost.scale = (0, 0, 0)
    ghost.keyframe_insert("scale", frame=scene.frame_end)
    for curve in animation_curves(ghost):
        for point in curve.keyframe_points:
            point.interpolation = "CONSTANT"

for fragment in fragments:
    fragment.scale = (0, 0, 0)
    fragment.keyframe_insert("scale", frame=scene.frame_end)
    for curve in animation_curves(fragment):
        for point in curve.keyframe_points:
            point.interpolation = "CONSTANT"

scene["mission_hud"] = (
    "Camera-mounted safe-area mesh typography: ten timed flight chapters, animated route "
    "progress, live speed/heading/roll/range digits, scan/cargo completion "
    "meters, moon-core search/lock/transfer/secured states, rotating signal "
    "scope, wireform lattice, radial scan and HUD-local signal faults; "
    "fixed-position labels and half-second telemetry updates; seamless loop"
)
source_path = str(Path(bpy.data.filepath).parent)
if source_path not in sys.path:
    sys.path.insert(0, source_path)
from asterion_hud_identity import add_identity

identity = add_identity()
scene.frame_set(1)
print("ASTERION_HUD", {"objects": len(hud.objects), "phases": len(phases),
                       "core_states": len(statuses),
                       "telemetry_samples": len(telemetry),
                       "signal_events": len(signal_events()),
                       "hud_fault_events": len(fault_events),
                       "identity": identity})

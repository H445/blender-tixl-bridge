"""Stage Asterion's single-take rescue story in the open Blender MCP scene.

Run this inside Blender through the MCP TCP extension after building/loading
``AsterionBreakaway.blend``.  It is idempotent and leaves the part choreography
and the TiXL-owned home graph intact.
"""

import math
import random
from pathlib import Path

import bpy
from mathutils import Vector


scene = bpy.context.scene
fps = scene.render.fps
assert fps == 60 and scene.frame_end == 6481, "Expected the 108-second Asterion scene"
camera = scene.camera
assert camera and camera.name.startswith("CAM |"), "Asterion camera missing"
parts = [obj for obj in scene.objects if obj.get("asterion_part", False)]
assert len(parts) >= 400, "Asterion detachable craft is incomplete"


def remove_story_objects():
    for obj in parts:
        if obj.parent and obj.parent.get("asterion_story_object", False):
            obj.parent = None
    for obj in scene.objects:
        if obj.type == "LIGHT" and obj.parent and obj.parent.get("asterion_story_object", False):
            obj.parent = None
    for obj in list(scene.objects):
        if obj.get("asterion_story_object", False):
            bpy.data.objects.remove(obj, do_unlink=True)


remove_story_objects()
story = bpy.data.collections.get("04 Story | navigation and signal")
if story is None:
    story = bpy.data.collections.new("04 Story | navigation and signal")
    scene.collection.children.link(story)

flight = bpy.data.objects.new("ASTERION | flight rig", None)
story.objects.link(flight)
flight["asterion_story_object"] = True
flight["story_role"] = "Reusable craft motion; all 500 existing pieces are children"
for part in parts:
    part.parent = flight
for lamp in (obj for obj in scene.objects if obj.type == "LIGHT"):
    lamp.parent = flight


def smooth01(value):
    u = min(1.0, max(0.0, value))
    return u*u*u*(u*(u*6-15)+10)


def envelope(t, enter, full, leave, gone):
    return smooth01((t-enter)/(full-enter)) * (1-smooth01((t-leave)/(gone-leave)))


# Place and attitude control are separate: the craft can bank, brake and turn
# while the one-shot camera keeps moving. The fast passages at 11-16 and 84-90
# seconds are two deliberate warp jumps. A third jump closes the journey.
waypoints = [
    (0, (0, 0, 0)), (8, (2, 8, 1)), (11, (5, 13, 2)),
    (16, (14, 38, 4)), (24, (21, 44, 0)), (34, (25, 45, -4)),
    (45, (28, 50, -7)), (58, (31, 54, -8)), (72, (27, 50, -6)),
    (80, (23, 47, -4)), (84, (21, 44, -3)), (90, (-30, -22, 9)),
    (96, (-34, -33, 10)), (102, (-43, -39, 11)),
    (104, (-45, -37, 11)), (106, (-20, -15, 4)), (108, (0, 0, 0)),
]
attitudes = [
    (0, -.12, 0, 0), (8, -.25, -.04, .16),
    (16, -.12, .04, -.10), (24, .34, -.10, .38),
    (36, .15, .06, -.27), (45, .24, -.04, .12),
    (58, -.08, .06, -.18), (72, -.62, -.06, .28),
    (80, -1.02, .08, -.42), (84, -1.82, -.10, .43),
    (90, -2.52, .05, -.27), (96, -2.93, -.07, .22),
    (104, -4.20, .04, -.30), (108, -.12-math.tau, 0, 0),
]


def hermite_scalar(t, points):
    for index in range(len(points)-1):
        t0, value0 = points[index]
        t1, value1 = points[index+1]
        if t <= t1:
            dt = t1-t0
            u = max(0, min(1, (t-t0)/dt))
            def slope(i):
                before = points[max(0, i-1)]
                after = points[min(len(points)-1, i+1)]
                return (after[1]-before[1])/(after[0]-before[0])
            m0, m1 = slope(index)*dt, slope(index+1)*dt
            return ((2*u**3-3*u*u+1)*value0 + (u**3-2*u*u+u)*m0
                    + (-2*u**3+3*u*u)*value1 + (u**3-u*u)*m1)
    return points[-1][1]


paths = [[(t, xyz[axis]) for t, xyz in waypoints] for axis in range(3)]
angles = [[(row[0], row[axis]) for row in attitudes] for axis in range(1, 4)]


def flight_pose(t):
    return Vector(hermite_scalar(t, points) for points in paths), tuple(
        hermite_scalar(t, points) for points in angles)


def emission(name, color, strength):
    material = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    material.diffuse_color = (*color, 1)
    material.use_nodes = True
    nodes = material.node_tree.nodes
    nodes.clear()
    output = nodes.new("ShaderNodeOutputMaterial")
    shader = nodes.new("ShaderNodeEmission")
    shader.inputs["Color"].default_value = (*color, 1)
    shader.inputs["Strength"].default_value = strength
    material.node_tree.links.new(shader.outputs[0], output.inputs["Surface"])
    return material


cyan = emission("STORY | ion warp cyan", (.08, .68, 1.0), 8)
violet = emission("STORY | ion warp violet", (.57, .17, 1.0), 7)
signal_mat = emission("STORY | distress signal amber", (1.0, .48, .08), 8)
scan_mat = emission("STORY | survey beam", (.12, 1.0, .72), 4)


def ember_material():
    """Use packed image maps so the second location exports faithfully."""
    assets = Path(__file__).resolve().parent / "advanced_spaceship" / "textures"
    material = bpy.data.materials.get("STORY | ember giant PBR") or bpy.data.materials.new(
        "STORY | ember giant PBR")
    material.use_nodes = True
    nodes, links = material.node_tree.nodes, material.node_tree.links
    nodes.clear()
    output = nodes.new("ShaderNodeOutputMaterial")
    bsdf = nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.inputs["Roughness"].default_value = .69
    links.new(bsdf.outputs["BSDF"], output.inputs["Surface"])

    def image(name, noncolor=False):
        path = assets / name
        assert path.is_file(), f"Missing planet map: {path}"
        data = bpy.data.images.load(str(path), check_existing=True)
        data.pack()
        data.filepath = "//advanced_spaceship/textures/" + name
        if noncolor:
            data.colorspace_settings.name = "Non-Color"
        node = nodes.new("ShaderNodeTexImage")
        node.image = data
        return node

    links.new(image("ember_albedo.png").outputs["Color"], bsdf.inputs["Base Color"])
    orm = image("ember_orm.png", True)
    separate = nodes.new("ShaderNodeSeparateColor")
    links.new(orm.outputs["Color"], separate.inputs["Color"])
    links.new(separate.outputs["Green"], bsdf.inputs["Roughness"])
    links.new(separate.outputs["Blue"], bsdf.inputs["Metallic"])
    normal = nodes.new("ShaderNodeNormalMap")
    normal.inputs["Strength"].default_value = .45
    links.new(image("ember_normal.png", True).outputs["Color"], normal.inputs["Color"])
    links.new(normal.outputs["Normal"], bsdf.inputs["Normal"])
    gltf_group = bpy.data.node_groups.get("glTF Material Output")
    if gltf_group is None:
        gltf_group = bpy.data.node_groups.new("glTF Material Output", "ShaderNodeTree")
        gltf_group.interface.new_socket("Occlusion", socket_type="NodeSocketFloat")
    gltf = nodes.new("ShaderNodeGroup")
    gltf.node_tree = gltf_group
    links.new(separate.outputs["Red"], gltf.inputs["Occlusion"])
    return material


def move_to_story(obj, role):
    for collection in list(obj.users_collection):
        collection.objects.unlink(obj)
    story.objects.link(obj)
    obj["asterion_story_object"] = True
    obj["story_role"] = role
    return obj


# The amber signal is at the near surface of the moon. During the hauler beat
# the recovered core travels into the cargo cradle and leaves with the ship.
beacon_origin = Vector((41, 61, -14))
bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=2, radius=.72)
beacon = move_to_story(bpy.context.object, "Distress signal and recovered core")
beacon.name = "SIGNAL | recovered moon core"
beacon.data.materials.append(signal_mat)

bpy.ops.mesh.primitive_cylinder_add(vertices=10, radius=1, depth=2)
scan = move_to_story(bpy.context.object, "Visible explorer survey link")
scan.name = "SCAN | explorer to lunar signal"
scan.data.materials.append(scan_mat)

# The escape warp reveals a warmer, ringed system. Its PBR maps and static
# lighting make this leg visually distinct from the psychedelic cratered moon.
ember_center = Vector((-55, -57, 8))
bpy.ops.mesh.primitive_uv_sphere_add(segments=72, ring_count=36, radius=18,
                                     location=ember_center)
ember = move_to_story(bpy.context.object, "Second destination: copper storm giant")
ember.name = "EMBER | storm giant"
ember.rotation_euler = (.17, -.23, .34)
ember.data.materials.append(ember_material())

ring_vertices, ring_faces = [], []
for inner, outer in ((20.5, 22.1), (23.0, 23.7), (25.0, 27.4)):
    offset = len(ring_vertices)
    for side in range(96):
        a = math.tau * side / 96
        for radius in (inner, outer):
            ring_vertices.append((radius*math.cos(a), radius*math.sin(a),
                                  .22*math.sin(a*3)))
    for side in range(96):
        j = offset + 2*side
        k = offset + 2*((side+1) % 96)
        ring_faces.append((j, k, k+1, j+1))
ring_mesh = bpy.data.meshes.new("EMBER | broken dust rings mesh")
ring_mesh.from_pydata(ring_vertices, [], ring_faces)
ring_mesh.update()
ring = bpy.data.objects.new("EMBER | broken dust rings", ring_mesh)
story.objects.link(ring)
ring["asterion_story_object"] = True
ring["story_role"] = "Second location orbital dust rings"
ring.location = ember_center
ring.rotation_euler = (.62, .18, -.35)
ring.data.materials.append(emission("STORY | amber dust rings", (.36, .11, .035), .45))

key_data = bpy.data.lights.new("EMBER | orange solar bounce", "AREA")
key_data.energy = 12500
key_data.color = (1.0, .43, .21)
key_data.shape = "DISK"
key_data.size = 24
key = bpy.data.objects.new("EMBER | orange solar bounce", key_data)
story.objects.link(key)
key["asterion_story_object"] = True
key.location = (-36, -28, 36)
key.rotation_euler = (ember_center-key.location).to_track_quat("-Z", "Y").to_euler()


# Short streak meshes use a narrow hexagonal prism along local Y. Scaling
# them to zero hides them without material-opacity tricks in glTF/TiXL.
streaks = []
randomizer = random.Random(91420)
for index in range(28):
    radius = randomizer.uniform(7.5, 22)
    theta = randomizer.uniform(0, math.tau)
    length = randomizer.uniform(4, 15)
    width = randomizer.uniform(.025, .075)
    x, z = radius*math.cos(theta), radius*math.sin(theta)
    vertices = []
    for y in (-length/2, length/2):
        for side in range(6):
            a = math.tau*side/6
            vertices.append((width*math.cos(a), y, width*math.sin(a)))
    faces = [(0, 5, 4, 3, 2, 1), (6, 7, 8, 9, 10, 11)]
    faces += [(side, (side+1)%6, (side+1)%6+6, side+6) for side in range(6)]
    mesh = bpy.data.meshes.new(f"WARP | streak mesh {index:02d}")
    mesh.from_pydata(vertices, [], faces)
    mesh.update()
    obj = bpy.data.objects.new(f"WARP | ion trail {index:02d}", mesh)
    story.objects.link(obj)
    obj["asterion_story_object"] = True
    obj["story_role"] = "Warp speed line"
    obj.parent = flight
    mesh.materials.append(cyan if index % 3 else violet)
    streaks.append((obj, x, z, randomizer.uniform(-20, 30)))


camera.animation_data_clear()
flight.animation_data_clear()
previous_rotation = None
for frame in list(range(1, scene.frame_end, 12)) + [scene.frame_end]:
    t = (frame-1)/fps
    position, (yaw, pitch, bank) = flight_pose(t)
    flight.location = position
    flight.rotation_euler = (pitch, bank, yaw)
    flight.keyframe_insert("location", frame=frame)
    flight.keyframe_insert("rotation_euler", frame=frame)

    # A roving camera: wide moon approach, close survey, faster pursuit, then
    # a slowed arc around each breakaway. No camera cuts or instant relocations.
    orbit = -.97 + math.tau*5*t/108 + .34*math.sin(math.tau*t/54)
    slow_arc = max(envelope(t, 24, 27, 32, 36),
                   envelope(t, 60, 63, 68, 72),
                   envelope(t, 96, 99, 102, 104))
    warp = max(envelope(t, 10.3, 11.5, 15.1, 16.5),
               envelope(t, 83.1, 84.5, 89.1, 90.5),
               envelope(t, 103.7, 104.8, 106.4, 107.8))
    survey = envelope(t, 37, 41, 56, 60)
    radius = 36 + 5*math.sin(math.tau*t/36) + 8*slow_arc - 9*survey
    height = 11 + 8*math.sin(math.tau*t/36-.4) + 4*slow_arc
    normal_offset = Vector((radius*math.cos(orbit), radius*math.sin(orbit), height))
    forward = Vector((-math.sin(yaw), math.cos(yaw), 0))
    # Pull the orbital camera inward for warp. Keeping its azimuth continuous
    # avoids a fast swing across the hull when chase and orbit oppose.
    offset = normal_offset * (1-.31*warp)
    separation = offset.length
    if separation < 28:
        offset += offset.normalized() * ((28-separation)*smooth01((28-separation)/8))
    camera.location = position + offset
    moon_center = Vector((41, 80, -14))
    moon_delta = camera.location-moon_center
    moon_clearance = moon_delta.length
    if moon_clearance < 29:
        camera.location += moon_delta.normalized() * (
            (29-moon_clearance)*smooth01((29-moon_clearance)/12))
    target = position + forward*(1 + 1.5*warp)
    target.z += .5 + 2.5*survey
    rotation = (target-camera.location).to_track_quat("-Z", "Y").to_euler()
    if previous_rotation is not None:
        rotation.make_compatible(previous_rotation)
    previous_rotation = rotation.copy()
    camera.rotation_euler = rotation
    camera.keyframe_insert("location", frame=frame)
    camera.keyframe_insert("rotation_euler", frame=frame)

    # Bring the signal into the cargo cradle over eight seconds; its later
    # motion matches the flight path without adding a new detachable part.
    recovery = smooth01((t-73)/9) * (1-smooth01((t-103)/5))
    beacon.location = beacon_origin.lerp(position + Vector((0, 2, 1.5)), recovery)
    beacon_size = 1-.4*recovery
    beacon.scale = (beacon_size,)*3
    beacon.keyframe_insert("location", frame=frame)
    beacon.keyframe_insert("scale", frame=frame)

    scan_start = position + Vector((0, 3, 0))
    direction = beacon.location - scan_start
    scan.location = (scan_start + beacon.location)/2
    scan.rotation_euler = direction.to_track_quat("Z", "Y").to_euler()
    beam = envelope(t, 42, 45, 55, 58)
    scan.scale = (.055*beam, .055*beam, direction.length/2*beam)
    scan.keyframe_insert("location", frame=frame)
    scan.keyframe_insert("rotation_euler", frame=frame)
    scan.keyframe_insert("scale", frame=frame)

    for index, (obj, x, z, phase) in enumerate(streaks):
        streak_power = warp
        obj.location = (x, phase + 25*math.sin(t*4.4 + index*.41), z)
        obj.scale = (streak_power, streak_power, streak_power)
        obj.keyframe_insert("location", frame=frame)
        obj.keyframe_insert("scale", frame=frame)

for curve_owner in (camera, flight):
    action = curve_owner.animation_data.action
    if action and hasattr(action, "fcurves"):
        for fcurve in action.fcurves:
            for key in fcurve.keyframe_points:
                key.interpolation = "BEZIER"

for marker in list(scene.timeline_markers):
    if marker.name.startswith("STORY |"):
        scene.timeline_markers.remove(marker)
for second, label in [
    (0, "Signal detected"), (11, "Warp to Tethys"),
    (24, "Armor separates under threat"), (36, "Explorer surveys signal"),
    (60, "Reconfigure for recovery"), (73, "Core retrieved"),
    (84, "Escape warp"), (90, "Ember ring orbit"),
    (96, "Combat rebuild and escort"), (104, "Return warp"),
]:
    scene.timeline_markers.new("STORY | " + label, frame=int(second*fps+1))

scene["story"] = (
    "A distress signal from Tethys draws the combat craft through warp. "
    "Under threat it sheds armor and rebuilds as an explorer to scan the core; "
    "it reforms as a hauler to retrieve the core, escapes through a second "
    "warp jump to the ember giant, then rebuilds its combat shell and returns "
    "through a final jump to repeat the signal pursuit."
)
scene["camera_style"] = "single continuous moving take; warp chases, survey push-in, bullet-time debris arcs"
scene["demo_phases"] = (
    "0-11 signal pursuit; 11-16 arrival warp; 16-24 lunar approach; "
    "24-36 evasive breakaway; 36-60 survey; 60-72 cargo rebuild; "
    "72-84 recovery; 84-90 escape warp; 90-104 ember system; "
    "104-108 return warp; 108=0 seamless project loop"
)
scene.frame_set(1)
print("ASTERION_STORY", {"parts": len(parts), "streaks": len(streaks),
                        "duration_s": scene.frame_end/fps})

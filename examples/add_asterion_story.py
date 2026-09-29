"""Stage Asterion's single-take rescue story in the open Blender MCP scene.

Run this inside Blender through the MCP TCP extension after building/loading
``AsterionBreakaway.blend``.  It is idempotent and leaves the part choreography
and the TiXL-owned home graph intact.
"""

import math
import random
from pathlib import Path

import bpy
from mathutils import Euler, Vector


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


# The actual craft trajectory, rather than the camera, circles both planets.
# Every join shares position and tangent, including the 108 -> 0 project seam.
MOON_CENTER = Vector((65, 185, -40))
EMBER_CENTER = Vector((-55, -57, 8))
MOON_THETA = math.atan2(45, -35)
EMBER_THETA = math.atan2(-73, 30)
MOON_OMEGA = -math.tau/68
EMBER_OMEGA = math.tau/14
START_VELOCITY = Vector((0, 8, 0))
CRUISE_VELOCITY = Vector((2, 15, 0))


def orbit_position(center, radius, z_offset, phase, theta0, sweep):
    theta = theta0+phase*sweep
    return center + Vector((radius*math.cos(theta), radius*math.sin(theta),
                            z_offset+4*math.sin(phase*math.tau)))


def orbit_velocity(radius, phase, theta0, omega, period):
    theta = theta0+phase*omega*period
    return Vector((-radius*omega*math.sin(theta), radius*omega*math.cos(theta),
                   4*math.tau/period*math.cos(phase*math.tau)))


def moon_orbit(t):
    phase = (t-16)/68
    return orbit_position(MOON_CENTER, 64, 42, phase, MOON_THETA, -math.tau)


def moon_velocity(t):
    phase = (t-16)/68
    return orbit_velocity(64, phase, MOON_THETA, MOON_OMEGA, 68)


def ember_orbit(t):
    phase = (t-90)/14
    return orbit_position(EMBER_CENTER, 79, 8, phase, EMBER_THETA, math.tau)


def ember_velocity(t):
    phase = (t-90)/14
    return orbit_velocity(79, phase, EMBER_THETA, EMBER_OMEGA, 14)


def hermite_path(t, start, end, first, last, first_speed, last_speed):
    duration = end-start
    u = max(0, min(1, (t-start)/duration))
    return ((2*u**3-3*u*u+1)*first + (u**3-2*u*u+u)*duration*first_speed
            + (-2*u**3+3*u*u)*last + (u**3-u*u)*duration*last_speed)


def baseline_position(t):
    if t < 11:
        return hermite_path(t, 0, 11, Vector((0, 0, 0)), Vector((10, 110, 2)),
                            START_VELOCITY, CRUISE_VELOCITY)
    if t < 16:
        return hermite_path(t, 11, 16, Vector((10, 110, 2)), moon_orbit(16),
                            CRUISE_VELOCITY, moon_velocity(16))
    if t < 84:
        return moon_orbit(t)
    if t < 90:
        # A direct Hermite chord clips the copper giant near 88 seconds.
        # Sweep wide of its sunward limb while preserving both endpoint
        # positions and tangents for the continuous single-take warp.
        u = (t-84)/6
        clearance_arc = 70*math.sin(math.pi*u)**2
        return (hermite_path(t, 84, 90, moon_orbit(84), ember_orbit(90),
                             moon_velocity(84), ember_velocity(90))
                + Vector((clearance_arc, 0, 0)))
    if t < 104:
        return ember_orbit(t)
    return hermite_path(t, 104, 108, ember_orbit(104), Vector((0, 0, 0)),
                        ember_velocity(104), START_VELOCITY)


# The pilot moves around the rocks, rather than simply rolling in place. The
# envelopes have zero edge velocity and keep the rocks clear of the hull.
dodges = ((7.3, 2.0, 5.0, 9.0, 12.0, Vector((16, 0, 2))),
          (19.3, 14.0, 16.5, 24.0, 29.0, Vector((0, -2, 13))),
          (95.2, 87.5, 90.0, 105.0, 107.5, Vector((0, 0, 14))))
rolls = ((6.3, 9.2), (18.0, 21.4), (93.5, 97.0))


def flight_position(t):
    position = baseline_position(t)
    for _, enter, full, leave, gone, displacement in dodges:
        position += displacement * envelope(t, enter, full, leave, gone)
    return position


def flight_pose(t):
    position = flight_position(t)
    if t <= 0 or t >= 108:
        velocity = START_VELOCITY
    else:
        before = flight_position(max(0, t-.02))
        after = flight_position(min(108, t+.02))
        velocity = after-before
    yaw = math.atan2(-velocity.x, velocity.y)
    pitch = math.atan2(velocity.z, math.hypot(velocity.x, velocity.y))
    bank = .18*math.sin(math.tau*2*t/108)
    # Roll around the craft's longitudinal Y axis. Complete turns remain in
    # the Euler channel so TiXL sees the rotation rather than a static pose.
    bank += sum(math.tau*smooth01((t-start)/(end-start)) for start, end in rolls)
    return position, (yaw, pitch, bank)


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


# Move the moon into the destination system rather than placing it beside the
# opening asteroid run. The core remains just outside its near surface.
moon = bpy.data.objects.get("Tethys analogue | cratered moon")
assert moon is not None, "The Tethys moon is missing"
moon.location = MOON_CENTER
beacon_origin = Vector((65, 166, -40))
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
ember_center = EMBER_CENTER
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


# Distinct, stationary rock fields provide scale and parallax for the ship's
# three evasions. Their central rocks occupy the unmodified flight corridor;
# the animated rig clears them through the timed lateral/vertical dodges.
rock_material = bpy.data.materials.get("08 | cratered moon regolith")
assert rock_material is not None, "The asteroid field needs the packed regolith PBR maps"

asteroids = []
rock_offsets = ((0, 0, 0), (-25, -8, 10), (28, 7, -10),
                (-20, 13, -14), (27, -14, 13), (-33, 4, -4), (35, -3, 6),
                (-39, -17, 16), (42, 18, -15), (-18, -23, 18),
                (22, 24, -17), (-47, 10, 2), (48, -11, -2),
                (-31, 28, 12), (34, -29, -11), (-53, -5, -8))
for encounter, (second, *_) in enumerate(dodges):
    center = baseline_position(second)
    if encounter == 1:
        center.y += 5  # keep the exit from the lunar field open
    for index, offset in enumerate(rock_offsets):
        seed = random.Random(51000 + 101*encounter + index)
        radius = (2.8 if index == 0 else seed.uniform(.9, 2.4))
        rock_position = center + Vector(offset)
        if encounter > 0 and index > 0:
            # The center rock prompts an actual dodge. Its satellites sit in
            # inner/outer shells, clear of the full circular flight path.
            planet = MOON_CENTER if encounter == 1 else EMBER_CENTER
            radial = Vector((center.x-planet.x, center.y-planet.y, 0)).normalized()
            tangential = Vector((-radial.y, radial.x, 0))
            shell = (-37 if index % 2 else 39)
            if encounter == 1 and index == 3:
                shell = 54  # clear the inbound warp before the lunar orbit
            cross = (((index*7) % 11)-5)*5.5
            rock_position = (center + radial*shell + tangential*cross
                             + Vector((0, 0, seed.uniform(-14, 14))))
        bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=3, radius=1,
                                             location=rock_position)
        rock = move_to_story(bpy.context.object, "Stationary asteroid for evasive flight")
        rock.name = f"ASTEROID | field {encounter+1} rock {index+1:02d}"
        for vertex in rock.data.vertices:
            x, y, z = vertex.co
            shape = (1 + .13*math.sin(3.2*x+2.4*y+encounter)
                     + .09*math.sin(5.1*y-3.4*z+index)
                     + .055*seed.uniform(-1, 1))
            vertex.co *= radius*shape
        for polygon in rock.data.polygons:
            polygon.use_smooth = True
        rock.data.materials.append(rock_material)
        rock.rotation_euler = tuple(seed.uniform(-math.pi, math.pi) for _ in range(3))
        asteroids.append(rock)


# Five sparse, static dust lanes make long-distance and warp movement legible
# through parallax. Each lane is one mesh, keeping TiXL's object graph compact.
dust_materials = [emission("STORY | cold interstellar dust", (.27, .48, .68), 1.2),
                  emission("STORY | ember interstellar dust", (.72, .39, .16), 1.2)]
dust_lanes = []
for lane, (begin, end, warm) in enumerate(((1, 11, False), (11, 16, False),
                                          (16, 28, False), (84, 90, True),
                                          (90, 107, True))):
    dust_rng = random.Random(72900 + lane)
    vertices, faces = [], []
    for grain in range(230):
        t = dust_rng.uniform(begin, end)
        center = baseline_position(t) + Vector((dust_rng.uniform(-34, 34),
                                                dust_rng.uniform(-8, 8),
                                                dust_rng.uniform(-24, 24)))
        radius = dust_rng.uniform(.045, .13)
        base = len(vertices)
        vertices.extend((center + Vector((radius, 0, 0)),
                         center + Vector((0, radius, 0)),
                         center + Vector((0, 0, radius)),
                         center + Vector((-radius, -radius, -radius))))
        faces.extend(((base, base+2, base+1), (base, base+1, base+3),
                      (base, base+3, base+2), (base+1, base+2, base+3)))
    dust_mesh = bpy.data.meshes.new(f"DUST | flight lane {lane+1} mesh")
    dust_mesh.from_pydata(vertices, [], faces)
    dust_mesh.update()
    dust_mesh.materials.append(dust_materials[int(warm)])
    dust = bpy.data.objects.new(f"DUST | flight lane {lane+1}", dust_mesh)
    story.objects.link(dust)
    dust["asterion_story_object"] = True
    dust["story_role"] = "Sparse static space dust for flight parallax"
    dust_lanes.append(dust)


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


# Actual engine fire stays attached to each reusable thruster, even while the
# ship's modules tumble independently. Shared meshes keep the six pairs small.
def plasma_shell_material():
    material = bpy.data.materials.get("STORY | cobalt exhaust") or \
        bpy.data.materials.new("STORY | cobalt exhaust")
    material.use_nodes = True
    nodes = material.node_tree.nodes
    nodes.clear()
    output = nodes.new("ShaderNodeOutputMaterial")
    shader = nodes.new("ShaderNodeBsdfPrincipled")
    shader.inputs["Base Color"].default_value = (.002, .015, .18, 1)
    shader.inputs["Roughness"].default_value = 1
    shader.inputs["Emission Color"].default_value = (.002, .37, .9, 1)
    shader.inputs["Emission Strength"].default_value = .7
    shader.inputs["Alpha"].default_value = .72
    material.node_tree.links.new(shader.outputs["BSDF"], output.inputs["Surface"])
    material.surface_render_method = "DITHERED"
    material.diffuse_color = (.002, .37, .9, .72)
    return material


plume_outer = plasma_shell_material()
plume_core = emission("STORY | ice-blue exhaust core", (.002, .42, .8), .8)


def plume_mesh(name, profile, material, turbulent=False):
    sides = 12
    vertices = []
    for ring_index, (y, radius) in enumerate(profile):
        for index in range(sides):
            angle = math.tau * index / sides
            vertex_radius = radius
            if turbulent:
                # An uneven shell and multiple taper stations break up the
                # rigid cone silhouette without relying on a TiXL-only shader.
                vertex_radius *= (1 + .11*math.sin(3*angle + 1.7*ring_index)
                                  + .06*math.sin(5*angle - 2.3*ring_index))
            vertices.append((vertex_radius * math.cos(angle), y,
                             vertex_radius * math.sin(angle)))
    faces = [tuple(range(sides-1, -1, -1))]
    for ring_index in range(len(profile)-1):
        for index in range(sides):
            a = ring_index*sides+index
            b = ring_index*sides+(index+1)%sides
            faces.append((a, b, b+sides, a+sides))
    faces.append(tuple((len(profile)-1)*sides+index
                       for index in range(sides)))
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(vertices, [], faces)
    mesh.update()
    mesh.materials.append(material)
    return mesh


outer_mesh = plume_mesh("COBALT | sculpted exhaust", (
    (0.0, .16), (-.12, .27), (-.36, .23), (-.68, .13), (-1.0, .008)),
    plume_outer, turbulent=True)
core_mesh = plume_mesh("ICE BLUE | hot exhaust core", (
    (0.0, .085), (-.18, .13), (-.55, .085), (-1.0, .006)),
    plume_core)
engine_fire = []
for side in (-1, 1):
    for pod in range(3):
        thruster = bpy.data.objects[f"THRUSTER-{side:+d}-{pod}"]
        for layer, mesh in (("plasma", outer_mesh), ("core", core_mesh)):
            obj = bpy.data.objects.new(
                f"THRUST | {layer} {side:+d}-{pod}", mesh)
            story.objects.link(obj)
            obj.parent = thruster
            obj.location = (0, -.18, 0)
            obj["asterion_story_object"] = True
            obj["story_role"] = "Speed and steering reactive engine fire"
            obj["thruster_side"] = side
            engine_fire.append((obj, side, pod, layer))


def engine_response(t):
    # The endpoint repeats frame zero exactly, including exhaust brightness.
    sample_t = 0.0 if t >= 108 else t
    first = max(0.0, sample_t-.06)
    last = min(108.0, sample_t+.06)
    duration = max(last-first, .001)
    first_position, (first_yaw, first_pitch, first_bank) = flight_pose(first)
    last_position, (last_yaw, last_pitch, last_bank) = flight_pose(last)
    speed = (last_position-first_position).length / duration

    def turn_rate(first_angle, last_angle):
        delta = math.atan2(math.sin(last_angle-first_angle),
                           math.cos(last_angle-first_angle))
        return delta / duration

    yaw_rate = turn_rate(first_yaw, last_yaw)
    pitch_rate = turn_rate(first_pitch, last_pitch)
    bank_rate = turn_rate(first_bank, last_bank)
    warp = max(envelope(sample_t, 10.3, 11.5, 15.1, 16.5),
               envelope(sample_t, 83.1, 84.5, 89.1, 90.5),
               envelope(sample_t, 103.7, 104.8, 106.4, 107.8))
    breakaway = max(envelope(sample_t, 24, 24.8, 34.6, 36),
                    envelope(sample_t, 60, 60.8, 70.6, 72),
                    envelope(sample_t, 96, 96.8, 102.7, 104))
    visible = 1-.987*breakaway
    speed_power = min(1.0, (max(speed-4.0, 0.0)/88.0)**.65)
    turn = max(-.48, min(.48, .70*yaw_rate+.13*bank_rate))
    gimbal_yaw = max(-.19, min(.19, -.10*yaw_rate))
    gimbal_pitch = max(-.13, min(.13, .08*pitch_rate))
    return speed, warp, speed_power, turn, gimbal_yaw, gimbal_pitch, visible


camera.animation_data_clear()
flight.animation_data_clear()
previous_rotation = None
previous_flight_yaw = None
for frame in list(range(1, scene.frame_end, 12)) + [scene.frame_end]:
    t = (frame-1)/fps
    position, (yaw, pitch, bank) = flight_pose(t)
    if previous_flight_yaw is not None:
        yaw += round((previous_flight_yaw-yaw)/math.tau)*math.tau
    previous_flight_yaw = yaw
    flight.location = position
    flight.rotation_euler = (pitch, bank, yaw)
    flight.keyframe_insert("location", frame=frame)
    flight.keyframe_insert("rotation_euler", frame=frame)

    # A roving camera: wide moon approach, close survey, faster pursuit, then
    # a slowed arc around each breakaway. No camera cuts or instant relocations.
    moon_side = envelope(t, 62, 72, 80, 90)
    orbit = (-.97 + math.tau*5*t/108 + .34*math.sin(math.tau*t/54)
             - 1.7*envelope(t, 30, 37, 58, 68)
             + 2.25*moon_side
             + math.pi*envelope(t, 78, 92, 99, 108))
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
    moon_center = MOON_CENTER
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

    # Recover the core into the port cargo pod. The destination follows the
    # craft's orientation, and the emissive marker contracts once stowed.
    recovery = smooth01((t-73)/9) * (1-smooth01((t-103)/5))
    cargo_socket = position + Euler((pitch, bank, yaw), "XYZ").to_matrix() @ Vector(
        (-4.35, -.40, 1.50))
    beacon.location = beacon_origin.lerp(cargo_socket, recovery)
    beacon_size = 1-.97*recovery
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

    speed, warp_power, speed_power, turn, gimbal_yaw, gimbal_pitch, visible = engine_response(t)
    throttle = .28 + 1.3*speed_power + 1.8*warp_power
    blast_length = 1.0 + 2.2*throttle + 2.5*warp_power
    plume_width = .75 + .12*throttle + .35*warp_power
    for obj, side, pod, layer in engine_fire:
        # The outside engines carry slightly more visible exhaust, while the
        # stronger side switches with the sign of the turn/roll.
        pod_gain = (1.0, 1.09, 1.16)[pod]
        steering_gain = 1.0 + side*turn
        length = blast_length * pod_gain * steering_gain
        width = plume_width * (.90 + .06*pod)
        if layer == "core":
            length *= .78
            width *= .77
        pulse_time = 0.0 if t >= 108 else t
        pulse = (1 + .065*math.sin(math.tau*(1.7*pulse_time+.17*pod+.11*side))
                 + .025*math.sin(math.tau*(2.1*pulse_time+.29*pod)))
        length *= pulse
        obj.scale = (width*visible, length*visible, width*visible)
        obj.rotation_euler = (gimbal_pitch, pod*.73+side*.19, gimbal_yaw)
        obj.keyframe_insert("scale", frame=frame)
        obj.keyframe_insert("rotation_euler", frame=frame)

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
    (0, "Signal detected"), (7, "Asteroid slalom and barrel roll"),
    (11, "Warp to Tethys"), (19, "Lunar field loop"),
    (24, "Armor separates under threat"), (36, "Explorer surveys signal"),
    (60, "Reconfigure for recovery"), (73, "Core retrieved"),
    (84, "Escape warp"), (90, "Ember ring orbit"),
    (94, "Ring debris barrel roll"),
    (96, "Combat rebuild and escort"), (104, "Return warp"),
]:
    scene.timeline_markers.new("STORY | " + label, frame=int(second*fps+1))

scene["story"] = (
    "A distress signal from Tethys draws the combat craft through asteroid "
    "fields and warp. It dodges and barrel-rolls between the rocks. "
    "Under threat it sheds armor and rebuilds as an explorer to scan the core; "
    "it reforms as a hauler to retrieve the core, escapes through a second "
    "warp jump to the ember giant, then rebuilds its combat shell and returns "
    "through a final jump to repeat the signal pursuit."
)
scene["camera_style"] = "single continuous moving take; forward asteroid runs, warp chases, survey push-in, bullet-time debris arcs"
scene["thruster_fire"] = (
    "Six blue plasma plumes and six ice-blue cores follow their reusable "
    "engine parts; speed scales the fire, steering biases port/starboard, "
    "breakaways suppress the fire, and each assembled warp spools into a "
    "sustained blast before easing down"
)
scene["demo_phases"] = (
    "0-11 asteroid slalom; 11-16 arrival warp; 16-24 lunar field loop; "
    "24-36 evasive breakaway; 36-60 survey; 60-72 cargo rebuild; "
    "72-84 recovery; 84-90 escape warp; 90-104 ember debris dodge; "
    "104-108 return warp; 108=0 seamless project loop"
)
scene.frame_set(1)
print("ASTERION_STORY", {"parts": len(parts), "streaks": len(streaks),
                        "asteroids": len(asteroids), "dust_grains": 230*len(dust_lanes),
                        "duration_s": scene.frame_end/fps})

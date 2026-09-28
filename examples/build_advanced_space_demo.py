"""Build the 60-second Asterion spacecraft bridge stress test inside Blender MCP.

Run through the official Blender MCP TCP extension's execute_blender_code, for example
with ``exec(compile(open(path, encoding='utf-8').read(), path, 'exec'),
{'__file__': path})``. Never run
Blender via its command-line interface for this repository. The AI image assets live
in ``examples/advanced_spaceship/textures/`` and are supplied separately. Missing maps use PBR
fallback colors so the geometry can be inspected before the final textures arrive.
"""

from __future__ import annotations

import math
import random
from pathlib import Path

import bpy
from mathutils import Vector


ROOT = Path(__file__).resolve().parent
ASSETS = ROOT / "advanced_spaceship" / "textures"
OUTPUT = ROOT / "AsterionBreakaway.blend"
FPS = 60
LAST = 3601  # exactly 60 seconds from frame 1 at 60 fps
RNG = random.Random(24021984)

# Replace scene content without resetting preferences, extensions or the live
# MCP server. Removing just the old scene leaves orphan objects/materials and
# causes Blender to add .001/.002 suffixes on every run, so purge the data types
# this builder owns before allocating new objects.
SCENE_NAME = "ASTERION | modular spacecraft stress test"
previous_scenes = list(bpy.data.scenes)
scene = bpy.data.scenes.new("Asterion temporary build scene")
for window in bpy.context.window_manager.windows:
    window.scene = scene
for old_scene in previous_scenes:
    bpy.data.scenes.remove(old_scene)
for obj in list(bpy.data.objects):
    bpy.data.objects.remove(obj, do_unlink=True)
for coll in list(bpy.data.collections):
    if coll != scene.collection:
        bpy.data.collections.remove(coll, do_unlink=True)
for data_collection in (bpy.data.meshes, bpy.data.cameras, bpy.data.lights,
                        bpy.data.curves, bpy.data.materials, bpy.data.worlds):
    for block in list(data_collection):
        data_collection.remove(block, do_unlink=True)
for old_image in list(bpy.data.images):
    if old_image.type not in {"RENDER_RESULT", "COMPOSITING"}:
        bpy.data.images.remove(old_image, do_unlink=True)
scene.name = SCENE_NAME
scene.render.fps = FPS
scene.frame_start = 1
scene.frame_end = LAST
scene.render.resolution_x = 1920
scene.render.resolution_y = 1080
scene.render.resolution_percentage = 100
scene.render.engine = "BLENDER_EEVEE" if bpy.app.version >= (5, 0, 0) else "BLENDER_EEVEE_NEXT"
scene.render.image_settings.file_format = "PNG"
scene.view_settings.view_transform = "AgX"
scene["tixl_project_name"] = "AsterionBreakaway"
scene["demo_duration_seconds"] = 60
scene["demo_phases"] = "0-9 COMBAT; 9-21 projectile breakup to EXPLORER; 21-30 EXPLORER; 30-42 projectile breakup to HAULER; 42-51 HAULER; 51-60 return to COMBAT"
scene["variant_hold_frames"] = "COMBAT 1-541; EXPLORER 1261-1801; HAULER 2521-3061"
scene["texture_source"] = "GPT Images 2.5; see examples/advanced_spaceship/textures"

world = bpy.data.worlds.new("Near-black interstellar ambient")
world.use_nodes = True
world.node_tree.nodes["Background"].inputs[0].default_value = (0.001, 0.002, 0.008, 1)
world.node_tree.nodes["Background"].inputs[1].default_value = 0.18
scene.world = world


def collection(name):
    coll = bpy.data.collections.new(name)
    scene.collection.children.link(coll)
    return coll


craft = collection("01 Asterion | detachable craft")
space = collection("02 Space | geometry and matte")
rig = collection("03 Lighting and cameras")


def image_node(nodes, links, name, file_name, socket, bsdf, *, noncolor=False):
    path = ASSETS / file_name
    if not path.is_file():
        return None
    img = bpy.data.images.load(str(path), check_existing=True)
    img.pack()
    img.filepath = "//advanced_spaceship/textures/" + file_name
    if noncolor:
        img.colorspace_settings.name = "Non-Color"
    node = nodes.new("ShaderNodeTexImage")
    node.label = name
    node.image = img
    links.new(node.outputs["Color"], bsdf.inputs[socket])
    return node


def pbr(name, color, metallic, roughness, *, albedo=None, orm=None, normal=None,
        emission=None, emission_color=None, emission_strength=0):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    mat.diffuse_color = (*color, 1)
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    bsdf = nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = (*color, 1)
    bsdf.inputs["Metallic"].default_value = metallic
    bsdf.inputs["Roughness"].default_value = roughness
    if emission_color:
        bsdf.inputs["Emission Color"].default_value = (*emission_color, 1)
        bsdf.inputs["Emission Strength"].default_value = emission_strength
    if albedo:
        image_node(nodes, links, "GPT Images 2.5 albedo", albedo, "Base Color", bsdf)
    if orm:
        # glTF exports the channel-packed occlusion/roughness/metallic image.
        tex = image_node(nodes, links, "GPT Images 2.5 ORM", orm, "Roughness", bsdf, noncolor=True)
        if tex:
            sep = nodes.new("ShaderNodeSeparateColor")
            links.remove(bsdf.inputs["Roughness"].links[0])
            links.new(tex.outputs["Color"], sep.inputs["Color"])
            links.new(sep.outputs["Green"], bsdf.inputs["Roughness"])
            links.new(sep.outputs["Blue"], bsdf.inputs["Metallic"])
    if normal:
        path = ASSETS / normal
        if path.is_file():
            tex = nodes.new("ShaderNodeTexImage")
            tex.image = bpy.data.images.load(str(path), check_existing=True)
            tex.image.pack()
            tex.image.filepath = "//advanced_spaceship/textures/" + normal
            tex.image.colorspace_settings.name = "Non-Color"
            nmap = nodes.new("ShaderNodeNormalMap")
            nmap.inputs["Strength"].default_value = 0.52
            links.new(tex.outputs["Color"], nmap.inputs["Color"])
            links.new(nmap.outputs["Normal"], bsdf.inputs["Normal"])
    if emission:
        image_node(nodes, links, "GPT Images 2.5 emission", emission, "Emission Color", bsdf)
        bsdf.inputs["Emission Strength"].default_value = max(emission_strength, 1.0)
    return mat


hull = pbr("01 | ceramic titanium armored hull", (0.29, 0.36, 0.43), 0.84, 0.34,
           albedo="armor_graphite.png", orm="hull_orm.png", normal="hull_normal.png")
dark = pbr("02 | carbon ceramic recess", (0.025, 0.043, 0.061), 0.68, 0.47,
           albedo="carbon_albedo.png", orm="carbon_orm.png", normal="carbon_normal.png")
copper = pbr("03 | heat-scarred copper alloy", (0.53, 0.26, 0.11), 0.93, 0.38,
             albedo="heat_titanium.png", orm="copper_orm.png", normal="copper_normal.png")
white = pbr("04 | porcelain sensor cover", (0.66, 0.72, 0.75), 0.18, 0.25,
            albedo="solar_ceramic.png", normal="white_normal.png")
canopy_mat = pbr("04b | smoked iridium cockpit glazing", (0.015, 0.055, 0.085),
                 0.54, 0.12)
blue = pbr("05 | ion blue emitter", (0.04, 0.16, 0.28), 0.38, 0.22,
           emission_color=(0.045, 0.43, 0.95), emission_strength=7.0)
amber = pbr("06 | warning amber emitter", (0.24, 0.10, 0.015), 0.25, 0.3,
            emission_color=(1.0, 0.29, 0.035), emission_strength=3.0)
nebula = pbr("07 | distant ionized dust photograph", (0.008, 0.014, 0.025), 0, 1,
             emission="space_nebula.png", emission_color=(0.13, 0.24, 0.4),
             emission_strength=1.0)
planet_mat = pbr("08 | cratered moon regolith", (0.32, 0.31, 0.30), 0.02, 0.91,
                 albedo="moon_albedo.png", normal="moon_normal.png")
star_mat = pbr("09 | distant stars", (1, 1, 1), 0, 1,
               emission_color=(1, 1, 1), emission_strength=5)


def mesh_object(name, verts, faces, material, coll, uv=True):
    mesh = bpy.data.meshes.new(name + " mesh")
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    if uv:
        # Stable box-projection UVs for independent, uniquely transformed parts.
        layer = mesh.uv_layers.new(name="UVMap")
        for poly in mesh.polygons:
            n = poly.normal
            axis = max(range(3), key=lambda i: abs(n[i]))
            other = [i for i in range(3) if i != axis]
            for li in poly.loop_indices:
                co = mesh.vertices[mesh.loops[li].vertex_index].co
                layer.data[li].uv = (co[other[0]] * 0.35 + 0.5,
                                     co[other[1]] * 0.35 + 0.5)
    obj = bpy.data.objects.new(name, mesh)
    coll.objects.link(obj)
    mesh.materials.append(material)
    return obj


def box(name, size, location, material, coll=craft, bevel=0.0):
    x, y, z = (d * 0.5 for d in size)
    v = [(-x,-y,-z),(x,-y,-z),(x,y,-z),(-x,y,-z),
         (-x,-y,z),(x,-y,z),(x,y,z),(-x,y,z)]
    f = [(0,3,2,1),(4,5,6,7),(0,1,5,4),(1,2,6,5),
         (2,3,7,6),(3,0,4,7)]
    obj = mesh_object(name, v, f, material, coll)
    obj.location = location
    if bevel:
        mod = obj.modifiers.new("Machined radius", "BEVEL")
        mod.width = bevel
        mod.segments = 2
        obj.modifiers.new("Weighted face normals", "WEIGHTED_NORMAL")
    return obj


def tapered(name, front, rear, half_w_front, half_w_rear,
            half_h_front, half_h_rear, material, coll=craft):
    # Longitudinal tapered octagon, modelled in local coordinates around origin.
    center_y = (front + rear) * .5
    ys = (front-center_y, rear-center_y)
    verts = []
    for y, w, h in zip(ys, (half_w_front, half_w_rear), (half_h_front, half_h_rear)):
        verts.extend([(-w*.72,y,-h), (w*.72,y,-h), (w,y,-h*.65), (w,y,h*.65),
                      (w*.72,y,h), (-w*.72,y,h), (-w,y,h*.65), (-w,y,-h*.65)])
    faces = [tuple(reversed(range(8))), tuple(range(8,16))]
    faces += [(i,(i+1)%8,(i+1)%8+8,i+8) for i in range(8)]
    obj = mesh_object(name, verts, faces, material, coll)
    obj.location.y = center_y
    return obj


def ring(name, center, major, minor, material, coll=craft, segments=24):
    verts, faces = [], []
    for j in range(8):
        a = math.tau*j/8
        for i in range(segments):
            b = math.tau*i/segments
            r = major + minor*math.cos(a)
            verts.append((r*math.cos(b), minor*math.sin(a),r*math.sin(b)))
    for j in range(8):
        for i in range(segments):
            k = j*segments+i
            faces.append((k, j*segments+(i+1)%segments,
                          ((j+1)%8)*segments+(i+1)%segments, ((j+1)%8)*segments+i))
    obj = mesh_object(name, verts, faces, material, coll)
    obj.location = center
    return obj


def sphere(name, loc, radius, material, coll, segments=24, rings=12):
    verts, faces = [], []
    for j in range(rings+1):
        theta = math.pi*j/rings
        for i in range(segments+1):
            phi = math.tau*i/segments
            verts.append((radius*math.sin(theta)*math.cos(phi),
                          radius*math.sin(theta)*math.sin(phi),
                          radius*math.cos(theta)))
    for j in range(rings):
        for i in range(segments):
            a = j*(segments+1)+i
            faces.append((a,a+segments+1,a+segments+2,a+1))
    mesh = bpy.data.meshes.new(name + " mesh")
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    uv = mesh.uv_layers.new(name="UVMap")
    for poly in mesh.polygons:
        for li in poly.loop_indices:
            vi = mesh.loops[li].vertex_index
            j,i = divmod(vi,segments+1)
            uv.data[li].uv = (i/segments,1-j/rings)
    mesh.materials.append(material)
    obj = bpy.data.objects.new(name, mesh)
    coll.objects.link(obj)
    obj.location = loc
    return obj


def poly_prism(name, outline, z_bottom, z_top, material, coll=craft):
    count = len(outline)
    center = (sum(x for x,_ in outline)/count,
              sum(y for _,y in outline)/count,
              (z_bottom+z_top)*.5)
    signed_area = sum(outline[i][0]*outline[(i+1)%count][1]
                      -outline[(i+1)%count][0]*outline[i][1]
                      for i in range(count))
    verts = [(x-center[0],y-center[1],z_bottom-center[2]) for x,y in outline]
    verts += [(x-center[0],y-center[1],z_top-center[2]) for x,y in outline]
    top = tuple(range(count,2*count))
    if signed_area < 0:
        top = tuple(reversed(top))
    faces = [tuple(i-count for i in reversed(top)), top]
    for i in range(count):
        side=(i,(i+1)%count,(i+1)%count+count,i+count)
        faces.append(side if signed_area > 0 else tuple(reversed(side)))
    obj = mesh_object(name, verts, faces, material, coll)
    mod = obj.modifiers.new("Machined wing edge", "BEVEL")
    mod.width = min(.045, (z_top-z_bottom)*.20)
    mod.segments = 2
    obj.modifiers.new("Weighted wing normals", "WEIGHTED_NORMAL")
    obj.location = center
    return obj


def sky_sphere(name, material, coll, radius=350, segments=96, rings=48):
    # Inward-facing equirectangular UV mesh is visible from every camera cut.
    # The seam has duplicate vertices so the image spans the sphere exactly once.
    verts = []
    for j in range(rings+1):
        theta = math.pi*j/rings
        for i in range(segments+1):
            phi = math.tau*i/segments
            verts.append((radius*math.sin(theta)*math.cos(phi),
                          radius*math.sin(theta)*math.sin(phi),
                          radius*math.cos(theta)))
    faces=[]
    for j in range(rings):
        for i in range(segments):
            a=j*(segments+1)+i
            faces.append((a,a+1,a+segments+2,a+segments+1))
    mesh = bpy.data.meshes.new(name + " mesh")
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    uv = mesh.uv_layers.new(name="UVMap")
    for poly in mesh.polygons:
        for li in poly.loop_indices:
            vi=mesh.loops[li].vertex_index
            j,i=divmod(vi,segments+1)
            uv.data[li].uv=(i/segments,1-j/rings)
    mesh.materials.append(material)
    obj = bpy.data.objects.new(name, mesh)
    coll.objects.link(obj)
    return obj


parts = []


def detachable(obj, group, index):
    obj["asterion_part"] = True
    obj["assembly_group"] = group
    obj["part_index"] = index
    parts.append(obj)
    return obj


# Three faceted longitudinal hull volumes retain real silhouette depth.
for i, (a,b,w0,w1,h0,h1) in enumerate([
    (5.1, 1.1, 0.10, 1.33, 0.12, 0.90),
    (1.1,-3.1, 1.33, 1.48, 0.90, 0.82),
    (-3.1,-6.6,1.48, 1.00, 0.82, 0.66),
]):
    detachable(tapered(f"FUSELAGE-{i:02d} | pressure shell", a,b,w0,w1,h0,h1,hull), "spine", i)

# A raised, faceted two-seat bridge breaks the dorsal slab silhouette. Opaque
# iridium glass gives predictable glTF/TiXL PBR without unsupported refraction.
detachable(poly_prism("COCKPIT | faceted iridium canopy",
                      [(-.42,4.00),(.42,4.00),(.78,2.90),(.84,1.22),
                       (.50,.62),(-.50,.62),(-.84,1.22),(-.78,2.90)],
                      .89,1.48,canopy_mat),"spine",205)
for side in (-1,1):
    detachable(poly_prism(f"COCKPIT-RAIL-{side:+d} | titanium frame",
                          [(side*.82,1.0),(side*.96,1.0),
                           (side*.91,3.0),(side*.60,3.95),(side*.47,3.95)],
                          1.02,1.13,copper),"spine",206+(side+1)//2)
    for section in range(5):
        detachable(box(f"COCKPIT-HUD-{side:+d}-{section}",
                       (.045,.18,.025),(side*.51,3.48-section*.45,1.49),
                       blue,bevel=.007),"spine",210+section+(side+1)*3)

# Sixteen station ribs, 64 armor tiles, 48 individually identifiable recessed
# heat shields and fasteners. Each piece gets its own transform animation.
for station in range(16):
    y = 3.7 - station*0.60
    taper = max(0.48, 1.0 - abs(y+1.1)*0.065)
    for side in (-1,1):
        x = side*(1.48*taper)
        detachable(box(f"RIB-{station:02d}-{side:+d}", (0.13,0.10,1.55*taper),
                       (x,y,0), copper, bevel=.025), "spine", station*2+(side+1)//2)
        for row in (-1,1):
            z = row*0.49*taper
            detachable(box(f"ARMOR-{station:02d}-{side:+d}-{row:+d}",
                           (0.25,0.46,0.36), (x+side*0.08,y-0.23,z), hull,
                           bevel=.025), "spine", station*4+(side+1)+(row+1)//2)
            if station % 2 == 0:
                detachable(box(f"THERMAL-{station:02d}-{side:+d}-{row:+d}",
                               (0.08,0.31,0.15), (x+side*0.20,y-0.23,z), dark,
                               bevel=.012), "spine", station*4+(side+1)+(row+1)//2)

# Dorsal blade, underside keel, and sharply swept, layered wing pairs.
detachable(tapered("DORSAL | command fin", 3.5,-4.7,.16,.29,.18,1.25,white), "spine", 200)
detachable(tapered("VENTRAL | armored keel", 2.7,-5.3,.12,.22,.18,.72,dark), "spine", 201)
for side in (-1,1):
    outline=[(side*x,y) for x,y in [(1.0,2.0),(2.7,1.0),(7.3,-3.0),
                                    (8.9,-4.4),(8.4,-5.15),(6.1,-4.65),
                                    (2.0,-5.85),(1.0,-5.55)]]
    detachable(poly_prism(f"PRIMARY-SWEPT-WING-{side:+d}",outline,-.22,.10,hull),
               "wing-left" if side<0 else "wing-right",-1)
    # Leading-edge heat shielding and an illuminated navigation wedge trace
    # the diagonal wing outline at screen size.
    leading=[(side*x,y) for x,y in [(2.57,1.05),(2.72,1.0),
                                    (7.45,-2.95),(8.99,-4.36),
                                    (8.76,-4.56),(7.16,-3.14)]]
    detachable(poly_prism(f"LEADING-EDGE-HEATSHIELD-{side:+d}",
                          leading,.09,.17,copper),
               "wing-left" if side<0 else "wing-right",1)
    for bay in range(7):
        y = .45-bay*.73
        xbase = 1.75+bay*.56
        span = 1.35+bay*.34
        x = side*(xbase+span*.5)
        # Small polygon armor islands leave readable gaps and visible swept
        # skin between them, while retaining a high count of separate parts.
        island=[(side*(xbase+.14),y+.16),(side*(xbase+span*.78),y-.12),
                (side*(xbase+span),y-.42),(side*(xbase+.27),y-.30)]
        detachable(poly_prism(f"WING-ARMOR-{side:+d}-{bay:02d}",
                              island,.105,.19,white if bay in (0,6) else hull),
                   "wing-left" if side<0 else "wing-right", bay)
        detachable(box(f"WING-SPAR-{side:+d}-{bay:02d}",
                       (span*.66,.09,.08), (x,y-.32,-.22), dark, bevel=.014),
                   "wing-left" if side<0 else "wing-right", 20+bay)
        for p in range(3):
            xx = side*(xbase+(p+.5)*span/3)
            detachable(box(f"WING-FLAP-{side:+d}-{bay:02d}-{p}",
                           (span/3*.73,.12,.055), (xx,y-.45,.12),
                           copper if p==2 else hull, bevel=.015),
                   "wing-left" if side<0 else "wing-right", 40+bay*3+p)
    # Pod shells and mechanical collars are nested at the aft quarter.
    for pod in range(3):
        x=side*(2.15+pod*.96)
        detachable(tapered(f"NACELLE-{side:+d}-{pod} | shell",
                            -2.5,-6.9,.35,.45,.32,.43,hull),
                   "engine-left" if side<0 else "engine-right", pod)
        parts[-1].location.x=x
        for k in range(5):
            yy=-3.1-k*.72
            detachable(box(f"NACELLE-PLATE-{side:+d}-{pod}-{k}",
                           (.68,.48,.12),(x,yy,.40),dark,bevel=.028),
                       "engine-left" if side<0 else "engine-right", 10+pod*5+k)
        detachable(ring(f"NOZZLE-{side:+d}-{pod}", (x,-6.93,0),.34,.075,copper),
                   "engine-left" if side<0 else "engine-right", 100+pod)
        detachable(sphere(f"THRUSTER-{side:+d}-{pod}",(x,-6.98,0),.25,blue,craft,16,8),
                   "engine-left" if side<0 else "engine-right", 110+pod)

# Nose sensors, dorsal guns, twin keel antennae and surface greebles.
for i in range(18):
    a=math.tau*i/18
    x=math.cos(a)*.45
    z=math.sin(a)*.38
    detachable(box(f"NOSE-SENSOR-{i:02d}",(.13,.34,.1),
                   (x,4.6,z),white if i%3 else amber,bevel=.018),"spine",300+i)
for side in (-1,1):
    for gun in range(9):
        y=2.4-gun*.85
        x=side*(1.64+gun*.16)
        detachable(tapered(f"RAILGUN-{side:+d}-{gun:02d}",
                            .40,-.40,.07,.10,.07,.10,dark),
                   "wing-left" if side<0 else "wing-right",100+gun)
        parts[-1].location=(x,y,.32)
        detachable(box(f"RAILGUN-FLASH-{side:+d}-{gun:02d}",
                       (.09,.13,.09),(x,y+.42,.32),blue,bevel=.012),
                   "wing-left" if side<0 else "wing-right",120+gun)
for i in range(70):
    y=RNG.uniform(-5.5,3.6)
    x=RNG.choice((-1,1))*RNG.uniform(.12,1.14)
    z=RNG.choice((-1,1))*RNG.uniform(.82,1.03)
    size=RNG.uniform(.035,.105)
    detachable(box(f"MICRO-GREEBLE-{i:03d}",
                   (size*1.3,size*2,size*.55),(x,y,z),
                   copper if i%5==0 else dark,bevel=.008),"spine",400+i)

# Role silhouettes remain real separate meshes in the same export. Visibility
# and transforms are keyframed so TiXL can switch configurations at runtime.
role_parts = {"EXPLORER":[], "HAULER":[]}


def role_object(obj, role):
    obj["configuration_role"] = role
    role_parts[role].append(obj)
    return obj


# EXPLORER: long survey bow, wide finned radiator/sensor arrays, dense
# instrument grid. The panels are deliberately broader than the combat wings.
role_object(tapered("EXPLORER | ten-metre survey boom",12.2,4.65,
                    .08,.22,.08,.22,white),"EXPLORER")
role_object(sphere("EXPLORER | forward survey head",(0,12.55,0),.43,
                   canopy_mat,craft,32,16),"EXPLORER")
for side in (-1,1):
    for panel in range(2):
        near=side*(4.4+panel*3.9)
        far=side*(8.0+panel*4.1)
        outline=[(near,2.2),(far,1.8),(far,-4.8),(near,-4.3)]
        role_object(poly_prism(f"EXPLORER-RADIATOR-{side:+d}-{panel}",
                               outline,.65,.73,white),"EXPLORER")
        for rib in range(9):
            yy=1.60-rib*.70
            xx=side*(6.2+panel*4.0)
            role_object(box(f"EXPLORER-SOLAR-CELL-{side:+d}-{panel}-{rib:02d}",
                            (2.9,.055,.025),(xx,yy,.745),
                            canopy_mat if rib%2 else blue,bevel=.008),"EXPLORER")
    for probe in range(4):
        role_object(ring(f"EXPLORER-LIDAR-{side:+d}-{probe}",
                         (side*(2.1+probe*.85),3.8,.38),.21,.035,copper,
                         segments=16),"EXPLORER")

# HAULER: broad twin cargo rails, twelve tall transport modules and reinforced
# container ribs give a bulky rectangular planform with a raised cargo deck.
for side in (-1,1):
    role_object(box(f"HAULER | heavy cargo cradle rail {side:+d}",
                    (.55,10.8,.72),(side*5.4,-1.2,.28),copper,bevel=.065),"HAULER")
    for station in range(6):
        role_object(box(f"HAULER-CRADLE-BRACE-{side:+d}-{station}",
                        (.55,.20,1.65),(side*5.4,2.9-station*1.55,.82),
                        dark,bevel=.025),"HAULER")
for row in range(4):
    for col in range(3):
        xx=(col-1)*2.55
        yy=2.3-row*2.35
        role_object(box(f"HAULER-CARGO-{row:02d}-{col:02d}",
                        (2.15,2.0,1.34),(xx,yy,1.70),
                        white if (row+col)%3==0 else hull,bevel=.11),"HAULER")
        for edge in (-1,1):
            role_object(box(f"HAULER-CONTAINER-STRAP-{row:02d}-{col:02d}-{edge:+d}",
                            (.10,1.92,1.48),(xx+edge*.83,yy,1.70),
                            copper,bevel=.018),"HAULER")

# A portable space environment: textured emissive geometry and real meshes,
# since Blender's World shader is not represented by glTF/TiXL.
backdrop = sky_sphere("DEEP SPACE | GPT Images 2.5 equirectangular sky", nebula, space)
backdrop["fixed_background"] = True
moon = sphere("Tethys analogue | cratered moon",(41,80,-14),17,planet_mat,space,80,40)
moon.rotation_euler=(.31,.12,.45)
for i in range(150):
    x=RNG.uniform(-100,100)
    y=RNG.uniform(55,109)
    z=RNG.uniform(-54,54)
    if (Vector((x,y,z))-moon.location).length < 20:
        continue
    radius=RNG.uniform(.012,.060)
    sphere(f"STAR-{i:03d}",(x,y,z),radius,star_mat,space,8,4)


def light(name, kind, loc, energy, color, size=None):
    data=bpy.data.lights.new(name,kind)
    data.energy=energy
    data.color=color
    if size and kind=="AREA":
        data.shape="DISK"
        data.size=size
    obj=bpy.data.objects.new(name,data)
    rig.objects.link(obj)
    obj.location=loc
    obj.rotation_euler=(Vector((0,0,0))-obj.location).to_track_quat("-Z","Y").to_euler()
    return obj


light("Distant sun | broad cool key","AREA",(17,-14,28),4600,(.72,.84,1.0),18)
light("Warm reflected moonlight","AREA",(-14,15,2),2500,(1.0,.48,.22),12)
light("Engine cobalt bounce","POINT",(0,-7,-2),900,(.12,.40,1.0))
cargo_key = light("Cargo deck | warm inspection fill","AREA",(7,-6,19),
                  0,(1.0,.78,.56),11)
for frame, energy in ((1,0),(2401,0),(2521,5600),(3061,5600),
                      (3181,0),(LAST,0)):
    cargo_key.data.energy=energy
    cargo_key.data.keyframe_insert("energy",frame=frame)


def camera(name, loc, target, focal):
    data=bpy.data.cameras.new(name)
    obj=bpy.data.objects.new(name,data)
    rig.objects.link(obj)
    obj.location=loc
    obj.rotation_euler=(Vector(target)-obj.location).to_track_quat("-Z","Y").to_euler()
    data.lens=focal
    data.clip_end=500
    return obj


cameras=[
    camera("CAM A | three-quarter beauty",(22,-34,15),(0,-1,0),46),
    camera("CAM B | overhead breakaway",(3,-22,38),(0,-1,0),34),
    camera("CAM C | engines and debris",(-18,-23,4),(0,-2,0),40),
    camera("CAM D | frontal reassembly",(2,29,12),(0,-1,0),40),
    camera("CAM E | illuminated cargo deck",(17,-16,16),(0,-1,1.4),43),
]
scene.camera=cameras[0]
for frame, which, title in [(1,0,"COMBAT | compact strike ship"),
                            (541,1,"Projectile breakup to EXPLORER"),
                            (1261,3,"EXPLORER | survey array"),
                            (1801,2,"Projectile breakup to HAULER"),
                            (2521,4,"HAULER | cargo cradle"),
                            (3061,2,"Return to COMBAT"),
                            (3481,0,"COMBAT | final assembly")]:
    marker=scene.timeline_markers.new(title,frame=frame)
    marker.camera=cameras[which]


def pose(obj, frame, position, angle, scale=(1,1,1)):
    obj.location=position
    obj.rotation_euler=angle
    obj.scale=scale
    obj.keyframe_insert("location",frame=frame)
    obj.keyframe_insert("rotation_euler",frame=frame)
    obj.keyframe_insert("scale",frame=frame)


for idx,obj in enumerate(parts):
    rest=obj.location.copy()
    group=obj.get("assembly_group")
    # A single seeded vector per part gives distinct projectile trajectories.
    direction=Vector((RNG.uniform(-1,1), RNG.uniform(-.30,1.25),
                      RNG.uniform(-.85,.85)))
    direction.normalize()
    travel=RNG.uniform(5.0,16.0)
    if group=="wing-left": direction.x=-abs(direction.x)-.12
    if group=="wing-right": direction.x=abs(direction.x)+.12
    spin=Vector((RNG.uniform(-.7,.7),RNG.uniform(-.9,.9),RNG.uniform(-.8,.8)))
    projectile=rest+direction*travel
    explorer=rest.copy()
    hauler=rest.copy()
    explorer_angle=Vector((0,0,0))
    hauler_angle=Vector((0,0,0))
    explorer_scale=(1,1,1)
    hauler_scale=(1,1,1)
    if group.startswith("wing"):
        side=-1 if group.endswith("left") else 1
        explorer.x=side*(1.25+max(0,abs(rest.x)-1.25)*1.75)
        explorer.y=rest.y*1.18+max(0,abs(rest.x)-2)*.28
        explorer.z=rest.z+.57
        explorer_angle.z=side*.13
        hauler.x=side*(2.4+max(0,abs(rest.x)-1.25)*.66)
        hauler.y=rest.y-.75
        hauler.z=rest.z-.40
        hauler_angle.y=side*.62
    elif group.startswith("engine"):
        side=-1 if group.endswith("left") else 1
        explorer.x=side*(abs(rest.x)*1.36)
        explorer.y=rest.y-1.2
        hauler.x=side*(abs(rest.x)*1.55)
        hauler.y=rest.y-.6
        hauler.z=rest.z-.5
    elif group=="spine":
        explorer.y=rest.y*1.26
        explorer_scale=(.81,1.13,.82)
        hauler.x=rest.x*1.28
        hauler.y=rest.y*.86
        hauler_scale=(1.22,.88,1.22)
    # Each object fires independently, then joins two starkly different
    # layouts. Key hold frames make the three role silhouettes unambiguous.
    trajectory=[(1,rest,(0,0,0),(1,1,1)),
                (541,rest,(0,0,0),(1,1,1)),
                (841,projectile,spin,(1,1,1)),
                (1041,projectile+direction*2.0,spin*1.55,(1,1,1)),
                (1261,explorer,explorer_angle,explorer_scale),
                (1801,explorer,explorer_angle,explorer_scale),
                (2251,projectile+direction*1.3,spin*.95,(1,1,1)),
                (2461,projectile+direction*2.2,spin*1.5,(1,1,1)),
                (2521,hauler,hauler_angle,hauler_scale),
                (3061,hauler,hauler_angle,hauler_scale),
                (3301,projectile,spin,(1,1,1)),
                (LAST,rest,(0,0,0),(1,1,1))]
    for frame,position,angle,scale in trajectory:
        pose(obj,frame,position,angle,scale)
    obj["projectile_travel_m"] = round(travel,3)

# Survey and cargo modules emerge from the projectile stream near their role
# assembly and disappear only after the next breakup begins.
for role, objects in role_parts.items():
    appear, assembled, end = ((1121,1261,1801) if role=="EXPLORER"
                               else (2401,2521,3061))
    for idx,obj in enumerate(objects):
        destination=obj.location.copy()
        offset=Vector((RNG.uniform(-8,8),RNG.uniform(4,14),RNG.uniform(-6,6)))
        pose(obj,1,destination+offset,(0,0,RNG.uniform(-1,1)))
        pose(obj,appear,destination+offset,(0,0,RNG.uniform(-1,1)))
        pose(obj,assembled,destination,(0,0,0))
        pose(obj,end,destination,(0,0,0))
        for frame,hidden in ((1,True),(appear-1,True),(appear,False),
                             (end,False),(end+1,True),(LAST,True)):
            obj.hide_render=hidden
            obj.keyframe_insert("hide_render",frame=frame)

# The entire ship drifts and banks while geometry-based space remains fixed.
for cam in cameras:
    cam.data.dof.use_dof=False  # deterministic TiXL camera approximation

scene.frame_set(1)
scene["detachable_mesh_count"] = len(parts)
scene["role_component_counts"] = {name:len(objects) for name,objects in role_parts.items()}
scene["static_space_object_count"] = len(space.objects)
scene["asset_directory"] = "//advanced_spaceship/textures"
bpy.ops.wm.save_as_mainfile(filepath=str(OUTPUT))
print("ASTERION_BUILT",{"file":str(OUTPUT),"detachable_parts":len(parts),
                         "space_objects":len(space.objects),"seconds":60,
                         "texture_files_found":len(list(ASSETS.glob("*.png")))})

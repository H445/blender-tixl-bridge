"""Build the 108-second Asterion spacecraft bridge stress test inside Blender MCP.

Run through the official Blender MCP TCP extension's execute_blender_code, for example
with ``exec(compile(open(path, encoding='utf-8').read(), path, 'exec'),
{'__file__': path})``. Never run
Blender via its command-line interface for this repository. The AI image assets live
in ``examples/advanced_spaceship/textures/`` and are supplied separately. The
builder requires the complete albedo, normal, and ORM map set.
"""

from __future__ import annotations

import math
import random
import re
import hashlib
from pathlib import Path

import bpy
from mathutils import Vector


ROOT = Path(__file__).resolve().parent
ASSETS = ROOT / "advanced_spaceship" / "textures"
OUTPUT = ROOT / "AsterionBreakaway.blend"
REQUIRED_TEXTURES = (
    "armor_graphite.png", "hull_normal.png", "hull_orm.png",
    "carbon_albedo.png", "carbon_normal.png", "carbon_orm.png",
    "heat_titanium.png", "copper_normal.png", "copper_orm.png",
    "solar_ceramic.png", "solar_normal.png", "solar_orm.png",
    "moon_albedo.png", "moon_normal.png", "moon_orm.png",
    "ember_albedo.png", "ember_normal.png", "ember_orm.png",
    "nasa_starmap_16k.jpg",
)
missing_textures = [name for name in REQUIRED_TEXTURES if not (ASSETS / name).is_file()]
if missing_textures:
    raise FileNotFoundError(f"Required PBR texture maps are missing: {missing_textures}")
FPS = 60
SOURCE_LAST = 3601
SECONDS = 108
LAST = SECONDS*FPS+1
# Extend each assembled hold to 24 seconds for a complete unbroken orbit.
# The 12-second breakaways retain their original bullet-time choreography.
TIME_ANCHORS = ((1,1),(541,1441),(1261,2161),(1801,3601),
                (2521,4321),(3061,5761),(SOURCE_LAST,LAST))


def retimed_frame(frame):
    for (source_start,target_start),(source_end,target_end) in zip(
            TIME_ANCHORS,TIME_ANCHORS[1:]):
        if source_start <= frame <= source_end:
            return round(target_start+(frame-source_start)
                         *(target_end-target_start)/(source_end-source_start))
    raise ValueError(f"Frame {frame} lies outside the source choreography")


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
scene["demo_duration_seconds"] = SECONDS
scene["demo_phases"] = "0-24 COMBAT orbit; 24-36 breakaway to EXPLORER; 36-60 EXPLORER orbit; 60-72 breakaway to HAULER; 72-96 HAULER orbit; 96-108 return to COMBAT"
scene["variant_hold_frames"] = "COMBAT 1-1441; EXPLORER 2161-3601; HAULER 4321-5761"
scene["texture_source"] = "GPT Images 2.5 surface maps; NASA/Goddard space panorama; see examples/advanced_spaceship/textures"

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
        raise FileNotFoundError(path)
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
        tex = image_node(nodes, links, "GPT Images 2.5 source-derived ORM", orm,
                         "Roughness", bsdf, noncolor=True)
        if tex:
            sep = nodes.new("ShaderNodeSeparateColor")
            links.remove(bsdf.inputs["Roughness"].links[0])
            links.new(tex.outputs["Color"], sep.inputs["Color"])
            gltf_group = bpy.data.node_groups.get("glTF Material Output")
            if gltf_group is None:
                gltf_group = bpy.data.node_groups.new("glTF Material Output",
                                                      "ShaderNodeTree")
                gltf_group.interface.new_socket("Occlusion",
                                                socket_type="NodeSocketFloat")
            gltf_output = nodes.new("ShaderNodeGroup")
            gltf_output.node_tree = gltf_group
            links.new(sep.outputs["Red"], gltf_output.inputs["Occlusion"])
            links.new(sep.outputs["Green"], bsdf.inputs["Roughness"])
            links.new(sep.outputs["Blue"], bsdf.inputs["Metallic"])
    if normal:
        path = ASSETS / normal
        if not path.is_file():
            raise FileNotFoundError(path)
        tex = nodes.new("ShaderNodeTexImage")
        tex.label = "GPT Images 2.5 source-derived normal"
        tex.image = bpy.data.images.load(str(path), check_existing=True)
        tex.image.pack()
        tex.image.filepath = "//advanced_spaceship/textures/" + normal
        tex.image.colorspace_settings.name = "Non-Color"
        nmap = nodes.new("ShaderNodeNormalMap")
        nmap.inputs["Strength"].default_value = 0.52
        links.new(tex.outputs["Color"], nmap.inputs["Color"])
        links.new(nmap.outputs["Normal"], bsdf.inputs["Normal"])
    if emission:
        image_node(nodes, links, "Space panorama emission", emission, "Emission Color", bsdf)
        bsdf.inputs["Emission Strength"].default_value = max(emission_strength, 1.0)
    return mat


hull = pbr("01 | ceramic titanium armored hull", (0.29, 0.36, 0.43), 0.84, 0.34,
           albedo="armor_graphite.png", orm="hull_orm.png", normal="hull_normal.png")
dark = pbr("02 | carbon ceramic recess", (0.025, 0.043, 0.061), 0.08, 0.62,
           albedo="carbon_albedo.png", orm="carbon_orm.png", normal="carbon_normal.png")
copper = pbr("03 | heat-scarred copper alloy", (0.53, 0.26, 0.11), 0.93, 0.38,
             albedo="heat_titanium.png", orm="copper_orm.png", normal="copper_normal.png")
white = pbr("04 | photovoltaic ceramic cover", (0.66, 0.72, 0.75), 0.24, 0.32,
            albedo="solar_ceramic.png", orm="solar_orm.png",
            normal="solar_normal.png")
canopy_mat = pbr("04b | smoked iridium cockpit glazing", (0.10, 0.20, 0.27),
                 0.42, 0.22)
blue = pbr("05 | ion blue emitter", (0.04, 0.16, 0.28), 0.38, 0.22,
           emission_color=(0.045, 0.43, 0.95), emission_strength=7.0)
amber = pbr("06 | warning amber emitter", (0.24, 0.10, 0.015), 0.25, 0.3,
            emission_color=(1.0, 0.29, 0.035), emission_strength=3.0)
starfield = pbr("07 | NASA Goddard deep star map", (0, 0, 0), 0, 1,
                emission="nasa_starmap_16k.jpg", emission_color=(1, 1, 1),
                emission_strength=2.0)
planet_mat = pbr("08 | cratered moon regolith", (0.32, 0.31, 0.30), 0.02, 0.91,
                 albedo="moon_albedo.png", orm="moon_orm.png",
                 normal="moon_normal.png")
star_mat = pbr("09 | distant stars", (1, 1, 1), 0, 1,
               emission_color=(1, 1, 1), emission_strength=5)


def fabrication_signature(name):
    return hashlib.sha256(name.encode("utf-8")).digest()


def mesh_object(name, verts, faces, material, coll, uv=True,
                extra_materials=(), face_materials=None):
    mesh = bpy.data.meshes.new(name + " mesh")
    signature = fabrication_signature(name)
    # Individual machining tolerances and slight asymmetric panel draft give
    # repeated classes different physical profiles without changing the part
    # pool or compromising their keyed assembly positions.
    sx = .975 + signature[14]/255*.05
    sy = .975 + signature[15]/255*.05
    sz = .975 + signature[16]/255*.05
    draft_x = (signature[17]/255-.5)*.018
    draft_y = (signature[18]/255-.5)*.018
    verts = [(vx*sx+vz*draft_x,vy*sy+vz*draft_y,vz*sz)
             for vx,vy,vz in verts]
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    if uv:
        # Per-part rotations and offsets sample different patches of the packed
        # albedo maps, so neighboring plates do not repeat identical wear.
        layer = mesh.uv_layers.new(name="UVMap")
        quarter_turn = signature[0] % 4
        offset_u = signature[1] / 255 * .67
        offset_v = signature[2] / 255 * .67
        for poly in mesh.polygons:
            n = poly.normal
            axis = max(range(3), key=lambda i: abs(n[i]))
            other = [i for i in range(3) if i != axis]
            for li in poly.loop_indices:
                co = mesh.vertices[mesh.loops[li].vertex_index].co
                u = co[other[0]] * .35 + .5
                v = co[other[1]] * .35 + .5
                if quarter_turn == 1:
                    u,v=v,1-u
                elif quarter_turn == 2:
                    u,v=1-u,1-v
                elif quarter_turn == 3:
                    u,v=1-v,u
                layer.data[li].uv = (u+offset_u,v+offset_v)
    obj = bpy.data.objects.new(name, mesh)
    coll.objects.link(obj)
    mesh.materials.append(material)
    for extra in extra_materials:
        mesh.materials.append(extra)
    if face_materials is not None:
        for poly,index in zip(mesh.polygons,face_materials):
            poly.material_index=index
    obj["fabrication_variant"] = signature[:4].hex()
    return obj


def box(name, size, location, material, coll=craft, bevel=0.0):
    x, y, z = (d * 0.5 for d in size)
    signature = fabrication_signature(name)
    machined = size[0] >= .22 and size[1] >= .35 and size[2] >= .09
    if machined:
        corner = min(x,y)*(.12 + signature[4]/255*.16)
        inset = .13 + signature[5]/255*.10
        recess = min(z*.22,.065)
        offset_x = (signature[6]/255-.5)*x*.065
        offset_y = (signature[7]/255-.5)*y*.065
        def octagon(hx,hy,chamfer,dx=0,dy=0):
            return [(dx-hx+chamfer,dy-hy),(dx+hx-chamfer,dy-hy),
                    (dx+hx,dy-hy+chamfer),(dx+hx,dy+hy-chamfer),
                    (dx+hx-chamfer,dy+hy),(dx-hx+chamfer,dy+hy),
                    (dx-hx,dy+hy-chamfer),(dx-hx,dy-hy+chamfer)]
        rings = [(octagon(x,y,corner),-z),
                 (octagon(x,y,corner),z),
                 (octagon(x*(1-inset),y*(1-inset),corner*.65,
                          offset_x,offset_y),z-recess)]
        v=[(vx,vy,height) for outline,height in rings for vx,vy in outline]
        f=[tuple(reversed(range(8)))]
        for base in (0,8):
            f.extend((base+i,base+(i+1)%8,base+8+(i+1)%8,base+8+i)
                     for i in range(8))
        f.append(tuple(range(16,24)))
        face_materials=[0]*len(f)
        face_materials[-1]=1
        for i in range(8):
            if (i+signature[8])%4==0:
                face_materials[9+i]=1
        accent = copper if material == dark else dark
        extra_materials=(accent,copper,white)
        if size[0] >= 1.5 and size[1] >= 1.5 and size[2] >= .8:
            # Cargo pods are manufactured as individual service units, not
            # twelve copies of a plain block. Vents, latch plates and radiator
            # strips are welded into each pod's mesh so the piece stays whole.
            roof=z-recess+.008
            raised=min(.045,size[2]*.035)
            def roof_plate(cx,cy,sx,sy,slot):
                start=len(v)
                ax,bx=cx-sx*.5,cx+sx*.5
                ay,by=cy-sy*.5,cy+sy*.5
                v.extend(((ax,ay,roof),(bx,ay,roof),(bx,by,roof),(ax,by,roof),
                          (ax,ay,roof+raised),(bx,ay,roof+raised),
                          (bx,by,roof+raised),(ax,by,roof+raised)))
                f.extend(tuple(start+index for index in face)
                         for face in ((0,3,2,1),(4,5,6,7),(0,1,5,4),
                                      (1,2,6,5),(2,3,7,6),(3,0,4,7)))
                face_materials.extend((slot,)*6)
            roof_variant=signature[9]%4
            roof_color=2+signature[10]%2
            face_materials[17]=1+signature[11]%3
            if roof_variant==0:  # parallel cooling ducts
                for j in range(3):
                    roof_plate((j-1)*x*.54+offset_x,offset_y,
                               x*.13,y*1.20,roof_color)
            elif roof_variant==1:  # transverse impact ribs
                for j in range(4):
                    roof_plate(offset_x,(j-1.5)*y*.38+offset_y,
                               x*1.35,y*.11,roof_color)
            elif roof_variant==2:  # two offset access hatches and a latch
                roof_plate(-x*.27+offset_x,offset_y-y*.16,
                           x*.60,y*.82,roof_color)
                roof_plate(x*.38+offset_x,offset_y+y*.20,
                           x*.47,y*.58,1)
                roof_plate(x*.19+offset_x,offset_y-y*.17,
                           x*.10,y*.22,2)
            else:  # split thermal tiles around a service channel
                for side in (-1,1):
                    for row in (-1,1):
                        roof_plate(side*x*.43+offset_x,row*y*.40+offset_y,
                                   x*.43,y*.45,roof_color if side==row else 1)
            roof_plate((signature[12]/255-.5)*x*.65,
                       (signature[13]/255-.5)*y*.65,
                       x*.11,y*.13,2)
        else:
            extra_materials=(accent,)
        obj = mesh_object(name,v,f,material,coll,
                          extra_materials=extra_materials,
                          face_materials=face_materials)
        if size[0] >= 1.5 and size[1] >= 1.5 and size[2] >= .8:
            obj["roof_variant"] = roof_variant
        bevel=min(bevel,recess*.38,min(size)*.055)
    else:
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
    trench = name.startswith(("FUSELAGE", "NACELLE", "RAILGUN"))
    for y, w, h in zip(ys, (half_w_front, half_w_rear), (half_h_front, half_h_rear)):
        if trench:
            verts.extend([(-w*.72,y,-h),(w*.72,y,-h),(w,y,-h*.65),
                          (w,y,h*.65),(w*.72,y,h),(w*.30,y,h),
                          (w*.20,y,h*.57),(-w*.20,y,h*.57),
                          (-w*.30,y,h),(-w*.72,y,h),
                          (-w,y,h*.65),(-w,y,-h*.65)])
        else:
            verts.extend([(-w*.72,y,-h), (w*.72,y,-h), (w,y,-h*.65),
                          (w,y,h*.65),(w*.72,y,h),(-w*.72,y,h),
                          (-w,y,h*.65),(-w,y,-h*.65)])
    ring_size = 12 if trench else 8
    faces = [tuple(reversed(range(ring_size))),
             tuple(range(ring_size,ring_size*2))]
    faces += [(i,(i+1)%ring_size,(i+1)%ring_size+ring_size,i+ring_size)
              for i in range(ring_size)]
    if trench:
        face_materials=[0]*len(faces)
        face_materials[2+5]=2  # copper-lined descent
        face_materials[2+6]=3 if name.startswith("FUSELAGE-01") else 1
        face_materials[2+7]=2  # copper-lined ascent
        face_materials[2+2]=1
        face_materials[2+10]=1
        obj=mesh_object(name,verts,faces,material,coll,
                        extra_materials=(dark,copper,blue),
                        face_materials=face_materials)
        obj["service_trench"] = True
    else:
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
    signature = fabrication_signature(name)
    radii = tuple(radius*(.975+signature[14+i]/255*.05) for i in range(3))
    for j in range(rings+1):
        theta = math.pi*j/rings
        for i in range(segments+1):
            phi = math.tau*i/segments
            verts.append((radii[0]*math.sin(theta)*math.cos(phi),
                          radii[1]*math.sin(theta)*math.sin(phi),
                          radii[2]*math.cos(theta)))
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
    obj["fabrication_variant"] = signature[:4].hex()
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


def cockpit_shell():
    """A low, sloped flight deck seated against the tapered pressure hull."""
    outline = [(-.42, 4.00), (.42, 4.00), (.78, 2.90), (.84, 1.22),
               (.50, .62), (-.50, .62), (-.84, 1.22), (-.78, 2.90)]
    base_z = [.35, .35, .56, .83, .84, .84, .83, .56]
    roof_y = [3.69, 3.69, 2.77, 1.36, .84, .84, 1.36, 2.77]
    roof_z = [.92, .92, 1.43, 1.72, 1.43, 1.43, 1.72, 1.43]
    center = Vector((0, 2.30, 1.02))
    vertices = []
    for ring in range(3):
        for index, (x, y) in enumerate(outline):
            if ring == 0:
                point = (x, y, base_z[index])
            elif ring == 1:
                point = (x*.97, y, base_z[index]+.14)
            else:
                point = (x*.72, roof_y[index], roof_z[index])
            vertices.append(tuple(Vector(point)-center))
    faces = [tuple(reversed(range(8)))]
    faces.extend((i, (i+1)%8, (i+1)%8+8, i+8) for i in range(8))
    faces.extend((i+8, (i+1)%8+8, (i+1)%8+16, i+16) for i in range(8))
    faces.append(tuple(range(16, 24)))
    # The nose-to-tail outline winds clockwise when viewed from above.
    faces = [tuple(reversed(face)) for face in faces]
    obj = mesh_object("COCKPIT | faceted iridium canopy", vertices, faces,
                      canopy_mat, craft, extra_materials=(copper, hull),
                      face_materials=[2] + [1]*8 + [0]*8 + [0])
    obj.location = center
    obj["flight_deck_seated"] = True
    return obj


def cockpit_frame_rail(side):
    """One continuous shoulder rail follows each canopy's sloping glass edge."""
    stations = [(side*.32, 3.70, .91), (side*.56, 2.77, 1.43),
                (side*.60, 1.36, 1.72), (side*.36, .84, 1.43)]
    center = sum((Vector(point) for point in stations), Vector())/len(stations)
    vertices = []
    for point in stations:
        x, y, z = point
        vertices.extend(tuple(Vector((x+dx, y, z+dz))-center)
                        for dx, dz in ((-.055,-.045),(.055,-.045),
                                       (.055,.045),(-.055,.045)))
    faces = [(3,2,1,0)]
    for station in range(len(stations)-1):
        base = station*4
        faces.extend((base+i, base+(i+1)%4,
                      base+(i+1)%4+4, base+i+4) for i in range(4))
    faces.append(tuple(range((len(stations)-1)*4, len(stations)*4)))
    obj = mesh_object(f"COCKPIT-RAIL-{side:+d} | titanium frame",
                      vertices, faces, copper, craft)
    obj.location = center
    return obj


def sky_sphere(name, material, coll, radius=350, segments=96, rings=48):
    # Inward-facing equirectangular UV mesh is visible throughout the orbit.
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

# The shared flight deck has a sloped nose, glazing, metal skirt, and two
# shoulder rails. It stays seated on the pressure hull in every configuration.
detachable(cockpit_shell(),"spine",205)
for side in (-1,1):
    detachable(cockpit_frame_rail(side),"spine",206+(side+1)//2)
    for section in range(5):
        y = 3.48-section*.45
        detachable(box(f"COCKPIT-HUD-{side:+d}-{section}",
                       (.045,.18,.025),(side*.40,y,1.73-.22*(y-1.2)),
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
    x=math.cos(a)*.24
    z=math.sin(a)*.25
    detachable(box(f"NOSE-SENSOR-{i:02d}",(.13,.34,.1),
                   (x,4.6,z),white if i%3 else amber,bevel=.018),"spine",300+i)
for side in (-1,1):
    for gun in range(9):
        # Fasten each weapon to the swept wing skin, rather than leaving the
        # forward guns suspended beyond the leading edge.
        y=.8-gun*.56
        x=side*(2.2+gun*.55)
        detachable(tapered(f"RAILGUN-{side:+d}-{gun:02d}",
                            .40,-.40,.07,.10,.07,.10,dark),
                   "wing-left" if side<0 else "wing-right",100+gun)
        parts[-1].location=(x,y,.19)
        detachable(box(f"RAILGUN-FLASH-{side:+d}-{gun:02d}",
                       (.09,.13,.09),(x,y+.42,.19),blue,bevel=.012),
                   "wing-left" if side<0 else "wing-right",120+gun)
for i in range(70):
    y=RNG.uniform(-5.5,3.6)
    # Keep every machined fitting partially seated in the pressure shell.
    if y > 1.1:
        progress=(5.1-y)/4.0
        half_width=.10+(1.33-.10)*progress
        half_height=.12+(.90-.12)*progress
    elif y > -3.1:
        progress=(1.1-y)/4.2
        half_width=1.33+(1.48-1.33)*progress
        half_height=.90+(.82-.90)*progress
    else:
        progress=(-3.1-y)/3.5
        half_width=1.48+(1.00-1.48)*progress
        half_height=.82+(.66-.82)*progress
    x=RNG.choice((-1,1))*RNG.uniform(.12,.60)*half_width
    size=RNG.uniform(.035,.105)
    z=RNG.choice((-1,1))*(half_height+size*.08)
    detachable(box(f"MICRO-GREEBLE-{i:03d}",
                   (size*1.3,size*2,size*.55),(x,y,z),
                   copper if i%5==0 else dark,bevel=.008),"spine",400+i)

# Every role module starts in the COMBAT ship and is reused in EXPLORER and
# HAULER. No craft component is spawned, hidden, or swapped at a cut.
role_parts = {"EXPLORER":[], "HAULER":[]}


def role_object(obj, role):
    obj["configuration_role"] = role
    obj["asterion_part"] = True
    obj["assembly_group"] = role.lower()
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
                               outline,.40,.48,white),"EXPLORER")
        for rib in range(9):
            yy=1.60-rib*.70
            xx=side*(6.2+panel*4.0)
            role_object(box(f"EXPLORER-SOLAR-CELL-{side:+d}-{panel}-{rib:02d}",
                            (2.9,.055,.025),(xx,yy,.49),
                            canopy_mat if rib%2 else blue,bevel=.008),"EXPLORER")
    for station, yy in enumerate((.8,-3.0)):
        role_object(box(f"EXPLORER-ARRAY-TRUSS-{side:+d}-{station}",
                        (3.6,.24,.30),(side*3.0,yy,.36),copper,
                        bevel=.035),"EXPLORER")
    for probe in range(4):
        role_object(ring(f"EXPLORER-LIDAR-{side:+d}-{probe}",
                         (side*.17,5.2+probe*1.55+(0 if side<0 else .72),0),
                         .21,.035,copper,
                         segments=16),"EXPLORER")

# HAULER: two supported, evenly spaced cargo banks surround an unobstructed
# central flight deck instead of overlapping into an opaque wall.
for side in (-1,1):
    role_object(box(f"HAULER | heavy cargo cradle rail {side:+d}",
                    (.55,10.8,.72),(side*5.4,-1.2,.28),copper,bevel=.065),"HAULER")
    for station in range(6):
        role_object(box(f"HAULER-CRADLE-BRACE-{side:+d}-{station}",
                        (.55,.20,1.65),(side*5.4,2.9-station*1.55,.82),
                        dark,bevel=.025),"HAULER")
for row in range(4):
    # Four broad deck plates tie the two cargo banks into a deliberate,
    # load-bearing silhouette while leaving a 3.4 m cockpit corridor.
    deck_side = -1 if row < 2 else 1
    deck_y = 1.50 if row % 2 == 0 else -3.20
    deck_length = 4.60 if row % 2 == 0 else 6.20
    role_object(box(f"HAULER-CARGO-DECK-{row:02d}",
                    (3.0,deck_length,.38),(deck_side*3.20,deck_y,.68),
                    dark,bevel=.045),"HAULER")
    for col in range(3):
        # Six serial containers on each side have a 0.28 m longitudinal gap.
        xx=-4.35 if row<2 else 4.35
        pod_y=3.2-((row%2)*3+col)*1.8
        role_object(box(f"HAULER-CARGO-{row:02d}-{col:02d}",
                        (2.15,1.52,1.15),(xx,pod_y,1.50),
                        white if (row+col)%3==0 else hull,bevel=.11),"HAULER")
        for edge in (-1,1):
            role_object(box(f"HAULER-CONTAINER-STRAP-{row:02d}-{col:02d}-{edge:+d}",
                            (.10,1.48,1.25),(xx+edge*.83,pod_y,1.50),
                            copper,bevel=.018),"HAULER")

# A portable space environment: textured emissive geometry and real meshes,
# since Blender's World shader is not represented by glTF/TiXL.
backdrop = sky_sphere("DEEP SPACE | NASA Goddard 16K star map", starfield, space)
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


light("Distant sun | broad cool key","AREA",(17,-14,28),11000,(.82,.90,1.0),18)
light("Warm reflected moonlight","AREA",(-14,15,7),6500,(1.0,.72,.48),16)
light("Port bounce | ceramic detail","AREA",(-20,-10,11),4800,(.58,.72,1.0),15)
light("Starboard bounce | ceramic detail","AREA",(21,13,10),4800,(.72,.82,1.0),15)
light("Ventral reflected light","AREA",(2,3,-15),3600,(.55,.68,1.0),18)
light("Engine cobalt bounce","POINT",(0,-7,-2),1400,(.18,.45,1.0))
cargo_key = light("Cargo deck | warm inspection fill","AREA",(7,-6,19),
                  0,(1.0,.78,.56),11)
for frame, energy in ((1,0),(2401,0),(2521,5600),(3061,5600),
                      (3181,0),(SOURCE_LAST,0)):
    cargo_key.data.energy=energy
    cargo_key.data.keyframe_insert("energy",frame=retimed_frame(frame))

for burst_frame in (541, 1801, 3061):
    flash = light(f"Breakaway flash | {burst_frame}", "POINT", (0, 0, 1),
                  0, (0.57, 0.78, 1.0))
    for frame, energy in ((1, 0), (burst_frame-1, 0),
                          (burst_frame+4, 10500), (burst_frame+22, 1100),
                          (burst_frame+65, 0), (SOURCE_LAST, 0)):
        flash.data.energy = energy
        flash.data.keyframe_insert("energy", frame=retimed_frame(frame))


camera_data = bpy.data.cameras.new("CAM | uninterrupted orbital take")
camera_data.lens = 33
camera_data.clip_end = 500
camera_data.dof.use_dof = False  # deterministic TiXL camera approximation
cinema_camera = bpy.data.objects.new(camera_data.name, camera_data)
rig.objects.link(cinema_camera)
scene.camera = cinema_camera
previous_camera_rotation = None


def smootherstep(start, end, value):
    amount = max(0.0, min(1.0, (value-start)/(end-start)))
    return amount*amount*amount*(amount*(amount*6-15)+10)


def camera_pose(frame):
    global previous_camera_rotation
    seconds = (frame-1)/FPS
    progress = seconds/SECONDS
    # One complete azimuth revolution during each 24-second assembled hold.
    # The base orbit never stops, and three smooth extra arcs circle debris.
    orbit = (-0.97 + math.tau*(seconds/24.0
             + 0.12*smootherstep(24.0, 36.0, seconds)
             + 0.12*smootherstep(60.0, 72.0, seconds)
             + 0.12*smootherstep(96.0, 108.0, seconds)))
    radius = 36.0 + 3.5*math.sin(math.tau*progress+0.25)
    height = 15.0 + 5.5*math.sin(math.tau*progress-0.4)
    cinema_camera.location = (radius*math.cos(orbit),
                              radius*math.sin(orbit), height)
    target = Vector((0, -0.4 + 0.7*math.sin(math.tau*progress),
                     0.5 + 0.4*math.sin(math.tau*progress-0.5)))
    rotation = (target-cinema_camera.location).to_track_quat("-Z", "Y").to_euler()
    if previous_camera_rotation is not None:
        rotation.make_compatible(previous_camera_rotation)
    previous_camera_rotation = rotation.copy()
    cinema_camera.rotation_euler = rotation
    cinema_camera.keyframe_insert("location", frame=frame)
    cinema_camera.keyframe_insert("rotation_euler", frame=frame)


# Dense keys closely approximate the analytic continuous path in Blender and
# in the bridge's 60 Hz camera bake. No timeline camera markers create cuts.
for camera_frame in list(range(1, LAST, 12)) + [LAST]:
    camera_pose(camera_frame)
scene["camera_style"] = "single continuous take; full orbit of each assembled ship; bullet-time debris arcs"


def pose(obj, frame, position, angle, scale=(1,1,1)):
    obj.location=position
    obj.rotation_euler=angle
    obj.scale=scale
    output_frame=retimed_frame(frame)
    obj.keyframe_insert("location",frame=output_frame)
    obj.keyframe_insert("rotation_euler",frame=output_frame)
    obj.keyframe_insert("scale",frame=output_frame)


def slowed_burst(frame, start, start_angle, start_scale,
                 end, end_angle, end_scale, fraction):
    return (frame, start.lerp(end, fraction),
            start_angle.lerp(end_angle, fraction),
            tuple(a+(b-a)*fraction for a,b in zip(start_scale,end_scale)))


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
        # Rotate the complete wing assembly around one root hinge. Applying a
        # different stretch to each part separated its plates and weapons.
        pivot=Vector((side*1.0,1.0,0))
        relative=rest-pivot
        turn=side*.28
        explorer=Vector((pivot.x+relative.x*math.cos(turn)
                         -relative.y*math.sin(turn),
                         pivot.y+relative.x*math.sin(turn)
                         +relative.y*math.cos(turn),rest.z+.22))
        explorer_angle.z=turn
        fold=-side*.38
        hauler=Vector((pivot.x+relative.x*math.cos(fold)
                       +relative.z*math.sin(fold),
                       rest.y-.50,
                       pivot.z-relative.x*math.sin(fold)
                       +relative.z*math.cos(fold)-.20))
        hauler_angle.y=fold
    elif group.startswith("engine"):
        side=-1 if group.endswith("left") else 1
        explorer=rest+Vector((side*1.0,-.65,.12))
        hauler=rest+Vector((side*1.0,-.60,-.25))
    elif group=="spine":
        # The pressure shell stays watertight in every role. Mission hardware
        # and hinged wings change the outline around this common load path.
        explorer=rest.copy()
        hauler=rest.copy()
    # Each object fires independently, then joins two starkly different
    # layouts. Key hold frames make the three role silhouettes unambiguous.
    trajectory=[(1,rest,(0,0,0),(1,1,1)),
                (541,rest,(0,0,0),(1,1,1)),
                slowed_burst(580,rest,Vector((0,0,0)),(1,1,1),
                             projectile,spin,(1,1,1),.30),
                slowed_burst(900,rest,Vector((0,0,0)),(1,1,1),
                             projectile,spin,(1,1,1),.35),
                (1041,projectile+direction*2.0,spin*1.55,(1,1,1)),
                (1261,explorer,explorer_angle,explorer_scale),
                (1801,explorer,explorer_angle,explorer_scale),
                slowed_burst(1840,explorer,explorer_angle,explorer_scale,
                             projectile,spin,(1,1,1),.30),
                slowed_burst(2180,explorer,explorer_angle,explorer_scale,
                             projectile,spin,(1,1,1),.35),
                (2251,projectile+direction*1.3,spin*.95,(1,1,1)),
                (2461,projectile+direction*2.2,spin*1.5,(1,1,1)),
                (2521,hauler,hauler_angle,hauler_scale),
                (3061,hauler,hauler_angle,hauler_scale),
                slowed_burst(3100,hauler,hauler_angle,hauler_scale,
                             projectile,spin,(1,1,1),.30),
                slowed_burst(3230,hauler,hauler_angle,hauler_scale,
                             projectile,spin,(1,1,1),.35),
                (3301,projectile,spin,(1,1,1)),
                (SOURCE_LAST,rest,(0,0,0),(1,1,1))]
    for frame,position,angle,scale in trajectory:
        pose(obj,frame,position,angle,scale)
    obj["projectile_travel_m"] = round(travel,3)

# The same survey and cargo modules are armored combat fittings, explorer
# instruments, and hauler equipment. Their mesh identities and visibility
# persist across every configuration and every projectile salvo.
for role, objects in role_parts.items():
    for idx,obj in enumerate(objects):
        original=obj.location.copy()
        combat_angle=Vector((0,0,0))
        explorer_angle=Vector((0,0,0))
        hauler_angle=Vector((0,0,0))
        if role=="EXPLORER":
            explorer=original
            explorer_scale=(1,1,1)
            if "ten-metre" in obj.name:
                combat=Vector((0,0,-1.15))
                combat_scale=(.72,.60,.72)
                # The survey spar becomes a protected longitudinal keel below
                # the hauler's shared pressure hull, not a stalk above it.
                hauler=Vector((0,-1.15,-.78))
                hauler_scale=(1.35,.86,1.30)
            elif "forward survey head" in obj.name:
                combat=Vector((0,2.45,-1.15))
                combat_scale=(.80,.80,.80)
                hauler=Vector((0,-4.55,-.78))
                hauler_scale=(1.25,.78,1.25)
            elif "ARRAY-TRUSS" in obj.name:
                side=-1 if original.x<0 else 1
                combat=Vector((side*3.0,original.y,-.06))
                combat_scale=(.82,.86,.72)
                hauler=Vector((side*3.45,original.y,1.08))
                hauler_scale=(.92,1,.9)
            elif "RADIATOR" in obj.name:
                side=-1 if original.x<0 else 1
                panel=0 if abs(original.x)<8 else 1
                combat=Vector((side*(3.8+panel*1.75),-2.1,.36))
                combat_scale=(.52,.58,.8)
                combat_angle.z=side*.18
                hauler=Vector((side*(3.85+panel*.40),1.35-panel*3.15,2.36))
                hauler_scale=(.48,.47,.7)
                hauler_angle.y=side*.16
            elif "SOLAR-CELL" in obj.name:
                side=-1 if original.x<0 else 1
                panel=0 if abs(original.x)<8 else 1
                rib=round((1.60-original.y)/.70)
                combat=Vector((side*(3.8+panel*1.75),.50-rib*.47,.40))
                combat_scale=(.56,.80,.8)
                hauler=Vector((side*(3.85+panel*.40),
                               2.5-panel*3.15-rib*.32,2.40))
                hauler_scale=(.50,.8,.8)
            else:  # lidar rings become combat apertures and cargo couplers
                match=re.search(r"EXPLORER-LIDAR-([+-]1)-(\d+)",obj.name)
                if match is None:
                    raise ValueError(f"Unclassified survey collar: {obj.name}")
                side,probe=(int(value) for value in match.groups())
                combat=Vector((side*(2.6+probe*.8),.8-probe*1.3,.22))
                combat_scale=(.8,.8,.8)
                hauler=Vector((side*5.35,2.8-probe*2.1,1.05))
                hauler_scale=(1,1,1)
        else:
            hauler=original
            hauler_scale=(1,1,1)
            if "heavy cargo cradle rail" in obj.name:
                side=-1 if original.x<0 else 1
                combat=Vector((side*4.15,-1.6,-.55))
                combat_scale=(.63,.73,.72)
                explorer=Vector((side*1.20,-1.1,.55))
                explorer_scale=(.55,.83,.60)
            elif "CRADLE-BRACE" in obj.name:
                side=-1 if original.x<0 else 1
                station=round((2.9-original.y)/1.55)
                combat=Vector((side*3.45,-.2-station*.85,-.35))
                combat_scale=(.68,.72,.70)
                explorer=Vector((side*1.20,2.8-station*1.55,.85))
                explorer_scale=(.55,.72,.62)
            elif "CARGO-DECK" in obj.name:
                row=int(obj.name.rsplit("-",1)[-1])
                combat=Vector((0,1.7-row*1.6,-.32))
                combat_scale=(.70,.80,.50)
                explorer=Vector((0,2.6-row*1.9,-.45))
                explorer_scale=(.70,.80,.50)
            else:  # twelve cargo pods and their permanently attached straps
                match=re.search(r"HAULER-(?:CARGO|CONTAINER-STRAP)-(\d+)-(\d+)",obj.name)
                if match is None:
                    raise ValueError(f"Unclassified reusable cargo module: {obj.name}")
                row,col=(int(value) for value in match.groups())
                center_x=-4.35 if row<2 else 4.35
                local_x=original.x-center_x
                side=-1 if row<2 else 1
                combat=Vector((side*(2.45+col*1.12)+local_x*.50,
                               1.1-(row%2)*2.15-col*.30,
                               .53+(original.z-1.50)*.50))
                combat_scale=(.50,.52,.50)
                explorer=Vector(((col-1)*1.10+local_x*.43,
                                 2.6-row*1.9,1.02))
                explorer_scale=(.43,.46,.43)
        direction=Vector((RNG.uniform(-1,1),RNG.uniform(-.25,1.2),
                          RNG.uniform(-.85,.85)))
        direction.x+=(-.3 if combat.x<0 else .3)
        direction.normalize()
        travel=RNG.uniform(5.0,16.0)
        spin=Vector((RNG.uniform(-.7,.7),RNG.uniform(-.9,.9),
                     RNG.uniform(-.8,.8)))
        projectile=combat+direction*travel
        trajectory=((1,combat,combat_angle,combat_scale),
                    (541,combat,combat_angle,combat_scale),
                    slowed_burst(580,combat,combat_angle,combat_scale,
                                 projectile,spin,combat_scale,.30),
                    slowed_burst(900,combat,combat_angle,combat_scale,
                                 projectile,spin,combat_scale,.35),
                    (1041,projectile+direction*2,spin*1.55,combat_scale),
                    (1261,explorer,explorer_angle,explorer_scale),
                    (1801,explorer,explorer_angle,explorer_scale),
                    slowed_burst(1840,explorer,explorer_angle,explorer_scale,
                                 projectile,spin,combat_scale,.30),
                    slowed_burst(2180,explorer,explorer_angle,explorer_scale,
                                 projectile,spin,combat_scale,.35),
                    (2251,projectile+direction*1.3,spin*.95,combat_scale),
                    (2461,projectile+direction*2.2,spin*1.5,combat_scale),
                    (2521,hauler,hauler_angle,hauler_scale),
                    (3061,hauler,hauler_angle,hauler_scale),
                    slowed_burst(3100,hauler,hauler_angle,hauler_scale,
                                 projectile,spin,combat_scale,.30),
                    slowed_burst(3230,hauler,hauler_angle,hauler_scale,
                                 projectile,spin,combat_scale,.35),
                    (3301,projectile,spin,combat_scale),
                    (SOURCE_LAST,combat,combat_angle,combat_scale))
        for frame,position,angle,scale in trajectory:
            pose(obj,frame,position,angle,scale)
        obj["projectile_travel_m"] = round(travel,3)

import runpy
noise_tools = runpy.run_path(str(ROOT / "apply_breakaway_rotation_noise.py"))
noise_summary = noise_tools["apply_rotation_noise"](
    (obj for obj in scene.objects if obj.get("asterion_part", False)),
    noise_tools["ASTERION_WINDOWS"],
)
scene["breakup_rotation_noise"] = (
    "Per-part seeded XYZ F-curve noise in three breakup windows; "
    "smooth blend to each assembled ship"
)
print("ASTERION_ROTATION_NOISE", noise_summary)

scene.frame_set(1)
scene["detachable_mesh_count"] = len(parts)+sum(len(v) for v in role_parts.values())
scene["reused_part_count"] = scene["detachable_mesh_count"]
scene["role_component_counts"] = {name:len(objects) for name,objects in role_parts.items()}
scene["static_space_object_count"] = len(space.objects)
scene["asset_directory"] = "//advanced_spaceship/textures"
story_path = ROOT / "add_asterion_story.py"
exec(compile(story_path.read_text(encoding="utf-8"), str(story_path), "exec"),
     {"__file__": str(story_path)})
bpy.ops.wm.save_as_mainfile(filepath=str(OUTPUT))
print("ASTERION_BUILT",{"file":str(OUTPUT),"detachable_parts":scene["detachable_mesh_count"],
                         "space_objects":len(space.objects),"seconds":SECONDS,
    "texture_files_found":len(REQUIRED_TEXTURES)})

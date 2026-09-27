"""Export Blender worlds plus compact TiXL runtime animation caches.

Contract: GLB vertices stay in source object-local space and GLB nodes have
identity transforms.  Runtime owns absolute transforms from the cache.  Cache
matrices are float32 row-major System.Numerics matrices after
``C * BlenderColumnMatrix * C^-1`` where ``C(x,y,z)=(x,z,-y)``.
"""
import json
import hashlib
import sys
from array import array
from collections import Counter
import math
import struct
import time
from pathlib import Path

from animation_writer import MatrixRecordWriter, batch_samples

import bpy
from mathutils import Matrix


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / ".tixl_cache" / "worlds"
FPS = 60
END = 18000
SOURCE_FPS = 60.0
SOURCE_START = 1.0
WORLD_COLLECTIONS = {}
WORLD_CLIPS = {}


def curves(owner):
    ad = getattr(owner, "animation_data", None)
    action = getattr(ad, "action", None)
    if not action:
        return []
    if hasattr(action, "fcurves"):
        return list(action.fcurves)
    slot = getattr(ad, "action_slot", None)
    return [fc for layer in action.layers for strip in layer.strips
            for bag in strip.channelbags
            if slot and getattr(bag, "slot_handle", None) == slot.handle
            for fc in bag.fcurves]


def transparent(mat):
    if not mat:
        return False
    n = mat.name.lower()
    if any(x in n for x in ("glass", "water", "bubble", "transparent")):
        return True
    p = mat.node_tree.nodes.get("Principled BSDF") if mat.use_nodes else None
    if p:
        for key in ("Transmission Weight", "Transmission"):
            if key in p.inputs and p.inputs[key].default_value > 0.5:
                return True
    return mat.diffuse_color[3] < 0.75


def glass_material(src):
    if not src:
        return src
    m = bpy.data.materials.get("TiXL Runtime Glass / " + src.name) or src.copy()
    m.name = "TiXL Runtime Glass / " + src.name
    m.use_nodes = True
    alpha = 0.12 if "water" in src.name.lower() else 0.18
    p = m.node_tree.nodes.get("Principled BSDF")
    if p:
        if "Alpha" in p.inputs:
            p.inputs["Alpha"].default_value = alpha
        for key in ("Transmission Weight", "Transmission"):
            if key in p.inputs:
                p.inputs[key].default_value = 0.0
        p.inputs["Base Color"].default_value = (*p.inputs["Base Color"].default_value[:3], alpha)
    m.diffuse_color = (*m.diffuse_color[:3], alpha)
    try:
        m.surface_render_method = "DITHERED"
    except AttributeError:
        pass
    return m


def source_range(obj):
    frames = []
    owner = obj
    while owner:
        for fc in curves(owner):
            frames.extend(k.co.x for k in fc.keyframe_points)
        owner = owner.parent
    if not frames:
        return None
    return (max(1, int(math.floor((min(frames) - SOURCE_START) * FPS / SOURCE_FPS)) + 1),
            min(END, int(math.ceil((max(frames) - SOURCE_START) * FPS / SOURCE_FPS)) + 1))


def set_output_frame(scene, frame):
    source = SOURCE_START + (frame - 1) * SOURCE_FPS / FPS
    whole = math.floor(source)
    scene.frame_set(whole, subframe=source - whole)


def animated(obj):
    return source_range(obj) is not None


def runtime_matrix(obj):
    c = Matrix(((1, 0, 0, 0), (0, 0, 1, 0), (0, -1, 0, 0), (0, 0, 0, 1)))
    m = (c @ obj.matrix_world @ c.inverted()).transposed()
    return [float(m[r][col]) for r in range(4) for col in range(4)]


def material_tracks(materials):
    tracks = []
    for mat in materials:
        for fc in curves(mat):
            tracks.append({"material": mat.name, "path": fc.data_path,
                           "index": fc.array_index,
                           "keys": [[float(k.co.x), float(k.co.y)] for k in fc.keyframe_points]})
        if mat.use_nodes:
            for fc in curves(mat.node_tree):
                tracks.append({"material": mat.name, "node_tree": True,
                               "path": fc.data_path, "index": fc.array_index,
                               "keys": [[float(k.co.x), float(k.co.y)] for k in fc.keyframe_points]})
    return tracks


def prepare_cache(world, records, scene):
    clip = WORLD_CLIPS[world]
    path = OUT / f"{world}_animation.bin"
    stream = path.open("wb+")
    stream.write(b"TIXLANIM\x01" + struct.pack("<I", len(records)))
    details, animated_records, static_records = [], [], []
    channels = {"world": world, "fps": FPS, "morphs": [], "materials": [], "visibility": [], "lights": []}
    morph_records, visibility_records = [], []
    for idx, rec in enumerate(records):
        src = rec["source"]
        rng = source_range(src)
        rng = (max(rng[0], clip[0]), min(rng[1], clip[1])) if rng else None
        if rng and rng[0] > rng[1]: rng = None
        start, count = (rng[0], rng[1]-rng[0]+1) if rng else (clip[0], 1)
        stream.write(struct.pack("<III", idx, start, count))
        offset = stream.tell()
        stream.seek(count*64, 1)
        item = {**rec, "start": start, "end": start+count-1, "offset": offset}
        (animated_records if rng else static_records).append(item)
        details.append({"export_name": rec["export_name"], "source_name": src.name,
                        "start": start, "count": count, "animated": bool(rng),
                        "parent": src.parent.name if src.parent else None})
        keys = getattr(getattr(src.data, "shape_keys", None), "key_blocks", ())
        if len(keys)>1:
            channel = {"export_name": rec["export_name"], "start": clip[0],
                       "target_names": [k.name for k in keys[1:]], "weights": []}
            channels["morphs"].append(channel)
            morph_records.append((keys, channel))
        # Visibility can be keyed on the object or a parent collection instance.
        if any(fc.data_path in ("hide_render", "hide_viewport") for fc in curves(src)):
            channel = {"export_name": rec["export_name"], "start": clip[0], "values": []}
            channels["visibility"].append(channel)
            visibility_records.append((src, channel))
        elif src.hide_render:
            channels["visibility"].append({"export_name": rec["export_name"], "start": clip[0], "values": [False]})
    # All source materials get at least one explicit PBR sample, retaining
    # emission strength which TiXL's GLTF loader does not import by itself.
    mats = {m for rec in records for m in getattr(rec["source"].data, "materials", ()) if m}
    mat_records = []
    for mat in sorted(mats, key=lambda m:m.name):
        channel = {"material": mat.name, "export_name": "TiXL Runtime Glass / "+mat.name if transparent(mat) else mat.name, "start": clip[0], "base_color": [], "emission": []}
        channels["materials"].append(channel)
        mat_records.append((mat, bool(curves(mat) or (mat.use_nodes and curves(mat.node_tree))), channel))
    light_records=[]
    source_collection = scene.collection if WORLD_COLLECTIONS[world] == scene.collection.name else bpy.data.collections[WORLD_COLLECTIONS[world]]
    for light in source_collection.all_objects:
        if light.type!="LIGHT": continue
        if curves(light) or curves(light.data) or source_range(light):
            channel={"name":light.name,"samples":[]}
            channels["lights"].append(channel);light_records.append((light,channel))
    stream.truncate(stream.tell())
    meta = {"magic":"TIXLANIM\\x01", "fps":FPS, "matrix_layout":"float32 row-major System.Numerics",
            "coordinate_conversion":"C*(Blender column matrix)*C^-1; C(x,y,z)=(x,z,-y)", "records":details}
    (OUT/f"{world}_animation.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return {"world":world, "stream":stream, "clip":clip, "animated":animated_records,
            "static":static_records, "channels":channels, "morphs":morph_records,
            "visibility":visibility_records, "materials":mat_records, "lights":light_records}


def material_values(mat):
    p = mat.node_tree.nodes.get("Principled BSDF") if mat.use_nodes else None
    base = list(p.inputs["Base Color"].default_value) if p else list(mat.diffuse_color)
    if p and p.inputs["Base Color"].is_linked: base[:3]=[1.0,1.0,1.0]
    emission = list(p.inputs["Emission Color"].default_value) if p and "Emission Color" in p.inputs else [0,0,0,1]
    if p and "Emission Color" in p.inputs and p.inputs["Emission Color"].is_linked: emission[:3]=[1.0,1.0,1.0]
    if p and "Emission Strength" in p.inputs:
        emission[:3] = [float(v)*float(p.inputs["Emission Strength"].default_value) for v in emission[:3]]
    # Emission-only shader materials (electric arcs and small filaments).
    if mat.use_nodes and not p:
        e = next((n for n in mat.node_tree.nodes if n.type=="EMISSION"),None)
        if e: emission = [v*float(e.inputs["Strength"].default_value) for v in e.inputs["Color"].default_value[:3]]+[1.0]
    return base, emission


def bake_all(scene, jobs):
    started = time.monotonic()
    try:
        record_count = sum(len(job["animated"]) + len(job["static"]) for job in jobs)
        samples_per_batch = batch_samples(record_count)
        writers = {id(rec): MatrixRecordWriter(job["stream"], rec["offset"],
                                              rec["start"], samples_per_batch)
                   for job in jobs for rec in job["animated"] + job["static"]}
        for frame in range(1, END+1):
            set_output_frame(scene, frame)
            for job in jobs:
                start,end = job["clip"]
                if not start <= frame <= end: continue
                entries=job["animated"]+job["static"] if frame==start else job["animated"]
                for rec in entries:
                    if not rec["start"] <= frame <= rec["end"]: continue
                    writers[id(rec)].append(frame, struct.pack("<16f", *runtime_matrix(rec["source"])))
                for keys,ch in job["morphs"]:
                    ch["weights"].append([float(k.value) for k in keys[1:]])
                for src,ch in job["visibility"]:
                    ch["values"].append(not src.hide_render)
                for mat,dynamic,ch in job["materials"]:
                    if frame==start or dynamic:
                        base,emission=material_values(mat)
                        if transparent(mat): base[3]=0.12 if "water" in mat.name.lower() else 0.18
                        ch["base_color"].append(base);ch["emission"].append(emission)
                for light,ch in job["lights"]:
                    ch["samples"].append({"frame":frame,"energy":float(light.data.energy),"color":list(light.data.color),"position":list(light.matrix_world.translation)})
            if frame%600==0:
                print(f"BAKE_PROGRESS {frame}/{END} elapsed={time.monotonic()-started:.1f}s",flush=True)
        for job in jobs:
            for rec in job["animated"] + job["static"]:
                writers[id(rec)].flush()
    finally:
        active_error = sys.exc_info()[0] is not None
        close_error = None
        for job in jobs:
            try:
                job["stream"].close()
            except BaseException as error:
                if not active_error and close_error is None:
                    close_error = error
        if close_error is not None:
            raise close_error
    for job in jobs:
        (OUT/f'{job["world"]}_channels.json').write_text(json.dumps(job["channels"], separators=(",",":")), encoding="utf-8")
        print("CACHE_COMPLETE",job["world"],flush=True)


def export_world(scene, world, coll_name):
    coll = scene.collection if coll_name == scene.collection.name else bpy.data.collections.get(coll_name)
    if coll is None:
        raise RuntimeError(f"missing world collection: {coll_name}")
    temp = bpy.data.collections.new("TiXL Runtime Export / " + world)
    scene.collection.children.link(temp)
    records, opaque, glass = [], [], []
    lights = []
    set_output_frame(scene, WORLD_CLIPS[world][0])
    sources = [o for o in coll.all_objects if o.type in {"MESH", "CURVE", "SURFACE", "FONT"}]
    for light in (o for o in coll.all_objects if o.type == "LIGHT"):
        lights.append({"name": light.name, "type": light.data.type,
                       "position": [round(float(v), 6) for v in light.matrix_world.translation],
                       "color": [round(float(v), 6) for v in light.data.color],
                       "energy": float(light.data.energy),
                       "range": float(getattr(light.data, "cutoff_distance", 0.0)),
                       "size": float(getattr(light.data, "shadow_soft_size", 0.0))})
    set_output_frame(scene, WORLD_CLIPS[world][0])
    depsgraph = bpy.context.evaluated_depsgraph_get()
    prepared = []
    for src in sources:
        # Curves/fonts are evaluated to mesh; native mesh copies preserve shape keys.
        if src.type == "MESH" and src.data.shape_keys:
            mesh = src.data.copy()
        else:
            ev = src.evaluated_get(depsgraph)
            mesh = bpy.data.meshes.new_from_object(ev, depsgraph=depsgraph)
        if mesh is not None: prepared.append((src,mesh))
    print("MESHES_PREPARED", world, len(prepared), flush=True)
    for src,mesh in prepared:
        mats = list(getattr(src.data, "materials", ()))
        is_glass = any(transparent(m) for m in mats)
        kind = "glass" if is_glass else "opaque"
        face_materials = array("i", [0]) * len(mesh.polygons)
        mesh.polygons.foreach_get("material_index", face_materials)
        mesh.materials.clear()
        for mat in mats:
            mesh.materials.append(glass_material(mat) if transparent(mat) else mat)
        mesh.polygons.foreach_set("material_index", face_materials)
        out = bpy.data.objects.new(src.name, mesh)
        temp.objects.link(out)
        out.matrix_world = Matrix.Identity(4)
        out["source_object"] = src.name
        out["source_asset_id"] = str(src.get("source_asset_id", src.get("asset_id", "")))
        (glass if is_glass else opaque).append(out)
        records.append({"source": src, "export_name": out.name, "pass": kind,
                        "face_materials": {str(index): {"material": mesh.materials[index].name if index<len(mesh.materials) and mesh.materials[index] else None, "polygons": count}
                        for index,count in Counter(face_materials).items()}})
    for group, suffix in ((opaque, "opaque"), (glass, "glass")):
        if not group: continue
        bpy.ops.object.select_all(action="DESELECT")
        for obj in group: obj.select_set(True)
        path = OUT / f"{world}_{suffix}.glb"
        bpy.ops.export_scene.gltf(filepath=str(path), export_format="GLB", use_selection=True,
                                  export_animations=False, export_cameras=False, export_lights=False,
                                  export_extras=True, export_yup=True, export_texcoords=True,
                                  export_normals=True, export_tangents=True, export_morph=True)
    (OUT/f"{world}_face_materials.json").write_text(json.dumps({r["export_name"]:r["face_materials"] for r in records},indent=2))
    cache = OUT / f"{world}_animation.bin"
    cache_meta = OUT / f"{world}_animation.json"
    channels_path = OUT / f"{world}_channels.json"
    source_materials = {m for src in sources for m in getattr(src.data, "materials", ()) if m}
    manifest = {"world": world, "collection": coll_name, "fps": FPS,
                "glbs": {k: str((OUT / f"{world}_{k}.glb").resolve()).replace("\\", "/")
                         for k in ("opaque", "glass") if (opaque if k=="opaque" else glass)},
                "object_count": len(records), "opaque_count": len(opaque),
                "glass_count": len(glass), "animation_cache": cache.name,
                "animation_metadata": cache_meta.name,
                "channels": channels_path.name,
                "lights": lights,
                "active_clip": WORLD_CLIPS.get(world, (1, END)),
                "material_animation_tracks": material_tracks(source_materials),
                "runtime_contract": "GLB local geometry; absolute world matrices in cache"}
    (OUT / f"{world}_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    for obj in list(temp.objects):
        mesh = obj.data
        bpy.data.objects.remove(obj, do_unlink=True)
        if mesh and mesh.users == 0:
            bpy.data.meshes.remove(mesh)
    bpy.data.collections.remove(temp)
    print("GEOMETRY_COMPLETE", world, len(records), flush=True)
    return manifest, records


def export_all(scene=None):
    from sync_metrics import phase
    scene = scene or bpy.context.scene
    OUT.mkdir(parents=True, exist_ok=True)
    # Preserve the .blend frame rate; source frames are resampled at 60 Hz.
    set_output_frame(scene, 1)
    with phase("geometry_export"):
        exported = [export_world(scene, w, c) for w, c in WORLD_COLLECTIONS.items()]
    manifests = [m for m,r in exported]
    if "--geometry-only" not in sys.argv:
        with phase("animation_baking"):
            jobs = [prepare_cache(m["world"],r,scene) for m,r in exported]
            bake_all(scene,jobs)
    else:
        for m,records in exported:
            old=json.loads((OUT/f"{m['world']}_animation.json").read_text())
            assert [r["export_name"] for r in records]==[r["export_name"] for r in old["records"]],m["world"]
        print("GEOMETRY_ONLY_CACHE_NAMES_VERIFIED",flush=True)
    source_path = Path(bpy.data.filepath).resolve()
    (OUT / "manifest.json").write_text(json.dumps({"source_scene": scene.name,
        "worlds": manifests, "fps": FPS,
        "project_name": scene.get("tixl_project_name", ""),
        "source_blend": str(source_path).replace("\\", "/"),
        "source_sha256": hashlib.sha256(source_path.read_bytes()).hexdigest(),
        "runtime_contract": "identity GLB nodes; absolute converted row-major matrices"}, indent=2), encoding="utf-8")
    return manifests


if __name__ == "__main__":
    print(json.dumps(export_all(), indent=2))

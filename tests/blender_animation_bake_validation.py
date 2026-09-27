"""Compare original and bounded animation-cache bakes in disposable Blender.

Run with Blender MCP in a separate ``--background --factory-startup`` process.
The script creates a deterministic in-memory fixture, imports the supplied
baseline and current exporter under unique module names, and writes artifacts
only below ``examples/.tixl_cache/issue10_validation``.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import math
import statistics
import struct
import sys
import time
import traceback
import uuid
from pathlib import Path

import bpy

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "blender_tixl_bridge" / "source"
DEFAULT_BASELINE = ROOT / "examples" / ".tixl_cache" / "issue10_validation" / "exporter.baseline.py"
EXAMPLE_CACHE = ROOT / "examples" / ".tixl_cache" / "BlendShapeExample"
sys.path.insert(0, str(SOURCE))


def load_exporter(path: Path, unique_name: str):
    spec = importlib.util.spec_from_file_location(unique_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot import animation exporter: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[unique_name] = module
    spec.loader.exec_module(module)
    return module


def animation_curves(owner):
    ad = owner.animation_data
    action = getattr(ad, "action", None)
    if not action:
        return []
    if hasattr(action, "fcurves"):
        return list(action.fcurves)
    slot = getattr(ad, "action_slot", None)
    return [curve for layer in action.layers for strip in layer.strips for bag in strip.channelbags
            if slot and getattr(bag, "slot_handle", None) == slot.handle for curve in bag.fcurves]


def set_linear(owner, data_path: str):
    for curve in animation_curves(owner):
        if curve.data_path == data_path:
            for key in curve.keyframe_points:
                key.interpolation = "LINEAR"


def add_keys(owner, data_path: str, values):
    key_owner = owner.data if data_path == "energy" else owner
    for frame, value in values:
        if data_path == "location":
            owner.location = value
        elif data_path == "rotation_euler":
            owner.rotation_euler = value
        elif data_path == "hide_render":
            owner.hide_render = value
        elif data_path == "energy":
            owner.data.energy = value
        key_owner.keyframe_insert(data_path=data_path, frame=frame)
    set_linear(key_owner, data_path)


def new_material(name: str, color, transparent: bool = False, dynamic: bool = False):
    mat = bpy.data.materials.new(name)
    alpha = 0.28 if transparent else 1.0
    rgba = (*color[:3], alpha)
    mat.diffuse_color = rgba
    mat.use_nodes = True
    shader = mat.node_tree.nodes.get("Principled BSDF")
    shader.inputs["Base Color"].default_value = rgba
    shader.inputs["Roughness"].default_value = 0.38
    if "Emission Color" in shader.inputs:
        shader.inputs["Emission Color"].default_value = (*color[:3], 1.0)
    if "Emission Strength" in shader.inputs:
        shader.inputs["Emission Strength"].default_value = 0.35
    if dynamic:
        base_path = 'nodes["Principled BSDF"].inputs["Base Color"].default_value'
        emission_path = 'nodes["Principled BSDF"].inputs["Emission Color"].default_value'
        strength_path = 'nodes["Principled BSDF"].inputs["Emission Strength"].default_value'
        for frame, base, emission, strength in (
                (11, (*color[:3], alpha), (*color[:3], 1.0), 0.2),
                (23, (color[2], color[0], color[1], alpha), (color[1], color[2], color[0], 1.0), 0.8),
                (35, (*color[:3], alpha), (*color[:3], 1.0), 0.35)):
            shader.inputs["Base Color"].default_value = base
            shader.inputs["Emission Color"].default_value = emission
            shader.inputs["Emission Strength"].default_value = strength
            for path in (base_path, emission_path, strength_path):
                mat.node_tree.keyframe_insert(data_path=path, frame=frame)
        for curve in animation_curves(mat.node_tree):
            for key in curve.keyframe_points:
                key.interpolation = "LINEAR"
    return mat


def cube_mesh(name: str, collection, location=(0.0, 0.0, 0.0), material=None):
    half = 0.5
    vertices = [(-half, -half, -half), (-half, -half, half), (-half, half, -half),
                (-half, half, half), (half, -half, -half), (half, -half, half),
                (half, half, -half), (half, half, half)]
    faces = [(0, 4, 6, 2), (1, 3, 7, 5), (0, 1, 5, 4),
             (2, 6, 7, 3), (0, 2, 3, 1), (4, 5, 7, 6)]
    mesh = bpy.data.meshes.new(name + "Mesh")
    mesh.from_pydata(vertices, [], faces)
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    collection.objects.link(obj)
    obj.location = location
    if material:
        obj.data.materials.append(material)
    return obj


def add_shape_animation(obj):
    basis = obj.shape_key_add(name="Basis")
    target = obj.shape_key_add(name="Bend")
    for index, point in enumerate(target.data):
        point.co.z += 0.2 if index % 2 else -0.15
        point.co.x += 0.08
    for frame, value in ((11, 0.0), (18, 0.8), (29, 0.25), (35, 0.0)):
        target.value = value
        target.keyframe_insert(data_path="value", frame=frame)
    if obj.data.shape_keys.animation_data:
        for curve in animation_curves(obj.data.shape_keys):
            for key in curve.keyframe_points:
                key.interpolation = "LINEAR"


def make_animated_light(collection, name: str):
    data = bpy.data.lights.new(name + "Data", "AREA")
    data.energy = 400
    light = bpy.data.objects.new(name, data)
    collection.objects.link(light)
    add_keys(light, "energy", ((11, 300.0), (23, 850.0), (35, 450.0)))
    add_keys(light, "location", ((11, (2.0, -3.0, 4.0)), (23, (3.0, -2.0, 5.0)),
                                  (35, (2.0, -3.0, 4.0))))
    return light


def build_comprehensive_fixture():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.name = "AnimationBakeValidation"
    scene.frame_start, scene.frame_end = 11, 35
    scene.render.fps, scene.render.fps_base = 24, 1.0
    scene["tixl_project_name"] = "Issue10BakeValidation"
    worlds = {"overlap_a": "World_A", "overlap_b": "World_B", "disjoint_c": "World_C"}
    clips = {"overlap_a": (1, 32), "overlap_b": (20, 48), "disjoint_c": (49, 61)}
    static_names = set()
    expected = {"worlds": {}, "staticSourceNames": []}
    for index, (world, collection_name) in enumerate(worlds.items()):
        collection = bpy.data.collections.new(collection_name)
        scene.collection.children.link(collection)
        parent = bpy.data.objects.new(world + "_keyed_parent", None)
        collection.objects.link(parent)
        if world == "overlap_a":
            parent_keys = ((11, (0, 0, 0)), (18, (0.5, 0, 0.4)), (35, (1.5, 0.2, 0)))
        elif world == "overlap_b":
            parent_keys = ((15, (0.1, 0, 0)), (24, (0.8, 0.1, 0.2)), (31, (1.1, 0, 0)))
        else:
            parent_keys = ((29, (0, 0, 0)), (32, (0.5, 0, 0.5)), (35, (1, 0, 0)))
        add_keys(parent, "location", parent_keys)

        dynamic_opaque = new_material(world + "_opaque_dynamic", (0.8, 0.2, 0.1, 1), dynamic=True)
        static_opaque = new_material(world + "_opaque_static", (0.15, 0.45, 0.8, 1))
        dynamic_glass = new_material(world + "_water_dynamic", (0.1, 0.5, 0.8, 1),
                                     transparent=True, dynamic=True)
        static_glass = new_material(world + "_glass_static", (0.25, 0.7, 0.65, 1), transparent=True)

        animated_opaque = cube_mesh(world + "_animated_opaque", collection, material=dynamic_opaque)
        animated_opaque.parent = parent
        animated_opaque.matrix_parent_inverse = parent.matrix_world.inverted()
        if world == "overlap_a":
            motion_keys = ((11, (0, 0, 0)), (20, (0.2, 0.5, 0.2)), (35, (0.7, 0.2, 0.4)))
        elif world == "overlap_b":
            motion_keys = ((12, (0, 0, 0)), (22, (0.5, 0.2, 0)), (34, (0.8, 0.3, 0.4)))
        else:
            motion_keys = ((27, (0, 0, 0)), (31, (0.3, 0.5, 0.2)), (35, (0.8, 0, 0.5)))
        add_keys(animated_opaque, "location", motion_keys)
        add_shape_animation(animated_opaque)
        add_keys(animated_opaque, "hide_render", ((11, False), (19, True), (25, False), (35, False)))

        animated_glass = cube_mesh(world + "_animated_water", collection, (0.4, 0.0, 0.2), dynamic_glass)
        animated_glass.parent = parent
        animated_glass.matrix_parent_inverse = parent.matrix_world.inverted()
        add_keys(animated_glass, "location", ((11, (0.4, 0.0, 0.2)), (23, (0.5, 0.1, 0.3)),
                                               (35, (0.6, 0.2, 0.4))))

        static_solid = cube_mesh(world + "_static_opaque", collection, (-0.8, 0.0, 0.0), static_opaque)
        static_water = cube_mesh(world + "_static_glass", collection, (0.8, 0.0, 0.0), static_glass)
        static_names.update((static_solid.name, static_water.name))

        make_animated_light(collection, world + "_animated_key")
        static_light_data = bpy.data.lights.new(world + "_static_fillData", "POINT")
        static_light_data.energy = 150
        static_light = bpy.data.objects.new(world + "_static_fill", static_light_data)
        static_light.location = (-3, -2, 2)
        collection.objects.link(static_light)

        expected["worlds"][world] = {
            "collection": collection_name, "clip": list(clips[world]),
            "animatedObjects": [animated_opaque.name, animated_glass.name],
            "staticObjects": [static_solid.name, static_water.name],
            "parent": parent.name, "animatedLight": world + "_animated_key",
            "staticLight": static_light.name,
        }
    scene.frame_set(scene.frame_start)
    expected["staticSourceNames"] = sorted(static_names)
    expected["source"] = {"frameStart": 11, "frameEnd": 35, "sourceFps": 24,
                           "outputFps": 60, "outputEnd": 61}
    return scene, worlds, clips, expected


def configure_module(module, scene, worlds, clips, output: Path):
    module.OUT = output
    output.mkdir(parents=True, exist_ok=True)
    module.FPS = 60
    module.SOURCE_START = float(scene.frame_start)
    module.SOURCE_FPS = scene.render.fps / scene.render.fps_base
    module.END = max(2, round((scene.frame_end - scene.frame_start) / module.SOURCE_FPS * module.FPS) + 1)
    module.WORLD_COLLECTIONS = dict(worlds)
    module.WORLD_CLIPS = dict(clips)
    return module.END


def records_for_collections(scene, worlds, export_name_map=None):
    mapping = export_name_map or {}
    result = {}
    for world, collection_name in worlds.items():
        collection = bpy.data.collections.get(collection_name)
        if collection is None:
            raise RuntimeError(f"Fixture collection not found: {collection_name}")
        objects = [obj for obj in collection.all_objects if obj.type == "MESH"]
        result[world] = [{"source": obj, "export_name": mapping.get(obj.name, obj.name)} for obj in objects]
    return result


def records_from_existing_worlds(scene, generation: Path):
    old_manifest_path = generation / "worlds" / "manifest.json"
    manifest = json.loads(old_manifest_path.read_text(encoding="utf-8"))
    worlds, clips, records, mapping = {}, {}, {}, {}
    for entry in manifest["worlds"]:
        world = entry["world"]
        exported_manifest = json.loads((generation / "worlds" / f"{world}_manifest.json").read_text(encoding="utf-8"))
        cache_metadata = json.loads((generation / "worlds" / f"{world}_animation.json").read_text(encoding="utf-8"))
        collection_name = entry["collection"]
        worlds[world] = collection_name
        clips[world] = tuple(exported_manifest["active_clip"])
        sources = {obj.name: obj for obj in bpy.data.collections[collection_name].all_objects if obj.type == "MESH"}
        per_world = []
        for record in cache_metadata["records"]:
            source_name = record["source_name"]
            if source_name not in sources:
                raise RuntimeError(f"Existing cache source name is not in collection {collection_name}: {source_name}")
            mapping[source_name] = record["export_name"]
            per_world.append({"source": sources[source_name], "export_name": record["export_name"]})
        if set(sources) != {record["source_name"] for record in cache_metadata["records"]}:
            raise RuntimeError(f"Source objects for {world} differ from the existing cache metadata")
        records[world] = per_world
    return worlds, clips, records, mapping, manifest


def run_bake(module, scene, worlds, clips, records, output: Path, count_calls=False):
    end = configure_module(module, scene, worlds, clips, output)
    calls = {"setFrame": 0, "matrix": 0}
    original_set_frame = module.set_output_frame
    original_matrix = module.runtime_matrix
    if count_calls:
        def set_frame(scene_arg, frame):
            calls["setFrame"] += 1
            return original_set_frame(scene_arg, frame)
        def matrix(obj):
            calls["matrix"] += 1
            return original_matrix(obj)
        module.set_output_frame = set_frame
        module.runtime_matrix = matrix
    jobs = []
    try:
        for world in worlds:
            jobs.append(module.prepare_cache(world, records[world], scene))
        module.bake_all(scene, jobs)
    finally:
        module.set_output_frame = original_set_frame
        module.runtime_matrix = original_matrix
    return end, calls


def finite_vector(values, label):
    if not isinstance(values, list) or any(not math.isfinite(float(value)) for value in values):
        raise AssertionError(f"Non-finite or invalid numeric output in {label}")


def verify_world_output(module, output: Path, world: str, records, clip):
    binary_path = output / f"{world}_animation.bin"
    metadata_path = output / f"{world}_animation.json"
    channels_path = output / f"{world}_channels.json"
    data = binary_path.read_bytes()
    if data[:9] != b"TIXLANIM\x01":
        raise AssertionError(f"Invalid animation cache header for {world}")
    record_count = struct.unpack_from("<I", data, 9)[0]
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    channels = json.loads(channels_path.read_text(encoding="utf-8"))
    if record_count != len(records) or len(metadata["records"]) != record_count:
        raise AssertionError(f"Record count differs from source objects for {world}")
    offset = 13
    expected_matrix_count = 0
    source_by_export = {record["export_name"]: record["source"] for record in records}
    for index, entry in enumerate(metadata["records"]):
        record_index, start, count = struct.unpack_from("<III", data, offset)
        offset += 12
        if record_index != index or (start, count) != (entry["start"], entry["count"]):
            raise AssertionError(f"Binary and JSON transform record differ for {world}/{entry['export_name']}")
        if not (clip[0] <= start <= clip[1] and 1 <= count <= clip[1] - start + 1):
            raise AssertionError(f"Transform sample range escaped {world}'s clipped interval")
        expected_source = source_by_export[entry["export_name"]]
        rng = module.source_range(expected_source)
        if rng:
            expected_start = max(rng[0], clip[0])
            expected_end = min(rng[1], clip[1])
            if expected_start > expected_end:
                expected_start, expected_end = clip[0], clip[0]
            expected = (expected_start, expected_end - expected_start + 1)
        else:
            expected = (clip[0], 1)
        if (start, count) != expected:
            raise AssertionError(f"Unexpected source range for {world}/{entry['source_name']}: {(start, count)} != {expected}")
        if count > 1:
            expected_matrix_count += count
        else:
            expected_matrix_count += 1
        byte_count = count * 64
        if offset + byte_count > len(data):
            raise AssertionError(f"Truncated matrix samples for {world}/{entry['export_name']}")
        for matrix in struct.iter_unpack("<16f", memoryview(data)[offset:offset + byte_count]):
            if not all(math.isfinite(value) for value in matrix) or abs(matrix[15] - 1.0) > 1e-6:
                raise AssertionError(f"Invalid matrix sample for {world}/{entry['export_name']}")
        offset += byte_count
    if offset != len(data):
        raise AssertionError(f"Unexpected trailing transform bytes for {world}: {len(data) - offset}")

    clip_samples = clip[1] - clip[0] + 1
    if channels["world"] != world or channels["fps"] != 60:
        raise AssertionError(f"Channel metadata has the wrong world or output rate for {world}")
    for channel in channels["morphs"]:
        if channel["start"] != clip[0] or len(channel["weights"]) != clip_samples:
            raise AssertionError(f"Morph cache range is incomplete for {world}/{channel['export_name']}")
        for row in channel["weights"]:
            finite_vector(row, f"{world} morph {channel['export_name']}")
    for channel in channels["visibility"]:
        if channel["start"] != clip[0] or len(channel["values"]) not in (1, clip_samples):
            raise AssertionError(f"Visibility cache range is incomplete for {world}/{channel['export_name']}")
    for channel in channels["materials"]:
        if channel["start"] != clip[0]:
            raise AssertionError(f"Material channel start differs from clip for {world}/{channel['export_name']}")
        for field in ("base_color", "emission"):
            if not channel[field] or len(channel[field]) not in (1, clip_samples):
                raise AssertionError(f"Material {field} samples are missing for {world}/{channel['export_name']}")
            for row in channel[field]:
                finite_vector(row, f"{world} material {field}")
    for channel in channels["lights"]:
        if len(channel["samples"]) != clip_samples:
            raise AssertionError(f"Animated light samples are incomplete for {world}/{channel['name']}")
        for sample in channel["samples"]:
            finite_vector([sample["energy"], *sample["color"], *sample["position"]],
                          f"{world} light {channel['name']}")
    return {"recordCount": record_count, "matrixSamples": expected_matrix_count,
            "clip": list(clip), "clipSampleCount": clip_samples,
            "animatedRecords": sum(1 for entry in metadata["records"] if entry["animated"]),
            "staticRecords": sum(1 for entry in metadata["records"] if not entry["animated"]),
            "morphChannels": len(channels["morphs"]), "visibilityChannels": len(channels["visibility"]),
            "materialChannels": len(channels["materials"]), "animatedLightChannels": len(channels["lights"]),
            "animationBytes": len(data), "metadataBytes": metadata_path.stat().st_size,
            "channelsBytes": channels_path.stat().st_size}


def artifact_bytes(output: Path, world: str):
    return tuple((output / name).read_bytes() for name in
                 (f"{world}_animation.bin", f"{world}_animation.json", f"{world}_channels.json"))


def validate_comprehensive(baseline, current, scene, worlds, clips, expected, report_root):
    records = records_for_collections(scene, worlds)
    baseline_out, current_out = report_root / "comprehensive_baseline", report_root / "comprehensive_current"
    end_baseline, calls_baseline = run_bake(baseline, scene, worlds, clips, records, baseline_out, count_calls=True)
    end_current, calls_current = run_bake(current, scene, worlds, clips, records, current_out, count_calls=True)
    if end_baseline != expected["source"]["outputEnd"] or end_current != end_baseline:
        raise AssertionError("The exporter did not derive the expected 60 Hz timeline from 24 fps source frames")
    if calls_current["setFrame"] != end_current:
        raise AssertionError(f"Optimized bake did not share one frame evaluation across worlds: {calls_current}")
    parity, validation = {}, {}
    expected_matrix_calls = 0
    for world in worlds:
        baseline_validation = verify_world_output(baseline, baseline_out, world, records[world], clips[world])
        current_validation = verify_world_output(current, current_out, world, records[world], clips[world])
        expected_matrix_calls += current_validation["matrixSamples"]
        files_equal = artifact_bytes(baseline_out, world) == artifact_bytes(current_out, world)
        parity[world] = files_equal
        validation[world] = current_validation
        if not files_equal:
            raise AssertionError(f"Original and optimized animation payloads differ for {world}")
        if current_validation["morphChannels"] < 1 or current_validation["visibilityChannels"] < 1:
            raise AssertionError(f"Fixture did not exercise morph and visibility channels in {world}")
        if current_validation["materialChannels"] < 4 or current_validation["animatedLightChannels"] != 1:
            raise AssertionError(f"Fixture did not exercise static/dynamic PBR, emission, and light channels in {world}")
    if calls_current["matrix"] != expected_matrix_calls:
        raise AssertionError("Writer sample call count differs from finite contiguous matrix sample ranges")
    return {"fixture": expected, "baselineCurrentBytesEqual": parity,
            "worldValidation": validation,
            "baselineFrameSetCalls": calls_baseline["setFrame"],
            "optimizedFrameSetCalls": calls_current["setFrame"],
            "optimizedMatrixSampleCalls": calls_current["matrix"],
            "sharedFrameEvaluationVerified": True}


def build_benchmark_fixture():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.name = "AnimationBakeBenchmark"
    scene.frame_start, scene.frame_end = 1, 600
    scene.render.fps, scene.render.fps_base = 60, 1.0
    collection = bpy.data.collections.new("BenchmarkWorld")
    scene.collection.children.link(collection)
    records = []
    for index in range(100):
        obj = cube_mesh(f"BenchmarkObject{index:03d}", collection,
                        location=(index * 0.02, 0, 0))
        add_keys(obj, "location", ((1, (index * 0.02, 0, 0)),
                                    (300, (index * 0.02, 1, 0.5)),
                                    (600, (index * 0.02, 0, 0))))
        records.append({"source": obj, "export_name": obj.name})
    scene.frame_set(1)
    return scene, {"benchmark": "BenchmarkWorld"}, {"benchmark": (1, 600)}, {"benchmark": records}


def whole_benchmark(module, scene, worlds, clips, records, output: Path, samples=5):
    timings = []
    end = configure_module(module, scene, worlds, clips, output)
    for _ in range(samples):
        started = time.perf_counter()
        jobs = [module.prepare_cache(world, records[world], scene) for world in worlds]
        module.bake_all(scene, jobs)
        timings.append(time.perf_counter() - started)
    return {"objects": sum(len(records[world]) for world in worlds), "frames": end,
            "samples": samples, "unprofiledSeconds": timings,
            "medianSeconds": statistics.median(timings),
            "minimumSeconds": min(timings), "maximumSeconds": max(timings),
            "payloadBytes": sum((output / f"{world}_animation.bin").stat().st_size for world in worlds)}


def validate_example(baseline, current, blend_path: Path, report_root: Path):
    bpy.ops.wm.open_mainfile(filepath=str(blend_path))
    scene = bpy.context.scene
    from cache_publication import active_root
    current_pointer = EXAMPLE_CACHE / "current_generation.json"
    recovery_pointer = EXAMPLE_CACHE / "previous_generation.json"
    if current_pointer.is_file() or recovery_pointer.is_file():
        generation = active_root(EXAMPLE_CACHE)
    else:
        # Older ignored caches keep the same worlds/manifest layout directly at
        # the cache root; current generation caches resolve to a generation dir.
        if (EXAMPLE_CACHE / "worlds" / "manifest.json").is_file():
            generation = EXAMPLE_CACHE
        else:
            generation = active_root(EXAMPLE_CACHE)
    worlds, clips, records, mapping, manifest = records_from_existing_worlds(scene, generation)
    baseline_out, current_out = report_root / "example_baseline", report_root / "example_current"
    end, _ = run_bake(baseline, scene, worlds, clips, records, baseline_out)
    current_end, _ = run_bake(current, scene, worlds, clips, records, current_out)
    if current_end != end:
        raise AssertionError("Exporter baseline/current example timeline length differs")
    parity, worlds_report = {}, {}
    for world in worlds:
        parity[world] = artifact_bytes(baseline_out, world) == artifact_bytes(current_out, world)
        if not parity[world]:
            raise AssertionError(f"Bundled example output differs between baseline and current exporter: {world}")
        worlds_report[world] = verify_world_output(current, current_out, world, records[world], clips[world])
    return {"sourceBlend": str(blend_path.resolve()), "existingGeneration": str(generation.resolve()),
            "existingSourceSha256": manifest.get("source_sha256"), "exportNamesMatchExistingGlbNodes": True,
            "exportNameMap": mapping, "baselineCurrentBytesEqual": parity,
            "worldValidation": worlds_report,
            "currentDataPaths": {world: str(current_out / f"{world}_animation.bin") for world in worlds}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE,
                        help="Original tixl_animation_export.py snapshot")
    parser.add_argument("--current", type=Path, default=SOURCE / "tixl_animation_export.py",
                        help="Current animation exporter")
    parser.add_argument("--example", type=Path,
                        help="Optional bundled .blend for GLB-name-compatible parity output")
    blender_args = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else None
    args = parser.parse_args(blender_args)
    run_id = time.strftime("%Y%m%dT%H%M%S") + "_" + uuid.uuid4().hex[:8]
    report_root = ROOT / "examples" / ".tixl_cache" / "issue10_validation" / run_id
    report_root.mkdir(parents=True, exist_ok=False)
    baseline_path, current_path = args.baseline.resolve(), args.current.resolve()
    if not baseline_path.is_file():
        raise FileNotFoundError(f"Baseline exporter snapshot is missing: {baseline_path}")
    baseline = load_exporter(baseline_path, "tixl_exporter_issue10_baseline_" + run_id)
    current = load_exporter(current_path, "tixl_exporter_issue10_current_" + run_id)
    report = {"schema": 1, "runId": run_id, "status": "running",
              "runtime": {"blenderVersion": bpy.app.version_string, "pythonVersion": sys.version,
                          "baselineExporter": str(baseline_path), "currentExporter": str(current_path)},
              "outputRoot": str(report_root), "comprehensive": {}, "wholeBakeBenchmark": {},
              "example": None, "errors": []}
    try:
        scene, worlds, clips, expected = build_comprehensive_fixture()
        report["comprehensive"] = validate_comprehensive(baseline, current, scene, worlds, clips,
                                                         expected, report_root)
        benchmark_scene, bench_worlds, bench_clips, bench_records = build_benchmark_fixture()
        report["wholeBakeBenchmark"] = {
            "baseline": whole_benchmark(baseline, benchmark_scene, bench_worlds, bench_clips,
                                        bench_records, report_root / "whole_benchmark_baseline"),
            "optimized": whole_benchmark(current, benchmark_scene, bench_worlds, bench_clips,
                                          bench_records, report_root / "whole_benchmark_current"),
        }
        if args.example:
            report["example"] = validate_example(baseline, current, args.example.resolve(), report_root)
        report["status"] = "passed"
    except Exception:
        report["status"] = "failed"
        report["errors"].append(traceback.format_exc())
    report["finishedUtc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    output = report_root / "animation_bake_report.json"
    output.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print("BLENDER_ANIMATION_BAKE_VALIDATION " + json.dumps({"status": report["status"],
          "report": str(output), "runId": run_id}), flush=True)
    if report["status"] != "passed":
        raise RuntimeError("Animation bake validation failed; see " + str(output))


if __name__ == "__main__":
    main()

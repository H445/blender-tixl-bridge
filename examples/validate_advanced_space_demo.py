"""Read-only structural and animation validation for AsterionBreakaway.blend.

Execute this script inside Blender through the official Blender MCP TCP
extension. It temporarily samples animation frames, restores the original
playhead, and does not save or otherwise modify the .blend file.
"""

from __future__ import annotations

import json
import math
import hashlib
import re
import runpy
from pathlib import Path

import bpy
from mathutils import Vector


ROOT = Path(__file__).resolve().parent
EXPECTED_FILE = (ROOT / "AsterionBreakaway.blend").resolve()
scene = bpy.context.scene
assert scene is not None, "No active Blender scene is open"

opened_file = Path(bpy.data.filepath).resolve() if bpy.data.filepath else None
assert opened_file == EXPECTED_FILE, (
    f"Expected the saved demo {EXPECTED_FILE}, found {opened_file}"
)
assert opened_file.is_file(), f"The opened demo path is not a saved file: {opened_file}"

effective_fps = scene.render.fps / scene.render.fps_base
duration_seconds = (scene.frame_end - scene.frame_start) / effective_fps
assert math.isclose(effective_fps, 60.0, rel_tol=0.0, abs_tol=1e-9), (
    f"Expected 60 fps, found {effective_fps}"
)
assert math.isclose(duration_seconds, 108.0, rel_tol=0.0, abs_tol=1e-9), (
    f"Expected exactly 108 seconds, found {duration_seconds} seconds"
)

objects = list(scene.objects)
assert len(objects) >= 600, f"Expected at least 600 scene objects, found {len(objects)}"

detachable = [obj for obj in objects if bool(obj.get("asterion_part", False))]
assert len(detachable) >= 450, (
    f"Expected at least 450 reusable detachable parts, found {len(detachable)}"
)
craft_collection = bpy.data.collections.get("01 Asterion | detachable craft")
assert craft_collection is not None, "Detachable craft collection is missing"
craft_meshes = {obj for obj in craft_collection.objects if obj.type == "MESH"}
assert craft_meshes == set(detachable), (
    "Every instantiated craft mesh must be a reusable detachable part"
)
def geometry_signature(obj):
    coordinates = tuple((round(vertex.co.x, 5), round(vertex.co.y, 5),
                         round(vertex.co.z, 5)) for vertex in obj.data.vertices)
    return hashlib.sha256(repr(coordinates).encode("ascii")).hexdigest()

unique_profiles = {geometry_signature(obj) for obj in detachable}
assert len(unique_profiles) == len(detachable), (
    "Repeated exact mesh profiles remain in the reusable part pool"
)
assert all(obj.get("fabrication_variant") for obj in detachable), (
    "Every craft part needs a deterministic fabrication variant"
)
cargo_pods = [obj for obj in detachable
              if re.fullmatch(r"HAULER-CARGO-\d\d-\d\d", obj.name)]
roof_variants = {obj.get("roof_variant") for obj in cargo_pods}
assert len(cargo_pods) == 12 and len(roof_variants) >= 4, (
    "Cargo modules need individual roof machinery profiles"
)
service_trenches = sum(bool(obj.get("service_trench")) for obj in detachable)
assert service_trenches >= 20, "Structural service trenches are missing"

explorer = [obj for obj in objects if obj.get("configuration_role") == "EXPLORER"]
hauler = [obj for obj in objects if obj.get("configuration_role") == "HAULER"]
assert explorer, "No EXPLORER configuration components are present"
assert hauler, "No HAULER configuration components are present"
assert set(explorer + hauler).issubset(detachable), (
    "Specialized modules must belong to the persistent detachable pool"
)

recorded_counts = scene.get("role_component_counts")
if recorded_counts is not None:
    recorded_counts = dict(recorded_counts)
    assert int(recorded_counts.get("EXPLORER", -1)) == len(explorer), (
        "Recorded EXPLORER component count does not match scene objects"
    )
    assert int(recorded_counts.get("HAULER", -1)) == len(hauler), (
        "Recorded HAULER component count does not match scene objects"
    )

assert "GPT Images 2.5" in str(scene.get("texture_source", "")), (
    "The scene does not identify GPT Images 2.5 as its texture source"
)
texture_nodes = []
for material in bpy.data.materials:
    if not material.use_nodes or material.node_tree is None:
        continue
    for node in material.node_tree.nodes:
        if node.type == "TEX_IMAGE" and node.image is not None:
            texture_nodes.append((material, node))
packed_images = {node.image for _, node in texture_nodes}
required_maps = {
    "armor_graphite.png", "hull_normal.png", "hull_orm.png",
    "carbon_albedo.png", "carbon_normal.png", "carbon_orm.png",
    "heat_titanium.png", "copper_normal.png", "copper_orm.png",
    "solar_ceramic.png", "solar_normal.png", "solar_orm.png",
    "moon_albedo.png", "moon_normal.png", "moon_orm.png",
    "nasa_starmap_16k.jpg",
}
used_map_names = {Path(bpy.path.basename(image.filepath)).name
                  for image in packed_images}
assert required_maps <= used_map_names, (
    f"Required PBR maps are not connected: {sorted(required_maps-used_map_names)}"
)
for image in packed_images:
    assert image.packed_file is not None, f"Texture is not packed into the .blend: {image.name}"
    assert image.size[0] >= 32 and image.size[1] >= 32, (
        f"Texture has unexpectedly small dimensions: {image.name} {tuple(image.size)}"
    )
    if image.name.endswith(("_normal.png", "_orm.png")):
        assert image.colorspace_settings.name == "Non-Color", (
            f"Technical map is not in non-color space: {image.name}"
        )
sky_image = next(image for image in packed_images
                 if Path(bpy.path.basename(image.filepath)).name == "nasa_starmap_16k.jpg")
assert tuple(sky_image.size) == (16384, 8192), (
    f"The sky panorama is not the full 16K source: {tuple(sky_image.size)}"
)
occlusion_routes = 0
for material in bpy.data.materials:
    if material.use_nodes and material.node_tree:
        for node in material.node_tree.nodes:
            if (node.type == "GROUP" and node.node_tree is not None
                    and node.node_tree.name.startswith("glTF Material Output")
                    and node.inputs.get("Occlusion")
                    and node.inputs["Occlusion"].is_linked):
                occlusion_routes += 1
assert occlusion_routes >= 5, "Packed ORM red channels are not routed to glTF occlusion"

markers = list(scene.timeline_markers)
camera_markers = [marker for marker in markers if marker.camera is not None]
assert not camera_markers, "Camera-bound timeline markers would introduce cuts"
assert scene.camera is not None, "The uninterrupted camera is missing"
assert len(bpy.data.cameras) == 1, "The demo should use one physical camera"
flight_rig = bpy.data.objects.get("ASTERION | flight rig")
assert flight_rig is not None, "The narrative flight rig is missing"
assert all(obj.parent == flight_rig for obj in detachable), (
    "All reusable craft pieces must travel on the shared flight rig"
)
assert all(obj.parent == flight_rig for obj in objects
           if obj.type == "LIGHT" and not obj.name.startswith("EMBER |")), (
    "Craft lighting must follow the ship through the mission"
)
ember = bpy.data.objects.get("EMBER | storm giant")
assert ember and ember.type == "MESH", "The second planetary location is missing"
assert bpy.data.objects.get("EMBER | broken dust rings") is not None
assert all(any(Path(bpy.path.basename(image.filepath)).name == name
               for image in packed_images) for name in
           ("ember_albedo.png", "ember_normal.png", "ember_orm.png")), (
    "The second planet needs its complete PBR map set"
)
story_markers = [marker for marker in markers if marker.name.startswith("STORY |")]
assert len(story_markers) >= 8, "The mission beats are missing from the timeline"
assert bpy.data.objects.get("SIGNAL | recovered moon core") is not None
assert bpy.data.objects.get("SCAN | explorer to lunar signal") is not None
assert len([obj for obj in objects if obj.name.startswith("WARP | ion trail")]) >= 24


def local_pose(obj):
    rotation = (obj.rotation_quaternion.copy() if obj.rotation_mode == "QUATERNION"
                else obj.rotation_euler.to_quaternion())
    return obj.location.copy(), rotation, obj.scale.copy()


def pose_differs(first, second, epsilon=1e-4):
    first_loc, first_rot, first_scale = first
    second_loc, second_rot, second_scale = second
    return (
        (first_loc - second_loc).length > epsilon
        or first_rot.rotation_difference(second_rot).angle > epsilon
        or (first_scale - second_scale).length > epsilon
    )


def configuration_bounds(candidates):
    points = []
    for obj in candidates:
        if obj.type != "MESH" or obj.hide_render:
            continue
        points.extend(obj.matrix_world @ Vector(corner) for corner in obj.bound_box)
    assert points, "No visible configuration mesh bounds were found"
    low = tuple(min(point[axis] for point in points) for axis in range(3))
    high = tuple(max(point[axis] for point in points) for axis in range(3))
    return low + high


def assembly_components(candidates, clearance=.05):
    # AABB overlap is a conservative screen for visible floating modules. It
    # does not certify a welded joint, but catches separated wings, arrays,
    # fittings, and cargo pods in each assembled configuration.
    bounds = []
    for obj in candidates:
        points = [obj.matrix_world @ Vector(corner) for corner in obj.bound_box]
        bounds.append((tuple(min(point[axis] for point in points) for axis in range(3)),
                       tuple(max(point[axis] for point in points) for axis in range(3))))
    parent = list(range(len(candidates)))

    def root(index):
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    for index, first in enumerate(bounds):
        for other in range(index):
            second = bounds[other]
            gap_squared = sum(max(0, second[0][axis]-first[1][axis],
                                  first[0][axis]-second[1][axis])**2
                              for axis in range(3))
            if gap_squared <= clearance**2:
                parent[root(index)] = root(other)
    clusters = {}
    for index, obj in enumerate(candidates):
        clusters.setdefault(root(index), []).append(obj.name)
    return sorted(clusters.values(), key=len, reverse=True)


original_frame = scene.frame_current
original_subframe = scene.frame_subframe
time_anchors = ((1, 1), (541, 1441), (1261, 2161), (1801, 3601),
                (2521, 4321), (3061, 5761), (3601, 6481))


def retimed_frame(frame):
    for (source_start, target_start), (source_end, target_end) in zip(
            time_anchors, time_anchors[1:]):
        if source_start <= frame <= source_end:
            return round(target_start + (frame-source_start)
                         *(target_end-target_start)/(source_end-source_start))
    raise ValueError(frame)


sample_frames = tuple(retimed_frame(frame) for frame in (
    1, 541, 580, 841, 900, 1041, 1261, 1801, 1840,
    2180, 2251, 2521, 3061, 3100, 3230, 3301, 3601))
sampled_poses = {}
sampled_bounds = {}
visible_counts = {}
assembly_cluster_counts = {}
assembly_outliers = {}
camera_samples = {}
camera_probe_frames = sorted(set(range(1, scene.frame_end+1, 30)) | {scene.frame_end} |
                             {retimed_frame(frame)+offset for frame in (541, 580, 900, 1041,
                              1801, 1840, 2180, 2251, 3061, 3100, 3230, 3301)
                              for offset in (-1, 0, 1)} |
                             {1, 1441, 2161, 3601, 4321, 5761})
try:
    for frame in sample_frames:
        scene.frame_set(frame)
        bpy.context.view_layer.update()
        sampled_poses[frame] = {obj.name: local_pose(obj) for obj in detachable}
        visible_counts[frame] = sum(not obj.hide_render for obj in detachable)
        config_objects = [
            obj for obj in objects
            if obj.get("asterion_part", False)
            or obj.get("configuration_role") in {"EXPLORER", "HAULER"}
        ]
        sampled_bounds[frame] = configuration_bounds(config_objects)
        if frame in (1, retimed_frame(1261), retimed_frame(2521)):
            clusters = assembly_components(detachable)
            assembly_cluster_counts[frame] = len(clusters)
            assembly_outliers[frame] = [group[0] for group in clusters[1:]]
    for frame in camera_probe_frames:
        scene.frame_set(frame)
        bpy.context.view_layer.update()
        camera_samples[frame] = (scene.camera.matrix_world.translation.copy(),
                                 scene.camera.matrix_world.to_quaternion(),
                                 flight_rig.matrix_world.translation.copy())
finally:
    scene.frame_set(original_frame, subframe=original_subframe)
    bpy.context.view_layer.update()

start_camera, start_rig = camera_samples[1][0], camera_samples[1][2]
end_camera, end_rig = camera_samples[scene.frame_end][0], camera_samples[scene.frame_end][2]
assert (start_camera-end_camera).length < .001 and (start_rig-end_rig).length < .001, (
    "The ship and camera must meet their opening positions at the project loop seam"
)
assert camera_samples[1][1].rotation_difference(
    camera_samples[scene.frame_end][1]).angle < .001, (
    "The camera orientation must match across the complete project loop"
)

animated_detachable = [
    obj for obj in detachable
    if obj.animation_data is not None
    and obj.animation_data.action is not None
    and any(
        pose_differs(sampled_poses[retimed_frame(frame)][obj.name],
                     sampled_poses[1][obj.name])
        for frame in (841, 1261, 2521)
    )
]
assert len(animated_detachable) >= 350, (
    "Expected at least 350 detachable objects with active transform animation; "
    f"found {len(animated_detachable)}"
)
assert all(count == len(detachable) for count in visible_counts.values()), (
    f"Some craft pieces disappear instead of being reused: {visible_counts}"
)
assert all(count == 1 for count in assembly_cluster_counts.values()), (
    f"Assembled configurations contain floating groups: {assembly_outliers}"
)
camera_travel = sum((camera_samples[right][0]-camera_samples[left][0]).length
                    for left, right in zip(camera_probe_frames, camera_probe_frames[1:]))
max_camera_speed = max(
    (camera_samples[right][0]-camera_samples[left][0]).length/(right-left)
    for left, right in zip(camera_probe_frames, camera_probe_frames[1:]))
max_camera_turn = max(
    min((angle := camera_samples[left][1].rotation_difference(
        camera_samples[right][1]).angle), math.tau-angle)/(right-left)
    for left, right in zip(camera_probe_frames, camera_probe_frames[1:]))
assert camera_travel > 100, f"The camera orbit is too static: {camera_travel} m"
assert max_camera_speed < .5 and max_camera_turn < .02, (
    f"The camera has a visible jump: {max_camera_speed} m/frame, "
    f"{max_camera_turn} rad/frame"
)


def assembled_orbit(start, end):
    frames = [frame for frame in camera_probe_frames if start <= frame <= end]
    angles = [math.atan2((camera_samples[frame][0]-camera_samples[frame][2]).y,
                         (camera_samples[frame][0]-camera_samples[frame][2]).x)
              for frame in frames]
    return sum(math.atan2(math.sin(right-left), math.cos(right-left))
               for left, right in zip(angles, angles[1:]))


assembled_orbits = {name: assembled_orbit(start, end) for name, start, end in (
    ("COMBAT", 1, 1441), ("EXPLORER", 2161, 3601),
    ("HAULER", 4321, 5761))}
assert all(abs(angle) >= math.tau-.08 for angle in assembled_orbits.values()), (
    f"Each assembled ship needs a complete uninterrupted camera rotation: {assembled_orbits}"
)
warp_displacements = {}
for name, start, end in (("arrival", 11, 16), ("escape", 84, 90)):
    scene.frame_set(start*60+1)
    first = flight_rig.matrix_world.translation.copy()
    scene.frame_set(end*60+1)
    distance = (flight_rig.matrix_world.translation-first).length
    assert distance > 20, f"{name} warp lacks travel: {distance} m"
    warp_displacements[name] = distance
scene.frame_set(original_frame, subframe=original_subframe)


def mean_motion(first, last):
    return sum((sampled_poses[last][obj.name][0]
                -sampled_poses[first][obj.name][0]).length
               for obj in detachable)/len(detachable)/(last-first)


bullet_time = {}
for name, first, snap, hold, release in (
        ("combat_to_explorer", 541, 580, 900, 1041),
        ("explorer_to_hauler", 1801, 1840, 2180, 2251),
        ("hauler_to_combat", 3061, 3100, 3230, 3301)):
    first, snap, hold, release = map(retimed_frame, (first, snap, hold, release))
    snap_speed = mean_motion(first, snap)
    hold_speed = mean_motion(snap, hold)
    release_speed = mean_motion(hold, release)
    assert hold_speed < snap_speed*.12 and hold_speed < release_speed*.12, (
        f"{name} lacks a sustained bullet-time drift: "
        f"{snap_speed}, {hold_speed}, {release_speed}"
    )
    bullet_time[name] = {"snapMetersPerFrame": snap_speed,
                         "driftMetersPerFrame": hold_speed,
                         "releaseMetersPerFrame": release_speed}

noise_tools = runpy.run_path(str(ROOT / "apply_breakaway_rotation_noise.py"))
noise_windows = noise_tools["ASTERION_WINDOWS"]
noise_prefix = noise_tools["PREFIX"]
noise_count = 0
for obj in detachable:
    curves = noise_tools["rotation_curves"](obj)
    for axis in range(3):
        modifiers = [modifier for modifier in curves[axis].modifiers
                     if modifier.name.startswith(noise_prefix)]
        assert len(modifiers) == len(noise_windows), (
            f"{obj.name} rotation axis {axis} lacks breakup noise"
        )
        for modifier, (_, start, end) in zip(modifiers, noise_windows):
            assert (modifier.type == "NOISE" and modifier.blend_type == "ADD"
                    and modifier.use_restricted_range
                    and modifier.frame_start == start and modifier.frame_end == end
                    and modifier.blend_in > 0 and modifier.blend_out > 0), (
                f"{obj.name} has a mistimed breakup rotation modifier"
            )
        noise_count += len(modifiers)

noise_motion = {}
try:
    for name, start, _ in noise_windows:
        scene.frame_set(start + 160)
        first = {obj.name: obj.rotation_euler.to_quaternion().copy()
                 for obj in detachable}
        scene.frame_set(start + 310)
        motion = [first[obj.name].rotation_difference(
                  obj.rotation_euler.to_quaternion()).angle for obj in detachable]
        moving = sum(angle > .08 for angle in motion)
        assert moving >= len(detachable) * .8, (
            f"{name} has static debris rotations: {moving}/{len(detachable)} moving"
        )
        noise_motion[name] = {"rotatingParts": moving,
                              "meanRadians": sum(motion) / len(motion)}
finally:
    scene.frame_set(original_frame, subframe=original_subframe)
    bpy.context.view_layer.update()

return_errors = []
for obj in detachable:
    start_pose = sampled_poses[1][obj.name]
    end_pose = sampled_poses[retimed_frame(3601)][obj.name]
    if pose_differs(start_pose, end_pose):
        return_errors.append(obj.name)
assert not return_errors, (
    f"{len(return_errors)} detachable parts do not return to their frame-1 pose; "
    f"examples: {return_errors[:8]}"
)


def bounds_distance(a, b):
    return math.sqrt(sum((left - right) ** 2 for left, right in zip(a, b)))


combat_bounds = sampled_bounds[1]
explorer_bounds = sampled_bounds[retimed_frame(1261)]
hauler_bounds = sampled_bounds[retimed_frame(2521)]
configuration_distances = {
    "COMBAT_EXPLORER": bounds_distance(combat_bounds, explorer_bounds),
    "COMBAT_HAULER": bounds_distance(combat_bounds, hauler_bounds),
    "EXPLORER_HAULER": bounds_distance(explorer_bounds, hauler_bounds),
}
assert min(configuration_distances.values()) > 0.5, (
    "COMBAT, EXPLORER, and HAULER do not have measurably distinct assembled "
    f"geometry bounds: {configuration_distances}"
)

summary = {
    "valid": True,
    "file": str(opened_file),
    "durationSeconds": duration_seconds,
    "fps": effective_fps,
    "sceneObjectCount": len(objects),
    "uniqueCraftMeshProfiles": len(unique_profiles),
    "cargoRoofVariants": len(roof_variants),
    "serviceTrenchParts": service_trenches,
    "configurationComponentCounts": {
        "COMBAT": len(detachable),
        "EXPLORER": len(detachable),
        "HAULER": len(detachable),
    },
    "specializedModuleCounts": {"EXPLORER": len(explorer), "HAULER": len(hauler)},
    "visiblePartCounts": visible_counts,
    "assemblyClusterCounts": assembly_cluster_counts,
    "cameraTravelMeters": camera_travel,
    "maxCameraMetersPerFrame": max_camera_speed,
    "maxCameraRadiansPerFrame": max_camera_turn,
    "assembledOrbitRadians": assembled_orbits,
    "warpDisplacementsMeters": warp_displacements,
    "bulletTime": bullet_time,
    "breakupRotationNoiseModifiers": noise_count,
    "breakupRotationMotion": noise_motion,
    "animatedDetachableCount": len(animated_detachable),
    "packedTextureImageCount": len(packed_images),
    "gltfOcclusionRoutes": occlusion_routes,
    "cameraMarkerCount": len(camera_markers),
    "cameraObjectCount": len(bpy.data.cameras),
    "configurationBoundsDistance": configuration_distances,
    "returnedToRestCount": len(detachable),
    "restoredFrame": original_frame,
    "restoredSubframe": original_subframe,
}
print("ASTERION_ADVANCED_DEMO_VALID " + json.dumps(summary, sort_keys=True))

"""Read-only structural and animation validation for AsterionBreakaway.blend.

Execute this script inside Blender through the official Blender MCP TCP
extension. It temporarily samples animation frames, restores the original
playhead, and does not save or otherwise modify the .blend file.
"""

from __future__ import annotations

import json
import math
import hashlib
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
assert math.isclose(duration_seconds, 60.0, rel_tol=0.0, abs_tol=1e-9), (
    f"Expected exactly 60 seconds, found {duration_seconds} seconds"
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
cargo_pods = [obj for obj in detachable if obj.name.startswith("HAULER-CARGO-")]
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
marker_cameras = {marker.camera for marker in camera_markers}
assert len(camera_markers) >= 5, (
    f"Expected at least 5 camera-bound timeline markers, found {len(camera_markers)}"
)
assert len(marker_cameras) >= 3, (
    f"Expected at least 3 distinct marker cameras, found {len(marker_cameras)}"
)


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


original_frame = scene.frame_current
original_subframe = scene.frame_subframe
sample_frames = (1, 841, 1261, 1801, 2251, 2521, 3061, 3601)
sampled_poses = {}
sampled_bounds = {}
visible_counts = {}
camera_motion = {}
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
    ordered_markers = sorted(camera_markers, key=lambda marker: marker.frame)
    for index, marker in enumerate(ordered_markers):
        end = (ordered_markers[index + 1].frame - 1
               if index + 1 < len(ordered_markers) else scene.frame_end)
        scene.frame_set(marker.frame)
        bpy.context.view_layer.update()
        start_location = marker.camera.matrix_world.translation.copy()
        start_rotation = marker.camera.matrix_world.to_quaternion()
        scene.frame_set(end)
        bpy.context.view_layer.update()
        end_location = marker.camera.matrix_world.translation.copy()
        end_rotation = marker.camera.matrix_world.to_quaternion()
        distance = (end_location - start_location).length
        raw_angle = start_rotation.rotation_difference(end_rotation).angle
        angle = min(raw_angle, math.tau-raw_angle)
        camera_motion[marker.name] = {"travelMeters": distance,
                                      "rotationRadians": angle}
finally:
    scene.frame_set(original_frame, subframe=original_subframe)
    bpy.context.view_layer.update()

animated_detachable = [
    obj for obj in detachable
    if obj.animation_data is not None
    and obj.animation_data.action is not None
    and any(
        pose_differs(sampled_poses[frame][obj.name], sampled_poses[1][obj.name])
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
assert all(motion["travelMeters"] > 3.0 and motion["rotationRadians"] > .08
           for motion in camera_motion.values()), (
    f"Every camera shot must move and turn visibly: {camera_motion}"
)

return_errors = []
for obj in detachable:
    start_pose = sampled_poses[1][obj.name]
    end_pose = sampled_poses[3601][obj.name]
    if pose_differs(start_pose, end_pose):
        return_errors.append(obj.name)
assert not return_errors, (
    f"{len(return_errors)} detachable parts do not return to their frame-1 pose; "
    f"examples: {return_errors[:8]}"
)


def bounds_distance(a, b):
    return math.sqrt(sum((left - right) ** 2 for left, right in zip(a, b)))


combat_bounds = sampled_bounds[1]
explorer_bounds = sampled_bounds[1261]
hauler_bounds = sampled_bounds[2521]
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
    "movingCameraShots": camera_motion,
    "animatedDetachableCount": len(animated_detachable),
    "packedTextureImageCount": len(packed_images),
    "gltfOcclusionRoutes": occlusion_routes,
    "cameraMarkerCount": len(camera_markers),
    "distinctMarkerCameraCount": len(marker_cameras),
    "configurationBoundsDistance": configuration_distances,
    "returnedToRestCount": len(detachable),
    "restoredFrame": original_frame,
    "restoredSubframe": original_subframe,
}
print("ASTERION_ADVANCED_DEMO_VALID " + json.dumps(summary, sort_keys=True))

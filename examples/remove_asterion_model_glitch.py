"""Remove the Asterion model-glitch pass through the official Blender MCP."""

import bpy


def action_curves(obj):
    action = obj.animation_data.action if obj.animation_data else None
    if action is None:
        return []
    if hasattr(action, "fcurves"):
        return [(action.fcurves, curve) for curve in action.fcurves]
    return [(bag.fcurves, curve)
            for layer in action.layers for strip in layer.strips
            for bag in strip.channelbags for curve in bag.fcurves]


scene = bpy.context.scene
old_frame = scene.frame_current
restored = 0
for obj in bpy.data.objects:
    if not obj.get("asterion_model_glitch"):
        continue
    for owner, curve in action_curves(obj):
        if curve.data_path in {"delta_location", "delta_rotation_euler"}:
            owner.remove(curve)
    obj.delta_location = (0, 0, 0)
    obj.delta_rotation_euler = (0, 0, 0)
    del obj["asterion_model_glitch"]
    restored += 1

collection = bpy.data.collections.get("06 Glitch | model echoes and H445")
removed = 0
if collection:
    for obj in tuple(collection.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
        removed += 1
    bpy.data.collections.remove(collection)

for blocks in (bpy.data.meshes, bpy.data.curves, bpy.data.materials):
    for block in tuple(blocks):
        if block.users == 0 and block.name.startswith("GLITCH |"):
            blocks.remove(block)

if "model_glitch" in scene:
    del scene["model_glitch"]
scene.frame_set(old_frame)
print("REMOVED_ASTERION_MODEL_GLITCH", {"restored_parts": restored,
                                          "removed_objects": removed})

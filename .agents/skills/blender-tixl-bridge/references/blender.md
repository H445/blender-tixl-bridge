## Blender MCP capabilities

Blender MCP servers use different tool names. Inspect the connected server's advertised tools at the start of a task and map them to these capabilities. Prefer a specific read or write tool when one exists; otherwise use the MCP tool that executes Python in Blender. Do not guess a tool name.

The required Blender-side capabilities are:

1. Read Blender version, current file, scene, active camera, frame range, FPS, collections, objects, materials, lights, animation data, shape keys, custom properties, and add-on state.
2. Open and save `.blend` files and confirm `bpy.data.filepath` afterward.
3. Run Blender Python for precise bridge configuration and operator invocation.
4. Install, enable, disable, and inspect add-ons and persist user preferences.
5. Set scene custom properties used by the bridge: `tixl_project_name` and `tixl_worlds`.
6. Trigger the bridge sync and inspect its immediate result.
7. Render or capture Blender-side reference output when comparison with TiXL is required.

### Blender scene preflight

Run an equivalent of this through Blender MCP before syncing:

```python
import bpy
import json

scene = bpy.context.scene
print(json.dumps({
    "blenderVersion": bpy.app.version_string,
    "file": bpy.data.filepath,
    "scene": scene.name,
    "camera": scene.camera.name if scene.camera else None,
    "frameStart": scene.frame_start,
    "frameEnd": scene.frame_end,
    "fps": scene.render.fps / scene.render.fps_base,
    "collections": sorted(c.name for c in bpy.data.collections),
    "tixlProjectName": scene.get("tixl_project_name"),
    "tixlWorlds": scene.get("tixl_worlds"),
}, indent=2, default=str))
```

Require a saved file and either an active camera or camera-bound timeline markers. With no `tixl_worlds` property, the active scene becomes one world named `main`. When `tixl_worlds` exists, parse its JSON and verify that every entry has a unique non-empty name, an existing collection, and a contiguous time range. World names cannot contain `/` or `\\`.

The exporter supports meshes and UV textures through glTF, object transforms, visibility, shape keys, PBR base color and emission, lights, and active-camera or marker-based camera cuts. It samples runtime animation at 60 Hz. Do not promise exact transfer of arbitrary procedural Blender shaders or physical refraction.

### Configure the installed add-on through Blender MCP

Use Blender Python and read the values back:

```python
import bpy

addon = bpy.context.preferences.addons.get("blender_tixl_bridge")
if addon is None:
    raise RuntimeError("blender_tixl_bridge is not enabled")

prefs = addon.preferences
prefs.operator_project = r"<TiXL-created operator-project directory>"
prefs.editor_directory = r"<directory containing TiXL.exe>"
prefs.connection_mode = "DEBUG"  # AUTO, OFFLINE, or DEBUG
prefs.debug_port = 9042
bpy.ops.wm.save_userpref()

print({
    "operator_project": prefs.operator_project,
    "editor_directory": prefs.editor_directory,
    "connection_mode": prefs.connection_mode,
    "debug_port": prefs.debug_port,
})
```

For an update from this checkout, use Blender MCP's Python execution capability to run `install_blender_addon.py` with the desired arguments. The installer hashes every copied file, enables the add-on, preserves existing settings on updates, and saves preferences. Reconnect Blender MCP if an add-on reload or file open resets the connection.

### Save and sync through Blender MCP

```python
import bpy

if not bpy.data.filepath:
    raise RuntimeError("Save the .blend before syncing")
if bpy.context.scene.camera is None and not any(m.camera for m in bpy.context.scene.timeline_markers):
    raise RuntimeError("The scene needs an active camera or camera timeline markers")

bpy.ops.wm.save_mainfile()
sync_result = bpy.ops.tixl_bridge.sync_saved_blend()
print({"result": sorted(sync_result), "file": bpy.data.filepath})
```

The operator queues a background process; `FINISHED` means queued, not completed. Follow `<blend folder>/.tixl_cache/<blend name>/sync_logs/latest.log`. Then inspect `tixl_project.json` and `current_generation.json`. Use `cache_publication.active_root(cache)` to verify the committed generation (including recovery fallback), then inspect its `worlds/manifest.json`, per-world manifests and channels, and `camera_timeline.json`, plus the cache-root generated graph files before moving to TiXL verification. New generations change saved graph path inputs, so installation defers until the end user saves editor work and closes TiXL; never terminate it automatically.

`scene.tixl_bridge_autosync` controls sync-after-save. Enable it only when the end user asks for continuing automatic syncs.

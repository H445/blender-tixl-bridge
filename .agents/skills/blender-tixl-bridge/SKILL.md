---
name: blender-tixl-bridge
description: Operate, inspect, validate, edit, and troubleshoot the Blender-to-TiXL bridge using Blender MCP and TiXL's local debug protocol. Use for add-on configuration, scene preflight, sync, generated graphs, rendering, timing, mesh or texture edits, screenshots, and bridge diagnostics.
---

# Blender–TiXL bridge operational skill

Use this skill after the installation and first-run workflow in `../../README.md`. Blender is the authored source. The generated TiXL project owns editable timing and render-graph changes, while `.tixl_cache` contains replaceable generated imports.

Before relying on the catalogs below, read `../../CAPABILITIES.md`. The Blender add-on maintains that snapshot without an AI agent: it checks capabilities on install/update, add-on registration, and before sync. This skill supplies the safe workflows and semantics.

## Non-negotiable tool routing

- Use Blender MCP for every action inside Blender. Never use Computer Use, UI automation, simulated input, or coordinate clicking.
- Use `blender_tixl_bridge/source/tixl_bridge.py` for every action inside a running TiXL editor. Never control TiXL through Computer Use.
- Terminal and filesystem tools are allowed for builds, logs, cache inspection, tests, and documented command-line bootstrap. They do not replace either application API.
- If Blender MCP lacks a required capability, or TiXL is not running with its debug server, stop and ask the end user to perform the unsupported bootstrap step.
- After every mutation, read the resulting state back through the same API. A successful call alone is not verification.

## Documentation structure

When documentation changes are in scope, keep the root `README.md` as a concise human landing page. It should communicate the project purpose, main capabilities, a minimal quick start, links to deeper documents, and important limitations. Do not accumulate exhaustive operator lists, JSON examples, CLI reference, graph-editing recipes, troubleshooting catalogs, or agent instructions there.

Put human setup and procedures in `docs/USER_GUIDE.md`, the human-facing comparison and advantages of plug-in-only versus agentic-workspace use in `docs/AGENTIC_WORKFLOW.md`, technical behavior and graph ownership in `docs/BRIDGE_REFERENCE.md`, example-specific material in `examples/README.md`, and agent-only instructions under `.agents/`. Prefer links over copying the same explanation into several files.

Do not imply that an agent is required to use the bridge. The plug-in-only mode is a complete manual workflow. In agentic-workspace mode, the repository root provides shared context for Blender MCP, the TiXL debug bridge, filesystem artifacts, builds, tests, capability discovery, and validation.

## Capability router

| Goal | Required interface | Preferred capability |
| --- | --- | --- |
| Inspect or modify a `.blend` | Blender MCP | Scene/object inspection or Blender Python execution |
| Open, save, or configure Blender | Blender MCP | File and preference operations, or Blender Python |
| Install/configure the add-on | Blender MCP | Run `install_blender_addon.py` or set add-on preferences through `bpy` |
| Start a sync | Blender MCP | Save, then invoke `bpy.ops.tixl_bridge.sync_saved_blend()` |
| Follow a build | Filesystem | Read `.tixl_cache/<blend>/sync_logs/latest.log` and manifests |
| Inspect or edit a TiXL graph | TiXL debug bridge | `getGraphState`, graph-edit commands, and read-back verification |
| Evaluate output | TiXL debug bridge | Pause, set time, pump frames, inspect outputs, capture screenshots |
| Diagnose TiXL | TiXL debug bridge | `getLogTail`, `getMetrics`, `getContext`, and screenshots |
| Change loaded `.t3`/`.t3ui` structure on disk | Filesystem plus end-user-safe restart | Save editor work and restart TiXL with `--debug-server 9042` |

## Automatic capability discovery

Agents do not assemble capability inputs. `.agents/capability_automation.py` performs deterministic local discovery and invokes the lower-level generator. The Blender add-on queues it:

- with `--force` after checkout installation or update;
- without force when the add-on registers after Blender starts;
- before every sync;
- with `--force` when the user clicks **Refresh agent capabilities**.

The automation fingerprints Blender, Blender MCP, TiXL, the TiXL debug bridge client/server, this add-on, and its operator contracts. It connects directly to Blender's official MCP TCP extension, using the saved extension host and port passed by the bridge add-on. It can also speak stdio MCP to obtain server version, tool descriptions, and input schemas. It speaks TiXL's local debug protocol directly and parses matching source when present. A lock prevents overlapping plugin triggers, and the state fingerprint prevents unnecessary rewrites. It is a one-shot process and must not be replaced with a scheduled task, watcher, or background service.

The official Blender MCP TCP extension requires no local automation configuration. For a different MCP implementation whose stdio command cannot be discovered from supported user configuration, configure it once in the ignored `.agents/capability_automation.json` using `.agents/capability_automation.example.json`. Do not place credentials in the checked-in example or capability snapshot.

An agent should read `.agents/CAPABILITIES.md` and investigate any new **unclassified** method. It may ask the user to click the manual refresh button if the snapshot reports a missing configured component, but it must not fabricate probe results or use Computer Use. Developers can force the same non-AI path with:

```powershell
python .agents/capability_automation.py once --force
```

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
result = bpy.ops.tixl_bridge.sync_saved_blend()
print({"result": sorted(result), "file": bpy.data.filepath})
```

The operator queues a background process; `FINISHED` means queued, not completed. Follow `<blend folder>/.tixl_cache/<blend name>/sync_logs/latest.log`. Then inspect `tixl_project.json` and `current_generation.json`. Use `cache_publication.active_root(cache)` to verify the committed generation (including recovery fallback), then inspect its `worlds/manifest.json`, per-world manifests and channels, and `camera_timeline.json`, plus the cache-root generated graph files before moving to TiXL verification. New generations change saved graph path inputs, so installation defers until the end user saves editor work and closes TiXL; never terminate it automatically.

`scene.tixl_bridge_autosync` controls sync-after-save. Enable it only when the end user asks for continuing automatic syncs.

## TiXL debug bridge

TiXL must be running with `--debug-server 9042` or the configured port. The server binds to `127.0.0.1`. The repository client sends one JSON-lines request per connection and raises on any `{ok:false}` response.

```python
import sys
from pathlib import Path

source = Path(r"<repository>\blender_tixl_bridge\source")
sys.path.insert(0, str(source))
from tixl_bridge import call

port = 9042
print(call("getVersion", port))
```

Use a generous timeout for compilation or screenshots: `call("reload", port, timeout=300, project="ProjectName")`.

### Read-only inspection and diagnostics

| Method | Important parameters | Use |
| --- | --- | --- |
| `ping` | none | Confirm that the main-thread request queue responds. |
| `getVersion` | none | Read protocol and editor versions; always call first. |
| `getStructureVersion` | none | Detect symbol-structure changes. |
| `getContext` | none | Read open composition, path, selection, output pin, time, BPM, and playback state. |
| `getGraphState` | `compositionId?`, `includeDefaults?` | Read children, positions, inputs, connections, unresolved children, and unresolved connections. |
| `getGraphView` | none | Read canvas scale, scroll, visible area, and window bounds. |
| `getOutput` | `childId?`, `outputName?` or `outputId?`, `update?`, `dumpObj?` | Evaluate scalar/vector/string/bool outputs or inspect mesh counts, bounds, manifoldness, and volume. |
| `getLogTail` | `sinceSeq?`, `minLevel?`, `maxCount?` | Read incremental debug/info/warning/error entries. Track `latestSeq`. |
| `getMetrics` | none | Read FPS, frame delta, managed memory, render stats, and GPU memory. |
| `screenshot` | `path`, `target="output"|"ui"` | Save the rendered output texture or editor-rendered UI without OS screen capture. |
| `screenshotWindow` | `path`, `region?="graph"` | Capture the editor client area or graph canvas. |

`screenshot target="output"` requires a renderable pinned output. Use PNG unless a smaller JPEG is deliberately desired. A screenshot is evidence to inspect, never an input-control mechanism.

### Project, graph-view, and evaluation control

| Method | Important parameters | Use |
| --- | --- | --- |
| `openProject` | `name` or `symbolId`, `pinOutput?` | Open a project; short names match display names with namespaces. |
| `select` | `childId?`, `childIds?`, `add?` | Replace/add selection; no IDs clears it. |
| `focusGraphView` | `childIds?`, `all?`, `includeMissing?`, `padding?`, `smooth?` | Frame specific nodes, selection, or the whole graph. |
| `setGraphView` | `area?`; or `centerX?`, `centerY?`, `scale?`, `zoomBy?`, `scrollByX?`, `scrollByY?`, `smooth?` | Set the graph camera exactly. |
| `pin` | `childId` | Pin a child instance in the output window. |
| `setTime` | `timeInSecs` or `timeInBars` | Move the playhead. |
| `setPlayback` | `playing` or `speed` | Pause, play, or change playback speed. |
| `pumpFrames` | `count` (1–100000) | Advance deterministic editor frames after state changes. |
| `outputSetup` | `entity?`, `mode?` | Drive the output window's setup state through the protocol. |
| `resetView` | none | Reset the output view. |

After `openProject`, `setTime`, `pin`, graph-view changes, or graph mutations, pump two or three frames before evaluating or capturing. Preserve the original time and playback state from `getContext` and restore them when a diagnostic task is complete.

### Graph creation and mutation

| Method | Important parameters | Use |
| --- | --- | --- |
| `setInput` | `childId`, `inputName` or `inputId`, `value`, `compositionId?` | Set typed input values with undo support. |
| `addOp` | `symbolName` or `symbolId`, `posX?`, `posY?`, `compositionId?` | Add an operator. Prefer `symbolId` when a name is ambiguous. |
| `connect` | `sourceChildId`, `sourceOutput?`, `targetChildId`, `targetInput?`, `multiInputIndex?`, `compositionId?` | Add a type-checked, cycle-checked connection. |
| `deleteOp` | `childId`, `compositionId?` | Delete an operator with undo support. |
| `setBypass` | `childId`, `bypassed?`, `compositionId?` | Bypass or re-enable a compatible operator. |
| `undo` / `redo` | none | Traverse the TiXL undo stack. |
| `reload` | `project` | Recompile an editable project. This can block and does not reliably replace a loaded graph structure. |
| `newProject` | `name` | Create and compile a shared-resource project. Use only after collecting the user's namespace and project choices. |

For graph edits: capture `getGraphState`, make one logical mutation, pump frames, read `getGraphState` again, evaluate the affected output, and inspect `getLogTail`. If verification fails, use `undo` and confirm the rollback. Do not assume an in-memory edit has been persisted when there is no explicit save command; coordinate saving with the end user.

`shutdown` exits TiXL and discards unsaved changes. Never call it without explicit user authorization and a confirmed save. `stallMainThread` is a test-only fault-injection command and must not be used in normal operation. `setAgentState(state="busy"|"ready", note=...)` may advertise agent activity in the editor; clear it when finished.

### TiXL bridge call patterns

```python
# Inspect the current graph and fail on unresolved structure.
state = call("getGraphState", port, includeDefaults=False)
if state.get("missingChildren") or state.get("missingConnections"):
    raise RuntimeError("Generated graph contains unresolved structure")

# Evaluate and capture a stable frame.
context = call("getContext", port)
call("setPlayback", port, playing=False)
call("setTime", port, timeInSecs=4.0)
call("pumpFrames", port, count=3)
call("screenshot", port, path=r"<absolute-path>\output.png", target="output")
call("focusGraphView", port, all=True, padding=80)
call("pumpFrames", port, count=2)
call("screenshotWindow", port, path=r"<absolute-path>\graph.png", region="graph")

# Restore the original playhead and playback speed.
call("setTime", port, timeInSecs=context["time"]["timeInSecs"])
call("setPlayback", port, speed=context["time"]["playbackSpeed"])
```

## Reusable TiXL bridge operators

The bridge installs eleven operators under `PrismalLabs.BlenderExport`. Agents should recognize their roles and preserve these patterns during graph edits.

| Operator | Capability and correct use |
| --- | --- |
| `BlenderSourceClip` | Editable source `TimeClip`. Moving/stretching changes placement; its source range remains Blender-export seconds. Feed both the global sequence and its world's sequence. |
| `BlenderClipSequence` | Selects the active source clip and emits mapped source time plus active state. Use one global sequence and one sequence per world. |
| `BlenderWorldClipTime` | Reconciles global camera time with a world's time. Insert native float operators on the world-time wire to retime only that world. |
| `BlenderCameraTimeline` | Reads `camera_60hz.bin` and timeline JSON, producing pose, lens, clip planes, mapped source time, and active world. |
| `BlenderAnimationScene` | Applies transform, visibility, PBR/emission, and morph caches to matching glTF data at `TimeSeconds`; exposes opaque, transparent, and combined scenes. |
| `BlenderWorldPreload` | Warms every connected world on the first paused render and then passes the active command. Keep all animation-scene results connected. |
| `BlenderExportLights` | Preloads manifest/channel light data, chooses by world index, samples by time, and applies energy calibration. |
| `BlenderMeshSelect` | Selects a zero-based primitive and exposes its mesh for native TiXL mesh processing. Its status reports name and count. |
| `BlenderMeshReplace` | Replaces the selected primitive with edited mesh buffers while preserving other animated primitives. Match its `PrimitiveIndex` with `BlenderMeshSelect`. |
| `BlenderTextureSelect` | Exposes albedo, normal, roughness/metal/occlusion, and emissive textures for a primitive. |
| `BlenderTextureReplace` | Replaces those four maps after TiXL image processing. Match its `PrimitiveIndex` with `BlenderTextureSelect`. |

Preserve the default path:

```text
Blender Source Clips
  ├─> global Blender Clip Sequence ─> Blender Camera Timeline ─> world selection
  └─> per-world Blender Clip Sequence ─> Blender World Clip Time ─> Blender Animation Scene
       ├─> Blender Mesh Select ─> native mesh ops ─> Blender Mesh Replace
       ├─> Blender Texture Select ─> native image ops ─> Blender Texture Replace
       └─> Blender World Preload / drawing / lights ─> RenderTarget ─> tone mapping ─> Output target
```

Sync preserves the user-owned home graph, TimeClips, and supported editable routes while replacing generated import data. Keep generated imports separate from user edits. If Blender adds or removes worlds, update the corresponding user-owned scene branches deliberately.

## End-to-end playbooks

### Sync and validate a project

1. Through Blender MCP, inspect the current file, camera, timing, collections, world JSON, add-on preferences, and add-on registration.
2. Save through Blender MCP, invoke `tixl_bridge.sync_saved_blend`, and confirm the queue result.
3. Follow `latest.log` to completion and inspect generated manifests and `tixl_project.json` with filesystem tools.
4. Through TiXL debug bridge, call `getVersion`, set agent state to busy, pause playback, and `openProject` using the generated project name.
5. Call `getContext` and `getGraphState`. Reject unresolved children/connections and verify the expected operators and wiring.
6. Locate and pin `Output target`, set meaningful times, pump frames, and capture output images. For multi-world projects, sample every world and both sides of cuts.
7. Focus the full graph and capture the graph region. Read warning/error logs and metrics.
8. Inspect the saved images. A non-empty file is not enough; confirm expected geometry, camera, lighting, material, and transitions.
9. Restore time/playback, clear agent state, and report cache, project, screenshots, and any remaining warnings.

### Edit a TiXL graph safely

1. Read context and full graph state; identify children by stable IDs, not screen position.
2. Pause playback. Apply the smallest mutation through `setInput`, `addOp`, `connect`, `setBypass`, or `deleteOp`.
3. Pump frames and compare graph state before/after.
4. Evaluate the affected output. For geometry, use `getOutput(update=True)` and its numeric mesh description before relying on screenshots.
5. Capture graph and output evidence and inspect logs.
6. Undo immediately if type, topology, render, or log validation fails.

### Diagnose a stale or blank result

1. Check Blender-side saved path, camera, collections, custom properties, and add-on preferences through Blender MCP.
2. Check `latest.log`, cache hashes/manifests, and generated project path.
3. Use `getContext` to confirm the intended project, paused state, time, and pinned output.
4. Use `getGraphState` to find missing nodes/connections and inspect relevant input paths.
5. Pin `Output target`, pump frames, capture output, and read `getLogTail(minLevel="warning")`.
6. If `.t3` or `.t3ui` structure changed while loaded, do not trust `reload`; save work and restart TiXL with the debug server before rechecking.

## Source-of-truth files

- `blender_tixl_bridge/__init__.py`: add-on preferences, save handler, and sync operator.
- `install_blender_addon.py`: verified checkout installation and preference migration.
- `blender_tixl_bridge/source/blend_sync.py`: build, cache, mode selection, reload, and project opening.
- `blender_tixl_bridge/source/blend_sync_worker.py`: Blender preflight, worlds, and camera export.
- `blender_tixl_bridge/source/tixl_animation_export.py`: supported scene and animation data.
- `blender_tixl_bridge/source/tixl_bridge.py`: JSON-lines TiXL client.
- `.agents/capability_automation.py`: non-AI component discovery, fingerprints, MCP probing, and refresh triggers.
- `.agents/rebuild_capabilities.py`: deterministic Markdown renderer used by the automation.
- `blender_tixl_bridge/operators/`: reusable TiXL operator implementations and UI contracts.
- `tests/debug_blend_shape_example_render.py`: proven time/pump/screenshot validation pattern.

If implementation and this skill disagree, treat implementation as authoritative and update this skill in the same change.

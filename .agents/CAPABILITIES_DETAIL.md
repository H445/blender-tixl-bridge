# Discovered Blender–TiXL capabilities

> Generated automatically. Do not hand-edit. `.agents/capability_automation.py` rebuilds this file when a monitored component changes.

## Discovery coverage

| Source | Status | Evidence |
| --- | --- | --- |
| Bridge checkout | complete | add-on 0.5.1; source SHA-256 `4dda3a8fe5e1cb2c` |
| Blender installation | complete | Blender 5.2.2 LTS via MCP runtime |
| Blender runtime via MCP | complete | 5.2.2 LTS |
| Blender MCP | complete | 1 tool; Blender MCP TCP extension 1.0.3 |
| TiXL installation | complete | TiXL 4.3.0.2 |
| TiXL source | complete | matching `Editor/App/DebugProtocol/DebugServer.cs`; SHA-256 `1b3dae492cd919b4` |
| TiXL debug bridge | complete | client `1fef203b064fecf4`; server `1b3dae492cd919b4` |
| Live TiXL debug server | complete | {"capabilityDiscovery": "not supported by this protocol version", "port": 9042, "version": {"editorVersion": "4.3.0.2", "protocolVersion": 1}} |

The automation keeps retrying unavailable live probes. A `missing` row means its component is not configured or discoverable and is not yet monitored.

## Blender bridge runtime

- Add-on: **Prismal Labs Blender → TiXL Bridge 0.5.1**
- Minimum Blender declared by add-on: **4.3.0**
- Registered bridge operators: `tixl_bridge.check_release_update`, `tixl_bridge.install_release_update`, `tixl_bridge.refresh_agent_capabilities`, `tixl_bridge.sync_saved_blend`
- Add-on properties discovered from source: `auto_update`, `capability_repository`, `connection_mode`, `debug_port`, `editor_directory`, `operator_project`, `tixl_bridge_autosync`

Runtime probe:

```json
{
  "addonEnabled": true,
  "addonVersion": [
    0,
    5,
    1
  ],
  "background": false,
  "blenderMcpTcpExtension": {
    "autostart": true,
    "host": "localhost",
    "module": "bl_ext.lab_blender_org.mcp",
    "port": 9876,
    "version": "1.0.3"
  },
  "blenderVersion": "5.2.2 LTS",
  "blenderVersionTuple": [
    5,
    2,
    2
  ],
  "bridgeOperators": [
    "check_release_update",
    "install_release_update",
    "refresh_agent_capabilities",
    "sync_saved_blend"
  ],
  "canExecutePython": true,
  "canOpenAndSaveBlend": true,
  "canReadScene": true,
  "canRender": true,
  "pythonVersion": "3.13.13",
  "sceneHasAutosyncProperty": true
}
```

## Blender MCP tools discovered automatically

| Tool | Inputs | Advertised capability |
| --- | --- | --- |
| `execute_blender_code` | `code` (required) | Execute Python inside Blender through the official Blender MCP TCP extension. |

## TiXL debug-protocol methods

| Method | Category | Capability | Evidence |
| --- | --- | --- | --- |
| `addOp` | Mutation | Add an operator by symbol name or ID. | `DebugServer.cs:318` |
| `connect` | Mutation | Create a type-checked, cycle-checked connection. | `DebugServer.cs:322` |
| `deleteOp` | Mutation | Delete an operator with undo support. | `DebugServer.cs:326` |
| `focusGraphView` | Navigation | Frame selected, specified, missing, or all operators. | `DebugServer.cs:295` |
| `getContext` | Inspection | Read project, composition, selection, output, time, and playback context. | `DebugServer.cs:250` |
| `getGraphState` | Inspection | Read graph children, values, positions, connections, and unresolved structure. | `DebugServer.cs:254` |
| `getGraphView` | Inspection | Read graph camera and visible bounds. | `DebugServer.cs:287` |
| `getLogTail` | Diagnostics | Read buffered log entries incrementally. | `DebugServer.cs:246` |
| `getMetrics` | Diagnostics | Read FPS, memory, render statistics, and GPU memory. | `DebugServer.cs:258` |
| `getOutput` | Evaluation | Evaluate scalar, vector, string, bool, or mesh output data. | `DebugServer.cs:303` |
| `getStructureVersion` | Inspection | Read the symbol-structure version counter. | `DebugServer.cs:239` |
| `getVersion` | Inspection | Read protocol and editor versions. | `DebugServer.cs:225` |
| `newProject` | Creation | Create and compile a shared-resource project. | `DebugServer.cs:314` |
| `openProject` | Navigation | Open a project by name or symbol ID and optionally pin its output. | `DebugServer.cs:270` |
| `outputSetup` | Output | Drive output-setup state through the protocol. | `DebugServer.cs:358` |
| `pin` | Evaluation | Pin a child in the output window. | `DebugServer.cs:330` |
| `ping` | Inspection | Confirm the main-thread request queue responds. | `DebugServer.cs:206` |
| `pumpFrames` | Evaluation | Advance deterministic editor frames. | `DebugServer.cs:307` |
| `redo` | Mutation | Redo the latest undone command. | `DebugServer.cs:423` |
| `reload` | Build | Recompile an editable project. | `DebugServer.cs:390` |
| `resetView` | Output | Reset the output view. | `DebugServer.cs:377` |
| `screenshot` | Evidence | Capture output texture or editor-rendered UI. | `DebugServer.cs:262` |
| `screenshotWindow` | Evidence | Capture the editor client area or graph region. | `DebugServer.cs:266` |
| `select` | Navigation | Select graph children by stable IDs. | `DebugServer.cs:274` |
| `setAgentState` | Coordination | Publish busy/ready state and a note in the editor. | `DebugServer.cs:210` |
| `setBypass` | Mutation | Bypass or re-enable a compatible operator. | `DebugServer.cs:334` |
| `setGraphView` | Navigation | Set graph camera, zoom, scroll, or fitted area. | `DebugServer.cs:291` |
| `setInput` | Mutation | Set a typed child input with undo support. | `DebugServer.cs:299` |
| `setPlayback` | Evaluation | Pause, play, or change playback speed. | `DebugServer.cs:445` |
| `setTime` | Evaluation | Set timeline time in seconds or bars. | `DebugServer.cs:429` |
| `shutdown` | Lifecycle | Exit TiXL; unsaved changes are discarded. | `DebugServer.cs:233` |
| `stallMainThread` | Test only | Inject a main-thread stall; never use in normal operation. | `DebugServer.cs:394` |
| `undo` | Mutation | Undo the latest editor command. | `DebugServer.cs:417` |

## Reusable TiXL bridge operators

| Operator | Contract from current `.t3ui` |
| --- | --- |
| `BlenderAnimationScene` | Applies a Blender export cache to a loaded glTF scene. DataPath points to the TIXLANIM transform/channel cache and GlbPath points to the matching GLB. Evaluates transforms, visibility, animated PBR/emission channels, and mesh morph targets at TimeSeconds. Use OpaqueResult for depth-writing solids and TransparentResult for back-to-front alpha geometry; Result is the unpartitioned scene. Export caches must use the TIXLANIM binary contract and preserve source node names. |
| `BlenderCameraTimeline` | Reads the Blender camera rail and outputs interpolated pose, lens, clip planes, and source time. The project TimeClips drive OverrideTime for shared camera, geometry, material, light, and world timing. WorldStartSeconds selects the active Blender world from source time; ActiveWorld remains available as a fallback. |
| `BlenderClipSequence` | Selects the active Blender Source Clip and exposes its mapped source time and HasActiveClip state. One global sequence controls the camera and world switch; each world's sequence connects its source clips to that world's Animation Scene through World Clip Time. Insert float operators after a world sequence to retime it independently. |
| `BlenderExportLights` | Preloads every Blender light manifest and keyed channel set on a paused initialization frame. WorldDirectory contains <scene>_manifest.json and optional <scene>_channels.json files. WorldIndex selects cached lights, TimeSeconds samples their animation, and EnergyScale calibrates Blender energy to TiXL point-light units. The operator forwards the incoming Command after pushing lights. |
| `BlenderMeshReplace` | Replace one scene primitive with edited MeshBuffers. Keep PrimitiveIndex aligned with BlenderMeshSelect; all other animated primitives, transforms, and materials pass through. |
| `BlenderMeshSelect` | Choose an animated primitive by zero-based index. The node status shows its name and total count. Route Mesh through TiXL mesh modifiers before BlenderMeshReplace. |
| `BlenderSourceClip` | Editable Blender source TimeClip. Move or stretch it in the TiXL timeline; SourceRange stays in seconds of the Blender export. Its output feeds both the global timing sequence and the sequence for its Blender Animation Scene world. |
| `BlenderTextureReplace` | Replace the selected primitive's four texture maps after TiXL image processing. Keep PrimitiveIndex aligned with BlenderTextureSelect; Blender PBR color and roughness values remain animated. |
| `BlenderTextureSelect` | Tap the selected primitive's albedo, normal, roughness/metal/occlusion, and emissive textures. Insert TiXL image operators on these wires before BlenderTextureReplace. |
| `BlenderWorldClipTime` | Connect this world's Blender Source Clips through a Blender Clip Sequence to WorldClipTime. By default, GlobalClipTime and WorldClipTime match, so the camera-mapped time passes through unchanged. Insert any TiXL float operators on the WorldClipTime or TimeSeconds wires to retime this world's animation without changing camera cuts or other worlds. |
| `BlenderWorldPreload` | Preloads every connected Blender world on the first paused render, then passes through the active drawing command without revisiting inactive worlds. Connect each BlenderAnimationScene Result output to Worlds. |

## Review result

No unclassified TiXL methods were discovered.

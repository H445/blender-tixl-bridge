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

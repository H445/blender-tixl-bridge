## Reusable TiXL bridge operators

The bridge installs fourteen operators under `PrismalLabs.BlenderExport`. Agents should recognize their roles and preserve these patterns during graph edits.

| Operator | Capability and correct use |
| --- | --- |
| `BlenderSourceClip` | Editable source `TimeClip`. Moving/stretching changes placement; its source range remains Blender-export seconds. Feed both the global sequence and its world's sequence. |
| `BlenderClipSequence` | Selects the active source clip and emits mapped source time plus active state. Use one global sequence and one sequence per world. Set `LoopDurationSeconds` to the same positive duration on every lane to repeat the entire composition; zero keeps ordinary timeline behavior. The wrap applies before each TimeClip maps source time. |
| `BlenderWorldClipTime` | Reconciles global camera time with a world's time. Insert native float operators on the world-time wire to retime only that world. |
| `BlenderCameraTimeline` | Reads `camera_60hz.bin` and timeline JSON, producing pose, lens, clip planes, mapped source time, and active world. |
| `BlenderAnimationScene` | Applies transform, visibility, PBR/emission, and morph caches to matching glTF data at `TimeSeconds`; exposes opaque, transparent, and combined scenes. |
| `BlenderWorldPreload` | Warms every connected world on the first paused render and then passes the active command. Keep all animation-scene results connected. |
| `BlenderExportLights` | Preloads manifest/channel light data, chooses by world index, samples by time, and applies energy calibration. |
| `BlenderObjectIndex` | Its searchable `ObjectName` dropdown lists mesh objects from the connected imported scene after evaluation. Multi-primitive objects get one labeled choice per part. `SelectedObject` and status show the resolved label; older unique name fragments still resolve, while ambiguity selects nothing. `PrimitiveIndex` is an internal wire shared by all four mesh and texture ports. |
| `BlenderMeshSelect` | Selects a zero-based primitive and exposes its mesh for native TiXL mesh processing. Its status reports name and count. |
| `BlenderMeshReplace` | Replaces the selected primitive with edited mesh buffers while preserving other animated primitives. Match its `PrimitiveIndex` with `BlenderMeshSelect`. |
| `BlenderTextureSelect` | Exposes albedo, normal, roughness/metal/occlusion, and emissive textures for a primitive. |
| `BlenderTextureReplace` | Replaces those four maps after TiXL image processing. Match its `PrimitiveIndex` with `BlenderTextureSelect`. |
| `BlenderAudioClip` | Legacy graph playback operator. For new timeline audio, use TiXL's native `Lib.io.audio.AudioClip` instead; it creates a visible editable TimeClip and exposes `AudioReference`. |
| `BlenderAudioBus` | Legacy command bus for bridge audio clips. For new timeline audio, use native `Lib.io.audio.AudioBus` and route its `Result` through `Lib.flow.Execute` with the final image command. |

Preserve the default path:

```text
Blender Source Clips
  ├─> global Blender Clip Sequence ─> Blender Camera Timeline ─> world selection
  └─> per-world Blender Clip Sequence ─> Blender World Clip Time ─> Blender Animation Scene
       ├─> Blender Object Index ─> mesh and texture primitive indices
       ├─> Blender Mesh Select ─> native mesh ops ─> Blender Mesh Replace
       ├─> Blender Texture Select ─> native image ops ─> Blender Texture Replace
       └─> Blender World Preload / drawing / lights ─> RenderTarget ─> tone mapping ─> Output target

Native AudioClip TimeClips ─> AudioReference ─> native AudioBus ─┐
Tone mapping ─────────────────────────────────────────────────────┴─> Execute ─> Output target
```

For audio-synced edits, generate the audio chops and TiXL control curves from
the same beat/event schedule. Keep each native AudioClip's `TimeRange` in bars
and `SourceRange` in file seconds; route its `AudioReference` to the native
AudioBus, then evaluate the bus through `Execute` on the final render path.
Drive visual effect strength with the shared event curve and inspect rendered
frames on and between accents so a graph connection is not mistaken for a
visible effect.
For randomized music-video sections, seed choices per bar so every build and
108-second loop repeats exactly while adjacent bars differ. Use one event list
for percussion, melodic packets, and sparse visual accents. Close all sampled
curves at the loop seam. A moving SDF needs animation of field parameters or
space transforms (for example radius, tilt, deformation, and noise offset),
not merely a blend opacity curve. Compare separated frames and nearby off-beat
frames before claiming motion or visual variety.

Sync preserves the user-owned home graph, TimeClips, and supported editable routes while replacing generated import data. Keep generated imports separate from user edits. If Blender adds or removes worlds, update the corresponding user-owned scene branches deliberately.

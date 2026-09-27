# Bridge reference

Blender owns the source scene. The bridge produces replaceable caches and installs them into a TiXL project whose home graph remains editable by the user.

## Data transferred from Blender

- Meshes, UV textures, and glTF-compatible PBR material properties.
- Object transforms, visibility, shape keys, material base color and emission, and lights sampled at 60 Hz.
- The active camera, lens and clipping data, plus camera-bound timeline markers for cuts.
- One generated import branch per configured world, with scene switching, rendering, and final resolution control.

Procedural Blender shaders, arbitrary World-node networks, and physical refraction are not guaranteed to match. Build TiXL-side equivalents when glTF cannot represent the source.

Transform baking groups consecutive samples for each record into contiguous writes.
The writer shares an 8 MiB buffered-payload budget across all world records, with
at most 1,024 samples per batch. When only one sample fits per record, it writes
directly without retaining payload buffers. Python object and allocator overhead
are outside this payload budget. The record-major `TIXLANIM` version 1 format,
float32 matrices, sparse static records, channel ordering, and shared 60 Hz frame
sampling remain unchanged; batching does not introduce runtime disk loading.

## Generated and editable ownership

The authored `.blend` stays in place. Generated data, logs, manifests, camera samples, animation caches, and the TiXL project link live in `.tixl_cache/<blend name>/` beside it. A generated TiXL project is created beside the configured operator project.

Sync replaces generated import data but preserves the user-owned project home, TimeClips, supported timing wires, editable mesh and texture routes, node positions, and render graph. If Blender adds or removes worlds, update the corresponding user-owned scene branches deliberately. Older home symbols replaced during migration are backed up under `project_backups/` in the cache.

## Export cache validity

Exports are published as immutable directories under `generations/<id>/`. Each contains worlds, both camera files, state, and a commit marker with file sizes and SHA-256 hashes. A single atomic `current_generation.json` replacement makes the complete generation visible. Readers verify the marker and use one generation for every generated graph input. Previous generations remain available to loaded graphs; publication never overwrites their data.

If the active generation is incomplete or damaged, readers try the previous committed generation recorded in the pointer or `previous_generation.json`. They never promote an uncommitted directory found by scanning. A save during export rejects publication after a final source-content check. A failed graph installation can leave the new cache committed while the editor keeps its previous complete generation; retry installation after the editor handoff. Legacy caches without a generation marker rebuild once.

Generation installation updates only known bridge file-path inputs that still point inside this cache, including those in editable homes and nested project symbols. Other inputs, connections, positions, custom external paths, and TimeClips remain intact. All proposed paths must exist before any graph is changed; saved originals are backed up and write failures roll back. Because a new generation changes saved graph input values, save editor work and close TiXL before installing it. The bridge defers installation while TiXL remains open; cache creation with `--no-install` is still available. An unchanged generation can use the existing live verification path.

Cache reuse requires the saved `.blend` hash and a versioned export contract. The contract fingerprints exporter/worker code, the Blender executable, glTF exporter scripts, and the fixed 60 Hz export configuration. Saved scene settings are covered by the `.blend` hash and recorded in the contract. Graph templates and TiXL operator builds use separate fingerprints; editing a graph or operator does not invalidate exported geometry by itself.

Save-triggered requests use a per-source queue inside Blender: one active CLI child and one replaceable latest pending request. A temporary timer polls children only while active or retryable work exists. Pending work starts after either a successful or failed child exit; different source paths have independent queues. Launch failures stop automatic retries after three attempts, retaining the latest request for the next submission. Status snapshots omit process environment and command arguments. The queue lives for the Blender process; exiting Blender before it drains can lose a pending request.

Exports use a kernel-owned advisory lock in `.blend_sync.process.lock`. The lock file remains in place, and ownership releases automatically on process exit, including crashes. An existing `.blend_sync.lock` belongs to an older bridge version: wait for that sync to finish, or verify it has exited before removing its stale marker. Do not run older and newer bridge versions concurrently against the same cache.

External resources come from Blender's path inventory, including linked libraries and their resources. Unpacked files are content-hashed; packed resources are covered by the `.blend` hash. Numbered image sequences and tiled textures track matching filenames as well as content, so added or removed files invalidate reuse. Missing resources, unrecognized directories, and unsupported sequence paths cannot be reused. Old caches without this contract require one fresh export. The worker checks that code, runtime, and dependencies remain unchanged through export before declaring the stage complete.

## Generated storage retention

Sync and explicit install share the publication lease through graph activation, retention, and recovery-summary publication. Retention policy and recovery procedures are in the [user guide](USER_GUIDE.md#generated-storage-and-recovery). Cleanup operates only on validated direct generated entries below the cache root, rechecks each tree immediately before removal, and rejects linked/reparse paths. New staging and backup directories carry ownership markers; legacy unmarked directories are excluded.

The current/previous commit pointers, latest successful/failed summaries, saved project graph references, and retained graph backups determine pins. Graph scanning uses checked non-following directory traversal and rejects malformed evidence before pruning. References from a backup removed in the current pass remain conservatively pinned until the next pass. Generation pruning is deferred while TiXL is open because the protocol cannot enumerate all unsaved or undo references. Manual pins cover copies of graphs or cache uses outside the recorded project. Protected entries can exceed the configured limits; the report makes that excess explicit.

Blender-launched sync and discovery children drain output through one-shot wrappers with a log-group lease. Active writers cannot be pruned. A logging interruption waits for its orchestration child, including the export worker it owns, before returning. Full output is scanned for completion while only bounded head/tail evidence is stored. `latest.log` is atomically updated after completion; queue status links to the per-run active log. Discovery keeps up to forty log/metadata files within 64 MiB and 30 days, with latest failure protection; the short automation status trail trims at 1 MiB.

## Home graph

The generated home has one row per world and a shared world switch and render chain. This zoomed view shows one world's animation, mesh, and texture path:

![Zoomed TiXL world branch showing Blender animation, mesh replacement, and texture editing](screenshots/tixl-graph.png)

A wider branch view includes the surrounding scene connections:

![TiXL graph detail showing animation and editable mesh and texture connections](screenshots/tixl-graph-detail.png)

The default timing path is:

```text
Blender Source Clips
  ├─> global Clip Sequence ─> Camera Timeline ─> world selection
  └─> world Clip Sequence ─> World Clip Time ─> Animation Scene
```

Move or trim source TimeClips to change placement and sampled source time. Insert native TiXL float operators before or after **World Clip Time** to retime one world without changing camera cuts or other worlds.

For geometry, **Select mesh** feeds **Replace mesh**. Keep their zero-based `PrimitiveIndex` values aligned and insert native TiXL mesh operators between them. For materials, **Select textures** exposes albedo, normal, roughness/metal/occlusion, and emissive maps; process any map with TiXL image operators before its matching **Replace textures** input.

**Preload all Blender worlds** initializes scene and animation branches on the first paused evaluation. The light operator caches world manifests and channels. The selected world then feeds the camera, environment, render target, tone mapping, and **Output target**.

New homes use the grid and lane defaults in `blender_tixl_bridge/templates/home_layout.json`. Sync preserves positions rearranged in TiXL. Home graphs have an internal **Resolution** node and no symbol ports; the generated import symbol keeps its ports for reuse inside other graphs.

## Reusable TiXL operators

The bridge installs eleven shared operators under `PrismalLabs.BlenderExport`:

| Operator | Role |
| --- | --- |
| `BlenderSourceClip` | Editable source TimeClip. |
| `BlenderClipSequence` | Maps active source clips to source time. |
| `BlenderWorldClipTime` | Separates global camera time from per-world timing. |
| `BlenderCameraTimeline` | Samples the exported camera and selects the active world. |
| `BlenderAnimationScene` | Applies transform, visibility, material, and morph animation to glTF scenes. |
| `BlenderWorldPreload` | Warms every connected world before switching. |
| `BlenderExportLights` | Samples and applies exported Blender lights. |
| `BlenderMeshSelect` | Exposes one animated primitive's mesh buffers. |
| `BlenderMeshReplace` | Replaces that primitive after TiXL mesh processing. |
| `BlenderTextureSelect` | Exposes four material texture groups. |
| `BlenderTextureReplace` | Replaces processed material textures. |

## Package layout

- `blender_tixl_bridge/__init__.py` — Blender add-on, preferences, save handler, and operators.
- `blender_tixl_bridge/operators/` — reusable TiXL `.cs`, `.t3`, and `.t3ui` operators.
- `blender_tixl_bridge/source/` — export, validation, graph generation, installation, and debug client.
- `blender_tixl_bridge/templates/` — internal graph and layout templates; do not install them as a TiXL project.
- `build_addon_zip.py` — reproducible add-on package builder.
- `install_blender_addon.py` — verified checkout installer and preference migration.

The background exporter never runs during TiXL render frames. Generated cache publication waits for a safe paused frame when a debug connection is active.

## Scene loading and shared animation memory

`BlenderAnimationScene` opens and parses each GLB once during paused initialization.
Morph geometry, material defaults, and primitive centers come from the same JSON
document and binary chunk. The document and raw binary bytes are released after
those projections finish; there is no additional shared GLB cache. A malformed
projection fails the load atomically and reports a cache warning instead of
applying only part of the GLB data.

Transform, visibility, morph-weight, and material tracks share a cache within the
loaded operator type. Keys include the resolved animation path and the size and
UTC modification time of its binary, metadata, and channel files. Immutable
export generation paths therefore have independent entries. On the next paused scene initialization, direct file edits
must change their modification time to invalidate an existing entry.

The cache retains at most 16 entries and 64 MiB of conservatively accounted
managed data. Accounting includes track arrays, names, cache keys, records, and
dictionary entries; it is an estimate rather than a measurement of the entire
managed heap. Entries are evicted in insertion order until both limits hold.
An export larger than the byte budget still loads for its requesting scene but
is not retained by the shared cache. Live scene bindings can continue using
tracks after cache eviction, so their memory is outside the shared-cache limit.

Debug render statistics report GLB file opens and successful JSON parses at the
operations themselves, including loads that later fail projection. Shared cache
entry and accounted-byte gauges are reported by one live instance to avoid
double counting when several worlds are connected. These gauges are separate
from the debug protocol's whole-editor managed-memory and GPU-memory readings.

Morph bindings own their replacement vertex buffers. Native glTF scenes own the
original vertex, index, and chunk buffers. Releasing a binding restores its
original mesh wrapper while that scene is alive. If the native scene was
disposed first, the binding requires a cleared dispatch list together with
disposed replacement, index, and chunk resource views before releasing the
original vertex buffer that its replacement had hidden. An empty filtered
scene alone does not release borrowed buffers. Shared index and chunk buffers
remain under native scene ownership.
This handles either disposal order without retaining a vertex buffer per resync.

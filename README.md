** WARNING: This is a very early experimental project. It is not yet ready for production use. Back up your current existing projects first. **

# blender-tixl-bridge

AI agents must follow the separate [agentic installation and operation guide](.agents/README.md).

Edit a scene in Blender, save its `.blend`, and let the bridge build the TiXL version in the background. The `.blend` owns the source scene; the TiXL project home exposes editable timing, mesh buffers, material textures, and rendering in one graph. GLB meshes, animation data, camera samples, lights, and the Blender import symbol are generated caches.

This repository contains the Blender add-on and eleven reusable TiXL operators: **Blender Animation Scene**, **Blender Camera Timeline**, **Blender Export Lights**, **Blender World Preload**, **Blender Source Clip**, **Blender Clip Sequence**, **Blender World Clip Time**, **Blender Mesh Select**, **Blender Mesh Replace**, **Blender Texture Select**, and **Blender Texture Replace**. They are shared by every generated project; none is tied to a particular scene.

## Blender add-on and TiXL graph

In Blender's **Scene Properties → TiXL Bridge**, enable **Sync after save**, run a sync on demand, or manually refresh the capabilities recorded for AI agents:

![Blender TiXL Bridge panel with save sync, on-demand sync, and agent capability refresh controls](docs/screenshots/blender-plugin.png)

The add-on preferences configure the TiXL operator project, Editor folder, connection mode, debug port, and capability repository. Capability discovery runs automatically when the add-on loads and before a sync; **Refresh agent capabilities** forces it immediately:

![Blender bridge add-on preferences showing TiXL paths, debug bridge settings, and capability refresh](docs/screenshots/blender-preferences.png)

After syncing, TiXL exposes an editable home graph. This overview shows four world branches feeding the shared world switch and render chain:

![TiXL home graph with four world branches and a shared render chain](docs/screenshots/tixl-graph.png)

A closer view shows the animation, mesh replacement, texture selection, and texture replacement nodes in one world branch:

![TiXL graph detail showing animation and editable mesh and texture connections](docs/screenshots/tixl-graph-detail.png)

See the [example README](examples/README.md#screenshots) for screenshots of the rendered shapes and morph.

## Set up once (Windows)

You need Blender 4.3 or newer, a TiXL Editor build, a TiXL C# operator project, and the .NET SDK. The current release was tested with Blender 5.2.2 LTS and TiXL 4.3.0.2. Create the operator project once in TiXL so it has valid release metadata. You can then close TiXL; **the debug server is optional**.

1. Download or clone this repository and run `python build_addon_zip.py` to build the local add-on package. In Blender, open **Edit → Preferences → Add-ons → Install from Disk**, choose **`blender_tixl_bridge.zip`**, and enable **Prismal Labs Blender → TiXL Bridge**. (In Blender versions that call it **Get Extensions**, use **Install from Disk** there.)
2. Open the add-on preferences and set **TiXL operator project** to the folder containing your TiXL `.csproj` and `Symbols` folder. Set **TiXL Editor folder** to the build folder containing `TiXL.exe`. Leave **TiXL connection** on **Auto** unless you want to force a mode.
3. Open any Blender project with an active camera. In **Scene Properties → TiXL Bridge**, turn on **Sync after save**. Save the `.blend`.

The first save can take a while. Watch `<blend folder>/.tixl_cache/<blend name>/sync_logs/latest.log`. The bridge installs the operators, creates a TiXL project for this `.blend` from your TiXL-created project scaffold, and builds it. The project is created beside the operator project; its exact path is recorded in `.tixl_cache/<blend name>/tixl_project.json`. In offline mode, **select the generated project once in TiXL**. In debug mode, the bridge opens it for you. Later Blender saves rebuild the import symbol while preserving edits to the project home and its TimeClips, mesh ports, texture ports, and render graph. TiXL may restart to load new files, so save any open TiXL work first. The **Sync saved .blend to TiXL** button runs the same process on demand.

**Daily use:** work in Blender and save. You do not need to export or import binary files by hand. A failed rebuild keeps the previous validated cache. A repeat sync with unchanged source keeps generated file timestamps and leaves an already-open TiXL project alone.

## TiXL connection modes

| Mode | Best for | What happens after a save |
| --- | --- | --- |
| **Auto** (default) | Most users, including release builds | Uses the debug bridge if one answers on the configured local port; otherwise builds offline. |
| **Offline** | Release builds without a debug server, or users who do not want a control socket | Writes and builds the project directly. TiXL restarts when files change; select a new project once. |
| **Debug bridge** | Live development | Reloads the loaded TiXL projects and opens the generated graph without restarting on routine saves. It requires an editor build with the opt-in debug protocol. |

To use live mode, start TiXL with `--debug-server 9042`, or select **Debug bridge** in the add-on preferences and let the bridge launch TiXL on the first build. The port is configurable there. The debug server listens on your own computer; it is not required to export a release-build project. If a particular TiXL release has no debug protocol, **Auto** uses offline mode.

## What comes across

- Meshes and UV textures in GLB; PBR material properties supported by Blender's glTF export.
- Object transforms, visibility, shape keys, material color and emission, and lights sampled at 60 Hz.
- The active camera, including camera-bound timeline markers for cuts.
- A generated Blender import symbol with one branch per world, camera movement, scene switching, rendering, and final output resolution control.
- An editable project home with source TimeClips. Moving a clip changes when that Blender section plays; trimming or changing its source range changes which part of the export it samples. Each clip feeds the global camera/world timing sequence and its own world's clip sequence. A **Blender World Clip Time** node connects each world sequence to its **Blender Animation Scene**, so their relationship is visible in the home graph. The default wires keep camera, geometry, materials, and world selection on the same mapped source time.
- Direct mesh and material texture edit ports in each animated world of the home graph, alongside `LoadGltfScene`, `DrawScene`, lights, camera, `RenderTarget`, and tone mapping.
- A **Preload all Blender worlds** node before the world switch. On the first paused evaluation, it initializes each GLB and animation branch; the light operator caches every world manifest and channel set. Scene cuts then select already-loaded data. If TiXL opens while transport is running, pause once to warm the project before playback. A background sync waits for TiXL to pause before publishing changed cache files or reloading operators.

By default the active Blender scene is one TiXL world. To use several worlds, add a **Scene custom property** named `tixl_worlds`. The bundled [BlendShapeExample](examples/README.md) uses these four collections and time ranges:

```json
[
  {"name":"cube","collection":"Cube","start_seconds":0,"end_seconds":4},
  {"name":"sphere","collection":"Sphere","start_seconds":4,"end_seconds":8},
  {"name":"prism","collection":"Prism","start_seconds":8,"end_seconds":12},
  {"name":"cylinder","collection":"Cylinder","start_seconds":12,"end_seconds":16}
]
```

The named collections must exist. Keep the time ranges contiguous; the generated graph switches branches at their boundaries. In this example, each world lasts eight beats at 120 BPM: four beats holding its shape, then four beats morphing into the next. Camera markers can control the view independently.

New project homes use a compact layout: each world has a row from clips and
source timing through mesh and texture edits to drawing. The world switch and
render chain sit to the right. Rows expand for glass passes and additional
clips. The defaults are defined in `blender_tixl_bridge/templates/home_layout.json`;
sync preserves positions you rearrange in TiXL.
New homes follow the grid-aligned `BlendShapeExample` layout using TiXL's
140 × 35 node grid. They have no symbol input or output ports: an internal
**Resolution** node drives both render targets. In debug mode the bridge pins
**Output target** for the preview; in offline mode, select and pin that node in
TiXL. The generated import symbol retains its ports for use inside other graphs.

## Release example

The add-on ZIP ships a small [BlendShapeExample example](examples/README.md): cube →
sphere → triangular prism → cylinder → cube. Open `examples/BlendShapeExample.blend`
from this checkout, or `blender_tixl_bridge/examples/BlendShapeExample.blend` from the
extracted release ZIP, and sync it through the add-on. Its four centered worlds
morph over a 16-second loop at the default 120 BPM.
The scene requests the exact TiXL project name `BlendShapeExample` through its
`tixl_project_name` custom property. Other scenes can use this property for an
explicit project name; it must be a C# identifier and the destination must be
unused on the first sync. Without it, the bridge keeps its automatic naming.

## Where things go

The authored `.blend` stays where you saved it. Generated data, logs, and the TiXL project link live in `.tixl_cache/<blend name>/` beside it. A newly generated TiXL project is created beside the operator project. Edit the project's home graph for timing, audio, effects, geometry, material maps, camera, lighting, and render settings. For each world, the default timing path is **Source Clips → world Clip Sequence → World Clip Time → Animation Scene**. Insert native TiXL float operators between the world sequence and World Clip Time, or between World Clip Time and Animation Scene. The latter point can also carry a complete user-built time path. The global clip sequence still controls camera mapping and world selection. Sync preserves modified timing wires and TimeClips. In each world, **Select mesh** feeds **Replace mesh** by default. Set the same zero-based `PrimitiveIndex` on both, then insert native TiXL mesh operators between their mesh ports. The selector's status shows the selected primitive's name and the total count. Operators such as `TransformMesh`, `DeformMesh`, and `SplitMeshVertices` can change vertex data or topology. **Select textures** exposes the chosen primitive's albedo, normal, roughness/metal/occlusion, and emissive maps as `Texture2D` outputs; route any map through TiXL image operators before its matching **Replace textures** input. Both selectors default to primitive zero, and their replacement nodes feed the rendered scene. The final `RenderTarget` and tone mapping texture chain is also in the home graph. These edits affect TiXL output; edit the `.blend` when the source asset itself should change. Sync preserves the home graph and replaces only the generated import symbol. If a Blender change adds or removes worlds, add or remove the corresponding scene branches in TiXL. When migrating an older project, the bridge backs up its former home symbol under `project_backups/` in the cache.

This is a save-driven build, not direct `.blend` playback inside TiXL. Blender shaders and World nodes that glTF cannot represent need TiXL-side equivalents. In particular, arbitrary procedural materials and physical refraction are not guaranteed to match Blender.

## Command line / troubleshooting

When updating this add-on from a checkout, copy the updated plugin into Blender and enable it with one command. Close Blender first if it is running, then run this from the repository folder using the Blender executable on your machine:

```powershell
& "<path-to-blender.exe>" --background --python install_blender_addon.py
```

This copies the current `blender_tixl_bridge/` package, checks every copied file, and enables the add-on. It saves first-install settings and keeps existing TiXL paths and connection mode on later updates. On a first install, either set those paths in Blender's add-on preferences or pass `-- --operator-project "C:\path\to\OperatorProject" --editor-dir "C:\path\to\TiXL\Editor\build"` after the script name. Restart any Blender window that was already open. Rebuild the distributable ZIP with `python build_addon_zip.py` whenever package files change.

The Blender add-on runs `blender_tixl_bridge/source/blend_sync.py` using Blender's bundled Python. For a cache-only build, set `TIXL_BRIDGE_BLENDER` to your Blender executable and run:

```powershell
python blender_tixl_bridge/source/blend_sync.py sync --blend C:\path\scene.blend --no-install
```

`status --blend ...` checks whether the cache matches the saved file. `--force` rebuilds even when the source hash matches. A full command-line TiXL installation also needs `TIXL_BRIDGE_OPERATOR_PROJECT` and `TIXL_BRIDGE_EDITOR` set to the same folders used in the add-on preferences. `TIXL_BRIDGE_MODE` selects `auto`, `offline`, or `debug`; `TIXL_BRIDGE_PORT` changes the local port. Set `TIXL_BRIDGE_LAUNCH_EDITOR=0` if you want the bridge to build files without starting TiXL.

If a save does not appear in TiXL, check `sync_logs/latest.log` first. Missing cameras, missing collections, and a project without release metadata are reported there. In offline mode, newly created projects require a one-time selection in TiXL.
After a bridge update changes the home graph's `.t3` structure, restart the TiXL editor to load that structure; the debug bridge's `reload` recompiles operators but can keep an already-open graph in memory.
If TiXL is open without the debug bridge, close it before publishing a changed cache. The bridge needs transport state to keep cache replacement off the realtime playback path.

## Package layout

- `blender_tixl_bridge/__init__.py` — Blender add-on and save handler.
- `blender_tixl_bridge/operators/` — reusable TiXL `.cs`, `.t3`, `.t3ui` operators.
- `blender_tixl_bridge/source/` — exporter, validation, graph generation, and TiXL installation.
- `blender_tixl_bridge/templates/` — internal graph template; never install it as a TiXL project.
- `build_addon_zip.py` — reproduces the installable ZIP.
- `install_blender_addon.py` — copies, enables, and verifies this checkout in local Blender.

The add-on currently targets Windows TiXL builds. Its background exporter does not run during TiXL render frames.

Repository: [blender-tixl-bridge](https://github.com/H445/blender-tixl-bridge). The Python add-on and release archive are named `blender_tixl_bridge` and `blender_tixl_bridge.zip`. Run `install_blender_addon.py` to migrate settings from the former `tixl_blender_bridge` module, then restart Blender. When installing the ZIP manually, disable the former add-on first and transfer its preferences to the new one.

# Setup and usage guide

This guide covers the human installation and daily workflow for the Blender–TiXL bridge. For graph structure and supported data, see the [bridge reference](BRIDGE_REFERENCE.md).

## Requirements

- Blender 4.3 or newer.
- The official Blender MCP extension, installed and enabled in Blender.
- A TiXL Editor build.
- The .NET SDK required by that TiXL build.
- A TiXL-created C# operator project containing a `.csproj`, `Symbols` directory, and valid release metadata.

The current bridge release is tested with Blender 5.2.2 LTS and TiXL 4.3.0.2.

## Complete application first-run setup

### Blender and Blender MCP

Launch Blender once and complete its first-run splash before installing the bridge. Install and enable the official Blender MCP extension through Blender's Extensions/Add-ons interface, then connect an MCP client and confirm it can read Blender state or execute a harmless Blender Python expression.

### TiXL

Launch TiXL once before configuring the bridge. Choose a short, stable username/root namespace when TiXL asks for one; it becomes part of project namespaces and is difficult to change later. Then create a dedicated operator project in TiXL rather than using its built-in `examples` project.

Keep the operator-project directory and the directory that directly contains `TiXL.exe`. You will enter both in Blender.

## Install the Blender add-on

From this repository, build the installable package:

```powershell
python build_addon_zip.py
```

In Blender:

1. Open **Edit → Preferences → Add-ons**.
2. Choose **Install from Disk** and select `blender_tixl_bridge.zip`. Blender versions that use **Get Extensions** expose the same command there.
3. Enable **Prismal Labs Blender → TiXL Bridge**.
4. Set **TiXL operator project** to the dedicated project directory.
5. Set **TiXL Editor folder** to the directory containing `TiXL.exe`.
6. Leave **TiXL connection** on **Auto** unless you deliberately need another mode.

![Blender bridge add-on preferences showing TiXL paths, debug bridge settings, and capability refresh](screenshots/blender-preferences.png)

## Sync a scene

The `.blend` must be saved and must have either an active camera or camera-bound timeline markers.

1. Open **Scene Properties → TiXL Bridge**.
2. Click **Sync saved .blend to TiXL**, or enable **Sync after save** for continuing automatic builds.
3. Follow `<blend folder>/.tixl_cache/<blend name>/sync_logs/latest.log` during the first build.

![Blender TiXL Bridge panel with save sync, on-demand sync, and capability refresh controls](screenshots/blender-plugin.png)

The first sync installs the reusable operators, creates a TiXL project beside the operator project, and records its exact location in `.tixl_cache/<blend name>/tixl_project.json`. Later syncs replace generated imports while preserving the project home, TimeClips, editable mesh and texture routes, and render graph.

Daily use is simply: work in Blender and save. A failed rebuild retains the previous validated cache. Save unrelated TiXL work before a sync that may restart or reload the editor.

## Connection modes

| Mode | Best for | Behavior |
| --- | --- | --- |
| **Auto** | Most users | Uses the debug bridge when available and otherwise builds offline. |
| **Offline** | Normal release builds without a control socket | Writes and builds the project directly. Select a new generated project once in TiXL. |
| **Debug bridge** | Bridge and TiXL development | Reloads projects and opens the generated graph without restarting on routine saves. |

For live development, start TiXL with `--debug-server 9042`, or select **Debug bridge** and let the bridge launch it on the first build. The port is configurable. The server listens only on the local computer and is not required for normal release use.

## Multi-world scenes

Without extra configuration, the active Blender scene becomes one TiXL world named `main`. For multiple worlds, add a Scene custom property named `tixl_worlds` containing JSON. Each entry needs a unique name, an existing collection, and a contiguous time range:

```json
[
  {"name":"cube","collection":"Cube","start_seconds":0,"end_seconds":4},
  {"name":"sphere","collection":"Sphere","start_seconds":4,"end_seconds":8},
  {"name":"prism","collection":"Prism","start_seconds":8,"end_seconds":12},
  {"name":"cylinder","collection":"Cylinder","start_seconds":12,"end_seconds":16}
]
```

Camera timeline markers can control cuts independently. See the bundled [BlendShapeExample](../examples/README.md), which morphs through these four worlds over a 16-second loop.

Set the optional `tixl_project_name` Scene property when the generated project needs an exact name. It must be a valid C# identifier and unused on the first sync.

## Update from a checkout

Close Blender, then run:

```powershell
& "<path-to-blender.exe>" --background --python install_blender_addon.py
```

The installer copies and hashes the add-on, enables it, migrates the former `tixl_blender_bridge` module, preserves existing settings on updates, and saves preferences. Restart Blender afterward. Rebuild the distributable ZIP with `python build_addon_zip.py` whenever package files change.

## Command-line cache build

Set `TIXL_BRIDGE_BLENDER` to the Blender executable, then run:

```powershell
python blender_tixl_bridge/source/blend_sync.py sync --blend C:\path\scene.blend --no-install
```

`status --blend ...` checks whether the cache matches the saved file. `--force` rebuilds unchanged input. A full command-line install also uses `TIXL_BRIDGE_OPERATOR_PROJECT`, `TIXL_BRIDGE_EDITOR`, `TIXL_BRIDGE_MODE`, and `TIXL_BRIDGE_PORT`. Set `TIXL_BRIDGE_LAUNCH_EDITOR=0` to build without starting TiXL.

## Troubleshooting

- Start with `.tixl_cache/<blend name>/sync_logs/latest.log`. It reports missing cameras, missing collections, and invalid project metadata.
- In Offline mode, select a newly generated project once in TiXL.
- If TiXL opens while transport is running, pause once so the project can preload every world.
- If a bridge update changes loaded `.t3` or `.t3ui` structure, save editor work and restart TiXL. `reload` can leave the old graph in memory.
- If TiXL is open without the debug bridge, close it before publishing changed cache files.
- On a manual ZIP update, disable the former add-on before enabling the new package and transfer its preferences.

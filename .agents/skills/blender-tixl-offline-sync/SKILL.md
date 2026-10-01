---
name: blender-tixl-offline-sync
description: Rebuild or install a saved Blender scene's TiXL cache without relying on a live TiXL debug session. Use for repeatable offline exports, deferred installation, cache recovery, and handoff to a manual TiXL session; use the bridge router for live render verification.
---

# Offline Blender–TiXL sync

Read [repository rules](../../../AGENTS.md), [capability summary](../../CAPABILITIES.md), and the [bridge router](../blender-tixl-bridge/SKILL.md). The capability file reports what is available now; an unavailable live endpoint does not prevent an offline cache build. Consult [detailed capabilities](../../CAPABILITIES_DETAIL.md) only for an exact contract. Discovery is owned by the add-on; do not edit its reports or fabricate probes.

## Prepare

1. Use a saved `.blend` with an active camera. If an **agent** must inspect, change, or save Blender, use the official MCP TCP extension, including `BlenderTcpExtensionClient` when no named tool is exposed. A person using the plug-in can work directly in Blender.
2. Locate the configured Blender executable and a TiXL-created operator project. Follow the [user guide](../../../docs/USER_GUIDE.md#command-line-cache-build) for environment variables and add-on preferences. Do not invent first-run username/namespace or project scaffolding.
3. Keep source `.blend`, generated `.tixl_cache`, installed import symbols, and user-owned Home graphs/TimeClips distinct. Record the `.blend` path and existing project link before rebuilding.

## Build and inspect without TiXL

For a person or non-agent offline build, run from the repository root with `TIXL_BRIDGE_BLENDER` set to the configured Blender executable:

```powershell
python blender_tixl_bridge/source/blend_sync.py sync --blend "<saved scene.blend>" --no-install
python blender_tixl_bridge/source/blend_sync.py status --blend "<saved scene.blend>"
```

An agent triggers the equivalent add-on sync through Blender MCP; do not use the CLI as an alternative Blender control transport. The human plug-in path is **TiXL Bridge → Sync saved .blend to TiXL** in **Offline** mode. `--no-install` only publishes a validated cache; it does not install the project. Check `sync_logs/latest_run.json`, `current_generation.json`, the generation commit marker, `worlds/manifest.json`, per-world manifests, camera timeline, and generated graph files. Resolve the active generation through the bridge's recovery pointer, not a directory guess. Verify expected worlds, camera, assets, and graph paths before proceeding. See [sync checks](../blender-tixl-bridge/references/sync.md) and [cache behavior](../../../docs/BRIDGE_REFERENCE.md#export-cache-validity).

## Install when ready

After preserving editor work and closing TiXL, a person can run:

```powershell
python blender_tixl_bridge/source/blend_sync.py install --blend "<saved scene.blend>"
```

Supply the configured operator project and editor settings from the [user guide](../../../docs/USER_GUIDE.md#command-line-cache-build). Installation defers while TiXL is open; do not force it past a possible unsaved edit. An agent closes a known-clean configured session through the debug bridge and launches through the configured bridge with full process permissions. A person without the debug bridge saves and closes TiXL manually, then reopens the generated project. After installation, inspect the actual render and logs in TiXL; an offline build alone cannot establish render correctness. For an agent's live checks use [sync verification](../blender-tixl-bridge/references/sync.md); for a manual check use the [user guide](../../../docs/USER_GUIDE.md#troubleshooting).

Repeat with a new saved scene path and its own cache/project. Reuse the procedure and validations, not project-specific graph IDs, absolute user paths, or asset names.

## Installed ZIP paths

The ZIP bundles this skill and its reusable dependencies under the installed `blender_tixl_bridge` folder. In a checkout, run commands from the repository root. In an installed ZIP, use the add-on folder as the root and replace the checkout `blender_tixl_bridge/source/` prefix with `source/`. Offline audio helpers require NumPy in the Python interpreter used to run them. Example sound assets and scene generators remain workspace examples; they are not required by the generic workflow.

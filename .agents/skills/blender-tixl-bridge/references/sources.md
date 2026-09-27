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

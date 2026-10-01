---
name: blender-tixl-graph-layout
description: Arrange a TiXL graph from its current connections with minimal overlap and crossings while preserving topology and settings. Use for any newly generated or growing graph, including an offline staged .t3ui layout.
---

# Layout a TiXL graph

Read [repository rules](../../../AGENTS.md), [capability summary](../../CAPABILITIES.md), and the [bridge router](../blender-tixl-bridge/SKILL.md). Live graph/view inspection requires the TiXL debug capability; staging a saved graph is offline and needs no debug server. Use the [graph-layout agent rules](../blender-tixl-bridge/references/graph-layout.md) for the complete safety and visual checks.

1. Identify the matching Home `.t3` and `.t3ui`; if TiXL is open, compare saved positions with `getGraphView`. Preserve unsaved editor arrangement before touching disk. For an offline graph, use the saved files and state that live layout freshness is unverified.
2. Stage outside `Symbols` with `python tools/layout_tixl_graph.py --graph "<home.t3>" --ui "<home.t3ui>" --output "<staged.t3ui>"`. The helper derives lanes from the current DAG, changes positions only, and fails on cycles, dangling children, or outside connections. Never transplant a prior scene's coordinates.
3. Compare all child IDs, edges, non-position UI data, node count, position uniqueness, spacing and crossing metric. Preview the staged layout at a readable zoom. Keep semantic branches near consumers and give the graph enough room; do not compress it to fit one screenshot.
4. Once the editor is known clean and closed, apply with `--output "<home.t3ui>" --backup "<backup outside Symbols>"`. Do not leave a second `.t3` or `.t3ui` under any live `Symbols` folder. Restart TiXL after the disk change. For an agent use the configured debug bridge and full-permission launcher; in offline/manual use, the person reopens TiXL.
5. Verify graph view, missing children/connections, representative output frames and the loop seam. Restore the prior editor context where possible. If live TiXL is unavailable, report the layout as staged or installed, not visually verified.

This process applies to arbitrary graphs. New homes may use generated lane defaults; an existing user's layout is never silently overwritten by sync.

## Installed ZIP paths

The ZIP bundles this skill and its reusable dependencies under the installed `blender_tixl_bridge` folder. In a checkout, run commands from the repository root. In an installed ZIP, use the add-on folder as the root and replace the checkout `blender_tixl_bridge/source/` prefix with `source/`. Offline audio helpers require NumPy in the Python interpreter used to run them. Example sound assets and scene generators remain workspace examples; they are not required by the generic workflow.

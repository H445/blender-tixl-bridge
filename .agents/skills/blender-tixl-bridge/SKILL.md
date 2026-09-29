---
name: blender-tixl-bridge
description: Operate, inspect, validate, edit, and troubleshoot the Blender-to-TiXL bridge using Blender MCP and TiXL's local debug protocol. Use for add-on configuration, scene preflight, sync, generated graphs, rendering, timing, mesh or texture edits, screenshots, and bridge diagnostics.
---

# Blender–TiXL bridge task router

Follow [repository rules](../../../AGENTS.md). Read [generated capability summary](../../CAPABILITIES.md) for component coverage, availability and warnings. Investigate any **unclassified** method before use; load [detailed inventory](../../CAPABILITIES_DETAIL.md) when tool schemas/contracts are needed. Never manufacture evidence or infer a method's safety from its name.

Load only the reference required for the current task; follow conditional links when that subtask arises:

| Task | Required reading |
| --- | --- |
| New user installation / namespace choices | [Onboarding](../../README.md), then sync verification below |
| Saved-source sync / output verification | [Sync](references/sync.md) |
| Offline cache build / deferred install | [Offline sync](../blender-tixl-offline-sync/SKILL.md) |
| Add-on configuration / precise scene recipes | [Blender](references/blender.md) |
| TiXL graph edits | [Edit](references/edit.md) and [operator semantics](references/operators.md) |
| Repeatable live or staged Home edits | [Graph edit](../blender-tixl-graph-edit/SKILL.md) |
| TiXL graph readability or dynamic graph layout | [Graph layout](references/graph-layout.md), then [Sync](references/sync.md) for restart and output checks |
| Offline staged graph arrangement | [Graph layout skill](../blender-tixl-graph-layout/SKILL.md) |
| Native timeline audio and beat-linked visuals | [Audio skill](../blender-tixl-audio/SKILL.md) |
| Stale/blank output | [Troubleshooting](references/troubleshoot.md) |
| Bounded snapshots, log follow, or opt-in output capture | [Diagnostics](references/diagnostics.md) |
| Capability refresh failure / transport setup | [Discovery](references/discovery.md) |
| Unfamiliar debug command / exact parameters | [Protocol](references/protocol.md) and detailed inventory |
| Component upgrade / release evidence | [Release refresh](../blender-tixl-release-refresh/SKILL.md) |
| Implementation/documentation disagreement | [Source map](references/sources.md); implementation is authoritative |

The official Blender MCP TCP extension owns Blender actions. If no named Blender tool is exposed, connect directly to the configured TCP endpoint with the repository's `BlenderTcpExtensionClient`; check the endpoint before treating MCP as unavailable. The TiXL debug client owns editor actions. Terminal/filesystem tools handle builds, logs and artifact inspection. After a mutation, read state back through the same API and inspect the affected output. Restore diagnostic state. Keep user-authored Home graphs and TimeClips separate from replaceable imports. Neither a successful request nor a non-empty screenshot proves a correct render.

Launch or restart TiXL only through the configured bridge with full process permissions. On this host, invoke the bridge launcher with `sandbox_permissions="require_escalated"`; the restricted process environment can leave a headless TiXL process and show a `0xe0434352` application error before port 9042 opens. Read the configured Editor directory from Blender add-on preferences through MCP, pass it as `TIXL_BRIDGE_EDITOR` to `blend_sync.start_editor(debug=True)`, then require a successful `getVersion` on port 9042. Do not launch the editor from a default-sandbox command. Use the debug protocol for shutdown when a clean session is confirmed.

For a configured TiXL installation, follow the automatic clean-session close and restart rule in `AGENTS.md` before a sync that changes saved graph paths. Do not request a routine manual close; the first-run username/root namespace remains a user choice.

Keep graph backups outside every live TiXL `Symbols` directory. TiXL scans `.t3` files there; a backup with the same symbol ID can load as a duplicate and break graph resolution. After moving a duplicate out of `Symbols`, restart through the debug bridge before judging the loaded graph.

Onboarding and release instructions are conditional; routine work does not require rereading either. Protocol/operator inventories are references, not startup reading.

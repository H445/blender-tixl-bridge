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
| Add-on configuration / precise scene recipes | [Blender](references/blender.md) |
| TiXL graph edits | [Edit](references/edit.md) and [operator semantics](references/operators.md) |
| Stale/blank output | [Troubleshooting](references/troubleshoot.md) |
| Bounded snapshots, log follow, or opt-in output capture | [Diagnostics](references/diagnostics.md) |
| Capability refresh failure / transport setup | [Discovery](references/discovery.md) |
| Unfamiliar debug command / exact parameters | [Protocol](references/protocol.md) and detailed inventory |
| Component upgrade / release evidence | [Release refresh](../blender-tixl-release-refresh/SKILL.md) |
| Implementation/documentation disagreement | [Source map](references/sources.md); implementation is authoritative |

Blender MCP owns Blender actions; the TiXL debug client owns editor actions. Terminal/filesystem tools handle builds, logs and artifact inspection. After a mutation, read state back through the same API and inspect the affected output. Restore diagnostic state. Keep user-authored Home graphs and TimeClips separate from replaceable imports. Neither a successful request nor a non-empty screenshot proves a correct render.

Onboarding and release instructions are conditional; routine work does not require rereading either. Protocol/operator inventories are references, not startup reading.

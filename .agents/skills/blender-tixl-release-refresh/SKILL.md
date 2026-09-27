---
name: blender-tixl-release-refresh
description: Refresh the Blender–TiXL bridge release evidence after Blender, Blender MCP, TiXL, the TiXL debug bridge, or the bridge add-on is upgraded. Use for capability regeneration, current UI and graph screenshots, README accuracy review, add-on ZIP rebuilding, and post-upgrade validation.
---

# Blender–TiXL release refresh router

Apply this skill after upgrading Blender, Blender MCP, TiXL, the debug bridge or this add-on. Follow [repository rules](../../../AGENTS.md), the [operational router](../blender-tixl-bridge/SKILL.md), and [capability summary](../../CAPABILITIES.md), then load the [release procedure](references/refresh.md). Read onboarding only for new-user setup or changed first-run behavior.

Preserve the user's Blender scene and TiXL project, graph view, time, playback, selection and output pin. Use the bundled example for evidence. All Blender actions/screenshots use MCP and Blender-native operators; all TiXL actions/screenshots use the debug client. Unsupported view arrangements require a manual user step, never UI automation.

The procedure covers exact versions, forced one-shot capability refresh, unclassified capability review, legible screenshots, affected documentation, tests, ZIP contents and requested release tags. Inspect every image. Keep root README short; update focused documents for procedural/technical changes. Commit, tag, publish or push only when requested.

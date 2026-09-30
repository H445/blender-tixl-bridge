---
name: blender-tixl-graph-edit
description: Make repeatable TiXL Home graph, TimeClip, mesh, image, timing, or output edits while preserving user-authored work. Use for live debug edits or staged offline .t3/.t3ui changes; use the graph-layout and audio skills for those specialized tasks.
---

# Edit a TiXL graph

Read [repository rules](../../../AGENTS.md), [capability summary](../../CAPABILITIES.md), and the [bridge router](../blender-tixl-bridge/SKILL.md). Check that the needed debug method or bridge operator is available before using it; inspect [detailed capabilities](../../CAPABILITIES_DETAIL.md) for exact schemas and investigate unclassified methods. The capability report is evidence, not an edit instruction. Do not manufacture its inputs.

## Choose the edit surface

- **Live agent edit:** follow the [debug edit procedure](../blender-tixl-bridge/references/edit.md). Capture context, graph state, view, time and pinned output; mutate one logical unit by stable IDs; read back topology and render; undo a failed edit; restore diagnostic state. The debug protocol has no general save command, so coordinate persistence with the user.
- **Offline staged edit:** read the saved `.t3` and `.t3ui` as data, preserve originals outside every live `Symbols` tree, and write candidates outside `Symbols`. Validate child IDs, edge endpoints, input types, TimeClips, graph and UI IDs, and user-owned routes before replacing saved files. Do not modify generated import data to express user effects. A human can make and save the edit in TiXL directly when the debug bridge is unavailable; agents do not automate TiXL's UI.

Use [operator semantics](../blender-tixl-bridge/references/operators.md) for source/global/per-world timing, named mesh selection, mesh and four-map texture replacement, preloading, output, and native audio. Keep select/replace primitive indices matched. Preserve existing Home graph values and TimeClips during a Blender resync; add or remove world branches deliberately.

For an HDR glow and grade pass, confirm the imported render target uses a floating-point format, then put thresholded Bloom before tone mapping so emissive values above display white can form a halo. Place a restrained ColorGrade after tone mapping, and compare dark hull detail, background, HUD and highlights at multiple timeline points. Keyframe Blender material emission through Blender MCP when the glow belongs to moving geometry; verify the exported material channel samples, not just Blender's shader UI. Drive TiXL glow strength from mapped clip time and, when music exists, add a small pulse from the same project BPM or event schedule. Test on-beat and off-beat frames, breakup suppression, warp peaks and the exact loop seam. Stage structural Home edits outside `Symbols` and restart after installation.

## Publish and verify

Compare the candidate with the original: planned topology and inputs change, unrelated children, connections, TimeClips and positions remain. Install only while TiXL is closed and editor work is saved. A structural `.t3`/`.t3ui` disk change requires a TiXL restart; `reload` may keep the old graph. For a configured agent session use the debug bridge to shut down a known-clean editor and the configured full-permission bridge launcher to reopen it. In offline/manual mode, the person saves and closes TiXL and reopens the project. Check graph resolution, representative rendered frames, and warning logs after restart. A file diff or successful debug response is not render proof.

For graph positions use [graph layout](../blender-tixl-graph-layout/SKILL.md); for timeline sound use [audio](../blender-tixl-audio/SKILL.md). Neither specialization should overwrite unrelated user edits.

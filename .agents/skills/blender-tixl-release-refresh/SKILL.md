---
name: blender-tixl-release-refresh
description: Refresh the Blender–TiXL bridge release evidence after Blender, Blender MCP, TiXL, the TiXL debug bridge, or the bridge add-on is upgraded. Use for capability regeneration, current UI and graph screenshots, README accuracy review, add-on ZIP rebuilding, and post-upgrade validation.
---

# Blender–TiXL release refresh

Use this workflow whenever a monitored component version changes. Read the operational bridge skill first and treat the live applications and generated capability report as the source of truth.

## Hard rules

- Never use Computer Use, screen automation, accessibility automation, simulated input, or coordinate clicking.
- Use Blender MCP for every Blender action and Blender-native screenshot operator.
- Use `blender_tixl_bridge/source/tixl_bridge.py` for every TiXL action and screenshot.
- If an application API cannot arrange a legible view, ask the end user to arrange it, then resume through the API. Do not substitute generic UI automation.
- Preserve the user's Blender scene, TiXL project, time, playback state, selection, and output pin. Use the bundled example for release evidence.
- Keep the root README brief and approachable. Move procedural, technical, troubleshooting, and agent-only detail to the appropriate linked document instead of expanding the landing page.
- Do not commit, tag, publish, or push unless the user explicitly asks.

## 1. Establish the version set

1. Read `blender_tixl_bridge/__init__.py`, `README.md`, `.agents/README.md`, `.agents/CAPABILITIES.md`, and the operational bridge skill.
2. Through Blender MCP, record Blender, Python, add-on, and Blender MCP versions and confirm the bridge add-on is enabled.
3. Through the TiXL debug bridge, call `getVersion`, `getContext`, and `getGraphState` on `BlendShapeExample`.
4. Reject unresolved graph children or connections. Record TiXL and protocol versions.

## 2. Rebuild discovered capabilities

Use the add-on's **Refresh agent capabilities** operator through Blender MCP. Wait for `.agents/capability_plugin.log` and `.agents/capability_automation.log` to report completion, then inspect `.agents/CAPABILITIES.md`.

Require complete coverage for the installed components. Review any new or unclassified Blender MCP tool, TiXL debug method, add-on operator/property, or reusable TiXL operator before documenting it. Never infer parameters or safety from a method name.

## 3. Capture stable release screenshots

Keep these filenames so documentation links remain stable:

| File | Required evidence |
| --- | --- |
| `docs/screenshots/blender-plugin.png` | Scene Properties → TiXL Bridge, including save sync, on-demand sync, and capability refresh. |
| `docs/screenshots/blender-preferences.png` | Enabled add-on entry, version, TiXL paths, connection/port, capability repository, and refresh control. |
| `docs/screenshots/tixl-graph.png` | Full `BlendShapeExample` home graph with four world branches and shared render chain. |
| `docs/screenshots/tixl-graph-detail.png` | One world branch showing animation, mesh select/replace, texture select/replace, and scene output. |

For Blender, set the relevant area and call Blender's native `screen.screenshot_area` through MCP. Redraw before capture. For Preferences, use `screen.userpref_show` and `preferences.addon_show` through MCP.

For TiXL, pause playback, open `BlendShapeExample`, pump three frames, frame stable child IDs from `getGraphState`, pump again, and call `screenshotWindow` with `region="graph"`. Restore the original time and playback speed afterward.

Visually inspect every image. Text and wires must be legible, the intended controls/nodes must be visible, no modal dialog may obscure the subject, and captions must describe what the image actually shows. Never accept file existence or dimensions as visual verification.

## 4. Audit documentation

Treat documentation as a small hierarchy rather than one exhaustive README:

- `README.md`: short human overview, main capabilities, minimal quick start, document links, and important limitations.
- `docs/USER_GUIDE.md`: first run, installation, configuration, daily use, modes, multi-world setup, updates, CLI use, and troubleshooting.
- `docs/BRIDGE_REFERENCE.md`: transferred data, generated/editable ownership, graph behavior, reusable operators, files, and technical limitations.
- `examples/README.md`: example-specific instructions and output evidence.
- `.agents/`: agent-only installation, operation, and capability details.

Review every claim affected by the new version across the appropriate files, including:

- supported and tested Blender/TiXL versions;
- install/update wording and first-run behavior;
- add-on control labels, paths, connection modes, ports, and automatic capability refresh;
- Blender MCP transport and advertised tools;
- TiXL debug methods and lifecycle cautions;
- reusable operator count, names, wiring, cache/project locations, and preservation behavior;
- screenshot captions and example links.

Do not move detail back into the root README merely because it changed. Update the focused document and keep a short link or summary in the landing page only when it helps a first-time reader understand the project.

## 5. Rebuild and verify

1. Run the repository tests appropriate to the change.
2. Run `python build_addon_zip.py` and confirm the archive includes both skills and the capability automation.
3. Validate this skill with the skill-creator `quick_validate.py` script.
4. Run `git diff --check`, inspect `git diff --stat`, and review the final README and binary screenshot diff list.
5. Report the exact versions, refreshed files, capability coverage, tests, and any limitation that still needs end-user action.

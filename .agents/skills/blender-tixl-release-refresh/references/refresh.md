# Release verification procedure

## 1. Establish the version set

1. Read `blender_tixl_bridge/__init__.py`, `README.md`, `.agents/CAPABILITIES.md`, and the operational router. Read onboarding only for a new user or changed first-run behavior.
2. Through Blender MCP, record Blender, Python, add-on, and Blender MCP versions and confirm the bridge add-on is enabled.
3. Through the TiXL debug bridge, call `getVersion`, `getContext`, and `getGraphState` on `BlendShapeExample`.
4. Reject unresolved graph children or connections. Record TiXL and protocol versions.

## 2. Rebuild discovered capabilities

Use the add-on's **Refresh agent capabilities** operator through Blender MCP. Wait for `.agents/capability_plugin.log` and `.agents/capability_automation.log` to report completion, then inspect `.agents/CAPABILITIES.md` and the detailed inventory when reviewing changed contracts.

Require complete coverage for the installed components. Review any new or unclassified Blender MCP tool, TiXL debug method, add-on operator/property, or reusable TiXL operator before documenting it. Never infer parameters or safety from a method name.

## 3. Capture stable release screenshots

Keep these filenames so documentation links remain stable:

| File | Required evidence |
| --- | --- |
| `docs/screenshots/blender-plugin.png` | Scene Properties → TiXL Bridge, including save sync, on-demand sync, and capability refresh. |
| `docs/screenshots/blender-preferences.png` | Enabled add-on entry, version, TiXL paths, connection/port, capability repository, and refresh control. |
| `docs/screenshots/tixl-graph.png` | Readable zoom on one world branch showing animation, mesh select/replace, and texture select/replace. Do not fit the entire graph when that makes labels illegible. |
| `docs/screenshots/tixl-graph-detail.png` | Wider context around the same branch, including its scene output and surrounding connections. |

For Blender, set the relevant area and call Blender's native `screen.screenshot_area` through MCP. Redraw before capture. For Preferences, use `screen.userpref_show` and `preferences.addon_show` through MCP.

For TiXL, pause playback, open `BlendShapeExample`, pump three frames, and frame stable child IDs from `getGraphState`. For the main graph image, select only the nodes needed to explain one branch; a tiny full-graph thumbnail is not acceptable. Pump again, call `screenshotWindow` with `region="graph"`, and restore the original graph view, time, playback speed, selection, and output pin afterward.

Visually inspect every image. Text and wires must be legible, the intended controls/nodes must be visible, no modal dialog may obscure the subject, and captions must describe what the image actually shows. Never accept file existence or dimensions as visual verification.

## 4. Audit documentation

Treat documentation as a small hierarchy rather than one exhaustive README:

- `README.md`: short human overview, main capabilities, minimal quick start, document links, and important limitations.
- `docs/USER_GUIDE.md`: first run, installation, configuration, daily use, modes, multi-world setup, updates, CLI use, and troubleshooting.
- `docs/AGENTIC_WORKFLOW.md`: human-facing comparison of plug-in-only and agentic-workspace use, including current benefits, setup, and boundaries.
- `docs/BRIDGE_REFERENCE.md`: transferred data, generated/editable ownership, graph behavior, reusable operators, files, and technical limitations.
- `examples/README.md`: example-specific instructions and output evidence.
- `.agents/`: agent-only installation, operation, and capability details.

Review every claim affected by the new version across the appropriate files, including:

- supported and tested Blender/TiXL versions;
- the distinction between optional plug-in-only use and agentic-workspace use, without implying that an agent is required;
- install/update wording and first-run behavior;
- add-on control labels, paths, connection modes, ports, and automatic capability refresh;
- Blender MCP transport and advertised tools;
- TiXL debug methods and lifecycle cautions;
- reusable operator count, names, wiring, cache/project locations, and preservation behavior;
- screenshot captions and example links.

Do not move detail back into the root README merely because it changed. Update the focused document and keep a short link or summary in the landing page only when it helps a first-time reader understand the project.

## 5. Rebuild and verify

1. Run the repository tests appropriate to the change.
2. Run `python build_addon_zip.py` and confirm it creates `blender-tixl-bridge-<bl_info version>.zip` containing repository rules, both skills and their task references, both generated capability files, and the capability automation.
3. Before a requested release, confirm the tag is exactly `v<bl_info version>`; the release workflow rejects a mismatched tag and uploads the versioned ZIP as a GitHub Release asset.
4. Validate this skill with the skill-creator `quick_validate.py` script.
5. Run `git diff --check`, inspect `git diff --stat`, and review the final README and binary screenshot diff list.
6. Report the exact versions, refreshed files, capability coverage, tests, and any limitation that still needs end-user action.

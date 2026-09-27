# Agentic workspace workflow

The bridge works without an AI agent. Install the Blender add-on, configure TiXL, and use Blender's sync controls for a conventional manual workflow.

The second option is to open this repository root as the workspace for Codex, Claude, or another compatible coding agent. In this mode, the repository is not only source code: it is the shared operating context connecting Blender, TiXL, generated caches, logs, tests, and the bridge's instructions.

## Why use the workspace

### One workflow across Blender and TiXL

An agent can inspect and edit the Blender scene through the official Blender MCP, start a bridge sync, follow its build, and inspect the resulting TiXL project through the debug bridge. The task stays connected from authored scene to rendered output instead of requiring the user to relay paths, node IDs, logs, or screenshots between applications.

### Faster iteration

The agent can move through the full loop—inspect, change, save, sync, evaluate, and compare—without repeatedly re-establishing context. This is especially useful for multi-world scenes, camera timing, mesh and texture processing, and render-graph work that crosses both applications.

### Better validation

The workspace gives the agent direct access to Blender state, generated manifests and caches, sync logs, TiXL graph structure, evaluated outputs, metrics, and API-produced screenshots. It can verify both graph wiring and rendered results, sample multiple times or scene cuts, and report the exact evidence behind a failure.

### More efficient troubleshooting

Scene configuration, exporter output, build errors, missing connections, stale graph structure, and render problems can be correlated in one place. The agent can distinguish a Blender source problem from a cache/build problem or a TiXL graph problem before recommending a fix.

### Safer ownership boundaries

The repository instructions teach agents that Blender owns source geometry and animation, generated imports are replaceable, and the TiXL home graph and TimeClips are user-owned. They also require Blender MCP and the TiXL debug bridge instead of screen automation, and require state to be read back after changes.

### Repeatable setup and upgrades

The workspace includes first-run guidance, installation scripts, tests, capability discovery, and release-refresh instructions. After Blender, Blender MCP, TiXL, or the bridge changes, an agent can rebuild the package, refresh the discovered capability map, update screenshots and documentation, and validate the supported workflow consistently.

### Shared guidance across agents

`AGENTS.md`, `.agents/README.md`, and the bundled skills describe the same operating contract for different compatible agents. Capability discovery records the locally installed Blender, Blender MCP, TiXL, debug protocol, and bridge versions, so agents work from observed tools rather than assuming a fixed environment.

## Recommended workspace setup

1. Complete the Blender, official Blender MCP, TiXL, namespace, operator-project, and .NET prerequisites in the [setup guide](USER_GUIDE.md).
2. Clone this repository and open its root—not a parent folder or only the add-on subfolder—as the agent workspace.
3. Connect the agent to the official Blender MCP extension.
4. For full TiXL inspection and control, run TiXL with its local debug server on the configured port. The add-on can still sync in Auto or Offline mode when live TiXL control is not needed.
5. Let the agent follow `AGENTS.md` and `.agents/README.md`; those files route it to the current capabilities and safe workflows.

## When each mode fits

Use the **plug-in-only workflow** when you mainly want to save Blender scenes and continue editing manually in TiXL.

Use the **agentic workspace workflow** for installation or upgrades, repeated cross-application changes, complex scene and graph work, automated validation, or troubleshooting that needs evidence from both Blender and TiXL.

The agentic workflow is optional. It does not replace either application, does not remove the need for the user's first-run choices, and must not use Computer Use or generic UI automation as a substitute for Blender MCP or the TiXL debug bridge.

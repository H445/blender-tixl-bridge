> [!WARNING]
> This is an early alpha project and is not ready for production use. Back up existing projects first.

# Blender–TiXL Bridge

Save a Blender scene and turn it into an editable TiXL project. Blender remains the source for geometry and animation; TiXL gets a graph where timing, meshes, textures, lighting, effects, and rendering can be changed without rebuilding the source scene by hand.

![Zoomed TiXL world branch showing Blender animation, mesh replacement, and texture editing](docs/screenshots/tixl-graph.png)

## Main features

- **Save-driven workflow:** sync automatically after a Blender save or run it on demand.
- **Release updates:** check published GitHub releases from the add-on, update on demand, or enable auto-update.
- **Scene transfer:** meshes, UV textures, supported PBR materials, transforms, visibility, shape keys, animated material values, lights, and cameras.
- **Native SDF shapes:** static Blender objects tagged as spheres, boxes, or tori become editable TiXL field and raymarch nodes.
- **Editable TiXL graph:** select an imported object by name, process its mesh and material textures, retime source clips, change lighting, and extend the render chain with native TiXL operators.
- **Multiple Blender worlds:** map collections and time ranges to switchable TiXL scene branches.
- **Safe regeneration:** generated imports are replaceable caches while the user-edited TiXL home graph and TimeClips are preserved.
- **Release and development modes:** build offline against a normal TiXL release or use the optional debug bridge for live reload, inspection, and screenshots.
- **Agent-ready tooling:** capabilities for Blender MCP and the TiXL debug bridge are discovered automatically after installs and upgrades.

## Two ways to use the project

1. **Blender plug-in only:** install the add-on, configure TiXL once, and sync scenes from Blender. This is the simplest option for routine manual work and requires no AI agent.
2. **Agentic workspace:** open this repository root in Codex, Claude, or another compatible coding agent. The agent can coordinate Blender MCP, the TiXL debug bridge, builds, caches, logs, graph inspection, and screenshots from one workspace. This reduces application switching and makes cross-application setup, editing, validation, and troubleshooting faster and more repeatable.

See [Agentic workspace workflow](docs/AGENTIC_WORKFLOW.md) for the advantages, boundaries, and recommended setup.

## Quick start on Windows

Before installing the bridge:

- Install Blender 4.3 or newer, complete its first launch, and install and enable the official Blender MCP extension.
- Install TiXL, complete its welcome and username/root-namespace setup, and create a dedicated TiXL C# operator project.
- Install the .NET SDK required by TiXL.

The current release is tested with Blender 5.2.2 LTS and TiXL 4.3.0.2.

1. Download `blender-tixl-bridge-<version>.zip` from the [latest GitHub release](https://github.com/H445/blender-tixl-bridge/releases/latest).
2. In Blender, install that ZIP from **Preferences → Add-ons → Install from Disk** and enable **Prismal Labs Blender → TiXL Bridge**.
3. In the add-on preferences, select the TiXL operator-project folder and the folder containing `TiXL.exe`. Leave the connection mode on **Auto** for normal use.
4. Open a saved `.blend` with an active camera, then use **Scene Properties → TiXL Bridge → Sync saved .blend to TiXL**.

![Blender TiXL Bridge panel with save sync, on-demand sync, and capability refresh controls](docs/screenshots/blender-plugin.png)

The first build creates a TiXL project beside the operator project. After that, normal use is simply: edit in Blender, save, and continue working in the generated TiXL graph.

## Documentation

- [Setup and usage guide](docs/USER_GUIDE.md) — first run, installation, connection modes, multi-world scenes, updates, and troubleshooting.
- [Agentic workspace workflow](docs/AGENTIC_WORKFLOW.md) — when to use the repository as an agent workspace and what it improves.
- [Bridge reference](docs/BRIDGE_REFERENCE.md) — transferred data, generated files, graph ownership, editable operator paths, and limitations.
- [Validation and benchmarks](docs/VALIDATION.md) — regression checks, phase measurements, and performance baselines.
- [BlendShapeExample](examples/README.md) — bundled scene and rendered results.
- [Agent installation and operation guide](.agents/README.md) — required workflow for Claude, Codex, and other AI agents.

The add-on currently targets Windows TiXL builds. Blender shaders and World nodes that glTF cannot represent, including arbitrary procedural materials and physical refraction, need TiXL-side equivalents.

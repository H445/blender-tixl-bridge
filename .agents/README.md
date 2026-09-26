# Blender–TiXL bridge onboarding for AI agents

This is the canonical, vendor-neutral setup guide for any AI agent helping an end user install and configure this bridge. Codex, Claude, Copilot, and other agents must follow the same workflow and completion criteria.

The bridge currently targets Windows. Blender is the authored source; TiXL projects, graphs, and cache files are generated from a saved `.blend`.

## Mandatory tool boundary

- Use Blender MCP for every Blender action, including launching or attaching, reading state, opening files, running Blender Python, installing or enabling add-ons, changing preferences, saving, syncing, and verification.
- Use `blender_tixl_bridge/source/tixl_bridge.py` and TiXL's local debug protocol for every TiXL action, including launch checks, project selection, graph inspection, evaluation, pinning, and screenshots.
- Never use Computer Use, screen automation, accessibility automation, simulated mouse/keyboard input, coordinate clicking, or screenshots as an input-control mechanism for Blender or TiXL.
- If Blender MCP is not installed, connected, or capable of a required bootstrap step, stop and ask the end user to perform that step manually. Do not fall back to UI automation.
- If the TiXL debug bridge is not available during first-run setup, guide the end user through the stated UI steps and wait for confirmation. Do not fall back to UI automation.
- Terminal and filesystem tools may be used for downloads, builds, file checks, logs, and documented command-line setup, but they are not substitutes for Blender MCP or the TiXL debug bridge when interacting with the running applications.

## Operational skill

Before operating, validating, editing, or troubleshooting a bridge project, read [`.agents/skills/blender-tixl-bridge/SKILL.md`](skills/blender-tixl-bridge/SKILL.md). It is the canonical capability reference for:

- Blender MCP discovery, Blender Python recipes, add-on configuration, scene preflight, sync, and Blender-side verification.
- Every supported TiXL debug-protocol command, including inspection, graph navigation and editing, evaluation, screenshots, logs, metrics, and lifecycle cautions.
- The eleven reusable TiXL bridge operators and the correct node patterns for timing, geometry, textures, lighting, camera, preloading, and output.
- End-to-end playbooks for syncing, validating, modifying, and diagnosing a generated project.

Tool names exposed by a particular Blender MCP server may vary. Use the MCP server's advertised tools and map them to the capabilities in the skill. Never invent an unavailable tool or replace it with Computer Use.

Capability discovery is automated without an AI agent. The Blender add-on starts `.agents/capability_automation.py` when the add-on is installed or updated, when it registers after Blender starts, and before a bridge sync. The add-on also exposes **Refresh agent capabilities** for an explicit manual run. Each trigger launches one fingerprinted refresh; it installs no scheduled task, watcher, or background service. The refresh rewrites `.agents/CAPABILITIES.md` only when Blender, Blender MCP, TiXL, the TiXL debug bridge, or this bridge changes.

## Agent contract

1. Guide the end user through downloading and first-launch setup. Do not assume that an installed executable means first-run configuration is complete.
2. Use only official download sources. Explain what will be downloaded, where it will be installed or extracted, and obtain any approval required by the active environment before downloading or installing software.
3. Never invent the user's TiXL username/root namespace. Ask the user to choose it before completing TiXL's first-run prompt. This value becomes part of every project namespace and is costly to change later.
4. Do not dismiss first-run dialogs blindly. Ask about meaningful preferences; otherwise state that application defaults will be kept.
5. Before closing Blender or TiXL, ask the user to save any unrelated work. Never force-close an editor that might contain unsaved work.
6. Prefer a dedicated, TiXL-created operator project for this bridge. Do not use TiXL's built-in `examples` project for a normal end-user installation.
7. Keep `Auto` as the normal end-user connection mode. Use `Debug bridge` only when TiXL is intentionally launched with `--debug-server 9042`.
8. A successful command is not sufficient verification. Complete the first sync, inspect the generated graph, and check the rendered output.
9. Never use Computer Use or another GUI automation fallback. Use Blender MCP, the TiXL debug bridge, or an explicit end-user handoff.

## Official downloads

- Blender 4.3 or newer: <https://www.blender.org/download/>
- TiXL releases: <https://github.com/tixl3d/tixl/releases>
- TiXL source: <https://github.com/tixl3d/tixl>
- .NET SDK: <https://dotnet.microsoft.com/download/dotnet/10.0>
- Blender–TiXL bridge: <https://github.com/H445/blender-tixl-bridge>

Prefer Blender's Windows installer or portable ZIP when command-line bootstrap is required. The Microsoft Store build works in the UI, but Windows may deny direct execution of its `WindowsApps` executable. Do not weaken `WindowsApps` permissions or use Computer Use to work around that restriction. Connect through Blender MCP, or ask the end user to complete the UI-only bootstrap step.

## Choices to collect from the end user

Ask for these before changing application state:

- Install locations, unless the user accepts the installers' defaults.
- Blender first-run preferences if they do not want the defaults: language, keymap, mouse selection, spacebar action, and theme.
- A TiXL username/root namespace. Recommend a short stable C# identifier such as `JaneDoe` or `StudioNorth`: no spaces or special characters, and preferably PascalCase.
- The parent directory in which TiXL user projects should be stored.
- Whether the setup is a normal release workflow (`Auto`) or a TiXL development workflow (`Debug bridge`, port 9042).

Record the resolved Blender executable, TiXL editor directory, TiXL operator-project directory, connection mode, and port in the final handoff.

## 1. Install and run Blender once

1. Have the user download Blender 4.3 or newer from the official Blender site.
2. Install it, or extract the portable ZIP to a stable user-writable directory.
3. Ask the end user to launch Blender normally before connecting Blender MCP.
4. Ask the end user to apply the requested language/keymap/input/theme choices on the first-run splash. If they have no preference, tell them to keep Blender's defaults and continue. The agent must not operate this dialog through Computer Use.
5. Confirm that the main Blender window opens and note the actual executable path.
6. Close this first-run Blender session before using `install_blender_addon.py`. Ask the user to save first if they did any work.

Do not assume a Store package's displayed install path is directly executable by scripts. Test the executable with `--version` when command-line installation is planned.

## 2. Install TiXL and complete its first run

### Release build

1. Have the user download a Windows release from the official TiXL GitHub releases page.
2. Extract it to a stable user-writable folder; do not run it from inside the downloaded archive or a temporary directory.
3. Locate the folder that directly contains `TiXL.exe`. This is the **TiXL Editor folder** used by the Blender add-on.

### Source/development build

1. Have the user clone or download the official TiXL repository.
2. Install the .NET SDK required by TiXL's `global.json` (currently .NET 10 for this checkout).
3. Verify the SDK with `dotnet --info`.
4. Build the solution in Rider/Visual Studio, or build the editor from the TiXL repository root:

   ```powershell
   dotnet build Editor\Editor.csproj -c Debug --nologo
   ```

5. The normal Debug editor directory is `Editor\bin\Debug\net10.0-windows` and must contain `TiXL.exe`.
6. On the first launch, TiXL may compile operator packages. Warnings about missing `.temp\bin\Debug\...\OperatorPackage.json` files are transient only while compilation is still running. Wait for completion. If they persist, rebuild the TiXL solution in Rider/Visual Studio, restart TiXL, and verify that the package JSON files now exist.

### Required first-run UI

1. Ask the end user to launch TiXL normally. The debug bridge is not assumed to be available before first-run setup.
2. Let TiXL initialize its settings and operator packages.
3. Review and close the **Welcome to TiXL** window. TiXL deliberately waits until this window is closed before showing the username prompt.
4. In **Edit username**, enter the exact username/root namespace chosen by the end user. TiXL describes this as a nickname used to group projects into a namespace. It must be short and contain no spaces or special characters.
5. If the prompt was previously completed, verify or change the value under **Settings → Projects → UserName**. Do not change an established username without explaining that existing project namespaces will not be renamed automatically.
6. Under **Settings → Projects → Project Directories**, confirm the parent directory for user projects. Changes to this list require an editor restart.

TiXL constructs a new project's full namespace as:

```text
<UserName>.<OptionalNamespace>.<ProjectName>
```

The `UserName` is the first-run value. The optional Namespace field is an additional grouping entered in the New Project dialog; it is not a replacement for the root username.

## 3. Create a dedicated TiXL operator project

Create this project through TiXL so its `.csproj`, home GUID, package ID, namespace, and release metadata are valid.

1. Use **File → New Project…** or the create-project button in the Project Hub.
2. Use a clear name such as `BlenderBridge`. Project names must be valid C# identifiers, must start with a capital letter, and must not contain dots, spaces, or special characters.
3. Leave the optional Namespace field blank unless the user wants another grouping layer.
4. Leave **Share Resources** enabled unless the user has a specific reason to disable it.
5. Create the project and wait for its initial compile to finish.
6. Locate the created directory. It must contain both `<ProjectName>.csproj` and `Symbols\`.
7. Record that directory as the **TiXL operator project**. Generated per-`.blend` projects will be created beside it.

Do not manufacture a project by copying only a `.csproj`. The bridge can clone a valid TiXL-created scaffold for generated projects, but the initial scaffold must come from TiXL.

## 4. Install the Blender add-on

### Universal UI method

From this repository, first build the ZIP if necessary:

```powershell
python build_addon_zip.py
```

Then ask the end user to perform these steps in Blender if Blender MCP is not yet connected:

1. Open **Edit → Preferences**.
2. Open **Add-ons**. In Blender versions that use **Get Extensions**, use its **Install from Disk** command.
3. Select `blender_tixl_bridge.zip`.
4. Enable **Prismal Labs Blender → TiXL Bridge**.
5. Remove or disable the legacy `tixl_blender_bridge` add-on if present.

### Checkout/headless method

When Blender MCP is connected and supports Blender Python execution, use it to run the repository installer inside Blender. If MCP is not connected yet, ask the end user to close Blender and run this command themselves:

```powershell
& "<path-to-blender.exe>" --background --python install_blender_addon.py -- `
  --operator-project "<path-to-TiXL-project>" `
  --editor-dir "<folder-containing-TiXL.exe>" `
  --connection-mode AUTO
```

The installer copies and hashes every add-on file, enables the add-on, saves preferences, and preserves existing bridge preferences on later updates. Restart any Blender window that was open during an installation. An agent must not use Computer Use to perform or verify this installation.

## 5. Configure the add-on

In the add-on preferences, set:

- **TiXL operator project**: the dedicated TiXL-created project directory containing its `.csproj` and `Symbols\`.
- **TiXL Editor folder**: the directory directly containing `TiXL.exe`.
- **TiXL connection**: `Auto` for normal users. `Offline` is valid for release builds without the debug protocol. `Debug bridge` is for deliberate development sessions.
- **Debug port**: `9042`, unless the user has chosen another free local port.

For Debug mode, launch TiXL with:

```powershell
& "<TiXL Editor folder>\TiXL.exe" --debug-server 9042
```

The server binds locally. Verify it with `getVersion` through `blender_tixl_bridge/source/tixl_bridge.py` before relying on live reload.

## 5a. Verify automatic capability discovery

The checkout installer records this repository in the add-on's **Agent capability repository** preference and queues a forced refresh. Confirm that `.agents/capability_plugin.log` and `.agents/capability_automation.log` show a completed run and that `.agents/CAPABILITIES.md` reflects the installed versions.

No AI-generated probe file is required. The refresh process:

- fingerprints the Blender executable or Windows Store package;
- starts the configured/discovered Blender MCP server and calls MCP `initialize` and `tools/list` directly;
- runs the read-only Blender probe through an advertised Blender Python tool when Blender is connected;
- fingerprints `TiXL.exe`, parses the matching `DebugServer.cs`, and calls the running TiXL debug protocol when available;
- fingerprints `blender_tixl_bridge/source/tixl_bridge.py` and the TiXL server implementation;
- preserves the last successful live inventory when an application is temporarily closed.

If Blender MCP is not found in a supported user MCP configuration, copy `.agents/capability_automation.example.json` to the ignored local file `.agents/capability_automation.json` and set `blenderMcp.command` to the installed server command. Do this once during setup; later updates are detected automatically from the MCP server version, command fingerprint, and tool schemas.

Review newly discovered or unclassified capabilities before using them. Never infer safety or parameters from a method name alone. The user can force an immediate non-AI refresh with the add-on's **Refresh agent capabilities** button or:

```powershell
python .agents/capability_automation.py once --force
```

## 6. Perform the first sync with the end user

1. Ask the user to save any open TiXL work. Pause TiXL playback before publishing changed cache files.
2. Open a saved `.blend` that has an active camera. The bundled `examples\BlendShapeExample.blend` is the preferred smoke test.
3. In **Scene Properties → TiXL Bridge**, click **Sync saved .blend to TiXL**. Enable **Sync after save** only if the user wants continuing automatic syncs.
4. Follow `<blend folder>\.tixl_cache\<blend name>\sync_logs\latest.log` until the background job finishes.
5. Confirm that `.tixl_cache\<blend name>\tixl_project.json` identifies the generated TiXL project.
6. In Debug mode the bridge should open the generated project. In Offline mode, select the generated project once in TiXL.
7. The first sync may take longer because it installs the shared bridge operators and builds both the operator project and generated scene project.

If TiXL closes cleanly during the first install and the sync reports a subsequent `Stop-Process` failure, do not discard a validated Blender cache. Leave TiXL closed and rerun the sync/install step; the bridge can resume from the cache without re-exporting the `.blend`.

## 7. Required verification

Do not declare success until all of the following pass:

- The source `.blend` remains the authored file and is openable in Blender.
- The cache manifest contains every expected Blender world, animation file, GLB, and camera rail.
- The generated TiXL project builds successfully and its home graph opens.
- The graph has no unresolved children or unresolved connections.
- Source clips feed the global and per-world clip sequences; each world clip sequence feeds its **Blender World Clip Time**, which feeds its **Blender Animation Scene**.
- Mesh-select/replace and texture-select/replace nodes are connected for each world.
- **Preload all Blender worlds**, camera, lights, world selection, render targets, and tone mapping are present.
- The **Output target** render target is pinned.
- Evaluate at one or more meaningful times and capture both a graph screenshot and rendered-output screenshot.
- Visually inspect the output; a successful build with a blank or stale render is not success.
- Check TiXL's error log and the bridge's `latest.log`.

Use Blender MCP exclusively for Blender-side inspection and actions. Use the TiXL debug bridge exclusively for `getContext`, `getGraphState`, `setTime`, `pumpFrames`, `pin`, `screenshot`, and `screenshotWindow`. Never use Computer Use. If either application API cannot perform a required action, stop and ask the end user to perform it manually.

After changing a loaded `.t3` or `.t3ui` structure on disk, save editor work and restart TiXL with `--debug-server 9042`; `reload` can leave the old graph instance in memory.

## Completion report

Tell the end user:

- The Blender version and executable used.
- The TiXL version and editor directory used.
- Their confirmed TiXL username/root namespace.
- The dedicated operator-project path.
- The connection mode and debug port.
- The generated project and cache paths for the smoke test.
- Whether graph validation, rendered-output validation, and error-log checks passed.
- Any warnings that remain and whether they are actionable.

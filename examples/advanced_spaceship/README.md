# Asterion Breakaway demo

A 60-second Blender-to-TiXL stress scene: a modular spacecraft breaks into individually animated projectile parts, then reassembles as three distinct configurations. The builder creates 600+ scene objects across the craft, variants, space environment, cameras, and lights. Its build summary prints the exact counts for the current run.

## GPT Images 2.5 texture assets

Five generated images are supplied in `textures/`. Their prompt themes are:

| File | Prompt theme |
| --- | --- |
| `armor_graphite.png` | Graphite ceramic spacecraft armor with fine machined surface detail |
| `heat_titanium.png` | Heat-scarred copper titanium alloy for exposed structural parts |
| `solar_ceramic.png` | Blue-black photovoltaic ceramic cells with silver traces |
| `moon_albedo.png` | Gray cratered moon regolith with varied impact detail |
| `space_nebula.png` | Deep space nebula panorama with distant luminous dust |

The builder also references optional normal and ORM maps. When those files are absent, the corresponding material uses its available PBR fallback channels.

The generation prompts and texture hashes are recorded in [textures/GENERATION.md](textures/GENERATION.md).

## Build in Blender

Run `../build_advanced_space_demo.py` through the official Blender MCP TCP extension, normally at `localhost:9876`, using its `execute_blender_code` request to execute the saved script. Do not launch Blender from the command line or use UI automation. The script saves `../AsterionBreakaway.blend` and prints `ASTERION_BUILT` with the object and texture counts.

## Timeline

The scene is 60 seconds at 60 fps. Camera markers and keyed object transforms stage the sequence:

| Time | Configuration or action |
| --- | --- |
| 0–9 s | COMBAT strike craft |
| 9–21 s | Projectile breakup and EXPLORER assembly |
| 21–30 s | EXPLORER survey array |
| 30–42 s | Projectile breakup and HAULER assembly |
| 42–51 s | HAULER cargo configuration |
| 51–60 s | Return to COMBAT and final assembly |

The different hull layouts and variant modules are real mesh objects with transform and visibility animation, so the transition exercises many independent animation records.

## TiXL sync and verification

With the saved scene open through Blender MCP TCP, sync it using the bridge workflow and the configured TiXL operator project. In TiXL, inspect the generated world graph and texture routes, then evaluate and capture renders at the COMBAT, breakup, EXPLORER, HAULER, and final assembly markers. Confirm the rendered output as well as graph connections.

The reference run synced successfully to TiXL 4.3.0.2. Its generated cache contains 642 exported mesh objects and 492 animated records, including 392 animated detachable craft parts. The seven camera cuts and 60-second range transferred. The generated graph had 29 children and 52 connections, with no missing child or connection references. The first full sync took about 59 seconds and published about 139 MB of generated cache data. TiXL rendered all three configurations, both breakup sequences, reassembly, and the final combat ship; see the [TiXL combat](previews/tixl_combat.png), [explorer](previews/tixl_explorer.png), [hauler](previews/tixl_hauler.png), and [graph overview](previews/tixl_graph_overview.png). The matching [Blender combat](previews/combat_blender.png), [explorer](previews/explorer_blender.png), and [hauler](previews/hauler_blender.png) previews are also included.

The bounded live playback sample in [playback_metrics.json](playback_metrics.json) advanced the editor clock roughly three seconds in each assembled configuration. TiXL reported 59.6–60.6 FPS, 225–239 MB managed memory, and about 151 MB GPU memory across those samples. Its output-evaluation counters did not advance during this sample, so these values do not establish continuous scene-rendering performance. The captured output at seven timeline checkpoints verifies the scene content and transitions separately.

## Current limitations

- The Blender World shader is not transferred as a TiXL environment. The scene uses generated space geometry and emissive materials for its background.
- Blender area lights are represented as TiXL point lights by the bridge; area-light softness and shape do not carry over.
- Only the five listed GPT-generated images are included. Optional normal and ORM maps are not present unless added separately.
- The bridge's editor FPS counter does not isolate scene evaluation or GPU rendering cost. Use captured output and workload-specific profiling when measuring sustained playback on other hardware.

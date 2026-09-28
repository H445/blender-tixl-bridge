# Asterion Breakaway demo

A 60-second Blender-to-TiXL stress scene: one persistent set of 492 spacecraft meshes breaks into individually animated projectile parts and rebuilds as three distinct configurations. Every part is visible and reused in COMBAT, EXPLORER, and HAULER; no role modules are swapped in or hidden. The builder creates 600+ scene objects including the space environment, cameras, and lights.

## Materials and texture assets

Six GPT-generated source images and ten aligned technical maps are supplied in `textures/`. The five surface families each have albedo, tangent normal, and packed occlusion/roughness/metallic maps. The space panorama is an emission texture.

| File | Prompt theme |
| --- | --- |
| `armor_graphite.png` | Graphite ceramic spacecraft armor with fine machined surface detail |
| `carbon_albedo.png` | Soot-dark woven carbon ceramic for recesses and structural gaps |
| `heat_titanium.png` | Heat-scarred copper titanium alloy for exposed structural parts |
| `solar_ceramic.png` | Blue-black photovoltaic ceramic cells with silver traces |
| `moon_albedo.png` | Gray cratered moon regolith with varied impact detail |
| `space_nebula.png` | Deep space nebula panorama with distant luminous dust |

The builder requires every map and packs it into the blend. The Blender glTF export includes base color, normal, metallic/roughness, and occlusion links for the five textured surface families. Uniform cockpit glazing and small light emitters use direct PBR values. The source prompts, map derivation method, and file hashes are recorded in [textures/GENERATION.md](textures/GENERATION.md).

## Build in Blender

Run `../build_advanced_space_demo.py` through the official Blender MCP TCP extension, normally at `localhost:9876`, using its `execute_blender_code` request to execute the saved script. Do not launch Blender from the command line or use UI automation. The script saves `../AsterionBreakaway.blend` and prints `ASTERION_BUILT` with the object and texture counts.

## Timeline

The scene is 60 seconds at 60 fps. Camera markers select seven moving dolly and orbit shots while keyed object transforms stage the sequence:

| Time | Configuration or action |
| --- | --- |
| 0–9 s | COMBAT strike craft |
| 9–21 s | Projectile breakup and EXPLORER assembly |
| 21–30 s | EXPLORER survey array |
| 30–42 s | Projectile breakup and HAULER assembly |
| 42–51 s | HAULER cargo configuration |
| 51–60 s | Return to COMBAT and final assembly |

The same hull, survey, and cargo meshes form all three ships. Each module has combat, explorer, hauler, and projectile poses, so the transition exercises hundreds of independent transform records without adding or removing craft parts. All 492 craft meshes have distinct manufactured profiles and individually offset texture wear. The hull and engine pieces have recessed service trenches; cargo pods have four roof machinery patterns. `../validate_advanced_space_demo.py`, run through Blender MCP TCP, checks the persistent pool, its visibility at representative frames, distinct mesh profiles, packed maps, and movement within every camera shot.

## TiXL sync and verification

With the saved scene open through Blender MCP TCP, sync it using the bridge workflow and the configured TiXL operator project. In TiXL, inspect the generated world graph and texture routes, then evaluate and capture renders at the COMBAT, breakup, EXPLORER, HAULER, and final assembly markers. Confirm the rendered output as well as graph connections.

The current reference run synced successfully to TiXL 4.3.0.2. Its generated cache contains 642 exported mesh objects and 492 animated reusable craft parts, with no visibility-switch channels. The seven moving camera shots and 60-second range transferred. The generated graph had 29 children and 52 connections, with no missing child or connection references. The full sync took about 58 seconds and published about 179 MB of generated cache data. TiXL rendered all three configurations, both breakup sequences, reassembly, and the final combat ship; see the [TiXL combat](previews/tixl_combat.png), [explorer](previews/tixl_explorer.png), [hauler](previews/tixl_hauler.png), and [graph overview](previews/tixl_graph_overview.png). Compare the [explorer camera move](previews/tixl_explorer_move.png) and [hauler camera move](previews/tixl_hauler_move.png) with their earlier frames. Matching [Blender combat](previews/combat_blender.png), [explorer](previews/explorer_blender.png), [hauler](previews/hauler_blender.png), and [cargo roof detail](previews/detail_hauler_blender.png) renders are included.

The bounded live playback sample in [playback_metrics.json](playback_metrics.json) advanced the editor clock roughly three seconds in each assembled configuration. TiXL reported 58.9–60.2 FPS, 327–341 MB managed memory, and 247–323 MB GPU memory across those samples. Its output-evaluation counters did not advance during this sample, so these values do not establish continuous scene-rendering performance. The captured output at ten timeline checkpoints verifies the scene content and camera views separately.

## Current limitations

- The Blender World shader is not transferred as a TiXL environment. The scene uses generated space geometry and emissive materials for its background.
- Blender area lights are represented as TiXL point lights by the bridge; area-light softness and shape do not carry over.
- The tangent normal and ORM maps are mathematically derived from the GPT-generated albedos, not measured scans. Their surface response is approximate.
- The bridge's editor FPS counter does not isolate scene evaluation or GPU rendering cost. Use captured output and workload-specific profiling when measuring sustained playback on other hardware.

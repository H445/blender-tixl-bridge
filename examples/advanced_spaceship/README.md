# Asterion Breakaway demo

A 108-second Blender-to-TiXL stress scene: one persistent set of 500 spacecraft meshes breaks into individually animated projectile parts and rebuilds as three distinct configurations. Every part is visible and reused in COMBAT, EXPLORER, and HAULER; no role modules are swapped in or hidden. One camera follows the action in an uninterrupted orbital take.

## Materials and texture assets

Five GPT-generated surface images and ten aligned technical maps are supplied in `textures/`. The five surface families each have albedo, tangent normal, and packed occlusion/roughness/metallic maps. The background uses NASA/Goddard's 16,384 × 8,192 equirectangular star map as an emission texture, replacing the 1,774 × 887 generated panorama.

| File | Prompt theme |
| --- | --- |
| `armor_graphite.png` | Graphite ceramic spacecraft armor with fine machined surface detail |
| `carbon_albedo.png` | Soot-dark woven carbon ceramic for recesses and structural gaps |
| `heat_titanium.png` | Heat-scarred copper titanium alloy for exposed structural parts |
| `solar_ceramic.png` | Blue-black photovoltaic ceramic cells with silver traces |
| `moon_albedo.png` | Gray cratered moon regolith with varied impact detail |
| `nasa_starmap_16k.jpg` | NASA/Goddard Deep Star Maps spherical star panorama |

The builder requires every map and packs it into the blend. The Blender glTF export includes base color, normal, metallic/roughness, and occlusion links for the five textured surface families. Uniform cockpit glazing and small light emitters use direct PBR values. The surface prompts, map derivation method, NASA credit, usage terms, and file hashes are recorded in [textures/GENERATION.md](textures/GENERATION.md).

## Build in Blender

Run `../build_advanced_space_demo.py` through the official Blender MCP TCP extension, normally at `localhost:9876`, using its `execute_blender_code` request to execute the saved script. Do not launch Blender from the command line or use UI automation. The script saves `../AsterionBreakaway.blend` and prints `ASTERION_BUILT` with the object and texture counts.

## Timeline

The scene is 108 seconds at 60 fps. A single camera follows a continuous orbit with no camera markers or cuts. It makes one full rotation around each assembled ship. Five broad bounce and key lights keep the painted hull, machinery, and cargo details readable through the full orbit. At each breakaway, the parts snap outward, drift almost motionless while the camera circles the suspended debris, then accelerate into the next configuration. Brief blue-white point-light flashes emphasize the three explosions. Keyed object transforms stage the sequence:

| Time | Configuration or action |
| --- | --- |
| 0–24 s | COMBAT strike craft, complete orbit |
| 24–36 s | Projectile breakup and EXPLORER assembly |
| 36–60 s | EXPLORER survey array, complete orbit |
| 60–72 s | Projectile breakup and HAULER assembly |
| 72–96 s | HAULER cargo configuration, complete orbit |
| 96–108 s | Return to COMBAT and final assembly |

The same hull, survey, and cargo meshes form all three ships. Each module has combat, explorer, hauler, and projectile poses, so the transition exercises hundreds of independent transform records without adding or removing craft parts. All 500 craft meshes have distinct manufactured profiles and individually offset texture wear. The hull and engine pieces have recessed service trenches; cargo pods have four roof machinery patterns. Wing plates and guns now rotate as rigid assemblies around shared hinges. Survey panels sit on array trusses; cargo pods rest on a deck; small fittings are seated in the pressure shell. `../validate_advanced_space_demo.py`, run through Blender MCP TCP, checks the persistent pool, its visibility at representative frames, connected assemblies, distinct mesh profiles, packed maps, camera continuity, and the slowed debris intervals.

## Design references

The role silhouettes draw on [Starbound's official visual gallery](https://playstarbound.com/media/) and [No Man's Sky's fighter, explorer, and hauler component system](https://www.nomanssky.com/orbital-update/). The structural pass takes its mounting logic from [NASA's integrated truss](https://www.nasa.gov/international-space-station/integrated-truss-structure/) and [ESA's spacecraft boom and solar-array examples](https://www.esa.int/TEC/Structures/SEMWAE7DWZE_1.html). These are visual and engineering references; the meshes are original procedural assets.

## TiXL sync and verification

With the saved scene open through Blender MCP TCP, sync it using the bridge workflow and the configured TiXL operator project. In TiXL, inspect the generated world graph and texture routes, then evaluate and capture renders at the COMBAT, breakup, EXPLORER, HAULER, and final assembly markers. Confirm the rendered output as well as graph connections. Existing TiXL projects can retain their editable 60-second TimeClips across syncs. After closing TiXL through its debug bridge, run `../retime_advanced_space_demo_clips.py` on that project's `Symbols/AsterionBreakaway.t3` and restart TiXL through the bridge. The retimer changes only the seven known source clips and refuses to overwrite unexpected timing.

The current reference run synced successfully to TiXL 4.3.0.2. Its generated cache contains 500 animated reusable craft parts, with no visibility-switch channels. The single 108-second camera rail has 6,480 samples; its largest adjacent-frame move is 0.248 m and its largest forward-direction turn is 0.0061 rad. The editable home graph has 35 children and 64 connections, with no missing child or connection references. The 16K panorama remains embedded in the glTF scene. The generated cache contains about 294 MB of data. TiXL renders show each ship at the start and opposite side of its complete orbit: [combat](previews/tixl_combat.png) / [opposite](previews/tixl_combat_opposite.png), [explorer](previews/tixl_explorer.png) / [opposite](previews/tixl_explorer_opposite.png), and [hauler](previews/tixl_hauler.png) / [opposite](previews/tixl_hauler_opposite.png) / [orbit end](previews/tixl_hauler_end.png). The [first snap](previews/tixl_bullet_snap.png), [first suspended drift](previews/tixl_bullet_drift.png), [second suspended drift](previews/tixl_bullet_hauler.png), [return drift](previews/tixl_bullet_return.png), and [final combat](previews/tixl_final.png) verify the full 108-second sequence. Matching Blender views show the [combat](previews/combat_blender.png), [explorer](previews/explorer_blender.png), [hauler](previews/hauler_blender.png), and their [opposite](previews/combat_opposite_blender.png), [opposite](previews/explorer_opposite_blender.png), and [opposite](previews/hauler_opposite_blender.png) sides.

The earlier bounded playback sample in [playback_metrics.json](playback_metrics.json) predates this camera revision. The current output captures above verify the new camera views and breakup staging. TiXL's output-evaluation counters do not establish continuous scene-rendering performance; use workload-specific profiling for that question.

## Selected moon effects in TiXL

The editable graph's **Blender object: moon** node has a searchable dropdown of the connected Blender scene's imported mesh objects. Its earlier `moon` search value still resolves to `Tethys analogue | cratered moon.001` in **SelectedObject**; the primitive index is only an internal wire. **Moon | AnimValue mesh amount** drives **DisplaceMeshNoise.Amount** from the mapped world time. A second **AnimValue** drives the moon's **Pixelate** block size through **FloatToInt**, creating changing texture glitches. The moon is in view around 84 seconds, while the opening shot shows only the ship. Compare the [original TiXL frame](previews/tixl_planet_before.png) with the [glitch at 84 seconds](previews/tixl_planet_after.png) and [glitch at 85 seconds](previews/tixl_planet_glitch_next.png). At 85 seconds the ship correctly occludes the moon. The reproducible graph migration is in [`../configure_asterion_planet_effects.py`](../configure_asterion_planet_effects.py); it refuses unexpected user-edited routes or object selections.

## Current limitations

- The Blender World shader is not transferred as a TiXL environment. The scene uses generated space geometry and emissive materials for its background.
- Blender area lights are represented as TiXL point lights by the bridge; area-light softness and shape do not carry over.
- The tangent normal and ORM maps are mathematically derived from the GPT-generated albedos, not measured scans. Their surface response is approximate.
- The bridge's editor FPS counter does not isolate scene evaluation or GPU rendering cost. Use captured output and workload-specific profiling when measuring sustained playback on other hardware.

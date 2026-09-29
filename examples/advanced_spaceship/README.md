# Asterion Breakaway demo

A 108-second Blender-to-TiXL looping rescue scene: a combat craft slaloms through asteroid fields on its way to the psychedelic Tethys moon, rebuilds as an explorer and hauler, warps to a distant copper storm giant, dodges ring debris, then returns through a final jump to its opening pose. One persistent set of 500 spacecraft meshes breaks into individually animated parts and rebuilds as three distinct configurations. Every part is visible and reused in COMBAT, EXPLORER, and HAULER. One camera follows the journey in a continuous take.

The [audio package](audio/README.md) supplies a 120 BPM cinematic score, an independent EDM/IDM pulse and arpeggio stem, chopped break drums, and separate propulsion, lunar scanning, and cargo effects. Eight editable native TiXL AudioClips route through a shared AudioBus with clip and master levels.

## Materials and texture assets

Five GPT-generated surface images and ten aligned technical maps are supplied in `textures/`. The copper giant adds three deterministic procedural maps made by `generate_ember_planet_maps.py`. All six surface families have albedo, tangent normal, and packed occlusion/roughness/metallic maps. The background uses NASA/Goddard's 16,384 × 8,192 equirectangular star map as an emission texture, replacing the 1,774 × 887 generated panorama.

| File | Prompt theme |
| --- | --- |
| `armor_graphite.png` | Graphite ceramic spacecraft armor with fine machined surface detail |
| `carbon_albedo.png` | Soot-dark woven carbon ceramic for recesses and structural gaps |
| `heat_titanium.png` | Heat-scarred copper titanium alloy for exposed structural parts |
| `solar_ceramic.png` | Blue-black photovoltaic ceramic cells with silver traces |
| `moon_albedo.png` | Gray cratered moon regolith with varied impact detail |
| `ember_albedo.png` | Copper cloud bands and two turbulent storm systems |
| `nasa_starmap_16k.jpg` | NASA/Goddard Deep Star Maps spherical star panorama |

The builder requires every map and packs it into the blend. The Blender glTF export includes base color, normal, metallic/roughness, and occlusion links for all six textured surface families. Uniform cockpit glazing and small light emitters use direct PBR values. The surface prompts, map derivation method, NASA credit, usage terms, and file hashes are recorded in [textures/GENERATION.md](textures/GENERATION.md).

## Build in Blender

Run `../build_advanced_space_demo.py` through the official Blender MCP TCP extension, normally at `localhost:9876`, using its `execute_blender_code` request to execute the saved script. Do not launch Blender from the command line or use UI automation. The script saves `../AsterionBreakaway.blend` and prints `ASTERION_BUILT` with the object and texture counts.

## Timeline

The scene is 108 seconds at 60 fps. The craft flies on one continuous route while all 500 pieces retain their local breakup choreography. Its key and bounce lights travel with it. The opening pursuit covers over 110 metres; the first and second warp jumps span about 125 and 370 metres. The hull makes a complete orbit around Tethys and another around the copper giant before the return warp. Three 16-rock fields and five lanes of 1,150 fine dust grains establish parallax while the pilot steers around the center rocks and completes three longitudinal rolls. Both planets remain tens of metres from the ship even at the closest story beats. A single camera makes at least one full rotation around each assembled ship, moves inward for the survey, and pulls closer on the warp passages without cuts. At each breakaway, the parts snap outward, drift almost motionless while the camera circles the suspended debris, then accelerate into the next configuration.

| Time | Configuration or action |
| --- | --- |
| 0–11 s | COMBAT craft accelerates through the first asteroid field and rolls clear |
| 11–16 s | First warp jump toward Tethys |
| 16–24 s | Begin the continuous Tethys orbit; dodge the lunar field and roll |
| 24–36 s | Evasive breakup and EXPLORER assembly |
| 36–60 s | EXPLORER scans the core near the moon |
| 60–72 s | Breakup and HAULER cargo rebuild |
| 72–84 s | Recover the luminous core into a cargo pod and complete the Tethys orbit |
| 84–90 s | Escape warp arcs clear of the copper giant's surface |
| 90–104 s | Complete a fast orbit of the ringed copper giant; COMBAT rebuilds, dodges debris, and rolls |
| 104–108 s | Return warp to the opening position and camera pose |

The same hull, survey, and cargo meshes form all three ships. Each module has combat, explorer, hauler, and projectile poses, so the transition exercises hundreds of independent transform records without adding or removing craft parts. The faceted cockpit has a sloped windshield, metal lower skirt, fitted shoulder rails, and instrument lights. It stays seated on the common pressure hull in every configuration. The hauler's twelve cargo pods form two spaced side banks on broad deck plates, leaving the flight deck and central corridor visible. Its reused survey spar becomes an attached underdeck keel and aft docking fitting. The hauler camera keeps the moon beside the ship during recovery instead of visually overlapping the hull. During all three breakups, every reusable piece also gets its own seeded XYZ rotation noise, with smooth fade-in and fade-out so the rebuilt ships settle into their exact poses. Larger parts tumble less than small fittings; the slowed debris intervals retain gentle angular drift. The reusable `../apply_breakaway_rotation_noise.py` recipe accepts any animated mesh collection and breakup frame windows. `../add_asterion_story.py` adds the mission flight, camera, 48 textured asteroids, space dust, scan beam, retrieved core, two planets, and warp trails without replacing any craft pieces. `../add_asterion_hud.py` adds camera-mounted mesh typography for ten trip chapters, a route progress bar, and changing moon-core status. All three scripts are rerunnable through Blender MCP. `../validate_advanced_space_demo.py` checks reuse, packed maps, full ship orbits around both planets, camera orbits around all three roles, cockpit fit, cargo spacing and support, camera continuity, forward travel, warp distances, rolls, asteroid clearance, planet standoff, HUD states, the project seam, and the slowed debris intervals.

## Design references

The role silhouettes draw on [Starbound's official visual gallery](https://playstarbound.com/media/) and [No Man's Sky's fighter, explorer, and hauler component system](https://www.nomanssky.com/orbital-update/). The structural pass takes its mounting logic from [NASA's integrated truss](https://www.nasa.gov/international-space-station/integrated-truss-structure/) and [ESA's spacecraft boom and solar-array examples](https://www.esa.int/TEC/Structures/SEMWAE7DWZE_1.html). These are visual and engineering references; the meshes are original procedural assets.

## TiXL sync and verification

With the saved scene open through Blender MCP TCP, sync it using the bridge workflow and the configured TiXL operator project. In TiXL, inspect the generated world graph and texture routes, then evaluate and capture renders at the COMBAT, breakup, EXPLORER, HAULER, and final assembly markers. Confirm the rendered output as well as graph connections. Existing TiXL projects can retain their editable 60-second TimeClips across syncs. After closing TiXL through its debug bridge, run `../retime_advanced_space_demo_clips.py` on that project's `Symbols/AsterionBreakaway.t3` and restart TiXL through the bridge. The retimer changes only the seven known source clips and refuses to overwrite unexpected timing.

The current reference run synced successfully to TiXL 4.3.0.2. Its generated cache contains 500 animated reusable craft parts. The single 108-second camera rail has 6,480 samples. The validated camera orbit covers more than 360° for each assembled role. The editable home graph has 119 children and 206 connections, with no missing child or connection references. Both clip lanes have a 108-second loop duration; TiXL renders at 0, 108, and 216 seconds were pixel identical. The 16K panorama remains embedded in the glTF scene. Current TiXL renders show [restored lunar color](previews/story_lunar_color_restored.png), [copper giant with native surface and ring dust](previews/story_ember_dust.png), [arrival warp](previews/story_arrival_warp.png), and [escape warp](previews/story_escape_warp.png).

The current output captures verify the camera views and effect variation. `../tune_asterion_story_fx.py` adds mission-paced Bloom and intermittent signal glitches. `../tune_asterion_loop.py` restores the moon's precise selector, wraps both clip lanes, and resets the moon feedback at each project seam. `../add_asterion_planet_dust.py` adds TiXL point clouds on the storm giant's atmosphere and rings with small randomized motes rotating over the loop. These scripts back up the saved home graph outside `Symbols` before modifying it. TiXL's output-evaluation counters do not establish continuous scene-rendering performance; use workload-specific profiling for that question.

## Selected moon effects in TiXL

The editable graph's **Blender object: moon** node has a searchable dropdown of the connected Blender scene's imported mesh objects. **Moon | AnimValue mesh amount** drives **DisplaceMeshNoise.Amount** from mapped world time. Further branches animate its albedo through fluid feedback and pixel fracture. The moon now enters the story during the approach and survey. The separate post-effect signal gate gives those shots different levels of corruption while leaving calmer shots clean. The reproducible moon graph migration is in [`../configure_asterion_planet_effects.py`](../configure_asterion_planet_effects.py); it refuses unexpected user-edited routes or object selections.

## Current limitations

- The Blender World shader is not transferred as a TiXL environment. The scene uses generated space geometry and emissive materials for its background.
- Blender area lights are represented as TiXL point lights by the bridge; area-light softness and shape do not carry over.
- The tangent normal and ORM maps are mathematically derived from the GPT-generated albedos, not measured scans. Their surface response is approximate.
- The bridge's editor FPS counter does not isolate scene evaluation or GPU rendering cost. Use captured output and workload-specific profiling when measuring sustained playback on other hardware.

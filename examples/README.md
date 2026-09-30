# Examples

- [Asterion Breakaway](advanced_spaceship/README.md) — 108-second looping spacecraft journey with distinct combat, explorer, and hauler builds, two planetary locations, and TiXL effects.
- [BlendShapeExample](#blendshapeexample) — 16-second four-shape morph demo.

The Asterion home can be refined with `refine_asterion_visuals.py` after TiXL has been closed through the debug bridge. It preserves native AudioClip timelines, reduces full-frame tearing, and adds sparse ASCII accents plus a native turbulent torus SDF signal. The script backs up the original home graph outside `Symbols` before installation. `install_asterion_techno_refresh.py` then replaces the old score clip with seeded techno drums and continuously animates that SDF.

`anchor_asterion_sdf.py` moves that signal onto the named copper giant: its texture drives the selected surface color and mesh relief, while a bright world-space contour uses the main camera and depth buffer. This example uses the static giant's exported position and scale; re-derive these values if its Blender transform changes. Stage the Home graph and UI outside `Symbols`, arrange the staged UI with `tools/layout_tixl_graph.py`, then install with `--apply` while the saved editor is closed. It preserves audio clips, TimeClips, and other object effects, and refuses to replace an already installed branch.

```powershell
python examples/anchor_asterion_sdf.py --output examples/.tixl_cache/AsterionBreakaway/sdf_planet/AsterionBreakaway.t3 --ui-output examples/.tixl_cache/AsterionBreakaway/sdf_planet/AsterionBreakaway.t3ui
python tools/layout_tixl_graph.py --graph examples/.tixl_cache/AsterionBreakaway/sdf_planet/AsterionBreakaway.t3 --ui examples/.tixl_cache/AsterionBreakaway/sdf_planet/AsterionBreakaway.t3ui --output examples/.tixl_cache/AsterionBreakaway/sdf_planet/AsterionBreakaway.layout.t3ui
python examples/anchor_asterion_sdf.py --output examples/.tixl_cache/AsterionBreakaway/sdf_planet/AsterionBreakaway.t3 --ui-output examples/.tixl_cache/AsterionBreakaway/sdf_planet/AsterionBreakaway.layout.t3ui --apply
```

After that pass, `animate_asterion_sdf_rings.py` replaces the world contour with three braided, opening SDF orbits. Hide `EMBER | broken dust rings` in Blender's render and sync before installation; the story generator also hides this legacy mesh. The native CustomSDF field varies its shape per chapter and pulses gently at 120 BPM, with an exact 108-second loop. The script places only its new controls near their consumer, preserving the saved layout and checking wire crossings.

```powershell
python examples/animate_asterion_sdf_rings.py --output examples/.tixl_cache/AsterionBreakaway/sdf_rings/AsterionBreakaway.t3 --ui-output examples/.tixl_cache/AsterionBreakaway/sdf_rings/AsterionBreakaway.t3ui
python examples/animate_asterion_sdf_rings.py --output examples/.tixl_cache/AsterionBreakaway/sdf_rings/AsterionBreakaway.t3 --ui-output examples/.tixl_cache/AsterionBreakaway/sdf_rings/AsterionBreakaway.t3ui --apply
```

`fractalize_asterion_sdf.py` adds three levels of recursive Menger cavities to the copper ribbons and creates a larger moon corona with four interlocking fractal orbits, fourteen Menger knots, moving magenta/cyan cells, and beat-linked surges. The shared field functions live in `advanced_spaceship/fractal_orbits.hlsl` and run through native CustomSDF operators. The two anchors use their Blender-exported static positions; update them if the source objects move. The staged edit retains existing node positions, audio clips, surface effects, and the 108-second loop. Render checks at 28, 54, and 104 seconds cover the new geometry.

```powershell
python examples/fractalize_asterion_sdf.py --output examples/.tixl_cache/AsterionBreakaway/sdf_fractal/AsterionBreakaway.t3 --ui-output examples/.tixl_cache/AsterionBreakaway/sdf_fractal/AsterionBreakaway.t3ui
python examples/fractalize_asterion_sdf.py --output examples/.tixl_cache/AsterionBreakaway/sdf_fractal/AsterionBreakaway.t3 --ui-output examples/.tixl_cache/AsterionBreakaway/sdf_fractal/AsterionBreakaway.t3ui --apply
```

## BlendShapeExample

Open `BlendShapeExample.blend` in Blender and run **Scene Properties → TiXL Bridge →
Sync saved .blend to TiXL** after configuring the add-on. Use the generated
**BlendShapeExample** TiXL project at its default **120 BPM**. Loop bars **0–8**
(seconds **0–16**). The saved scene's `tixl_project_name` property supplies the
project name on the first sync.

## Screenshots

These screenshots show BlendShapeExample rendered in TiXL after syncing its Blender source. Four scenes morph in sequence—cube → sphere → triangular prism → cylinder → cube—over a 16-second loop at 120 BPM. All four meshes are centered at `(0, 0, 0)`.

| Cube · 0 seconds | Sphere · 4 seconds |
| --- | --- |
| ![Blue cube rendered in TiXL](screenshots/cube.png) | ![Blue sphere rendered in TiXL](screenshots/sphere.png) |
| **Triangular prism · 8 seconds** | **Cylinder · 12 seconds** |
| ![Blue triangular prism rendered in TiXL](screenshots/prism.png) | ![Blue cylinder rendered in TiXL](screenshots/cylinder.png) |

The geometry changes continuously between scenes. At 3 seconds, the cube is midway through its morph into the sphere:

![Cube midway through its morph into a sphere in TiXL](screenshots/cube-to-sphere.png)

| Source time | World | Transition |
| --- | --- | --- |
| 0–4 s | Cube | Cube → sphere |
| 4–8 s | Sphere | Sphere → triangular prism |
| 8–12 s | Prism | Triangular prism → cylinder |
| 12–16 s | Cylinder | Cylinder → cube |

Each world holds its starting shape for four beats and morphs over the next
four beats. All mesh origins remain at `(0, 0, 0)`. The targets use identical
closed mesh topology, so the end of each morph matches the next world's mesh.
There is no audio dependency; timing is authored at 60 FPS, with 30 frames per
beat. The four collections become four TiXL worlds and four editable source clips.

The release ZIP includes this file and the `.blend` under
`blender_tixl_bridge/examples/`. From a checkout, rebuild the source with:

```powershell
& "<path-to-blender.exe>" --background --python examples/build_blend_shape_example.py
& "<path-to-blender.exe>" --background examples/BlendShapeExample.blend --python examples/validate_blend_shape_example.py
```

Generated `.tixl_cache` files and local TiXL projects are rebuilt by the bridge
and are not distributed. The builder resets only its current Blender session;
run it in a separate background process as shown above.

# Asterion sound design

Eight original stereo PCM stems span the 108-second loop at 44.1 kHz. The
project runs at 120 BPM (54 bars). Each stem is an editable native TiXL
`Lib.io.audio.AudioClip`: `AudioReference` → native `AudioBus` → `Execute`
alongside the final image command. The chopped break uses three TimeClips on
one lane; the other stems have separate visible lanes.

The shared harmony is Dm9 → B♭maj7 → Fadd9 → Cadd9, two bars per chord,
with the final two bars resolving to Dm9 before the loop.
`techno_pattern.py` provides the seeded audio and visual accent schedule;
`break_pattern.py` owns the chopped-break cuts and corresponding visual gates.
The 120 BPM accent times remain stable when the harmony changes.

| Stem | Timeline | Role |
| --- | --- | --- |
| `asterion_music_cinematic_120bpm.wav` | 0–108 s | Low ensemble, four-chord pulse, recurring rescue motif, and chapter arrivals. |
| `asterion_music_electronic_120bpm.wav` | 0–108 s | Harmonic analog bass, broken sequencer, and short stereo answers. |
| `asterion_music_techno_drums_120bpm.wav` | 0–108 s | Heavy kick, metallic snare, ghost hits, shuffled hats, and fills. |
| `asterion_amen_chops_120bpm.wav` | 10–24, 36–60, 72–104 s | Original synthesized break cut into reverses, repeats, and crushed slices. |
| `asterion_fx_flight.wav` | 0–108 s | Reactive engine, staged warp spool/blast/deceleration, dodges, and the retained expansion bass falls. |
| `asterion_fx_scan.wav` | 43–59 s | Spectral sensor bed, irregular D-minor data grains, and harmonic lock. |
| `asterion_fx_cargo.wav` | 72–84 s | Tractor field, accelerating servo packets, capture, and tonal resolution. |
| `asterion_fx_glitch.wav` | 0–108 s | Sparse bit-held transmission faults, ring-modulated packets, and cut-grid clicks. |

The arrangement has space for the first intercept, gains density through the
first warp, opens into half-time bass falls during each expansion, becomes
curious and sparse for the survey, tightens for cargo pickup, and reaches its
most intense groove in the Ember orbit before resolving at the loop seam.
The zero and 108-second sample endpoints are silent in every stem.

The current TiXL Home graph keeps Blender source clips on lane 0 and places
the eight audio stem groups on lanes 1–8. The chopped break uses three clips
on lane 4. `examples/rebalance_asterion_audio.py` stages or reapplies those
lanes, clears accidental music mutes, sets the clip and bus levels, and fits
the saved TiXL timeline and render export range to all 54 bars. Audit the
candidate with `tools/audit_tixl_audio.py --graph <staged.t3> --assets
<TiXL-project-Assets>`. The measured stereo sum peaks at about 0.705 with
no clipped samples at the current levels. The project has no unused WAVs;
all eight assets are referenced by its AudioClips.

Run `generate_asterion_audio.py --stem all` to reproduce the WAVs with NumPy.
Individual stems can be rendered with `--stem cinematic`, `electronic`,
`techno`, `flight`, `scan`, `cargo`, `glitch`, or `break`. The synthesized break
is original; no third-party sample or song recording is required.

For an existing Asterion TiXL Home graph, first confirm the live editor graph
matches its saved `.t3` and `.t3ui`, then close TiXL through the debug bridge.
Run `examples/refresh_asterion_sound_design.py --dry-run`, then run it without
`--dry-run` to refresh the project audio assets and add the cinematic and
glitch AudioClips. It retains the other clips, TimeClips, bus, visual graph,
and Blender imports. The graph backup stays outside the live `Symbols` tree.
Restart TiXL through the configured bridge with full process permissions and
check the AudioClip lanes, bus route, rendered output, and warning log.

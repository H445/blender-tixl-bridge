# Asterion audio

Six original stereo PCM files span the full 108-second project at 44.1 kHz.
Each native `Lib.io.audio.AudioClip` has its own visible, editable TiXL timeline
lane and feeds native `Lib.io.audio.AudioBus`. The bus command and final image
command meet at `Lib.flow.Execute` before the Output target. Electronic music,
techno drums, and flight span the composition; scan and cargo cover their cue windows, while three
chopped-break clips share one lane across the action chapters.
The music uses 120 BPM in 4/4: 54 bars, 216 beats, and 30 Blender frames per
beat. `techno_pattern.py` chooses different, repeatable events per bar. The
electronic stem plays D-minor sub bass, pitched stabs, and packet tones. The
drum stem has synthesized kicks, snares, ghost hits, hats, and fills. Their
seeded signal accents also animate TiXL's ASCII and SDF effects. Both music
stems remain editable native AudioClips, separate from the chopped break and
the flight, scan, and cargo sound effects.

| File | Cue window | Purpose |
| --- | --- | --- |
| `asterion_music_electronic_120bpm.wav` | 0–108 s | Seeded D-minor bass, stabs, and packet tones with quieter survey and breakaway passages. |
| `asterion_music_techno_drums_120bpm.wav` | 0–108 s | Seeded techno kicks, snares, hats, ghost hits, and short fills. |
| `asterion_fx_flight.wav` | 0–108 s | Propulsion bed, warp spools/blasts, breakup rumbles, and asteroid evasion. |
| `asterion_fx_scan.wav` | 43–59 s | Soft magnetic sweeps, subdued spatial pulses, and a scan lock. |
| `asterion_fx_cargo.wav` | 72–84 s | Tractor field, packet transfers, capture gate, and docking resolution. |
| `asterion_amen_chops_120bpm.wav` | 10–24, 36–60, 72–104 s | Newly synthesized funk break cut into sixteenth-note slices, with repeats, reverses, and bit reduction. Three native AudioClip blocks share one TiXL timeline lane. |

Run `generate_asterion_audio.py` to reproduce the WAVs with NumPy (`--stem scan`
renders only the survey cue). After TiXL has been saved and closed through the
bridge, run `examples/install_asterion_audio.py` to copy the five main
files into the project's `Assets/audio` and add the native clip/bus/execute
nodes. The installer backs up the Home graph and keeps existing visual nodes,
connections, and TimeClips.
TiXL's native TimeClips map timeline bars to file seconds. `Audio | mission
audio bus` owns the master fader. For a project with the earlier bridge-specific
audio operators, use `examples/upgrade_asterion_audio_timeline.py` with TiXL
closed through the bridge; it preserves other graph work and replaces only the
scan WAV.

Run `generate_asterion_audio.py --stem break` to regenerate the chopped break.
`break_pattern.py` owns the 120 BPM chop timestamps used by both the audio
renderer and `examples/install_asterion_break.py`. The latter adds three native
AudioClips to the existing bus and a matching keyframe curve to the video
glitch controls. Save and close TiXL through the bridge before running it.

Run `generate_asterion_audio.py --stem electronic` and `--stem techno` to
regenerate the music. For an existing Asterion Home that still contains the old
score clip, run `examples/install_asterion_techno_refresh.py` after closing TiXL
through the debug bridge. It removes that clip and asset, adds the techno drum
clip, installs the refreshed electronic WAV, and animates the native TiXL SDF.
The installer backs up only the Home graph files outside `Symbols`.

# Asterion audio

Four original stereo PCM files span the full 108-second project at 44.1 kHz.
Each native `Lib.io.audio.AudioClip` has its own visible, editable TiXL timeline
lane and feeds native `Lib.io.audio.AudioBus`. The bus command and final image
command meet at `Lib.flow.Execute` before the Output target. Score and flight span the
composition; scan and cargo lanes cover their cue windows.
The score uses 120 BPM in 4/4: 54 bars, 216 beats, and 30 Blender frames per
beat. It uses original organ-like harmonies, bowed textures, a five-note signal
figure, low pulses, and sparse percussion. The three effects clips remain
separate so the flight, survey, and recovery levels can be mixed independently.

| File | Cue window | Purpose |
| --- | --- | --- |
| `asterion_score_120bpm.wav` | 0–108 s | Original dramatic score; quiet survey and debris passages give way to warp and recovery swells. |
| `asterion_fx_flight.wav` | 0–108 s | Propulsion bed, warp spools/blasts, breakup rumbles, and asteroid evasion. |
| `asterion_fx_scan.wav` | 43–59 s | Soft magnetic sweeps, subdued spatial pulses, and a scan lock. |
| `asterion_fx_cargo.wav` | 72–84 s | Tractor field, packet transfers, capture gate, and docking resolution. |

Run `generate_asterion_audio.py` to reproduce the WAVs with NumPy (`--stem scan`
renders only the survey cue). After the
editor has been saved and closed through the bridge, run
`examples/install_asterion_audio.py` to copy the four files into the TiXL
project's `Assets/audio` and add the native clip/bus/execute nodes. The installer backs up the
Home graph and keeps all existing visual nodes, connections, and TimeClips.
TiXL's native TimeClips map timeline bars to file seconds. `Audio | mission
audio bus` owns the master fader. For a project with the earlier bridge-specific
audio operators, use `examples/upgrade_asterion_audio_timeline.py` with TiXL
closed through the bridge; it preserves other graph work and replaces only the
scan WAV.

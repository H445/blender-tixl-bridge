# Asterion audio

Four original stereo PCM clips span the full 108-second project at 44.1 kHz.
Every clip begins at project second zero, loops with the image, and is editable
as its own `BlenderAudioClip` feeding `BlenderAudioBus` in the TiXL Home graph.
The score uses 120 BPM in 4/4: 54 bars, 216 beats, and 30 Blender frames per
beat. It uses original organ-like harmonies, bowed textures, a five-note signal
figure, low pulses, and sparse percussion. The three effects clips remain
separate so the flight, survey, and recovery levels can be mixed independently.

| File | Cue window | Purpose |
| --- | --- | --- |
| `asterion_score_120bpm.wav` | 0–108 s | Original dramatic score; quiet survey and debris passages give way to warp and recovery swells. |
| `asterion_fx_flight.wav` | 0–108 s | Propulsion bed, warp spools/blasts, breakup rumbles, and asteroid evasion. |
| `asterion_fx_scan.wav` | 43–59 s | Port/starboard triangulation chirps, spectral sweeps, and scan lock. |
| `asterion_fx_cargo.wav` | 72–84 s | Tractor field, packet transfers, capture gate, and docking resolution. |

Run `generate_asterion_audio.py` to reproduce the WAVs with NumPy. After the
editor has been saved and closed through the bridge, run
`examples/install_asterion_audio.py` to copy the four files into the TiXL
project's `Assets/audio` and add the clip/bus nodes. The installer backs up the
Home graph and keeps all existing visual nodes, connections, and TimeClips.
TiXL uses the graph's `Audio | 120 BPM project time` operator to connect every
clip to the same playhead; `Audio | mission audio bus` owns the master fader.

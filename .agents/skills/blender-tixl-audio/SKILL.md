---
name: blender-tixl-audio
description: Build and revise synchronized TiXL audio with visible native AudioClip timeline lanes, an AudioBus, and Execute. Use for repeatable music, effects, beat-linked visuals, offline WAV preparation, and audio graph verification across Blender scenes.
---

# Audio and beat-linked visuals

Read [repository rules](../../../AGENTS.md), [capability summary](../../CAPABILITIES.md), and the [bridge router](../blender-tixl-bridge/SKILL.md). Consult [detailed capabilities](../../CAPABILITIES_DETAIL.md) for bridge operator coverage, [operator semantics](../blender-tixl-bridge/references/operators.md) for routing, and the installed TiXL project/native graph for exact native symbol IDs and ports before construction. Native TiXL `Lib.io.audio.AudioClip` and `Lib.io.audio.AudioBus` are the current timeline pattern; the bridge's `BlenderAudioClip` and `BlenderAudioBus` are legacy. If native operators are unavailable, stop that graph step rather than substituting a hidden sample player.

## Prepare offline assets

Choose tempo, key/harmonic plan, full loop duration, cue points, and stem roles for the scene. Derive music, effects, and visual accents from one time/event schedule. Seed random choices per bar or event so builds reproduce and the loop seam closes. Export separate, consistently formatted WAVs for music and effects; check channel count, sample rate, peak/clipping, silence/decay at boundaries, cue alignment and loop seam by listening and waveform inspection. Keep the source generator/assets and hashes so the sound design can be rebuilt without a live TiXL session or internet. [Asterion's generator and notes](../../../examples/advanced_spaceship/audio/README.md) are one example, not a required key, tempo, duration or clip inventory.

## Put sound on the TiXL timeline

Create one native `AudioClip` per independently editable lane or chop group, with a visible TimeClip. `TimeRange` uses TiXL bars; `SourceRange` uses seconds in the WAV. Compute bar positions from the actual project BPM and verify every clip's source bounds. Connect each clip's `AudioReference` to native `AudioBus.Input`, then route `AudioBus.Result` with the final image command through `Lib.flow.Execute` to the output target. Keep the bus in the evaluated render path. Preserve user-edited clip timing, volume, mute, and mix when updating files or adding lanes.

For a staged offline graph edit, use [graph-edit](../blender-tixl-graph-edit/SKILL.md): work from the saved project namespace/graph, validate IDs, connections and assets, back up outside `Symbols`, and install only with TiXL closed. Do not reuse Asterion's IDs or `:audio/` paths in another project. A human may make the same native connections in TiXL and save them manually. An agent uses only the TiXL debug bridge for live editor operations.

## Verify the result

Check that each WAV resolves, TimeClips appear at the intended bars, all clip outputs reach the bus, the bus reaches `Execute`, and the final image route remains connected. Listen across cues, offbeats, transitions, and the seam; compare rendered frames on and between shared accent events. After disk structural edits restart TiXL, then inspect the live graph, audio/output, and warning log. Offline preparation can prove file and graph consistency, but live sound/render verification remains pending until TiXL is reopened.

For stereo PCM16 projects, `python tools/audit_tixl_audio.py --graph "<Home.t3>"` reports lane collisions, mute state, clip/bus levels, peak and RMS by stem, six-second mix windows, and clipped sample count. Use `--assets "<project Assets>"` when auditing a staged graph outside the project. Measure the candidate mix before applying level changes; a low peak alone does not prove perceptual balance, so listen in TiXL afterward.

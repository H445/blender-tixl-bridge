"""Shared 120 BPM drum-chop schedule for the Asterion audio and TiXL video.

The source drum break is newly synthesized in generate_asterion_audio.py. These
slice choices, reverses and accents drive both its WAV and the visual curves.
"""

from __future__ import annotations

from dataclasses import dataclass


BPM = 120
SIXTEENTH = 60 / BPM / 4
ACTIVE_WINDOWS = ((10, 24), (36, 60), (72, 104))
PATTERNS = (
    (0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15),
    # Fifteen slices leave a deliberate sixteenth-note dropout before the next bar.
    (0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 12, 13, 12, 13, 15),
    (0, 1, 2, 3, 4, 5, 6, 7, 0, 1, 10, 11, 12, 13, 14, 15),
    (0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 12, 12, 15),
    (0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 12, 15),
)


@dataclass(frozen=True)
class Chop:
    time: float
    source_step: int
    gain: float
    reverse: bool
    crush: bool
    accent: float


def section_gain(time):
    if time < 24:
        return .64 if time < 16 else .77
    if time < 42:
        return .28
    if time < 60:
        return .46 if time < 54 else .58
    if time < 84:
        return .48
    return .86 if time < 98 else .96


def chops():
    result = []
    for start, end in ACTIVE_WINDOWS:
        for bar_start in range(start, end, 2):
            bar_index = bar_start // 2
            pattern = PATTERNS[(bar_index + bar_index // 4) % len(PATTERNS)]
            for step, source_step in enumerate(pattern):
                time = bar_start + step * SIXTEENTH
                gain = section_gain(time) * (1.08 if step in (0, 4, 8, 12) else .85)
                reverse = step in (11, 14) and bar_index % 3 == 1
                crush = (step in (13, 14, 15) and bar_index % 4 == 3)
                # Kick/snare transients and deliberately re-cut slices share
                # one visual accent grid; hats alone do not flash the image.
                strong = source_step in (0, 4, 7, 10, 12, 15)
                cut = source_step != step or reverse or crush
                accent = min(.88, section_gain(time) *
                             (.78 if strong else .46 if cut else 0))
                result.append(Chop(time, source_step, gain, reverse, crush,
                                   round(accent, 5)))
    return tuple(result)


def visual_keys(*, baseline=0.0, scale=1.0):
    keys = [(0.0, baseline)]
    for chop in chops():
        if chop.accent < .15:
            continue
        t = chop.time
        peak = baseline + scale * chop.accent
        keys.extend(((t-.018, baseline), (t, peak),
                     (t+.055, baseline+scale*chop.accent*.22),
                     (t+.105, baseline)))
    keys.append((108.0, baseline))
    return tuple(keys)

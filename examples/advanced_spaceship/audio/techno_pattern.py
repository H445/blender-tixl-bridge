"""Deterministic 120 BPM techno events shared by audio and TiXL visuals.

Random choices are seeded per bar. Rebuilding the project produces the same
loop, while adjacent bars have different kick, hat, bass, and signal patterns.
"""

from __future__ import annotations

import random
from dataclasses import dataclass


BPM = 120
STEP = 60 / BPM / 4
BARS = 54
LOOP_SECONDS = 108
SEED = 740142


@dataclass(frozen=True)
class Event:
    time: float
    kind: str
    gain: float
    pan: float = 0.0
    note: int = 0


def intensity(t: float) -> float:
    if t < 10:
        return .25
    if t < 24:
        return .83
    if t < 36:
        return .38
    if t < 60:
        return .53
    if t < 72:
        return .26
    if t < 84:
        return .72
    if t < 104:
        return .97
    return .28


def events() -> tuple[Event, ...]:
    result: list[Event] = []
    # Roots and melodic choices stay within D natural minor, matching the
    # scanner's D/F/G/E notes while leaving the percussion mostly unpitched.
    roots = (38, 36, 41, 33, 43, 40)
    degrees = (0, 3, 5, 7, 10, 12, 15, 17)
    for bar in range(BARS):
        start = 2.0 * bar
        level = intensity(start)
        rng = random.Random(SEED + bar * 1009)
        root = roots[bar % len(roots)]
        skip = {rng.randrange(1, 16)} if level >= .7 and bar % 4 == 3 else set()
        for step in range(16):
            if step in skip:
                continue
            t = start + step * STEP
            if step % 4 == 0 and (level >= .5 or step in (0, 8)):
                result.append(Event(t, "kick", level * rng.uniform(.82, 1.05)))
            elif level >= .5 and step in (2, 3, 5, 7, 9, 10, 14, 15) and rng.random() < .15 + .13*level:
                result.append(Event(t, "kick", level * rng.uniform(.27, .51)))
            if step in (4, 12) and level >= .38:
                result.append(Event(t, "snare", level * rng.uniform(.68, 1.05),
                                    -.1 if bar % 2 else .1))
            elif level >= .5 and step in (6, 14, 15) and rng.random() < .28:
                result.append(Event(t, "ghost", level * rng.uniform(.23, .43),
                                    rng.choice((-.35, .35))))
            if level >= .38 and (step % 2 == 0 or rng.random() < level * .29):
                result.append(Event(t, "hat", level * rng.uniform(.18, .48),
                                    rng.choice((-.55, .55))))
            if step in (0, 6, 10, 13) and rng.random() < .42 + .35 * level:
                result.append(Event(t, "bass", level * rng.uniform(.66, 1.1),
                                    rng.choice((-.2, .2)), root + rng.choice((0, 0, 7, 12))))
            if level >= .38 and rng.random() < (.13 if level < .7 else .27):
                note = root + 24 + rng.choice(degrees)
                result.append(Event(t, "stab", level * rng.uniform(.34, .9),
                                    rng.uniform(-.75, .75), note))
        # Rare, musically timed signal bursts and short fills give the image
        # edit points without putting a full-frame glitch on every beat.
        if level >= .38 and (bar % 2 == 1 or level >= .9):
            step = rng.choice((2, 7, 11, 14))
            result.append(Event(start + step * STEP, "signal",
                                level * rng.uniform(.48, .9),
                                rng.uniform(-.8, .8), root + 36))
        if level >= .7 and bar % 4 == 3:
            for step in (13, 14, 15):
                result.append(Event(start + step * STEP, "fill",
                                    level * rng.uniform(.32, .78),
                                    (-.7, 0, .7)[step - 13], root + 24 + degrees[(step + bar) % 8]))
    return tuple(sorted(result, key=lambda e: (e.time, e.kind)))


def signal_events() -> tuple[Event, ...]:
    return tuple(e for e in events() if e.kind in ("signal", "fill"))

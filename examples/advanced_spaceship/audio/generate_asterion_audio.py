"""Render Asterion's original 120 BPM, 108-second score and isolated effects.

Only NumPy and Python's standard library are required. Each WAV starts at
project second zero so TiXL clips can be moved, muted, or mixed independently.
"""

from __future__ import annotations

import math
import wave
from pathlib import Path

import numpy as np


SAMPLE_RATE = 44_100
DURATION = 108
BPM = 120
BEAT = 60 / BPM
COUNT = SAMPLE_RATE * DURATION
OUT = Path(__file__).resolve().parent
RNG = np.random.default_rng(14031984)


def seconds(length):
    return max(1, round(length * SAMPLE_RATE))


def smooth(x):
    x = np.clip(x, 0, 1)
    return x * x * (3 - 2 * x)


def envelope(length, attack=.02, release=.2):
    n = seconds(length)
    t = np.arange(n, dtype=np.float32) / SAMPLE_RATE
    return (smooth(t / max(attack, .001))
            * smooth((length - t) / max(release, .001))).astype(np.float32)


def place(track, start, signal, gain=1, pan=0):
    index = round(start * SAMPLE_RATE)
    if index >= COUNT or index + len(signal) <= 0:
        return
    first = max(0, -index)
    end = min(len(signal), COUNT - index)
    left = math.sqrt((1 - pan) / 2) * gain
    right = math.sqrt((1 + pan) / 2) * gain
    track[max(0, index):index + end, 0] += signal[first:end] * left
    track[max(0, index):index + end, 1] += signal[first:end] * right


def note(hz, length, color="organ"):
    n = seconds(length)
    t = np.arange(n, dtype=np.float32) / SAMPLE_RATE
    if color == "organ":
        phase = 2 * np.pi * hz * (t + .0009 * np.sin(2 * np.pi * .31 * t))
        sound = (.70 * np.sin(phase) + .22 * np.sin(2 * phase)
                 + .105 * np.sin(3 * phase) + .045 * np.sin(4 * phase))
        env = envelope(length, .32, .56)
    elif color == "strings":
        phase = 2 * np.pi * hz * t
        sound = sum(np.sin((k + 1) * phase + .08 * np.sin(2*np.pi*.23*t))
                    / (k + 1) ** 1.32 for k in range(7))
        env = envelope(length, .17, .45)
    elif color == "bell":
        phase = 2 * np.pi * hz * t
        sound = (np.sin(phase) + .28*np.sin(2.003*phase)
                 + .13*np.sin(3.98*phase) + .08*np.sin(6.02*phase))
        env = np.exp(-t * 3.5 / max(length, .25)) * envelope(length, .004, .09)
    elif color == "bass":
        phase = 2 * np.pi * hz * t
        sound = np.sin(phase) + .23*np.sin(2*phase) + .08*np.sin(3*phase)
        env = envelope(length, .009, .16)
    elif color == "brass":
        phase = 2 * np.pi * hz * t
        sound = sum(np.sin(k*phase) / k ** .9 for k in range(1, 7))
        env = envelope(length, .18, .46)
    else:
        raise ValueError(color)
    return (sound * env).astype(np.float32)


def frequency(midi):
    return 440 * 2 ** ((midi - 69) / 12)


def energy_at(t):
    if t < 11:
        return .42 + .22 * smooth((t - 2) / 9)
    if t < 16:
        return .85
    if t < 24:
        return .70
    if t < 36:
        return .35
    if t < 60:
        return .36 + .14 * smooth((t-43)/15)
    if t < 72:
        return .44 + .18*smooth((t-66)/6)
    if t < 84:
        return .62 + .20*smooth((t-73)/10)
    if t < 90:
        return .97
    if t < 104:
        return .80
    return .60 * (1-smooth((t-105)/3))


def room(track, amount=.15):
    # Diffuse stereo taps give the synthetic organ/strings a large hall tail.
    wet = track.copy()
    for delay, gain in ((.087, .17), (.169, .15), (.283, .13),
                        (.451, .10), (.707, .075), (1.061, .05)):
        shift = seconds(delay)
        wet[shift:, 0] += track[:-shift, 1] * gain
        wet[shift:, 1] += track[:-shift, 0] * gain
    track[:] = (1-amount)*track + amount*wet


def write(name, track, peak=.88):
    # Fade only the small seam region; the 108-second audio and image loop align.
    edge = seconds(.12)
    track[:edge] *= np.linspace(0, 1, edge, dtype=np.float32)[:, None]
    track[-edge:] *= np.linspace(1, 0, edge, dtype=np.float32)[:, None]
    amplitude = float(np.max(np.abs(track)))
    assert amplitude > .01, name
    track *= min(1, peak/amplitude)
    output = OUT / name
    with wave.open(str(output), "wb") as wav:
        wav.setnchannels(2)
        wav.setsampwidth(2)
        wav.setframerate(SAMPLE_RATE)
        wav.writeframes((np.clip(track, -1, 1)*32767).astype("<i2").tobytes())
    print(name, "seconds", DURATION, "peak", round(float(np.max(np.abs(track))), 3),
          "bytes", output.stat().st_size)


def score():
    out = np.zeros((COUNT, 2), np.float32)
    # A minor-centred six-bar harmonic circuit lands on A at the loop seam.
    chords = ((45, 52, 57, 60), (41, 48, 53, 57), (48, 55, 60, 64),
              (43, 50, 55, 59), (38, 45, 50, 53), (40, 47, 52, 56))
    motif = (69, 72, 76, 72, 67, 72, 76, 79, 81, 76, 72, 69,
             65, 69, 72, 69, 67, 71, 74, 71, 69, 64, 67, 71)
    for bar in range(54):
        start = 2*bar
        chord = chords[bar % len(chords)]
        level = energy_at(start)
        for voice, midi in enumerate(chord):
            place(out, start, note(frequency(midi), 2.4, "organ"),
                  .105*level, (-.60, -.18, .22, .58)[voice])
        # Low ostinato grows into large pulses on the warp and storm passages.
        for beat in range(4):
            t = start + beat*BEAT
            dynamic = energy_at(t)
            place(out, t, note(frequency(chord[0]-12), .42, "bass"),
                  .18*dynamic*(1.25 if beat == 0 else .67))
            if dynamic > .45:
                place(out, t+.25, note(frequency(chord[1]), .22, "strings"),
                      .045*dynamic, .35 if beat % 2 else -.35)
        if bar % 2 == 0 and 20 <= start < 104:
            for voice, midi in enumerate(chord[1:]):
                place(out, start+.08, note(frequency(midi+12), 3.75, "strings"),
                      .067*level, (-.6, .05, .6)[voice])
        # Four-note rising answer, restrained during the floating debris shots.
        if bar % 4 in (0, 2):
            for step in range(4):
                t = start + .25 + step*.375
                place(out, t, note(frequency(motif[(bar*2+step) % len(motif)]),
                                   1.02, "bell"), .10*energy_at(t),
                      -.42 + .28*step)
        if start in (12, 22, 72, 84, 90, 100):
            for j, midi in enumerate(chord[1:]):
                place(out, start, note(frequency(midi+12), 2.6, "brass"),
                      .085*level, (-.5, 0, .5)[j])

    # In the quiet survey, a distinctive delayed five-note signal motif.
    for t in np.arange(38, 59, 2):
        for j, midi in enumerate((81, 76, 72, 79, 76)):
            place(out, float(t+j*.25), note(frequency(midi), 1.1, "bell"),
                  .035, -.5+j*.25)

    # Cinematic low impacts and restrained IDM ticks; strictly beat aligned.
    for beat in range(216):
        t = beat*BEAT
        level = energy_at(t)
        if beat % 4 == 0 and level > .48:
            n = seconds(.48)
            x = np.arange(n, dtype=np.float32)/SAMPLE_RATE
            kick = np.sin(2*np.pi*(48*x + 33*.030*(1-np.exp(-x/.030))))
            place(out, t, kick*np.exp(-x*14), .17*level)
        if beat % 2 == 1 and level > .4:
            n = seconds(.10)
            hiss = RNG.standard_normal(n).astype(np.float32)
            hiss = np.diff(hiss, prepend=0)
            place(out, t, hiss*np.exp(-np.arange(n)/SAMPLE_RATE*42),
                  .008*level, .4 if beat%4 == 1 else -.4)
    room(out, .43)
    write("asterion_score_120bpm.wav", out)


def airy_noise(length, lower=65, upper=5000):
    n = seconds(length)
    raw = RNG.standard_normal(n).astype(np.float32)
    freqs = np.fft.rfftfreq(n, 1/SAMPLE_RATE)
    band = np.exp(-((freqs - lower)/max(upper-lower, 1))**2)
    band[freqs < lower] *= (freqs[freqs < lower]/max(lower, 1))**2
    signal = np.fft.irfft(np.fft.rfft(raw)*band, n=n).astype(np.float32)
    return signal/(np.max(np.abs(signal))+.001)


def sweep(length, low, high, noise=.0):
    n = seconds(length)
    t = np.arange(n, dtype=np.float32)/SAMPLE_RATE
    phase = 2*np.pi*(low*t + (high-low)*t*t/(2*length))
    tone = np.sin(phase) + .18*np.sin(2*phase)
    if noise:
        tone += noise*airy_noise(length, min(low,high), max(low,high)*3)
    return (tone*envelope(length, .06, .19)).astype(np.float32)


def flight_fx():
    out = np.zeros((COUNT, 2), np.float32)
    # Propulsion throbs with chapter velocity, while the warp engines bloom.
    noise = airy_noise(DURATION, 45, 2000)
    t = np.arange(COUNT, dtype=np.float32)/SAMPLE_RATE
    power = np.array([energy_at(float(x)) for x in np.arange(0, DURATION, .5)],
                     np.float32)
    envelope_speed = np.interp(t, np.arange(len(power))*.5, power).astype(np.float32)
    base = (.22*noise + .08*np.sin(2*np.pi*(56*t + .2*np.sin(2*np.pi*.7*t))))
    out[:, 0] = base*envelope_speed
    out[:, 1] = np.roll(base, 317)*envelope_speed
    for start, end in ((11, 16), (84, 90), (104, 108)):
        length = end-start
        n = seconds(length)
        u = np.linspace(0, 1, n, endpoint=False, dtype=np.float32)
        whoosh = airy_noise(length, 90, 7800)
        ramp = smooth(u/.42) * smooth((1-u)/.11)
        pulse = np.sin(2*np.pi*(70+170*u)*np.arange(n)/SAMPLE_RATE)
        place(out, start, (.55*whoosh+.19*pulse)*ramp, .67, -.17)
        place(out, end-.35, sweep(.7, 120, 28, .45), .30, .2)
    for start, end in ((24, 36), (60, 72), (97, 104)):
        place(out, start, sweep(end-start, 40, 16, .28), .24)
        place(out, end-.42, sweep(.7, 90, 370, .1), .16)
    for t0 in (7.3, 19.3, 95.2):
        place(out, t0-.4, sweep(1.2, 110, 470, .42), .19,
              -.5 if t0 < 30 else .5)
    room(out, .12)
    write("asterion_fx_flight.wav", out)


def scan_fx():
    out = np.zeros((COUNT, 2), np.float32)
    # Soft, wide magnetic sweeps replace the shrill repeating sonar chirps.
    # The half-bar pulses are felt as a scan cycle without masking the score.
    for start, length, pan in ((43, 7.5, -.55), (49, 8.5, .55)):
        n = seconds(length)
        t = np.arange(n, dtype=np.float32) / SAMPLE_RATE
        u = t / length
        contour = smooth(t / 1.3) * smooth((length-t) / 1.4)
        shimmer = airy_noise(length, 150, 1900)
        slow_pitch = 174 + 80 * smooth(u)
        phase = 2*np.pi*np.cumsum(slow_pitch) / SAMPLE_RATE
        beam = (.30*np.sin(phase) + .11*np.sin(1.998*phase)
                + .13*shimmer) * contour
        place(out, start, beam.astype(np.float32), .34, pan)
    for i, t0 in enumerate(np.arange(44, 57.5, 1.5)):
        n = seconds(.9)
        t = np.arange(n, dtype=np.float32) / SAMPLE_RATE
        hz = (293.66, 349.23, 392.0, 329.63)[i % 4]
        ping = (np.sin(2*np.pi*hz*t) + .16*np.sin(2*np.pi*hz*2.01*t))
        ping *= np.exp(-t*4.6) * envelope(.9, .016, .24)
        place(out, float(t0), ping.astype(np.float32), .055,
              -.42 if i % 2 else .42)
    for t0 in (43.0, 49.0, 57.0):
        place(out, t0, sweep(1.8, 88, 142, .05), .11)
    room(out, .19)
    write("asterion_fx_scan.wav", out)


def cargo_fx():
    out = np.zeros((COUNT, 2), np.float32)
    n = seconds(10.4)
    t = np.arange(n, dtype=np.float32)/SAMPLE_RATE
    tractor = (.48*np.sin(2*np.pi*(64*t+8*t*t/10.4))
               + .27*np.sin(2*np.pi*128*t)
               + .15*airy_noise(10.4, 100, 1800))
    place(out, 72, tractor*envelope(10.4, 1.2, .7), .35, -.2)
    for i, t0 in enumerate(np.arange(73, 81, .8)):
        place(out, float(t0), sweep(.44, 210+i*22, 670+i*34, .08),
              .14, -.38 + .07*i)
    for t0 in (72.5, 75.5, 78.5):
        place(out, t0, sweep(1.15, 460, 180, .24), .20)
    place(out, 80.2, sweep(1.65, 300, 80, .4), .29)
    for j, midi in enumerate((72, 76, 81, 88)):
        place(out, 81.1+j*.15, note(frequency(midi), 2.2, "bell"),
              .085, -.5+j/3)
    room(out, .35)
    write("asterion_fx_cargo.wav", out)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--stem", choices=("all", "score", "flight", "scan", "cargo"),
                        default="all")
    stem = parser.parse_args().stem
    for name, render in (("score", score), ("flight", flight_fx),
                         ("scan", scan_fx), ("cargo", cargo_fx)):
        if stem in ("all", name):
            render()

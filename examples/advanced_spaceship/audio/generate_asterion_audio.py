"""Render Asterion's 120 BPM seeded techno stems and isolated effects.

Only NumPy and Python's standard library are required. Each WAV starts at
project second zero so TiXL clips can be moved, muted, or mixed independently.
"""

from __future__ import annotations

import math
import wave
from pathlib import Path

import numpy as np

from break_pattern import SIXTEENTH, chops
from techno_pattern import STEP, events


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


def electronic_note(hz, length, *, brightness=.5):
    """Band-limited-ish wavetable stack with a short FM attack and stereo-safe body."""
    n = seconds(length)
    t = np.arange(n, dtype=np.float32)/SAMPLE_RATE
    phase = 2*np.pi*hz*t + (1.2 + brightness*2.4)*np.exp(-t*18)*np.sin(2*np.pi*hz*2.01*t)
    body = np.sin(phase) + .25*np.sin(2*phase) + .12*brightness*np.sin(3*phase)
    body = np.tanh(body*(1.3+brightness))
    return (body*envelope(length, .004, max(.06, length*.22))).astype(np.float32)


def electronic_music():
    """Seeded D-minor bass, stabs, and packet tones with changing bar patterns."""
    out = np.zeros((COUNT, 2), np.float32)
    for event in events():
        if event.kind == "bass":
            tone = electronic_note(frequency(event.note), .28, brightness=.27)
            place(out, event.time, tone, .20 * event.gain, event.pan)
        elif event.kind == "stab":
            tone = electronic_note(frequency(event.note), .17,
                                   brightness=.55 + .32 * event.gain)
            place(out, event.time, tone, .095 * event.gain, event.pan)
            # A short stereo answer establishes an evolving, not fixed, riff.
            if event.time + .1875 < DURATION:
                place(out, event.time + .1875, tone[:seconds(.11)],
                      .031 * event.gain, -event.pan)
        elif event.kind in ("signal", "fill"):
            tone = electronic_note(frequency(event.note), .105, brightness=.96)
            place(out, event.time, tone, .060 * event.gain, event.pan)
    for entrance in (10, 72, 84):
        # Pitched engine-like landings tie the electronics to the flight.
        place(out, entrance, electronic_note(73.42, 1.15, brightness=.88),
              .13, -.22)
        place(out, entrance + .125,
              electronic_note(146.83, .58, brightness=.74), .045, .38)
    room(out, .19)
    out *= 2.2
    write("asterion_music_electronic_120bpm.wav", out, peak=.68)


def techno_percussion():
    """Original drum synthesis driven by the same seeded bar events as TiXL."""
    out = np.zeros((COUNT, 2), np.float32)
    rng = np.random.default_rng(19790814)

    n = seconds(.36)
    t = np.arange(n, dtype=np.float32) / SAMPLE_RATE
    phase = 2 * np.pi * (45*t + 95*.024*(1-np.exp(-t/.024)))
    kick = (np.sin(phase) * np.exp(-t*15)
            + .08 * rng.standard_normal(n).astype(np.float32) * np.exp(-t*92))

    n = seconds(.28)
    t = np.arange(n, dtype=np.float32) / SAMPLE_RATE
    snare_noise = np.diff(rng.standard_normal(n).astype(np.float32), prepend=0)
    snare = (.23*np.sin(2*np.pi*187*t) + .30*snare_noise) * np.exp(-t*20)

    n = seconds(.085)
    t = np.arange(n, dtype=np.float32) / SAMPLE_RATE
    hat = np.diff(rng.standard_normal(n).astype(np.float32), prepend=0)
    hat *= np.exp(-t*76)

    for event in events():
        if event.kind == "kick":
            place(out, event.time, kick, .30*event.gain, event.pan)
        elif event.kind == "snare":
            place(out, event.time, snare, .36*event.gain, event.pan)
        elif event.kind == "ghost":
            place(out, event.time, snare, .15*event.gain, event.pan)
        elif event.kind == "hat":
            place(out, event.time, hat, .090*event.gain, event.pan)
        elif event.kind == "fill":
            for repeat in range(3):
                place(out, event.time + repeat*STEP/3,
                      hat[:seconds(.045)], .11*event.gain*(1-repeat*.18),
                      event.pan if repeat % 2 == 0 else -event.pan)
    room(out, .12)
    out *= 1.7
    write("asterion_music_techno_drums_120bpm.wav", out, peak=.72)


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
    # The half-bar pulses suggest a scan cycle without masking the music.
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


def break_fx():
    """Build an original played-feeling funk break, then slice it like a sampler."""
    rng = np.random.default_rng(19880617)
    source = np.zeros((seconds(2), 2), np.float32)

    def add_hit(start, signal, gain=1, pan=0):
        first = round(start * SAMPLE_RATE)
        length = min(len(signal), len(source)-first)
        if length <= 0:
            return
        l = math.sqrt((1-pan)/2)*gain
        r = math.sqrt((1+pan)/2)*gain
        source[first:first+length, 0] += signal[:length]*l
        source[first:first+length, 1] += signal[:length]*r

    def colored_noise(length, low, high):
        n = seconds(length)
        raw = rng.standard_normal(n).astype(np.float32)
        freq = np.fft.rfftfreq(n, 1/SAMPLE_RATE)
        band = np.clip((freq-low)/max(low, 1), 0, 1)
        band *= np.clip((high-freq)/max(high*.3, 1), 0, 1)
        filtered = np.fft.irfft(np.fft.rfft(raw)*band, n=n).astype(np.float32)
        return filtered / max(.001, np.max(np.abs(filtered)))

    def kick():
        n = seconds(.32)
        t = np.arange(n, dtype=np.float32)/SAMPLE_RATE
        phase = 2*np.pi*(48*t + 77*.041*(1-np.exp(-t/.041)))
        return (np.sin(phase)*np.exp(-t*15)
                + .16*colored_noise(.32, 80, 1800)*np.exp(-t*55)).astype(np.float32)

    def snare(ghost=False):
        n = seconds(.24)
        t = np.arange(n, dtype=np.float32)/SAMPLE_RATE
        noise = colored_noise(.24, 170, 6500)
        body = np.sin(2*np.pi*(183*t+8*.018*(1-np.exp(-t/.018))))
        out = .72*noise*np.exp(-t*17) + .31*body*np.exp(-t*27)
        return (out*(.43 if ghost else 1)).astype(np.float32)

    def hat(opened=False):
        length = .20 if opened else .075
        n = seconds(length)
        t = np.arange(n, dtype=np.float32)/SAMPLE_RATE
        return (colored_noise(length, 2400, 16000)
                * np.exp(-t*(18 if opened else 67))).astype(np.float32)

    for step in range(16):
        t = step*SIXTEENTH
        if step in (0, 7, 10):
            add_hit(t, kick(), .85 if step == 0 else .57)
        if step in (4, 12):
            add_hit(t, snare(), .88 if step == 4 else 1.0, -.06)
        if step in (6, 14, 15):
            add_hit(t, snare(True), .52 if step == 15 else .32, .08)
        if step % 2 == 0 or step in (7, 15):
            add_hit(t, hat(step == 15), .30 if step % 4 else .25,
                    -.24 if step % 4 else .21)
    # A little short room makes the newly generated hits feel like one kit.
    room(source, .22)
    source = np.tanh(source*1.9).astype(np.float32)
    source *= .8 / max(.8, float(np.max(np.abs(source))))

    out = np.zeros((COUNT, 2), np.float32)
    for event in chops():
        src0 = round(event.source_step*SIXTEENTH*SAMPLE_RATE)
        src1 = round((event.source_step+1)*SIXTEENTH*SAMPLE_RATE)
        dst0 = round(event.time*SAMPLE_RATE)
        dst1 = round((event.time+SIXTEENTH)*SAMPLE_RATE)
        segment = source[src0:src1].copy()
        if event.reverse:
            segment = segment[::-1].copy()
        if event.crush:
            segment = np.round(segment*64)/64
            segment[1::3] = segment[::3][:len(segment[1::3])]
        needed = dst1-dst0
        if len(segment) != needed:
            segment = np.stack([np.interp(np.linspace(0, 1, needed),
                                          np.linspace(0, 1, len(segment)),
                                          segment[:,ch]) for ch in range(2)], axis=1)
        edge = min(seconds(.0025), needed//3)
        segment[:edge] *= np.linspace(0, 1, edge, dtype=np.float32)[:, None]
        segment[-edge:] *= np.linspace(1, 0, edge, dtype=np.float32)[:, None]
        out[dst0:dst1] += segment*event.gain
    room(out, .10)
    write("asterion_amen_chops_120bpm.wav", out, peak=.54)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--stem", choices=("all", "electronic", "techno", "flight", "scan", "cargo", "break"),
                        default="all")
    stem = parser.parse_args().stem
    for name, render in (("electronic", electronic_music),
                         ("techno", techno_percussion),
                         ("flight", flight_fx),
                         ("scan", scan_fx), ("cargo", cargo_fx),
                         ("break", break_fx)):
        if stem in ("all", name):
            render()

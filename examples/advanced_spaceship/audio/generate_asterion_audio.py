"""Render Asterion's 120 BPM cinematic techno stems and isolated effects.

Only NumPy and Python's standard library are required. Each WAV starts at
project second zero so TiXL clips can be moved, muted, or mixed independently.
"""

from __future__ import annotations

import math
import random
import wave
from pathlib import Path

import numpy as np

from break_pattern import ACTIVE_WINDOWS, SIXTEENTH, chops
from techno_pattern import STEP, events, harmony_at, intensity, signal_events


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
        phase = 2*np.pi*hz*(t+.0007*np.sin(2*np.pi*.31*t))
        phase_2 = 2*np.pi*hz*1.0026*t
        sound = (.62*np.sin(phase)+.21*np.sin(2*phase)
                 +.11*np.sin(3*phase)+.045*np.sin(4*phase)
                 +.23*np.sin(phase_2))
        env = envelope(length, .32, .56)
    elif color == "strings":
        phase = 2 * np.pi * hz * t
        detuned = 2*np.pi*hz*1.0022*t
        bow = .12*np.sin(2*np.pi*4.3*t+.3*np.sin(2*np.pi*.21*t))
        sound = sum((np.sin(k*phase+bow)
                     +.63*np.sin(k*detuned-bow*.6))
                    / (1.63*k**1.44) for k in range(1, 7))
        sound *= .89+.11*np.sin(2*np.pi*.39*t+.4)
        env = envelope(length, .21, .52)
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
        pitch = hz*(1+.009*np.exp(-t*12))
        phase = 2*np.pi*np.cumsum(pitch)/SAMPLE_RATE
        brightness = .48+.52*smooth(t/.46)
        sound = sum(np.sin(k*phase)*brightness**(k-1)/k**.81
                    for k in range(1, 7))
        sound = np.tanh(sound*.91)
        env = envelope(length, .13, .54)
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
    """A harmonically locked analog bass and broken, syncopated sequencer."""
    out = np.zeros((COUNT, 2), np.float32)
    for event in events():
        if event.kind == "bass":
            tone = electronic_note(frequency(event.note), .37,
                                   brightness=.31)
            # The octave below is felt as motion, while the small upper layer
            # keeps the bass audible on speakers without much sub extension.
            place(out, event.time, tone, .24 * event.gain, event.pan*.3)
            place(out, event.time,
                  electronic_note(frequency(event.note+12), .19,
                                  brightness=.49), .045*event.gain,
                  -event.pan*.45)
        elif event.kind == "stab":
            tone = electronic_note(frequency(event.note), .23,
                                   brightness=.54 + .25*event.gain)
            place(out, event.time, tone, .070*event.gain, event.pan)
        elif event.kind in ("signal", "fill"):
            tone = electronic_note(frequency(event.note), .095,
                                   brightness=.92)
            place(out, event.time, tone, .046*event.gain, event.pan)

    # The clocked motif repeats as harmony, not as an identical loop. Each
    # bar gets seeded rests, octave shifts, and stereo answers.
    for bar in range(54):
        start = bar*2
        root, chord = harmony_at(start)
        level = intensity(start)
        rng = random.Random(51703+bar*421)
        active = (0, 3, 6, 10, 13) if level >= .6 else (0, 6, 11)
        for step in active:
            if step and rng.random() < (.23 if level < .6 else .11):
                continue
            degree = chord[(step+bar//2) % (len(chord)-1)]
            midi = root+12+degree+(12 if rng.random()<.17 else 0)
            pan = rng.uniform(-.58, .58)
            sound = electronic_note(frequency(midi),
                                    .16 if step%3 else .29,
                                    brightness=.40+.22*level)
            place(out, start+step*STEP, sound,
                  (.033+.045*level)*rng.uniform(.78, 1.13), pan)
            if step in (6, 13) and level >= .72:
                place(out, start+(step+1)*STEP, sound[:seconds(.075)],
                      .014*level, -pan)
    for entrance in (10, 16, 72, 84, 90):
        root, _ = harmony_at(entrance)
        place(out, entrance, electronic_note(frequency(root),
              1.15, brightness=.76), .14, -.18)
    room(out, .16)
    write("asterion_music_electronic_120bpm.wav", out, peak=.74)


def cinematic_music():
    """Four-chord filmic pulse, low ensemble, and a recurring rescue motif."""
    out = np.zeros((COUNT, 2), np.float32)
    for pair in range(27):
        start = pair*4
        root, chord = harmony_at(start)
        energy = energy_at(start+1)
        # Low string and brass voices swell over two bars; their chord tones
        # never fight the electronic bass root.
        for index, degree_index in enumerate((0, 2, 3, 4)):
            midi = root+12+chord[degree_index]
            color = "organ" if index == 0 else "strings"
            signal = note(frequency(midi), 4.7, color)
            place(out, start-.18, signal,
                  (.030 if index == 0 else .018)*(.55+energy),
                  (-.54, .52, -.30, .28)[index])
        # A restrained ostinato supplies propulsion through quiet chapters.
        for beat, degree_index in ((0, 0), (1.5, 2), (2, 3),
                                   (3.5, 2), (4, 4), (5.5, 3),
                                   (6, 2), (7.5, 1)):
            pitch = root+12+chord[degree_index]
            place(out, start+beat*BEAT,
                  note(frequency(pitch), .56, "strings"),
                  .018*(.4+energy), -.32 if beat%2 else .32)
    # One melodic identity appears at signal discovery, survey, recovery,
    # and return, changing instrumentation instead of changing key.
    for start, gain in ((1, .07), (16, .08), (42, .055),
                        (76, .09), (91, .10), (104, .055)):
        for index, midi in enumerate((62, 69, 72, 65, 69)):
            place(out, start+index*.5,
                  note(frequency(midi), 1.35,
                       "brass" if start in (16, 76, 91) else "strings"),
                  gain*(1-.08*index), -.35+.175*index)
    for t0 in (10, 16, 36, 72, 82, 84, 90, 104):
        root, _ = harmony_at(t0)
        place(out, t0, note(frequency(root), 2.7, "brass"),
              .074 if t0 in (16, 82, 90) else .048)
    room(out, .31)
    out *= 1.6
    write("asterion_music_cinematic_120bpm.wav", out, peak=.68)


def techno_percussion():
    """Heavy analog pulse with swung metal, ghost hits, and IDM fills."""
    out = np.zeros((COUNT, 2), np.float32)
    rng = np.random.default_rng(19790814)

    n = seconds(.36)
    t = np.arange(n, dtype=np.float32) / SAMPLE_RATE
    phase = 2 * np.pi * (48*t + 91*.028*(1-np.exp(-t/.028)))
    kick = (.91*np.sin(phase) * np.exp(-t*14)
            + .11*rng.standard_normal(n).astype(np.float32)*np.exp(-t*115))
    kick = np.tanh(kick*1.65).astype(np.float32)

    n = seconds(.28)
    t = np.arange(n, dtype=np.float32) / SAMPLE_RATE
    snare_noise = np.diff(rng.standard_normal(n).astype(np.float32), prepend=0)
    snare = (.32*np.sin(2*np.pi*(185*t+4*.012*(1-np.exp(-t/.012))))
             + .17*snare_noise)*np.exp(-t*21)
    snare += .20*np.roll(snare_noise, seconds(.011))*np.exp(-t*31)
    snare = np.tanh(snare*1.25).astype(np.float32)

    n = seconds(.085)
    t = np.arange(n, dtype=np.float32) / SAMPLE_RATE
    hat = np.diff(rng.standard_normal(n).astype(np.float32), prepend=0)
    hat *= np.exp(-t*69)
    hat = np.tanh(hat*.7).astype(np.float32)

    n = seconds(.12)
    t = np.arange(n, dtype=np.float32)/SAMPLE_RATE
    rim = (np.sin(2*np.pi*1130*t)+.33*np.sin(2*np.pi*1713*t))
    rim *= np.exp(-t*67)
    rim = rim.astype(np.float32)

    for event in events():
        if event.kind == "kick":
            place(out, event.time, kick, .32*event.gain, event.pan*.3)
        elif event.kind == "snare":
            place(out, event.time, snare, .42*event.gain, event.pan)
            place(out, event.time+.016, snare[:seconds(.10)],
                  .052*event.gain, -event.pan)
        elif event.kind == "ghost":
            place(out, event.time, snare, .22*event.gain, event.pan)
        elif event.kind == "hat":
            place(out, event.time, hat, .085*event.gain, event.pan)
        elif event.kind == "fill":
            for repeat in range(3):
                place(out, event.time + repeat*STEP/3,
                      hat[:seconds(.045)], .13*event.gain*(1-repeat*.18),
                      event.pan if repeat % 2 == 0 else -event.pan)
        elif event.kind == "signal":
            place(out, event.time, rim, .10*event.gain, event.pan)
    # Sparse extra rim answers on alternating bars keep motion without
    # adding a full-time metronome over the orchestral passages.
    for bar in range(54):
        if intensity(bar*2) >= .55 and bar % 2:
            place(out, bar*2+1.625, rim, .035, .45 if bar%4 else -.45)
    room(out, .09)
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
    # Engine speed follows the chapter trajectory; stereo vibration is narrow
    # enough to leave room for the drum kit and low cinematic pulse.
    noise = airy_noise(DURATION, 55, 1100)
    t = np.arange(COUNT, dtype=np.float32)/SAMPLE_RATE
    power = np.array([energy_at(float(x)) for x in np.arange(0, DURATION, .5)],
                     np.float32)
    envelope_speed = np.interp(t, np.arange(len(power))*.5, power).astype(np.float32)
    engine_hz = 48+23*envelope_speed+2.2*np.sin(2*np.pi*.31*t)
    engine_phase = 2*np.pi*np.cumsum(engine_hz)/SAMPLE_RATE
    base = .65*(.12*noise + .105*np.sin(engine_phase)
                + .032*np.sin(2.01*engine_phase))
    out[:, 0] = base*envelope_speed
    out[:, 1] = np.roll(base, 283)*envelope_speed
    for start, end in ((11, 16), (84, 90), (104, 108)):
        length = end-start
        n = seconds(length)
        u = np.linspace(0, 1, n, endpoint=False, dtype=np.float32)
        whoosh = airy_noise(length, 110, 6900)
        spool = smooth(u/.38)
        blast = smooth((u-.36)/.1)*smooth((1-u)/.14)
        phase = 2*np.pi*np.cumsum(65+190*u*u)/SAMPLE_RATE
        pulse = np.sin(phase)
        place(out, start, (.23*whoosh*spool+.23*pulse*blast),
              .70, -.17)
        place(out, start+length*.38, sweep(.84, 48, 210, .15),
              .22, .2)
        place(out, end-.35, sweep(.7, 120, 28, .36), .31, .2)
    for start, end in ((24, 36), (60, 72), (97, 104)):
        # Keep the existing long sub-bass falls through every expansion.
        place(out, start, sweep(end-start, 40, 16, .28), .24)
        place(out, end-.42, sweep(.7, 90, 370, .1), .16)
    for t0 in (7.3, 19.3, 95.2):
        place(out, t0-.4, sweep(1.2, 110, 470, .42), .19,
              -.5 if t0 < 30 else .5)
    for t0, pan in ((5.4, -.55), (7.2, .45), (9.1, -.35),
                    (92.7, .48), (95.2, -.42), (98.4, .35)):
        place(out, t0-.12, sweep(.48, 480, 130, .38), .082, pan)
    room(out, .12)
    write("asterion_fx_flight.wav", out)


def scan_fx():
    out = np.zeros((COUNT, 2), np.float32)
    # A moving spectral bed suggests a sensor combing through the lunar core.
    # Short, irregular data grains replace the old repeating sonar sequence.
    for start, length, pan in ((43, 8.1, -.48), (49.6, 9.2, .48)):
        n = seconds(length)
        t = np.arange(n, dtype=np.float32)/SAMPLE_RATE
        u = t/length
        hz = 146.83+72*smooth(u)+9*np.sin(2*np.pi*.37*t)
        phase = 2*np.pi*np.cumsum(hz)/SAMPLE_RATE
        contour = smooth(t/1.5)*smooth((length-t)/1.2)
        grain = airy_noise(length, 340, 2700)
        beam = (.20*np.sin(phase)+.075*np.sin(1.997*phase)
                +.068*grain)*contour
        place(out, start, beam.astype(np.float32), .33, pan)
    rng = random.Random(38307)
    allowed = (62, 65, 69, 72, 76)  # D F A C E
    for step in range(120):
        t0 = 43+step*STEP
        if t0 >= 58 or rng.random() < .38:
            continue
        midi = allowed[rng.randrange(len(allowed))]
        length = rng.choice((.045, .075, .12, .20))
        tone = electronic_note(frequency(midi), length,
                               brightness=.55+rng.random()*.35)
        place(out, t0+rng.choice((0, .012, .025)), tone,
              .016+rng.random()*.021, rng.uniform(-.86, .86))
    for t0 in (43, 49, 57.5):
        place(out, t0, sweep(1.55, 74, 129, .10), .105)
    for index, midi in enumerate((62, 65, 69, 72)):
        place(out, 58+index*.125,
              note(frequency(midi), 1.8, "bell"), .042,
              -.55+index*.36)
    room(out, .24)
    out *= 1.55
    write("asterion_fx_scan.wav", out)


def cargo_fx():
    out = np.zeros((COUNT, 2), np.float32)
    n = seconds(10.4)
    t = np.arange(n, dtype=np.float32)/SAMPLE_RATE
    phase = 2*np.pi*np.cumsum(62+18*smooth(t/10.4))/SAMPLE_RATE
    tractor = (.39*np.sin(phase)+.16*np.sin(2.005*phase)
               +.10*airy_noise(10.4, 110, 1500))
    place(out, 72, tractor*envelope(10.4, 1.0, .9), .33, -.2)
    rng = random.Random(72084)
    for step in range(72):
        t0 = 73+step*STEP
        if t0 >= 82 or rng.random() < .23:
            continue
        # Ratchets tighten as the recovered object reaches the pod.
        pitch = (146.83, 174.61, 220.0, 261.63)[step%4]
        servo = sweep(.14, pitch*.78, pitch*1.5, .10)
        place(out, t0, servo, .055+.045*smooth((t0-73)/9),
              -.65+1.3*((step*7)%11)/10)
    for t0 in (72.5, 75.5, 78.5):
        place(out, t0, sweep(1.1, 440, 170, .23), .19)
    place(out, 80.15, sweep(1.75, 320, 65, .37), .29)
    for j, midi in enumerate((62, 65, 69, 72)):
        place(out, 81.15+j*.125, note(frequency(midi), 2.1, "bell"),
              .072, -.5+j/3)
    room(out, .30)
    write("asterion_fx_cargo.wav", out)


def glitch_fx():
    """Short digital tears, modem fragments, and cut-grid stereo artifacts."""
    out = np.zeros((COUNT, 2), np.float32)
    rng = np.random.default_rng(231792)
    for index, event in enumerate(signal_events()):
        length = (.055, .09, .135, .21)[index%4]
        n = seconds(length)
        t = np.arange(n, dtype=np.float32)/SAMPLE_RATE
        hold = (4, 7, 11, 17)[index%4]
        raw = rng.standard_normal((n+hold-1)//hold).astype(np.float32)
        broken = np.repeat(raw, hold)[:n]
        broken = np.tanh(broken*1.7)
        hz = frequency(event.note if event.note else 62)
        carrier = np.sin(2*np.pi*hz*t)
        ring = np.sin(2*np.pi*(71+index%5*19)*t)
        burst = (.42*broken+.28*carrier*ring)*envelope(length,.002,.014)
        place(out, event.time, burst.astype(np.float32),
              .093*event.gain, event.pan)
        if index%5 == 3 and event.time+.125 < DURATION:
            place(out, event.time+.125, burst[:seconds(.045)],
                  .026*event.gain, -event.pan)
    for index, event in enumerate(chops()):
        if event.accent < .32 or index%3:
            continue
        n = seconds(.036)
        raw = rng.standard_normal((n+23)//24).astype(np.float32)
        step_noise = np.repeat(raw, 24)[:n]
        t = np.arange(n, dtype=np.float32)/SAMPLE_RATE
        click = np.diff(step_noise, prepend=0)*np.exp(-t*80)
        place(out, event.time, np.tanh(click*.47).astype(np.float32),
              .025*event.accent, -.58 if index%2 else .58)
    for t0 in (10.75, 15.75, 23.75, 35.75, 59.75,
               71.75, 83.75, 89.75, 103.75):
        for repeat in range(6):
            place(out, t0+repeat*.0375,
                  sweep(.06, 165+repeat*63, 70+repeat*19, .16),
                  .033*(1-repeat*.09), -.65+repeat*.26)
    room(out, .07)
    out *= 5.2
    write("asterion_fx_glitch.wav", out, peak=.56)


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

    def rim():
        n = seconds(.075)
        t = np.arange(n, dtype=np.float32)/SAMPLE_RATE
        return ((.65*np.sin(2*np.pi*1140*t)
                 +.25*np.sin(2*np.pi*1705*t))
                *np.exp(-t*78)).astype(np.float32)

    for step in range(16):
        t = step*SIXTEENTH
        if step in (0, 7, 10):
            add_hit(t, kick(), .85 if step == 0 else .57)
        if step in (4, 12):
            add_hit(t, snare(), .88 if step == 4 else 1.0, -.06)
            add_hit(t+.012, snare(True), .21, .26)
        if step in (6, 14, 15):
            add_hit(t, snare(True), .52 if step == 15 else .32, .08)
        if step in (3, 11):
            add_hit(t, rim(), .16, -.42 if step == 3 else .42)
        if step % 2 == 0 or step in (7, 15):
            add_hit(t, hat(step == 15), .30 if step % 4 else .25,
                    -.24 if step % 4 else .21)
    # A little short room makes the newly generated hits feel like one kit.
    room(source, .16)
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


def master_music():
    """Level the score independently of ship FX, preserving four editable stems."""
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
    from tools.music_stem_mastering import level_music_stems, read_pcm, write_pcm

    plan = (("asterion_music_cinematic_120bpm.wav", .86),
            ("asterion_music_electronic_120bpm.wav", .68),
            ("asterion_music_techno_drums_120bpm.wav", .74),
            ("asterion_amen_chops_120bpm.wav", .72))
    decoded = [read_pcm(OUT / filename) for filename, _ in plan]
    if any(rate != SAMPLE_RATE for _, rate in decoded):
        raise ValueError("Music sample rate changed")
    mastered, report = level_music_stems(
        [data for data, _ in decoded], [gain for _, gain in plan], SAMPLE_RATE,
        windows=[None, None, None, list(ACTIVE_WINDOWS)], target_rms=.075)
    for (filename, _), samples in zip(plan, mastered):
        write_pcm(OUT / filename, samples, SAMPLE_RATE)
    print("MUSIC_MASTER", report)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--stem", choices=("all", "music", "cinematic", "electronic",
                                           "techno", "flight", "scan",
                                           "cargo", "glitch", "break"),
                        default="all")
    stem = parser.parse_args().stem
    music_group = {"music", "cinematic", "electronic", "techno", "break"}
    for index, (name, render) in enumerate((("cinematic", cinematic_music),
                                            ("electronic", electronic_music),
                                            ("techno", techno_percussion),
                                            ("flight", flight_fx),
                                            ("scan", scan_fx),
                                            ("cargo", cargo_fx),
                                            ("glitch", glitch_fx),
                                            ("break", break_fx))):
        if stem in ("all", name) or (stem in music_group and name in music_group):
            RNG = np.random.default_rng(14031984+index*99991)
            render()
    if stem == "all" or stem in music_group:
        master_music()

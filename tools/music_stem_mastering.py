"""Level aligned music stems together without scene or listener inputs.

Manual use: python tools/music_stem_mastering.py --plan music.json --output out
The JSON plan contains stems [{path, gain, windows?}], sampleRate and targetRms.
Windows are active [start, end] seconds in the full-length source. Outputs
remain separate stereo PCM16 WAVs; input files are never overwritten by the CLI.
"""

from __future__ import annotations

import argparse
import json
import wave
from pathlib import Path

import numpy as np


def read_pcm(path: Path) -> tuple[np.ndarray, int]:
    with wave.open(str(path), "rb") as wav:
        if (wav.getnchannels(), wav.getsampwidth(), wav.getcomptype()) != (2, 2, "NONE"):
            raise ValueError(f"Expected stereo PCM16: {path}")
        rate = wav.getframerate()
        data = np.frombuffer(wav.readframes(wav.getnframes()), dtype="<i2")
    return data.reshape(-1, 2).astype(np.float32) / 32768, rate


def write_pcm(path: Path, data: np.ndarray, rate: int) -> None:
    if not np.isfinite(data).all() or np.max(np.abs(data)) >= 1:
        raise ValueError(f"Nonfinite or clipped music stem: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(2)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(np.rint(data * 32767).astype("<i2").tobytes())


def circular_smooth(values: np.ndarray, width: int) -> np.ndarray:
    width = max(3, width | 1)
    weights = np.hanning(width)
    weights /= weights.sum()
    return sum(np.roll(values, i - width // 2) * weight
               for i, weight in enumerate(weights))


def level_music_stems(stems: list[np.ndarray], gains: list[float], rate: int,
                      *, windows: list[list[tuple[float, float]] | None] | None = None,
                      target_rms: float = .075, peak_ceiling: float = .78,
                      minimum_gain: float = .45, maximum_gain: float = 3.0
                      ) -> tuple[list[np.ndarray], dict]:
    """Apply one slow, stereo-linked gain envelope to an aligned music group.

    Four-second RMS detection and two-second gain smoothing preserve drums
    and short musical accents. Circular smoothing makes the control envelope
    continuous at a loop seam. FX must be excluded from this music group.
    """
    if not stems or len(stems) != len(gains) or any(x.shape != stems[0].shape for x in stems):
        raise ValueError("Music stems must have matching lengths and gains")
    if stems[0].ndim != 2 or stems[0].shape[1] != 2 or rate <= 0:
        raise ValueError("Expected aligned stereo music")
    if not 0 < target_rms < peak_ceiling < 1 or not 0 < minimum_gain <= maximum_gain:
        raise ValueError("Invalid music mastering limits")
    if any(not np.isfinite(x).all() for x in stems) or any(not np.isfinite(g) or g < 0 for g in gains):
        raise ValueError("Invalid music data or gain")
    windows = windows or [None] * len(stems)
    if len(windows) != len(stems):
        raise ValueError("Every stem needs its active-window declaration")
    mix = np.zeros_like(stems[0])
    for data, gain, active in zip(stems, gains, windows):
        if active is None:
            mix += data * gain
        else:
            previous_end = 0
            for start, end in active:
                first, last = round(start * rate), round(end * rate)
                if not previous_end <= first < last <= len(mix):
                    raise ValueError("Music windows overlap or exceed the source")
                mix[first:last] += data[first:last] * gain
                previous_end = last
    block = max(1, round(rate * .125))
    starts = np.arange(0, len(mix), block)
    energy = np.mean(mix.astype(np.float64) ** 2, axis=1)
    counts = np.diff(np.append(starts, len(mix)))
    power = np.add.reduceat(energy, starts) / counts
    rms = np.sqrt(circular_smooth(power, round(4 * rate / block)))
    controls = np.clip(target_rms / np.maximum(rms, 1e-5), minimum_gain, maximum_gain)
    controls = circular_smooth(controls, round(2 * rate / block))
    centers = starts + counts / 2
    envelope = np.interp(np.arange(len(mix)),
                         np.concatenate(([centers[-1] - len(mix)], centers, [centers[0] + len(mix)])),
                         np.concatenate(([controls[-1]], controls, [controls[0]]))).astype(np.float32)
    mastered = [data * envelope[:, None] for data in stems]
    summed = mix * envelope[:, None]
    # A constant final safety trim preserves transient shape and stereo image.
    trim = min(1.0, peak_ceiling / max(1e-8, float(np.max(np.abs(summed)))),
               .98 / max(1e-8, max(float(np.max(np.abs(x))) for x in mastered)))
    mastered = [data * trim for data in mastered]
    summed *= trim
    report = {"targetRms": target_rms, "detectorSeconds": 4, "gainSmoothingSeconds": 2,
              "minimumGain": float(envelope.min()) * trim,
              "maximumGain": float(envelope.max()) * trim,
              "safetyTrim": trim, "musicPeak": float(np.max(np.abs(summed))),
              "musicRms": float(np.sqrt(np.mean(summed.astype(np.float64) ** 2))),
              "musicBySixSeconds": []}
    for first in range(0, len(mix), rate * 6):
        data = summed[first:first + rate * 6]
        report["musicBySixSeconds"].append({"start": first / rate,
                                             "rms": float(np.sqrt(np.mean(data.astype(np.float64) ** 2)))})
    return mastered, report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    paths = [(args.plan.parent / item["path"]).resolve() for item in plan["stems"]]
    if len({path.name for path in paths}) != len(paths):
        raise ValueError("Output filenames must be unique")
    decoded = [read_pcm(path) for path in paths]
    rates = {rate for _, rate in decoded}
    if len(rates) != 1:
        raise ValueError("Music sample rates differ")
    rate = rates.pop()
    if rate != plan.get("sampleRate", rate):
        raise ValueError("Plan sample rate differs from WAVs")
    outputs = [args.output.resolve() / path.name for path in paths]
    if set(outputs) & set(paths):
        raise ValueError("Choose an output directory separate from the raw music")
    data, report = level_music_stems(
        [data for data, _ in decoded], [float(item["gain"]) for item in plan["stems"]], rate,
        windows=[item.get("windows") for item in plan["stems"]],
        target_rms=float(plan.get("targetRms", .075)))
    for path, samples in zip(outputs, data):
        write_pcm(path, samples, rate)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()

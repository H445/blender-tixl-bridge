"""Inspect native TiXL AudioClip lanes and measure their rendered PCM mix offline.

Usage: python tools/audit_tixl_audio.py --graph <Home.t3>
Only 16-bit PCM WAVs with clips at normal speed are supported. This is a
read-only audit; it never edits the graph or audio assets.
"""

from __future__ import annotations

import argparse
import json
import re
import wave
from pathlib import Path

import numpy as np


PATH = "625951af-5f99-4171-b5b0-c97413121f56"
VOLUME = "06b8b927-ec47-4392-bb67-b9a140cc852b"
MUTE = "4ad8fba6-6e13-4698-b3c6-bd5c808724ab"
BUS_VOLUME = "b7e0d240-0003-4c8a-9f31-0ab1cd2e0100"


def read_graph(path: Path) -> dict:
    return json.loads(re.sub(r"/\*.*?\*/", "", path.read_text(encoding="utf-8"), flags=re.S))


def input_value(child: dict, slot: str, default=None):
    return next((item["Value"] for item in child.get("InputValues", [])
                 if item["Id"] == slot), default)


def is_muted(value) -> bool:
    if isinstance(value, str):
        return value.lower() == "true"
    return bool(value)


def pcm(path: Path) -> tuple[np.ndarray, int]:
    with wave.open(str(path), "rb") as wav:
        if wav.getsampwidth() != 2 or wav.getnchannels() != 2 or wav.getcomptype() != "NONE":
            raise ValueError(f"Expected stereo PCM16 WAV: {path}")
        rate = wav.getframerate()
        samples = np.frombuffer(wav.readframes(wav.getnframes()), dtype="<i2")
    return samples.reshape(-1, 2).astype(np.float32) / 32768, rate


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--graph", required=True, type=Path)
    parser.add_argument("--assets", type=Path, help="Project Assets directory, if graph is staged elsewhere")
    args = parser.parse_args()
    graph_path = args.graph.resolve()
    graph = read_graph(graph_path)
    playback = graph.get("PlaybackSettings") or graph.get("ProjectSettings", {}).get("Playback", {})
    bpm = float(playback["Bpm"])
    seconds_per_bar = 240 / bpm
    children = graph["Children"]
    clips = [child for child in children if child.get("SymbolName") == "Lib.io.audio.AudioClip"]
    source_lanes = sorted({float(data["TimeClip"]["LayerIndex"])
                           for child in children if child.get("SymbolName") == "PrismalLabs.BlenderExport.BlenderSourceClip"
                           for output in child.get("Outputs", [])
                           if (data := output.get("OutputData", {})).get("Type") == "T3.Core.Animation.TimeClip"})
    buses = [child for child in children if child.get("SymbolName") == "Lib.io.audio.AudioBus"]
    if len(buses) != 1:
        raise ValueError(f"Expected exactly one native AudioBus, found {len(buses)}")
    bus = buses[0]
    bus_gain = float(input_value(bus, BUS_VOLUME, 1))
    edges = graph["Connections"]
    bus_sources = {edge["SourceParentOrChildId"] for edge in edges
                   if edge["TargetParentOrChildId"] == bus["Id"]}
    if {clip["Id"] for clip in clips} != bus_sources:
        raise ValueError("AudioClip-to-AudioBus routing is incomplete or has extra sources")
    execute_ids = {child["Id"] for child in children if child.get("SymbolName") == "Lib.flow.Execute"}
    if not any(edge["SourceParentOrChildId"] == bus["Id"]
               and edge["TargetParentOrChildId"] in execute_ids for edge in edges):
        raise ValueError("AudioBus is not evaluated by Execute")
    asset_root = args.assets.resolve() if args.assets else graph_path.parent.parent / "Assets"
    decoded: dict[Path, tuple[np.ndarray, int]] = {}
    rows = []
    duration = 0.0
    for clip in clips:
        outputs = [output["OutputData"]["TimeClip"] for output in clip.get("Outputs", [])
                   if output.get("OutputData", {}).get("Type") == "T3.Core.Animation.TimeClip"]
        if len(outputs) != 1:
            raise ValueError(f"Expected one TimeClip on {clip.get('Name')}")
        time_clip = outputs[0]
        dest = time_clip["TimeRange"]
        source = time_clip["SourceRange"]
        if time_clip.get("SourceUnit") != "Seconds":
            raise ValueError(f"Expected seconds source range on {clip.get('Name')}")
        start, end = float(dest["Start"]) * seconds_per_bar, float(dest["End"]) * seconds_per_bar
        src_start, src_end = float(source["Start"]), float(source["End"])
        if abs((end - start) - (src_end - src_start)) > .002:
            raise ValueError(f"Retimed clip needs separate resampling audit: {clip.get('Name')}")
        resource = str(input_value(clip, PATH, ""))
        if ":" not in resource:
            raise ValueError(f"Missing project asset path on {clip.get('Name')}")
        path = asset_root / resource.split(":", 1)[1]
        if not path.is_file():
            raise FileNotFoundError(path)
        if path not in decoded:
            decoded[path] = pcm(path)
        data, rate = decoded[path]
        first, last = round(src_start * rate), round(src_end * rate)
        if first < 0 or last > len(data):
            raise ValueError(f"Clip exceeds source WAV: {clip.get('Name')}")
        window = data[first:last]
        rows.append({"name": clip.get("Name"), "id": clip["Id"], "path": str(path),
                     "lane": time_clip["LayerIndex"], "start": start, "end": end,
                     "sourceStart": src_start, "sourceEnd": src_end,
                     "gain": float(input_value(clip, VOLUME, 1)),
                     "muted": is_muted(input_value(clip, MUTE, False)),
                     "peak": float(np.max(np.abs(window))),
                     "rms": float(np.sqrt(np.mean(window.astype(np.float64) ** 2))),
                     "rate": rate})
        duration = max(duration, end)
    rates = {row["rate"] for row in rows}
    if len(rates) != 1:
        raise ValueError(f"Mixed WAV sample rates: {rates}")
    rate = rates.pop()
    mix = np.zeros((round(duration * rate), 2), dtype=np.float32)
    for row in rows:
        if row["muted"]:
            continue
        data, _ = decoded[Path(row["path"])]
        first, last = round(row["sourceStart"] * rate), round(row["sourceEnd"] * rate)
        dest = round(row["start"] * rate)
        window = data[first:last]
        mix[dest:dest + len(window)] += window * row["gain"] * bus_gain
    levels = []
    for start in np.arange(0, duration, 6):
        window = mix[round(start * rate):round(min(start + 6, duration) * rate)]
        levels.append({"start": float(start), "peak": float(np.max(np.abs(window))),
                       "rms": float(np.sqrt(np.mean(window.astype(np.float64) ** 2)))})
    print(json.dumps({"bpm": bpm, "sourceLanes": source_lanes, "busGain": bus_gain,
                      "clips": rows, "mixPeak": float(np.max(np.abs(mix))),
                      "mixRms": float(np.sqrt(np.mean(mix.astype(np.float64) ** 2))),
                      "clippedSamples": int(np.count_nonzero(np.abs(mix) >= 1)),
                      "mixBySixSeconds": levels}, indent=2))


if __name__ == "__main__":
    main()

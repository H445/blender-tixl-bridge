"""Install native TiXL AudioClip -> AudioBus -> Execute with the editor closed.

Five native AudioClip operators expose separate editable timeline lanes. Their
AudioReferences feed one native AudioBus, evaluated by Execute with the image.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import uuid
import wave
from datetime import datetime, timezone
from pathlib import Path


GRAPH_ID = "564f37c0-cb8c-5aff-97b3-683ec4ab5477"
DEFAULT_GRAPH = (Path.home() / "OneDrive/Documents/TiXL4.3-alpha/"
                 "AsterionBreakaway/Symbols/AsterionBreakaway.t3")
AUDIO = Path(__file__).resolve().parent / "advanced_spaceship/audio"
BACKUPS = Path(__file__).resolve().parent / ".tixl_cache/AsterionBreakaway/graph_backups"
CLIPS = (
    ("electronic", "asterion_music_electronic_120bpm.wav", .82),
    ("techno", "asterion_music_techno_drums_120bpm.wav", .66),
    ("flight", "asterion_fx_flight.wav", .48),
    ("scan", "asterion_fx_scan.wav", .64),
    ("cargo", "asterion_fx_cargo.wav", .62),
)
CLIP_SYMBOL = "f0008b50-091d-4e9f-91eb-baa212acfa20"
CLIP_OUTPUT = "4c9e7a20-3f81-4d5a-b6e2-1a2b3c4d5e6f"
CLIP_TIME_OUTPUT = "5fb7a174-9ab2-4688-89a0-7fbcbf831dcf"
BUS_SYMBOL = "b7e0d240-1e42-4c8a-9f31-0ab1cd2e0100"
BUS_OUTPUT = "b7e0d240-0001-4c8a-9f31-0ab1cd2e0100"
BUS_INPUT = "b7e0d240-0002-4c8a-9f31-0ab1cd2e0100"
EXECUTE_SYMBOL = "936e4324-bea2-463a-b196-6064a2d8a6b2"
EXECUTE_INPUT = "5d73ebe6-9aa0-471a-ae6b-3f5bfd5a0f9c"
EXECUTE_OUTPUT = "e81c99ce-fcee-4e7c-a1c7-0aa3b352b7e1"
TARGET_COMMAND = "4da253b7-4953-439a-b03f-1d515a78bddf"


def value(slot, kind, data):
    return {"Id": slot, "Type": kind, "Value": data}


def uid(name):
    return str(uuid.uuid5(uuid.NAMESPACE_URL, GRAPH_ID + "/audio/" + name))


def link(source, output, target, input_slot):
    return {"SourceParentOrChildId": source,
            "SourceSlotId": output,
            "TargetParentOrChildId": target,
            "TargetSlotId": input_slot}


def inspect_audio(path):
    with wave.open(str(path), "rb") as wav:
        assert (wav.getnchannels(), wav.getsampwidth(), wav.getframerate(),
                wav.getnframes()) == (2, 2, 44100, 108*44100), path
        assert wav.readframes(1) == bytes(4), f"Nonzero loop head: {path}"
        wav.setpos(wav.getnframes()-1)
        assert wav.readframes(1) == bytes(4), f"Nonzero loop tail: {path}"


def clip_output(name):
    start, end, layer = {
        "electronic": (0, 108, 6), "techno": (0, 108, 1),
        "flight": (0, 108, 2),
        "scan": (43, 59, 3), "cargo": (72, 84, 4),
    }[name]
    return {"Id": CLIP_TIME_OUTPUT,
            "OutputData": {"Type": "T3.Core.Animation.TimeClip",
                           "TimeClip": {
                               "TimeRange": {"Start": start/2, "End": end/2},
                               "SourceRange": {"Start": start, "End": end},
                               "LayerIndex": layer, "SourceUnit": "Seconds"}}}


def read_graph(path):
    return json.loads(re.sub(r'/\*.*?\*/', '',
                             path.read_text(encoding="utf-8"), flags=re.S))


def install(graph, ui, *, existing_scan=None):
    if graph["Id"] != GRAPH_ID or ui["Id"] != GRAPH_ID:
        raise ValueError("The selected graph is not AsterionBreakaway")
    names = {child.get("Name"): child for child in graph["Children"]}
    if any(name and name.startswith("Audio | ") for name in names):
        raise ValueError("Audio graph is already installed; preserve user edits")
    for name in ("Output fit", "Output target"):
        if name not in names:
            raise ValueError(f"Required final render node missing: {name}")
    fit, target = names["Output fit"], names["Output target"]
    direct = link(fit["Id"], "3c8116a2-2686-41ba-8bfd-d1b3fb929b02",
                  target["Id"], TARGET_COMMAND)
    if sum(edge == direct for edge in graph["Connections"]) != 1:
        raise ValueError("The expected direct output command route has changed")
    playback = graph.get("PlaybackSettings")
    if playback and playback.get("AudioClips"):
        raise ValueError("A user soundtrack is already installed; preserve it")
    if playback is None:
        playback = {"Enabled": True, "Bpm": 120.0,
                    "AudioSource": 0, "Syncing": 0,
                    "AudioDecayFactor": .9, "AudioGainFactor": 1.0,
                    "AudioInputDeviceName": "", "EnableAudioBeatLocking": False,
                    "BeatLockAudioOffsetSec": 0.0}
        graph["PlaybackSettings"] = playback
    playback["Enabled"] = True
    playback["Bpm"] = 120.0
    playback["AudioSource"] = 0
    playback["AudioClips"] = []

    def child(name, symbol, symbol_name, x, y, inputs):
        new = {"Id": uid(name), "SymbolId": symbol,
               "SymbolName": symbol_name, "Name": "Audio | " + name,
               "InputValues": inputs, "Outputs": []}
        graph["Children"].append(new)
        ui["SymbolChildUis"].append({"ChildId": new["Id"],
                                     "Position": {"X": x, "Y": y}})
        return new

    bus = child("mission audio bus", BUS_SYMBOL, "Lib.io.audio.AudioBus",
                21680, -520,
                [value("b7e0d240-0003-4c8a-9f31-0ab1cd2e0100",
                       "System.Single", .86)])
    execute = child("execute audio + image", EXECUTE_SYMBOL,
                    "Lib.flow.Execute", 22000, -80, [])
    for index, (name, filename, volume) in enumerate(CLIPS):
        inputs = [value("625951af-5f99-4171-b5b0-c97413121f56",
                        "System.String", f"AsterionBreakaway:audio/{filename}"),
                  value("06b8b927-ec47-4392-bb67-b9a140cc852b",
                        "System.Single", volume)]
        if name == "scan" and existing_scan is not None:
            clip = existing_scan
            clip.update(Name="Audio | scan clip", InputValues=inputs)
            position = next(item for item in ui["SymbolChildUis"]
                            if item["ChildId"] == clip["Id"])
            position["Position"] = {"X": 21360, "Y": -1570 + index*290}
        else:
            clip = child(name + " clip", CLIP_SYMBOL, "Lib.io.audio.AudioClip",
                         21360, -1570 + index*290, inputs)
        clip["Outputs"] = [clip_output(name)]
        graph["Connections"].append(link(clip["Id"], CLIP_OUTPUT,
                                         bus["Id"], BUS_INPUT))
    graph["Connections"].remove(direct)
    graph["Connections"].append(link(fit["Id"], direct["SourceSlotId"],
                                     execute["Id"], EXECUTE_INPUT))
    graph["Connections"].append(link(bus["Id"], BUS_OUTPUT,
                                     execute["Id"], EXECUTE_INPUT))
    graph["Connections"].append(link(execute["Id"], EXECUTE_OUTPUT,
                                     target["Id"], TARGET_COMMAND))
    target_ui = next(item for item in ui["SymbolChildUis"]
                     if item["ChildId"] == target["Id"])
    if target_ui["Position"] not in ({"X": 21420, "Y": 0},
                                      {"X": 22260, "Y": 0}):
        raise ValueError("Output target moved since layout was planned")
    target_ui["Position"] = {"X": 22260, "Y": 0}
    return graph, ui


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--graph", type=Path, default=DEFAULT_GRAPH)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    graph_path = args.graph.resolve()
    ui_path = graph_path.with_suffix(".t3ui")
    for filename in (clip[1] for clip in CLIPS):
        inspect_audio(AUDIO / filename)
    graph = read_graph(graph_path)
    ui = read_graph(ui_path)
    graph, ui = install(graph, ui)
    ids = {child["Id"] for child in graph["Children"]}
    assert len(ids) == len(graph["Children"])
    assert all(edge["SourceParentOrChildId"] in ids
               and edge["TargetParentOrChildId"] in ids
               for edge in graph["Connections"])
    print("ASTERION_AUDIO_PLAN", len(graph["Children"]), "children",
          len(graph["Connections"]), "connections", "120 BPM", "108 seconds")
    if args.dry_run:
        return

    assets = graph_path.parent.parent / "Assets/audio"
    for filename in (clip[1] for clip in CLIPS):
        destination = assets / filename
        if destination.exists() and destination.read_bytes() != (AUDIO / filename).read_bytes():
            raise ValueError(f"Existing project audio differs: {destination}")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = BACKUPS / f"before-audio-{stamp}"
    backup.mkdir(parents=True)
    shutil.copy2(graph_path, backup / graph_path.name)
    shutil.copy2(ui_path, backup / ui_path.name)
    assets.mkdir(parents=True, exist_ok=True)
    for filename in (clip[1] for clip in CLIPS):
        shutil.copy2(AUDIO / filename, assets / filename)
    graph_path.write_text(json.dumps(graph, indent=2) + "\n", encoding="utf-8")
    ui_path.write_text(json.dumps(ui, indent=2) + "\n", encoding="utf-8")
    print("ASTERION_AUDIO_INSTALLED", graph_path, "backup", backup,
          "clips", len(CLIPS))


if __name__ == "__main__":
    main()

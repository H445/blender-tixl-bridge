"""Install Asterion's editable TiXL AudioClips and AudioBus with the editor closed.

The score and three effect clips follow composition seconds and feed one master
AudioBus. The existing image graph and source TimeClips are preserved exactly.
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
    ("score", "asterion_score_120bpm.wav", .82),
    ("flight", "asterion_fx_flight.wav", .48),
    ("scan", "asterion_fx_scan.wav", .64),
    ("cargo", "asterion_fx_cargo.wav", .62),
)
SCORE = "asterion_score_120bpm.wav"
CLIP_SYMBOL = "4812d48b-f74e-49dd-98f3-bd6b5b1df82e"
CLIP_OUTPUT = "80923455-7af0-49f5-acb0-ed2a1e9fb715"
TIME_OUTPUT = "fd3049aa-4c22-405b-b9b4-0a2474d0e377"
BUS_OUTPUT = "6c6b994d-5fba-4c04-94a4-95a20314caf5"
BUS_COMMAND = "2786a789-4527-45a4-aeb8-581ee93a621e"
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


def read_graph(path):
    return json.loads(re.sub(r'/\*.*?\*/', '',
                             path.read_text(encoding="utf-8"), flags=re.S))


def install(graph, ui):
    if graph["Id"] != GRAPH_ID or ui["Id"] != GRAPH_ID:
        raise ValueError("The selected graph is not AsterionBreakaway")
    names = {child.get("Name"): child for child in graph["Children"]}
    if "Audio | 120 BPM project time" in names:
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

    time = child("120 BPM project time", "b0d75f21-df33-460b-beab-d8c5e1f23e5e",
                 "Lib.numbers.anim.time.Time", 21000, -1200,
                 [value("6d2f783a-23b7-425c-a4e3-cfcdcd61cf3a", "System.Int32", 2),
                  value("ba443b6a-487f-4739-94a3-915584ee2d46", "System.Int32", 1)])
    bus = child("mission audio bus", "c54e249e-0a7f-41a5-aa62-31117f33d5df",
                "PrismalLabs.BlenderExport.BlenderAudioBus", 21840, -80,
                [value("3974a495-1229-46c8-a1c7-7969a10b670d",
                       "System.Single", .86)])
    for index, (name, filename, volume) in enumerate(CLIPS):
        clip = child(name + " clip", CLIP_SYMBOL,
                     "PrismalLabs.BlenderExport.BlenderAudioClip",
                     21420, -1280 + index*315,
                     [value("20f00480-4039-4cb7-8120-5994db9ee296",
                            "System.String", f"AsterionBreakaway:audio/{filename}"),
                      value("8725b560-1ef8-4d87-9145-34e0547c80a9",
                            "System.Single", 108.0),
                      value("20249dd6-273f-49d9-976a-bf78b3970817",
                            "System.Single", volume)])
        graph["Connections"].append(link(time["Id"], TIME_OUTPUT,
                                         clip["Id"],
                                         "8ed11bc3-e8c1-4b0e-8c6c-26e79fe5d11b"))
        graph["Connections"].append(link(clip["Id"], CLIP_OUTPUT,
                                         bus["Id"], BUS_COMMAND))
    graph["Connections"].remove(direct)
    graph["Connections"].append(link(fit["Id"], direct["SourceSlotId"],
                                     bus["Id"], BUS_COMMAND))
    graph["Connections"].append(link(bus["Id"], BUS_OUTPUT,
                                     target["Id"], TARGET_COMMAND))
    target_ui = next(item for item in ui["SymbolChildUis"]
                     if item["ChildId"] == target["Id"])
    if target_ui["Position"] != {"X": 21420, "Y": 0}:
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
          "clips", 4)


if __name__ == "__main__":
    main()

"""Install the revised Asterion sound design into native TiXL audio lanes.

Run while TiXL is closed through the debug bridge. Existing editable clips,
TimeClips, bus levels, and the image route are preserved. Two new full-length
AudioClips join the same native AudioBus; all eight original WAV assets are
refreshed from the reproducible generator in this checkout.
"""

from __future__ import annotations

import argparse
import filecmp
import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

from install_asterion_audio import (AUDIO, BACKUPS, BUS_INPUT, CLIP_OUTPUT,
                                    CLIP_SYMBOL, CLIP_TIME_OUTPUT,
                                    DEFAULT_GRAPH, GRAPH_ID, inspect_audio,
                                    link, read_graph, uid, value)


STEMS = (
    "asterion_music_cinematic_120bpm.wav",
    "asterion_music_electronic_120bpm.wav",
    "asterion_music_techno_drums_120bpm.wav",
    "asterion_amen_chops_120bpm.wav",
    "asterion_fx_flight.wav",
    "asterion_fx_scan.wav",
    "asterion_fx_cargo.wav",
    "asterion_fx_glitch.wav",
)
NEW_LANES = (
    ("Music | cinematic ensemble clip", STEMS[0], .78, 0),
    ("FX | glitch transmission clip", STEMS[-1], .72, 7),
)
PATH_SLOT = "625951af-5f99-4171-b5b0-c97413121f56"
VOLUME_SLOT = "06b8b927-ec47-4392-bb67-b9a140cc852b"


def time_clip(layer: int) -> dict:
    return {"Id": CLIP_TIME_OUTPUT,
            "OutputData": {"Type": "T3.Core.Animation.TimeClip",
                           "TimeClip": {
                               "TimeRange": {"Start": 0, "End": 54},
                               "SourceRange": {"Start": 0, "End": 108},
                               "LayerIndex": layer,
                               "SourceUnit": "Seconds"}}}


def prepare(graph: dict, ui: dict) -> tuple[dict, dict, bool]:
    if graph["Id"] != GRAPH_ID or ui["Id"] != GRAPH_ID:
        raise ValueError("Expected the AsterionBreakaway Home graph")
    children = graph["Children"]
    names = {child.get("Name"): child for child in children}
    if len(names) != len(children):
        raise ValueError("Duplicate child names; inspect the graph first")
    bus = names["Audio | mission audio bus"]
    if bus["SymbolName"] != "Lib.io.audio.AudioBus":
        raise ValueError("Expected the native TiXL AudioBus")
    playback = (graph.get("ProjectSettings", {}).get("Playback")
                or graph.get("PlaybackSettings", {}))
    if float(playback["Bpm"]) != 120:
        raise ValueError("The project tempo has changed")
    existing = [child for child in children
                if child["SymbolName"] == "Lib.io.audio.AudioClip"]
    if len(existing) < 8:
        raise ValueError("Existing timeline audio lanes are missing")
    positions = {item["ChildId"]: item["Position"]
                 for item in ui["SymbolChildUis"]}
    for clip in existing:
        edge = link(clip["Id"], CLIP_OUTPUT, bus["Id"], BUS_INPUT)
        if graph["Connections"].count(edge) != 1:
            raise ValueError(f"Clip routing changed: {clip['Name']}")
    paths = [item["Value"] for clip in existing
             for item in clip.get("InputValues", []) if item["Id"] == PATH_SLOT]
    if not paths or any(":audio/" not in str(path) for path in paths):
        raise ValueError("Cannot resolve the project's audio namespace")
    namespace = str(paths[0]).split(":audio/", 1)[0]
    if any(str(path).split(":audio/", 1)[0] != namespace for path in paths):
        raise ValueError("Audio clips use different namespaces")
    for stem in STEMS[1:-1]:
        if not any(str(path).endswith("/"+stem) for path in paths):
            raise ValueError(f"Expected existing native clip for {stem}")

    changed = False
    left = min(positions[clip["Id"]]["X"] for clip in existing)
    top = min(positions[clip["Id"]]["Y"] for clip in existing)
    for index, (name, filename, volume, layer) in enumerate(NEW_LANES):
        edge_id = uid("sound-design/"+filename)
        current = next((child for child in children if child["Id"] == edge_id), None)
        if current is not None:
            current_path = next((item["Value"] for item in current.get("InputValues", [])
                                 if item["Id"] == PATH_SLOT), None)
            if current["SymbolName"] != "Lib.io.audio.AudioClip" or current_path != f"{namespace}:audio/{filename}":
                raise ValueError(f"Conflicting audio lane: {name}")
            continue
        if name in names:
            raise ValueError(f"Conflicting audio lane name: {name}")
        clip = {"Id": edge_id, "SymbolId": CLIP_SYMBOL,
                "SymbolName": "Lib.io.audio.AudioClip", "Name": name,
                "InputValues": [
                    value(PATH_SLOT, "System.String",
                          f"{namespace}:audio/{filename}"),
                    value(VOLUME_SLOT, "System.Single", volume),
                ],
                "Outputs": [time_clip(layer)]}
        children.append(clip)
        ui["SymbolChildUis"].append({"ChildId": clip["Id"],
                                     "Position": {"X": left,
                                                  "Y": top-290*(index+1)}})
        graph["Connections"].append(link(clip["Id"], CLIP_OUTPUT,
                                         bus["Id"], BUS_INPUT))
        changed = True
    ids = {child["Id"] for child in children}
    if len(ids) != len(children):
        raise ValueError("Audio child ID collision")
    if any(edge["SourceParentOrChildId"] not in ids or
           edge["TargetParentOrChildId"] not in ids
           for edge in graph["Connections"]):
        raise ValueError("Audio graph contains a dangling connection")
    return graph, ui, changed


def atomic_copy(source: Path, destination: Path) -> None:
    if destination.exists() and filecmp.cmp(source, destination, shallow=False):
        return
    temp = destination.with_name(destination.name+".incoming")
    shutil.copyfile(source, temp)
    os.replace(temp, destination)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--graph", type=Path, default=DEFAULT_GRAPH)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    graph_path = args.graph.resolve()
    ui_path = graph_path.with_suffix(".t3ui")
    for filename in STEMS:
        inspect_audio(AUDIO / filename)
    graph, ui, changed = prepare(read_graph(graph_path), read_graph(ui_path))
    print("ASTERION_SOUND_PLAN", {"children": len(graph["Children"]),
                                  "connections": len(graph["Connections"]),
                                  "new_lanes": changed,
                                  "assets": list(STEMS)})
    if args.dry_run:
        return
    assets = graph_path.parent.parent / "Assets" / "audio"
    assets.mkdir(parents=True, exist_ok=True)
    for filename in STEMS:
        atomic_copy(AUDIO / filename, assets / filename)
    if changed:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup = BACKUPS / f"before-sound-design-{stamp}"
        backup.mkdir(parents=True, exist_ok=False)
        shutil.copy2(graph_path, backup / graph_path.name)
        shutil.copy2(ui_path, backup / ui_path.name)
        for path, payload in ((graph_path, graph), (ui_path, ui)):
            temp = path.with_name(path.name+".incoming")
            temp.write_text(json.dumps(payload, indent=2)+"\n",
                            encoding="utf-8")
            os.replace(temp, path)
    print("ASTERION_SOUND_INSTALLED", graph_path, "new_lanes", changed)


if __name__ == "__main__":
    main()

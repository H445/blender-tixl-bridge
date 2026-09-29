"""Add a 120 BPM electronic music AudioClip to Asterion's native audio bus.

Run after checking that the live Home graph matches disk and closing TiXL
through the debug bridge. Preserve every existing visual and audio route.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from install_asterion_audio import (AUDIO, BACKUPS, BUS_INPUT, CLIP_OUTPUT,
                                    CLIP_SYMBOL, CLIP_TIME_OUTPUT, DEFAULT_GRAPH,
                                    GRAPH_ID, inspect_audio, link, read_graph,
                                    uid, value)


FILENAME = "asterion_music_electronic_120bpm.wav"
SCORE = "asterion_score_120bpm.wav"
PREVIOUS_SCORE_SHA256 = "68669507823cadaace71e7810cbb3343df733751fbc2b8cf31078bc132dd0af3"
NAME = "Music | electronic pulse and arpeggio clip"
BUS_NAME = "Audio | mission audio bus"


def clip_time():
    return {"Id": CLIP_TIME_OUTPUT,
            "OutputData": {"Type": "T3.Core.Animation.TimeClip",
                           "TimeClip": {
                               "TimeRange": {"Start": 0, "End": 54},
                               "SourceRange": {"Start": 0, "End": 108},
                               "LayerIndex": 6, "SourceUnit": "Seconds"}}}


def install(graph, ui):
    if graph["Id"] != GRAPH_ID or ui["Id"] != GRAPH_ID:
        raise ValueError("Expected the AsterionBreakaway Home graph")
    names = {child.get("Name"): child for child in graph["Children"]}
    if NAME in names:
        raise ValueError("Electronic music clip is already installed")
    bus = names[BUS_NAME]
    if bus["SymbolName"] != "Lib.io.audio.AudioBus":
        raise ValueError("Expected the native TiXL audio bus")
    clip = {"Id": uid("music/electronic"), "SymbolId": CLIP_SYMBOL,
            "SymbolName": "Lib.io.audio.AudioClip", "Name": NAME,
            "InputValues": [
                value("625951af-5f99-4171-b5b0-c97413121f56",
                      "System.String", f"AsterionBreakaway:audio/{FILENAME}"),
                value("06b8b927-ec47-4392-bb67-b9a140cc852b",
                      "System.Single", .82)],
            "Outputs": [clip_time()]}
    if any(c["Id"] == clip["Id"] for c in graph["Children"]):
        raise ValueError("Electronic music child ID collision")
    graph["Children"].append(clip)
    graph["Connections"].append(link(clip["Id"], CLIP_OUTPUT,
                                     bus["Id"], BUS_INPUT))
    ui["SymbolChildUis"].append({"ChildId": clip["Id"],
                                 "Position": {"X": 21360, "Y": -2440}})
    return graph, ui


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--graph", type=Path, default=DEFAULT_GRAPH)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    graph_path = args.graph.resolve()
    ui_path = graph_path.with_suffix(".t3ui")
    graph, ui = install(read_graph(graph_path), read_graph(ui_path))
    ids = {child["Id"] for child in graph["Children"]}
    if len(ids) != len(graph["Children"]):
        raise ValueError("Duplicate child IDs")
    if any(edge["SourceParentOrChildId"] not in ids or
           edge["TargetParentOrChildId"] not in ids
           for edge in graph["Connections"]):
        raise ValueError("Unresolved audio or visual connection")
    inspect_audio(AUDIO / FILENAME)
    inspect_audio(AUDIO / SCORE)
    assets = graph_path.parent.parent / "Assets/audio"
    original = assets / SCORE
    old_sha = hashlib.sha256(original.read_bytes()).hexdigest()
    new_sha = hashlib.sha256((AUDIO / SCORE).read_bytes()).hexdigest()
    if old_sha not in (PREVIOUS_SCORE_SHA256, new_sha):
        raise ValueError("The installed score differs from the original; preserve it")
    new_asset = assets / FILENAME
    if new_asset.exists() and new_asset.read_bytes() != (AUDIO / FILENAME).read_bytes():
        raise ValueError("A different electronic music asset already exists")
    print("ASTERION_ELECTRONIC_PLAN", len(graph["Children"]), "children",
          len(graph["Connections"]), "connections", new_asset)
    if args.dry_run:
        return
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = BACKUPS / f"before-electronic-music-{stamp}"
    backup.mkdir(parents=True)
    shutil.copy2(graph_path, backup / graph_path.name)
    shutil.copy2(ui_path, backup / ui_path.name)
    shutil.copy2(AUDIO / SCORE, original)
    shutil.copy2(AUDIO / FILENAME, new_asset)
    graph_path.write_text(json.dumps(graph, indent=2) + "\n", encoding="utf-8")
    ui_path.write_text(json.dumps(ui, indent=2) + "\n", encoding="utf-8")
    print("ASTERION_ELECTRONIC_INSTALLED", graph_path, "backup", backup)


if __name__ == "__main__":
    main()

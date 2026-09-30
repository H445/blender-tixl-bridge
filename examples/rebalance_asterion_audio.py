"""Repair Asterion's timeline lanes, viewport, export range, and audio levels.

Stage with --output and --ui-output, audit, then apply with --apply while TiXL
is closed. Graph topology and unrelated composition/UI settings stay intact.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

from install_asterion_audio import (BACKUPS, BUS_SYMBOL, CLIP_SYMBOL, GRAPH_ID,
                                    read_graph)


VOLUME = "06b8b927-ec47-4392-bb67-b9a140cc852b"
MUTE = "4ad8fba6-6e13-4698-b3c6-bd5c808724ab"
BUS_VOLUME = "b7e0d240-0003-4c8a-9f31-0ab1cd2e0100"
PATH = "625951af-5f99-4171-b5b0-c97413121f56"

# Full score, two electronic layers, one shared chopped-break lane, then effects.
PLAN = {
    "asterion_music_cinematic_120bpm.wav": ("Music | cinematic ensemble", 1, .86),
    "asterion_music_electronic_120bpm.wav": ("Music | electronic pulse and arpeggio", 2, .68),
    "asterion_music_techno_drums_120bpm.wav": ("Music | seeded techno drums", 3, .74),
    "asterion_amen_chops_120bpm.wav": ("Break | chopped drums", 4, .72),
    "asterion_fx_flight.wav": ("FX | propulsion and warp", 5, .50),
    "asterion_fx_scan.wav": ("FX | lunar scan", 6, .50),
    "asterion_fx_cargo.wav": ("FX | cargo capture", 7, .48),
    "asterion_fx_glitch.wav": ("FX | glitch transmission", 8, .36),
}


def slot(child: dict, ident: str) -> dict | None:
    return next((item for item in child.get("InputValues", []) if item["Id"] == ident), None)


def prepare(graph: dict, *, mix_only: bool = False) -> tuple[dict, list[dict]]:
    if graph["Id"] != GRAPH_ID:
        raise ValueError("Expected AsterionBreakaway Home graph")
    clips = [child for child in graph["Children"] if child.get("SymbolId") == CLIP_SYMBOL]
    buses = [child for child in graph["Children"] if child.get("SymbolId") == BUS_SYMBOL]
    if len(clips) != 10 or len(buses) != 1:
        raise ValueError("Unexpected native audio topology; preserve editor changes")
    used = set()
    changes = []
    for clip in clips:
        path_slot = slot(clip, PATH)
        name = str(path_slot["Value"]).rsplit("/", 1)[-1] if path_slot else ""
        if name not in PLAN:
            raise ValueError(f"Unknown AudioClip asset: {clip.get('Name')}: {name}")
        used.add(name)
        title, lane, gain = PLAN[name]
        outputs = [output["OutputData"]["TimeClip"] for output in clip.get("Outputs", [])
                   if output.get("OutputData", {}).get("Type") == "T3.Core.Animation.TimeClip"]
        if len(outputs) != 1:
            raise ValueError(f"Unexpected TimeClip count: {clip.get('Name')}")
        time_clip = outputs[0]
        source = time_clip["SourceRange"]
        if name == "asterion_amen_chops_120bpm.wav":
            suffix = f" | {int(source['Start'])}–{int(source['End'])} s"
        else:
            suffix = ""
        before = {"name": clip.get("Name"), "lane": time_clip["LayerIndex"],
                  "gain": slot(clip, VOLUME)["Value"],
                  "muted": slot(clip, MUTE)["Value"] if slot(clip, MUTE) else False}
        if not mix_only:
            clip["Name"] = title + suffix
            time_clip["LayerIndex"] = lane
        if any(edge["TargetParentOrChildId"] == clip["Id"]
               and edge["TargetSlotId"] in (VOLUME, MUTE)
               for edge in graph["Connections"]):
            raise ValueError(f"Audio gain/mute has a live driver: {clip.get('Name')}")
        slot(clip, VOLUME)["Value"] = gain
        if slot(clip, MUTE):
            slot(clip, MUTE)["Value"] = False
        changes.append({"asset": name, "before": before,
                        "after": {"name": clip["Name"], "lane": time_clip["LayerIndex"],
                                  "gain": gain, "muted": False}})
    if used != set(PLAN):
        raise ValueError(f"Missing planned assets: {set(PLAN) - used}")
    bus = buses[0]
    bus_level = slot(bus, BUS_VOLUME)
    if bus_level is None:
        raise ValueError("Native bus volume slot missing")
    changes.append({"bus": bus.get("Name"), "before": bus_level["Value"], "after": .82})
    bus_level["Value"] = .82
    return graph, changes


def prepare_ui(ui: dict) -> tuple[dict, dict]:
    if ui["Id"] != GRAPH_ID:
        raise ValueError("Expected matching AsterionBreakaway UI graph")
    settings = ui["Settings"]
    timeline = settings["Timeline"]
    export = settings["RenderExport"]
    if export["TimeRange"] != "Custom" or export["StartInBars"] != 0:
        raise ValueError("Unexpected render export range mode/start")
    if timeline["SourceExtentStart"] != 0 or timeline["SourceExtentEnd"] != 54:
        raise ValueError("The authored 54-bar source extent changed")
    before = {"scaleX": timeline["ScaleX"], "scrollX": timeline["ScrollX"],
              "timelineHeight": timeline["TimelineHeight"],
              "exportEndInBars": export["EndInBars"]}
    timeline["ScaleX"] = 10.0
    timeline["ScrollX"] = -5.0
    timeline["TimelineHeight"] = 360
    export["EndInBars"] = 54.0
    return ui, {"before": before,
                "after": {"scaleX": 10.0, "scrollX": -5.0,
                          "timelineHeight": 360, "exportEndInBars": 54.0}}


def dump(path: Path, graph: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(graph, indent=2) + "\n", encoding="utf-8")


def editor_running() -> bool:
    if os.name != "nt":
        return False
    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "[bool](Get-Process TiXL -ErrorAction SilentlyContinue)"],
        capture_output=True, text=True, check=True)
    return result.stdout.strip().lower() == "true"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--graph", required=True, type=Path)
    parser.add_argument("--output", type=Path, help="Staged graph path outside TiXL Symbols")
    parser.add_argument("--ui-output", type=Path, help="Staged matching .t3ui outside TiXL Symbols")
    parser.add_argument("--apply", action="store_true", help="Back up and replace the closed editor's graph")
    parser.add_argument("--mix-only", action="store_true",
                        help="Only restore audio gains/mutes; preserve timeline, layout and export settings")
    args = parser.parse_args()
    path = args.graph.resolve()
    ui_path = path.with_suffix(".t3ui")
    before_bytes = path.read_bytes()
    before_ui_bytes = ui_path.read_bytes()
    before = read_graph(path)
    before_ui = read_graph(ui_path)
    graph, changes = prepare(read_graph(path), mix_only=args.mix_only)
    if args.mix_only:
        ui, ui_changes = read_graph(ui_path), {}
    else:
        ui, ui_changes = prepare_ui(read_graph(ui_path))
    if len(graph["Children"]) != len(before["Children"]) or graph["Connections"] != before["Connections"]:
        raise ValueError("Audio-only change unexpectedly altered graph topology")
    if ui["SymbolChildUis"] != before_ui["SymbolChildUis"]:
        raise ValueError("Timeline repair unexpectedly altered node layout")
    print(json.dumps({"sourceSha256": hashlib.sha256(before_bytes).hexdigest(),
                      "uiSourceSha256": hashlib.sha256(before_ui_bytes).hexdigest(),
                      "changes": changes, "uiChanges": ui_changes}, indent=2))
    if args.output:
        output = args.output.resolve()
        if "Symbols" in output.parts:
            raise ValueError("Staged output must be outside every Symbols directory")
        dump(output, graph)
    if args.ui_output:
        ui_output = args.ui_output.resolve()
        if "Symbols" in ui_output.parts:
            raise ValueError("Staged UI output must be outside every Symbols directory")
        dump(ui_output, ui)
    if args.apply:
        if editor_running():
            raise RuntimeError("Close TiXL after saving before applying the staged timeline")
        if path.read_bytes() != before_bytes or ui_path.read_bytes() != before_ui_bytes:
            raise ValueError("Graph or UI changed during preparation")
        if not args.output or not args.ui_output:
            raise ValueError("Stage and audit both files before --apply")
        if read_graph(args.output.resolve()) != graph or read_graph(args.ui_output.resolve()) != ui:
            raise ValueError("Staged graph/UI differs from planned change")
        BACKUPS.mkdir(parents=True, exist_ok=True)
        backup = BACKUPS / (path.stem + "-before-rebalance-" + hashlib.sha256(before_bytes).hexdigest()[:12] + path.suffix)
        ui_backup = BACKUPS / (ui_path.stem + "-before-rebalance-" + hashlib.sha256(before_ui_bytes).hexdigest()[:12] + ui_path.suffix)
        if not backup.exists():
            shutil.copy2(path, backup)
        if not ui_backup.exists():
            shutil.copy2(ui_path, ui_backup)
        temp = path.with_name(path.name + ".incoming")
        ui_temp = ui_path.with_name(ui_path.name + ".incoming")
        try:
            shutil.copy2(args.output.resolve(), temp)
            shutil.copy2(args.ui_output.resolve(), ui_temp)
            os.replace(temp, path)
            try:
                os.replace(ui_temp, ui_path)
            except OSError:
                shutil.copy2(backup, path)
                raise
        finally:
            temp.unlink(missing_ok=True)
            ui_temp.unlink(missing_ok=True)
        print(json.dumps({"installed": [str(path), str(ui_path)],
                          "backups": [str(backup), str(ui_backup)]}))


if __name__ == "__main__":
    main()

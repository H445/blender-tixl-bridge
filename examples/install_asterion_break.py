"""Install chopped break AudioClips and matching TiXL video accents.

The editor must be closed through its debug bridge. This edits the saved home
graph deliberately, retaining every existing scene node and TimeClip.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

from install_asterion_audio import (AUDIO, BACKUPS, BUS_INPUT, CLIP_OUTPUT,
                                    CLIP_SYMBOL, CLIP_TIME_OUTPUT, DEFAULT_GRAPH,
                                    GRAPH_ID, inspect_audio, link, read_graph, uid,
                                    value)

sys.path.insert(0, str(AUDIO))
from break_pattern import ACTIVE_WINDOWS, visual_keys  # noqa: E402


BREAK_FILE = "asterion_amen_chops_120bpm.wav"
BREAK_BUS = "Audio | mission audio bus"
TIME_NAME = "Main / clip to scene time"
TEARS_NAME = "Story FX | rhythmic tears within windows"
COLOR_NAME = "Post FX | glitch blend RGB + alpha"
SCANLINE_NAME = "Post FX | 03 scanline signal"
CURVE_SYMBOL = "b724ea74-d5d7-4928-9cd1-7a7850e4e179"
CURVE_OUTPUT = "fc51bee8-091c-4c66-a7df-12f6f69e3783"
CURVE_INPUT = "108cb829-5f9e-4a45-bc6b-7cf40a0a0f89"
CURVE_TIME_INPUT = "2c24d4fe-6c96-4502-bf76-dac756a16215"
SCENE_TIME_OUTPUT = "c1dbdb9e-a7ad-424b-b2ba-94bd9ce71daf"
ADD_SYMBOL = "c160f925-0a66-4505-a569-cadd878dbb6f"
ADD_A = "e3550929-8905-4cdf-bc85-c31e97da4baa"
ADD_B = "993d59bb-1fc0-4857-a36d-629b0e7aa0d2"
ADD_OUTPUT = "5ce9c625-f890-4620-9747-c98eab4b9447"
TEARS_OUTPUT = "e011dd8c-1b9c-458f-8960-e6c38e83ca74"
COLOR_ALPHA = "6ce53000-34d6-4d9a-aef3-164fd223f6d2"
SCANLINE_AMOUNT = "f76c6202-34dc-4c10-adab-c10cb7665fed"
SCANLINE_FLICKER = "5cb6a27b-db0d-4d85-83aa-87316ba6f5a0"


def time_clip(start, end):
    return {"Id": CLIP_TIME_OUTPUT,
            "OutputData": {"Type": "T3.Core.Animation.TimeClip",
                           "TimeClip": {
                               "TimeRange": {"Start": start/2, "End": end/2},
                               "SourceRange": {"Start": start, "End": end},
                               "LayerIndex": 5, "SourceUnit": "Seconds"}}}


def curve_value(baseline, scale):
    return {"Curve": {"PreCurve": "Constant", "PostCurve": "Constant",
                      "Keys": [{"Time": t, "Value": round(v, 5),
                                "InInterpolation": "Linear",
                                "OutInterpolation": "Linear"}
                               for t, v in visual_keys(baseline=baseline,
                                                       scale=scale)]}}


def install(graph, ui):
    if graph["Id"] != GRAPH_ID or ui["Id"] != GRAPH_ID:
        raise ValueError("Expected the AsterionBreakaway home graph")
    names = {child.get("Name"): child for child in graph["Children"]}
    required = (BREAK_BUS, TIME_NAME, TEARS_NAME, COLOR_NAME, SCANLINE_NAME)
    if any(name not in names for name in required):
        raise ValueError("A required audio or video node is missing")
    if any((name or "").startswith("Break | ") for name in names):
        raise ValueError("The chopped break is already installed")
    bus, scene_time, tears, color, scanline = (names[name] for name in required)
    if bus["SymbolName"] != "Lib.io.audio.AudioBus":
        raise ValueError("Expected native TiXL AudioBus")
    old_alpha = link(tears["Id"], TEARS_OUTPUT, color["Id"], COLOR_ALPHA)
    if graph["Connections"].count(old_alpha) != 1:
        raise ValueError("Existing glitch alpha route changed")
    old_amount = [edge for edge in graph["Connections"]
                  if edge["TargetParentOrChildId"] == scanline["Id"]
                  and edge["TargetSlotId"] == SCANLINE_AMOUNT]
    if len(old_amount) != 1 or names.get("Moon Fluid | irregular signal drift", {}).get("Id") != old_amount[0]["SourceParentOrChildId"]:
        raise ValueError("Existing scanline drift route changed")
    if any(edge["TargetParentOrChildId"] == scanline["Id"]
           and edge["TargetSlotId"] == SCANLINE_FLICKER
           for edge in graph["Connections"]):
        raise ValueError("Scanline flicker is already wired")

    def child(name, symbol, symbol_name, x, y, inputs, outputs=()):
        result = {"Id": uid(name), "SymbolId": symbol,
                  "SymbolName": symbol_name, "Name": "Break | " + name,
                  "InputValues": inputs, "Outputs": list(outputs)}
        if any(c["Id"] == result["Id"] for c in graph["Children"]):
            raise ValueError(f"Conflicting node id for {name}")
        graph["Children"].append(result)
        ui["SymbolChildUis"].append({"ChildId": result["Id"],
                                     "Position": {"X": x, "Y": y}})
        return result

    for index, (start, end) in enumerate(ACTIVE_WINDOWS):
        clip = child(f"{start:02d}-{end:03d}s chopped drums", CLIP_SYMBOL,
                     "Lib.io.audio.AudioClip", 21360, -2150+index*290,
                     [value("625951af-5f99-4171-b5b0-c97413121f56",
                            "System.String",
                            f"AsterionBreakaway:audio/{BREAK_FILE}"),
                      value("06b8b927-ec47-4392-bb67-b9a140cc852b",
                            "System.Single", .67)],
                     [time_clip(start, end)])
        graph["Connections"].append(link(clip["Id"], CLIP_OUTPUT,
                                         bus["Id"], BUS_INPUT))

    gate = child("120 BPM chop accents", CURVE_SYMBOL,
                 "Lib.numbers.curve.SampleCurve", 5460, -4200,
                 [value(CURVE_INPUT, "T3.Core.DataTypes.Curve",
                        curve_value(0, 1))])
    intensity = child("scanline glitch on chops", CURVE_SYMBOL,
                      "Lib.numbers.curve.SampleCurve", 18900, -2250,
                      [value(CURVE_INPUT, "T3.Core.DataTypes.Curve",
                             curve_value(0, .34))])
    alpha = child("add break to story tears", ADD_SYMBOL,
                  "Lib.numbers.float.basic.Add", 6300, -3605, [])
    amount = child("add break to scanline drift", ADD_SYMBOL,
                   "Lib.numbers.float.basic.Add", 19740, -1785, [])
    for curve in (gate, intensity):
        graph["Connections"].append(link(scene_time["Id"], SCENE_TIME_OUTPUT,
                                         curve["Id"], CURVE_TIME_INPUT))
    graph["Connections"].remove(old_alpha)
    graph["Connections"].remove(old_amount[0])
    graph["Connections"].extend((
        link(tears["Id"], TEARS_OUTPUT, alpha["Id"], ADD_A),
        link(gate["Id"], CURVE_OUTPUT, alpha["Id"], ADD_B),
        link(alpha["Id"], ADD_OUTPUT, color["Id"], COLOR_ALPHA),
        link(gate["Id"], CURVE_OUTPUT, scanline["Id"], SCANLINE_FLICKER),
        link(old_amount[0]["SourceParentOrChildId"],
             old_amount[0]["SourceSlotId"], amount["Id"], ADD_A),
        link(intensity["Id"], CURVE_OUTPUT, amount["Id"], ADD_B),
        link(amount["Id"], ADD_OUTPUT, scanline["Id"], SCANLINE_AMOUNT),
    ))
    color_ui = next(item for item in ui["SymbolChildUis"]
                    if item["ChildId"] == color["Id"])
    if color_ui["Position"] != {"X": 5880.0, "Y": -2695.0}:
        raise ValueError("Glitch color node moved; preserve the user's layout")
    color_ui["Position"] = {"X": 6720.0, "Y": -2695.0}
    return graph, ui


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--graph", type=Path, default=DEFAULT_GRAPH)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    graph_path = args.graph.resolve()
    ui_path = graph_path.with_suffix(".t3ui")
    source = AUDIO / BREAK_FILE
    inspect_audio(source)
    graph, ui = install(read_graph(graph_path), read_graph(ui_path))
    ids = {child["Id"] for child in graph["Children"]}
    assert len(ids) == len(graph["Children"])
    assert all(edge["SourceParentOrChildId"] in ids
               and edge["TargetParentOrChildId"] in ids
               for edge in graph["Connections"])
    print("ASTERION_BREAK_PLAN", len(ids), "children",
          len(graph["Connections"]), "connections",
          len(visual_keys()), "shared visual keys")
    if args.dry_run:
        return
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = BACKUPS / f"before-break-{stamp}"
    backup.mkdir(parents=True)
    shutil.copy2(graph_path, backup / graph_path.name)
    shutil.copy2(ui_path, backup / ui_path.name)
    asset = graph_path.parent.parent / "Assets/audio" / BREAK_FILE
    if asset.exists() and asset.read_bytes() != source.read_bytes():
        raise ValueError(f"A different break asset already exists: {asset}")
    asset.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, asset)
    graph_path.write_text(json.dumps(graph, indent=2)+"\n", encoding="utf-8")
    ui_path.write_text(json.dumps(ui, indent=2)+"\n", encoding="utf-8")
    print("ASTERION_BREAK_INSTALLED", graph_path, "backup", backup)


if __name__ == "__main__":
    main()

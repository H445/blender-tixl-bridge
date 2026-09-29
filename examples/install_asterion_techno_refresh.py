"""Replace the out-of-key score with seeded techno and animate TiXL signal SDF.

Run with TiXL closed through its debug bridge. Only the Asterion Home graph and
its audio assets are changed; generated Blender world imports remain separate.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import shutil
from datetime import datetime, timezone
from pathlib import Path

from advanced_spaceship.audio.techno_pattern import LOOP_SECONDS, SEED, signal_events
from install_asterion_audio import (AUDIO, BACKUPS, BUS_INPUT, CLIP_OUTPUT,
                                    CLIP_SYMBOL, CLIP_TIME_OUTPUT, DEFAULT_GRAPH,
                                    GRAPH_ID, inspect_audio, link, read_graph,
                                    uid, value)
from install_asterion_break import (CURVE_INPUT, CURVE_OUTPUT, CURVE_SYMBOL,
                                    CURVE_TIME_INPUT, SCENE_TIME_OUTPUT)


OLD_SCORE = "asterion_score_120bpm.wav"
ELECTRONIC = "asterion_music_electronic_120bpm.wav"
DRUMS = "asterion_music_techno_drums_120bpm.wav"
OLD_NAME = "Audio | score clip"
NEW_NAME = "Music | seeded techno drums clip"
TIME_NAME = "Main / clip to scene time"

SLOT = {
    "torus_out": "14cd4d1f-0b9b-43c4-93cc-d730c137cee8",
    "torus_radius": "5fe2ab92-f8e5-400d-b5a3-197f20570d6f",
    "torus_thickness": "6a392bc1-2adf-4a50-bb3f-5d4f2a63bf0b",
    "rotate_in": "6204058c-ab34-46ad-af85-db3eeb718970",
    "rotate_angle": "5e037357-1a5c-4011-98ed-df061ea890ac",
    "rotate_axis": "c4ed2ce7-8f83-4999-ae7a-d3bd53ac1ab9",
    "rotate_out": "b1730fd1-dbf9-4415-b2ad-e53b3e9c7a96",
    "noise_in": "1799f18f-92c5-4885-b6c1-6a196eee805f",
    "noise_amount": "285d7cd9-1057-4ea8-bd0b-20ff52adc562",
    "noise_offset": "6cd7b3ca-323c-4a69-989b-1b10009b8a90",
    "vector_x": "084d5d0d-8fd4-431d-bf6c-8f082cce1d3f",
    "vector_y": "458891b9-0244-401a-b0a5-3a7ee365e7cb",
    "vector_out": "aedaead8-ccf0-43f0-9188-a79af8d45250",
    "ascii_scale": "4623488a-cef2-4aaa-bfea-54e39e0b5653",
    "ascii_mix": "68801326-950b-4675-8450-56abf64e8518",
    "tv_amount": "38529a44-4622-4c87-886e-72f4400ec468",
}


def curve(keys):
    points = sorted((round(float(t), 5), round(float(v), 5)) for t, v in keys)
    if points[0][0] != 0 or points[-1][0] != LOOP_SECONDS:
        raise ValueError("Curve must close at both loop endpoints")
    if any(not math.isfinite(v) for _, v in points):
        raise ValueError("Non-finite signal curve")
    # Duplicate pulse timestamps are collapsed deterministically.
    unique = {}
    for t, v in points:
        unique[t] = max(v, unique.get(t, -math.inf))
    return {"Curve": {"PreCurve": "Constant", "PostCurve": "Constant",
                      "Keys": [{"Time": t, "Value": v,
                                "InInterpolation": "Linear",
                                "OutInterpolation": "Linear"}
                               for t, v in sorted(unique.items())]}}


def pulse_curve(*, baseline, scale, duration):
    keys = [(0, baseline), (LOOP_SECONDS, baseline)]
    for event in signal_events():
        t = event.time
        peak = baseline + scale * event.gain
        keys.extend(((max(0, t - .018), baseline), (t, peak),
                     (min(LOOP_SECONDS, t + duration*.42),
                      baseline + (peak-baseline)*.38),
                     (min(LOOP_SECONDS, t + duration), baseline)))
    return curve(keys)


def morph_curves():
    rng = random.Random(SEED + 491)
    radius = [(0, .47)]
    thickness = [(0, .036)]
    noise = [(0, .042)]
    tilt = [(0, 0)]
    offset_x = [(0, 0)]
    offset_y = [(0, 0)]
    for t in range(2, LOOP_SECONDS, 2):
        seam = math.sin(math.pi*t/LOOP_SECONDS)
        radius.append((t, .47 + seam*rng.uniform(-.17, .20)))
        thickness.append((t, .036 + seam*rng.uniform(-.016, .043)))
        noise.append((t, .042 + seam*rng.uniform(-.025, .12)))
        tilt.append((t, 1080*t/LOOP_SECONDS + seam*rng.uniform(-25, 25)))
        offset_x.append((t, 2.4*math.sin(2*math.pi*4*t/LOOP_SECONDS)))
        offset_y.append((t, 1.9*math.sin(2*math.pi*7*t/LOOP_SECONDS)))
    for channel, end in ((radius, .47), (thickness, .036), (noise, .042),
                         (tilt, 1080), (offset_x, 0), (offset_y, 0)):
        channel.append((LOOP_SECONDS, end))
    return dict(radius=curve(radius), thickness=curve(thickness),
                noise=curve(noise), tilt=curve(tilt),
                offset_x=curve(offset_x), offset_y=curve(offset_y))


def install(graph, ui):
    if graph["Id"] != GRAPH_ID or ui["Id"] != GRAPH_ID:
        raise ValueError("Expected AsterionBreakaway Home")
    names = {c.get("Name"): c for c in graph["Children"]}
    if NEW_NAME in names:
        raise ValueError("Techno refresh already installed")
    score = names[OLD_NAME]
    bus = names["Audio | mission audio bus"]
    if score["SymbolName"] != "Lib.io.audio.AudioClip":
        raise ValueError("Expected native score AudioClip")
    score_edges = [e for e in graph["Connections"]
                   if e["SourceParentOrChildId"] == score["Id"]
                   or e["TargetParentOrChildId"] == score["Id"]]
    if score_edges != [link(score["Id"], CLIP_OUTPUT, bus["Id"], BUS_INPUT)]:
        raise ValueError("Score clip has user routing; preserve it")
    score_ui = next(x for x in ui["SymbolChildUis"] if x["ChildId"] == score["Id"])
    graph["Children"].remove(score)
    graph["Connections"].remove(score_edges[0])
    ui["SymbolChildUis"].remove(score_ui)

    clip = {"Id": uid("music/techno-drums"), "SymbolId": CLIP_SYMBOL,
            "SymbolName": "Lib.io.audio.AudioClip", "Name": NEW_NAME,
            "InputValues": [
                value("625951af-5f99-4171-b5b0-c97413121f56", "System.String",
                      f"AsterionBreakaway:audio/{DRUMS}"),
                value("06b8b927-ec47-4392-bb67-b9a140cc852b",
                      "System.Single", .66)],
            "Outputs": [{"Id": CLIP_TIME_OUTPUT,
                         "OutputData": {"Type": "T3.Core.Animation.TimeClip",
                                        "TimeClip": {
                                            "TimeRange": {"Start": 0, "End": 54},
                                            "SourceRange": {"Start": 0, "End": 108},
                                            "LayerIndex": 1, "SourceUnit": "Seconds"}}}]}
    graph["Children"].append(clip)
    graph["Connections"].append(link(clip["Id"], CLIP_OUTPUT,
                                     bus["Id"], BUS_INPUT))
    ui["SymbolChildUis"].append({"ChildId": clip["Id"],
                                 "Position": score_ui["Position"]})

    def set_input(child, slot, kind, data):
        existing = next((v for v in child["InputValues"] if v["Id"] == slot), None)
        if existing:
            existing["Value"] = data
        else:
            child["InputValues"].append(value(slot, kind, data))

    set_input(names["Signal | ASCII accents at 120 BPM"], CURVE_INPUT,
              "T3.Core.DataTypes.Curve",
              pulse_curve(baseline=0, scale=.17, duration=.12))
    set_input(names["Signal | SDF scan accents"], CURVE_INPUT,
              "T3.Core.DataTypes.Curve",
              pulse_curve(baseline=.042, scale=.19, duration=.30))
    set_input(names["Signal | ASCII on sparse chops"], SLOT["ascii_scale"],
              "System.Single", 9.0)
    set_input(names["Signal | ASCII on sparse chops"], SLOT["ascii_mix"],
              "System.Single", .18)
    set_input(names["Post FX | 03 scanline signal"], SLOT["tv_amount"],
              "System.Single", .024)

    torus = names["Signal | torus signed distance"]
    noise_node = names["Signal | SDF turbulent rim"]
    source_time = names[TIME_NAME]
    original_edge = link(torus["Id"], SLOT["torus_out"],
                         noise_node["Id"], SLOT["noise_in"])
    if graph["Connections"].count(original_edge) != 1:
        raise ValueError("SDF field path changed; refusing insertion")
    graph["Connections"].remove(original_edge)
    by_id = {c["Id"] for c in graph["Children"]}

    def add(name, symbol, symbol_name, x, y, inputs=()):
        child = {"Id": uid("techno/" + name), "SymbolId": symbol,
                 "SymbolName": symbol_name, "Name": "Techno | " + name,
                 "InputValues": list(inputs), "Outputs": []}
        if child["Id"] in by_id:
            raise ValueError("Techno node ID collision")
        by_id.add(child["Id"])
        graph["Children"].append(child)
        ui["SymbolChildUis"].append({"ChildId": child["Id"],
                                     "Position": {"X": x, "Y": y}})
        return child

    rotate = add("SDF rotating field", "7d9e1b37-5b44-40a3-bd81-281397e76e1a",
                 "Lib.field.space.RotateAxis", 20980, -4020,
                 [value(SLOT["rotate_axis"], "System.Int32", 0)])
    noise_ui = next(x for x in ui["SymbolChildUis"] if x["ChildId"] == noise_node["Id"])
    noise_ui["Position"] = {"X": 21400, "Y": -4020}
    graph["Connections"].extend((
        link(torus["Id"], SLOT["torus_out"], rotate["Id"], SLOT["rotate_in"]),
        link(rotate["Id"], SLOT["rotate_out"], noise_node["Id"], SLOT["noise_in"])))

    channels = morph_curves()
    curve_positions = dict(radius=(20560, -4450), thickness=(20560, -4740),
                           tilt=(20980, -4450), noise=(21400, -4450),
                           offset_x=(21000, -5050), offset_y=(21400, -5050))
    curves = {}
    for key, data in channels.items():
        x, y = curve_positions[key]
        node = add("SDF " + key, CURVE_SYMBOL,
                   "Lib.numbers.curve.SampleCurve", x, y,
                   [value(CURVE_INPUT, "T3.Core.DataTypes.Curve", data)])
        curves[key] = node
        graph["Connections"].append(link(source_time["Id"], SCENE_TIME_OUTPUT,
                                         node["Id"], CURVE_TIME_INPUT))
    vector = add("SDF fluid noise travel",
                 "94a5de3b-ee6a-43d3-8d21-7b8fe94b042b",
                 "Types.Values.Vector3", 21400, -4740,
                 [value("627f766e-056c-413e-8530-838d673bd031",
                        "System.Single", 0.0)])
    for key, target, slot in (
            ("radius", torus, SLOT["torus_radius"]),
            ("thickness", torus, SLOT["torus_thickness"]),
            ("tilt", rotate, SLOT["rotate_angle"]),
            ("noise", noise_node, SLOT["noise_amount"]),
            ("offset_x", vector, SLOT["vector_x"]),
            ("offset_y", vector, SLOT["vector_y"])):
        if any(e["TargetParentOrChildId"] == target["Id"] and
               e["TargetSlotId"] == slot for e in graph["Connections"]):
            raise ValueError(f"SDF input already connected: {key}")
        graph["Connections"].append(link(curves[key]["Id"], CURVE_OUTPUT,
                                         target["Id"], slot))
    graph["Connections"].append(link(vector["Id"], SLOT["vector_out"],
                                     noise_node["Id"], SLOT["noise_offset"]))
    return graph, ui


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--graph", type=Path, default=DEFAULT_GRAPH)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    graph_path = args.graph.resolve()
    ui_path = graph_path.with_suffix(".t3ui")
    graph, ui = install(read_graph(graph_path), read_graph(ui_path))
    ids = {c["Id"] for c in graph["Children"]}
    if len(ids) != len(graph["Children"]):
        raise ValueError("Duplicate Home node IDs")
    if any(e["SourceParentOrChildId"] not in ids or
           e["TargetParentOrChildId"] not in ids for e in graph["Connections"]):
        raise ValueError("Missing Home connection endpoint")
    if len({x["ChildId"] for x in ui["SymbolChildUis"]}) != len(ids):
        raise ValueError("Missing or duplicate Home UI position")
    for filename in (ELECTRONIC, DRUMS):
        inspect_audio(AUDIO / filename)
    print("TECHNO_PLAN", len(ids), "nodes", len(graph["Connections"]), "edges")
    if args.dry_run:
        return
    backup = BACKUPS / ("before-techno-refresh-" +
                        datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
    backup.mkdir(parents=True)
    shutil.copy2(graph_path, backup / graph_path.name)
    shutil.copy2(ui_path, backup / ui_path.name)
    assets = graph_path.parent.parent / "Assets/audio"
    shutil.copy2(AUDIO / ELECTRONIC, assets / ELECTRONIC)
    shutil.copy2(AUDIO / DRUMS, assets / DRUMS)
    graph_path.write_text(json.dumps(graph, indent=2) + "\n", encoding="utf-8")
    ui_path.write_text(json.dumps(ui, indent=2) + "\n", encoding="utf-8")
    (assets / OLD_SCORE).unlink(missing_ok=True)
    print("TECHNO_INSTALLED", graph_path, "backup", backup)


if __name__ == "__main__":
    main()

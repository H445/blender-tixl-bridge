"""Stage Asterion's HDR bloom, restrained 120 BPM pulse, and color grade.

This stages a candidate Home graph outside TiXL Symbols. Install the staged
.t3/.t3ui only after the editor work is saved and TiXL is closed through the
debug bridge, then restart and inspect representative frames.
"""

import json
import re
import sys
import uuid
from pathlib import Path


HOME_ID = "564f37c0-cb8c-5aff-97b3-683ec4ab5477"
SYMBOLS = {
    "grade": ("42d86738-d644-47c8-ab92-cc426d958e51", "Lib.image.color.ColorGrade"),
    "curve": ("b724ea74-d5d7-4928-9cd1-7a7850e4e179", "Lib.numbers.curve.SampleCurve"),
    "multiply": ("17b60044-9125-4961-8a79-ca94697b3726", "Lib.numbers.float.basic.Multiply"),
    "add": ("c160f925-0a66-4505-a569-cadd878dbb6f", "Lib.numbers.float.basic.Add"),
}


def read(path):
    raw = Path(path).read_text(encoding="utf-8")
    return json.loads(re.sub(r'("[0-9a-fA-F-]{36}")/\*.*?\*/', r"\1", raw))


def value(slot, kind, item):
    return {"Id": slot, "Type": kind, "Value": item}


def edge(source, output, target, input_slot):
    return {"SourceParentOrChildId": source["Id"], "SourceSlotId": output,
            "TargetParentOrChildId": target["Id"], "TargetSlotId": input_slot}


def set_value(child, slot, kind, item):
    inputs = child.setdefault("InputValues", [])
    found = next((entry for entry in inputs if entry["Id"] == slot), None)
    if found:
        found.update(Type=kind, Value=item)
    else:
        inputs.append(value(slot, kind, item))


def curve(points):
    return {"Curve": {"PreCurve": "Constant", "PostCurve": "Constant",
                      "Keys": [{"Time": float(t), "Value": float(v),
                                "InInterpolation": "Smooth", "OutInterpolation": "Smooth",
                                "InTangentAngle": 0.0, "OutTangentAngle": 0.0}
                               for t, v in points]}}


def stage(source, output_dir):
    source, output_dir = Path(source), Path(output_dir)
    if output_dir.resolve().is_relative_to(source.parent.resolve()):
        raise ValueError("Stage Home graph outside the live TiXL Symbols tree")
    graph, ui = read(source), read(source.with_suffix(".t3ui"))
    if graph["Id"] != HOME_ID or ui["Id"] != HOME_ID:
        raise ValueError("Asterion Home graph identity changed")
    children, connections = graph["Children"], graph["Connections"]
    by_name = {child.get("Name"): child for child in children}
    names = ("Render scene", "Tone mapping", "Post FX | 01 spectral bloom",
             "Story FX | ion starburst", "Moon Fluid | spectral breathing",
             "Main / clip to scene time", "Post FX | beat pulse | 120 BPM")
    if any(name not in by_name for name in names):
        raise ValueError("Expected render, effect, or 120 BPM clock node is missing")
    if any(name.startswith("Thruster HDR |") for name in by_name if name):
        raise ValueError("HDR grade already installed; preserve editor edits")
    render, tone, bloom, star, moon, time, beat = (by_name[name] for name in names)

    def replace(old, new):
        if connections.count(old) != 1 or new in connections:
            raise ValueError("The active postprocessing route has changed")
        connections.remove(old)
        connections.append(new)

    # TiXL renders to RGBA16F. Extract emissive highlights before the AgX tone
    # mapper compresses them; keep the existing artistic star/glitch chain LDR.
    replace(edge(render, "7a4c4feb-be2f-463e-96c6-cd9a6bad77a2", tone,
                 "72e51856-bc8f-4bcf-a6d8-6c7b4f8b0583"),
            edge(render, "7a4c4feb-be2f-463e-96c6-cd9a6bad77a2", bloom,
                 "97d8f330-5957-4309-8c56-d94c1266f6cb"))
    replace(edge(tone, "05c886f7-2c2c-4fe8-8b66-d6967dc43367", bloom,
                 "97d8f330-5957-4309-8c56-d94c1266f6cb"),
            edge(bloom, "f3fa372d-f037-48fd-8a8d-a0135b4c20cb", tone,
                 "72e51856-bc8f-4bcf-a6d8-6c7b4f8b0583"))
    old_star = edge(bloom, "f3fa372d-f037-48fd-8a8d-a0135b4c20cb", star,
                    "afcba3d4-b7db-40bd-919a-d4f49b1bf7fc")
    if connections.count(old_star) != 1:
        raise ValueError("Bloom to starburst route was edited")
    connections.remove(old_star)

    def add(key, name, x, y, settings=()):
        symbol_id, symbol_name = SYMBOLS[key]
        child = {"Id": str(uuid.uuid5(uuid.NAMESPACE_URL, HOME_ID + "/thruster-hdr/" + name)),
                 "SymbolId": symbol_id, "SymbolName": symbol_name,
                 "Name": "Thruster HDR | " + name,
                 "InputValues": list(settings), "Outputs": []}
        children.append(child)
        ui["SymbolChildUis"].append({"ChildId": child["Id"],
                                     "Position": {"X": x, "Y": y}})
        return child

    grade = add("grade", "ship contrast and cool shadows", 18900, 0, [
        value("16231de9-2e85-4a9a-a2d1-99dfac18a0f6", "System.Single", 1.08),
        value("4dc44a7b-fe7c-4807-aaaa-53fb553de017", "System.Numerics.Vector4",
              {"X": .495, "Y": .5, "Z": .505, "W": .5}),
        value("be4dc864-a5f9-4356-91f9-58de8056a3a8", "System.Numerics.Vector4",
              {"X": .5, "Y": .5, "Z": .5, "W": .5}),
        value("e8cc8a26-313e-4399-b800-901019bbaa78", "System.Numerics.Vector4",
              {"X": .495, "Y": .5, "Z": .505, "W": .25}),
    ])
    envelope = add("curve", "throttle and warp glow envelope", 17640, -2700, [
        value("108cb829-5f9e-4a45-bc6b-7cf40a0a0f89", "T3.Core.DataTypes.Curve",
              curve([(0, .8), (9, .8), (12, 1.25), (16, .7), (24, .7),
                     (29, .35), (36, .7), (60, .7), (66, .35), (72, .8),
                     (83, .9), (87, 1.35), (91, .8), (96, .7),
                     (100, .35), (104, .9), (105, 1.3), (107, .95),
                     (108, .8)])),
    ])
    beat_scale = add("multiply", "subtle beat glow modulation", 17640, -2350, [
        value("5ae4bb07-4214-4ec3-a499-24d9f6d404a5", "System.Single", .075),
    ])
    intensity = add("add", "mission plus beat glow", 18060, -2350)
    old_intensity = edge(moon, "ae4addf0-08cf-4b25-9515-4fef9359d183", bloom,
                         "bb706662-2555-4f3b-a81e-60e04f052f36")
    if connections.count(old_intensity) != 1:
        raise ValueError("Bloom intensity is no longer on the expected route")
    connections.remove(old_intensity)
    connections.extend((
        edge(tone, "05c886f7-2c2c-4fe8-8b66-d6967dc43367", grade,
             "777b2c27-a3c8-40d0-a196-80a08af51296"),
        edge(grade, "1680781d-af5e-4b77-beb6-3e4a12d73d59", star,
             "afcba3d4-b7db-40bd-919a-d4f49b1bf7fc"),
        edge(time, "c1dbdb9e-a7ad-424b-b2ba-94bd9ce71daf", envelope,
             "2c24d4fe-6c96-4502-bf76-dac756a16215"),
        edge(beat, "ae4addf0-08cf-4b25-9515-4fef9359d183", beat_scale,
             "372288fa-3794-47ba-9f91-59240513217a"),
        edge(envelope, "fc51bee8-091c-4c66-a7df-12f6f69e3783", intensity,
             "e3550929-8905-4cdf-bc85-c31e97da4baa"),
        edge(beat_scale, "e011dd8c-1b9c-458f-8960-e6c38e83ca74", intensity,
             "993d59bb-1fc0-4857-a36d-629b0e7aa0d2"),
        edge(intensity, "5ce9c625-f890-4620-9747-c98eab4b9447", bloom,
             "bb706662-2555-4f3b-a81e-60e04f052f36"),
    ))
    set_value(tone, "37d4e1e6-e5a0-40b6-ada9-9481f5a807de", "System.Int32", 5)
    set_value(tone, "b3ac35c2-7f59-49fb-a4ad-84dc5a8c3841", "System.Single", 1.0)
    set_value(bloom, "28e0b719-0888-4ef6-85d9-bbd75f7a4537", "System.Single", 1.15)
    set_value(bloom, "c6a0cadc-9e1c-40ac-97f1-d9271b5376df", "System.Single", 1.2)

    positions = {entry["ChildId"]: entry["Position"]
                 for entry in ui["SymbolChildUis"]}
    # Retain the existing lane arrangement, making one additional column for
    # ColorGrade. Move downstream nodes together so no new overlap is created.
    for child in children:
        cid = child["Id"]
        if cid in (grade["Id"], envelope["Id"], beat_scale["Id"], intensity["Id"]):
            continue
        x = positions[cid]["X"]
        if x >= 19320:
            positions[cid]["X"] = x + 420
    positions[bloom["Id"]]["X"] = 18060
    positions[tone["Id"]]["X"] = 18480
    positions[star["Id"]]["X"] = 19320

    ids = {child["Id"] for child in children}
    if len(ids) != len(children) or set(positions) != ids:
        raise ValueError("Graph/UI child sets disagree")
    if any(link["SourceParentOrChildId"] not in ids or
           link["TargetParentOrChildId"] not in ids for link in connections):
        raise ValueError("Graph has a dangling edge")
    if len({tuple(link.values()) for link in connections}) != len(connections):
        raise ValueError("Graph has duplicate edges")
    output_dir.mkdir(parents=True, exist_ok=True)
    for name, content in ((source.name, graph),
                          (source.with_suffix(".t3ui").name, ui)):
        (output_dir / name).write_text(json.dumps(content, indent=2) + "\n",
                                       encoding="utf-8")
    print({"staged": str(output_dir), "nodes": len(children),
           "connections": len(connections), "hdrBloomThreshold": 1.15,
           "toneMap": "AgX Punchy", "beatBpm": 120})


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("Usage: tune_asterion_hdr_grade.py <home.t3> <stage-dir>")
    stage(sys.argv[1], sys.argv[2])

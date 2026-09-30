"""Stage looped SDF ribbons in place of Asterion's legacy copper ring mesh.

Hide the legacy mesh in Blender and sync first. This changes the anchored
world field while retaining the planet surface effect, dust, and timeline.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import os
import random
import shutil
import sys
import uuid
from pathlib import Path

from anchor_asterion_sdf import CURVE, CURVE_OUT, set_value, vector
from install_asterion_audio import BACKUPS, DEFAULT_GRAPH, GRAPH_ID, read_graph, value
from rebalance_asterion_audio import editor_running

LOOP = 108
CURVE_SYMBOL = "b724ea74-d5d7-4928-9cd1-7a7850e4e179"
CURVE_TIME = "2c24d4fe-6c96-4502-bf76-dac756a16215"
FIELD_INPUT = "7248c680-7279-4c1d-b968-3864cb849c77"


def place_added_controls(graph, ui, new_ids, consumer_id):
    """Fit this branch near its consumer while preserving the saved layout."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
    from connected_graph_layout import count_wire_crossings
    by_id = {v["ChildId"]: v for v in ui["SymbolChildUis"]}
    anchor = by_id[consumer_id]["Position"]
    occupied = [v["Position"] for v in ui["SymbolChildUis"] if v["ChildId"] not in new_ids]
    best = None
    for dx in (420, 840, 1260):
        for step in range(-20, 21):
            x, y = anchor["X"] - dx, anchor["Y"] + step * 210
            positions = [vector(x, y)] + [vector(x - 420, y + (i - 1) * 300) for i in range(3)]
            if any(abs(p['X'] - old['X']) < 260 and abs(p['Y'] - old['Y']) < 180
                   for p in positions for old in occupied):
                continue
            for child_id, position in zip(new_ids, positions):
                by_id[child_id]["Position"] = position
            score = (count_wire_crossings(graph, ui), abs(step), dx)
            if best is None or score < best[0]:
                best = (score, positions)
    if best is None:
        raise ValueError("No clear space for the added SDF controls")
    for child_id, position in zip(new_ids, best[1]):
        by_id[child_id]["Position"] = position

# Three independent orbits: a braided filament and two opening/closing arcs.
# All phase harmonics are integers, so the shape closes after one phase cycle.
DISTANCE_FUNCTION = """p -= Offset;
// Skip the expensive angular field outside its enclosing sphere.
float bounds = length(p) - 1.12;
if (bounds > 0.02) return bounds;
float angle = atan2(p.z, p.x);
float radial = length(p.xz);
float r0 = 0.80 + 0.026*sin(3*angle + 4*A) + 0.018*B*sin(7*angle - 6*A);
float h0 = 0.030*(0.4 + 0.6*B)*sin(4*angle - 5*A);
float t0 = 0.018 + 0.006*sin(5*angle + 8*A) + C;
float d0 = length(float2(radial-r0, p.y-h0)) - t0;

float r1 = 0.895 + 0.035*sin(5*angle - 7*A) + 0.030*B;
float h1 = 0.045*sin(3*angle + 8*A);
float d1 = length(float2(radial-r1, p.y-h1)) - (0.009 + 0.018*B + 0.5*C);
d1 = max(d1, 0.070*(sin(3*angle + 6*A) - (0.3 + 0.5*B)));

float r2 = 0.99 + 0.050*(1-B)*sin(2*angle + 5*A);
float h2 = 0.080*B*sin(2*angle - 3*A);
float d2 = length(float2(radial-r2, p.y-h2)) - (0.009 + 0.018*(1-B) + 0.3*C);
d2 = max(d2, 0.040*(sin(6*angle - 5*A) - (0.4 + 0.3*cos(A))));
// Conservative distance for the angular bends; avoids overshooting thin arcs.
return 0.55 * min(d0, min(d1, d2));
"""


def sample_curve(keys):
    return {"Curve": {"PreCurve": "Constant", "PostCurve": "Constant",
                      "Keys": [{"Time": round(float(t), 6), "Value": round(float(v), 6),
                                "InInterpolation": "Linear", "OutInterpolation": "Linear"}
                               for t, v in keys]}}


def prepare(graph, ui):
    if graph["Id"] != GRAPH_ID or ui["Id"] != GRAPH_ID:
        raise ValueError("Expected Asterion Home")
    names = {c.get("Name"): c for c in graph["Children"]}
    if "Copper SDF | braided orbital ribbons" in names:
        raise ValueError("Orbital ribbons already installed; preserve editor changes")
    transform = names["Copper SDF | field anchored to object"]
    source_time = names["Main / clip to scene time"]
    edges = graph["Connections"]
    new_ids = []

    def link(source, output, target, slot):
        return {"SourceParentOrChildId": source["Id"], "SourceSlotId": output.lower(),
                "TargetParentOrChildId": target["Id"], "TargetSlotId": slot.lower()}

    def add(name, symbol, symbol_name, inputs):
        child = {"Id": str(uuid.uuid5(uuid.NAMESPACE_URL, GRAPH_ID + "/orbital-sdf/" + name)),
                 "SymbolId": symbol, "SymbolName": symbol_name,
                 "Name": "Copper SDF | " + name, "InputValues": inputs, "Outputs": []}
        graph["Children"].append(child)
        new_ids.append(child["Id"])
        ui["SymbolChildUis"].append({"ChildId": child["Id"],
                                     "Position": {"X": 9000., "Y": -290. * len(ui["SymbolChildUis"])}})
        return child

    field = add("braided orbital ribbons", "637d00e4-ab63-4fe3-8e63-1e206c728841",
                "Lib.field.generate.sdf.CustomSDF",
                [value("bde89b93-224c-4a3f-85ab-d85b0401c02a", "System.String", DISTANCE_FUNCTION),
                 value("64f1812f-7ebd-4231-8a6a-0bbc302bfaff", "System.Numerics.Vector3", vector(0, 0, 0))])
    rng = random.Random(445)
    morph_keys = [(0, .46)] + [(t, rng.uniform(.12, .88)) for t in range(6, LOOP, 6)] + [(LOOP, .46)]
    # 120 BPM: a small geometric surge on each half-second beat.
    beat_keys = [(i / 8, .007 + .007 * (.5 + .5 * math.cos(4 * math.pi * i / 8))**4)
                 for i in range(LOOP * 8 + 1)]
    channels = (
        ("orbital phase", [(0, 0), (LOOP, math.tau)], "3c366d34-c398-410e-972b-d8cc2baffddb"),
        ("chapter shape variation", morph_keys, "874ae9c8-5835-4d0c-9bef-253ac75d19b2"),
        ("120 BPM filament surges", beat_keys, "56e5d5ec-ec59-4ea0-85c1-1eca3dcb5790"),
    )
    for name, keys, slot in channels:
        child = add(name, CURVE_SYMBOL, "Lib.numbers.curve.SampleCurve",
                    [value(CURVE, "T3.Core.DataTypes.Curve", sample_curve(keys))])
        edges.extend((link(source_time, "c1dbdb9e-a7ad-424b-b2ba-94bd9ce71daf", child, CURVE_TIME),
                      link(child, CURVE_OUT, field, slot)))
    old = [e for e in edges if e["TargetParentOrChildId"] == transform["Id"]
           and e["TargetSlotId"].lower() == FIELD_INPUT]
    if len(old) != 1 or old[0]["SourceParentOrChildId"] != names["Signal | SDF turbulent rim"]["Id"]:
        raise ValueError("Anchored world field has different routing; preserve it")
    edges.remove(old[0])
    edges.append(link(field, "1aaaf637-a2f1-4706-909e-fa4fb102619d", transform, FIELD_INPUT))
    # The converted Blender ring normal is (-.062361, .800729, .595772).
    pitch = math.degrees(math.acos(.800729))
    yaw = math.degrees(math.atan2(-.062361, .595772))
    set_value(transform, "5339862d-5a18-4d0c-b908-9277f5997563", "System.Numerics.Vector3", vector(pitch, yaw, 0))
    ray = names["Copper SDF | depth-tested atmospheric contour"]
    set_value(ray, "9715075b-b02b-4290-9332-9bbfe67933f2", "System.Numerics.Vector4", vector(.4, 3.2, 2.5, 1))
    set_value(ray, "3148d927-8779-47ab-9e0a-fa63206f3002", "System.Single", 220)
    set_value(ray, "0b4d60de-261f-4dbf-ad44-6395cda3a496", "System.Single", .02)
    # Native RaymarchField can shade exhausted rays; discard those misses.
    set_value(ray, "1251368b-f8f4-4210-be1e-4d05223caf21", "System.Single", 8)
    ids = {c["Id"] for c in graph["Children"]}
    assert len(ids) == len(graph["Children"])
    assert all(e[k] in ids for e in edges for k in ("SourceParentOrChildId", "TargetParentOrChildId"))
    place_added_controls(graph, ui, new_ids, transform["Id"])
    return graph, ui


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--graph", type=Path, default=DEFAULT_GRAPH)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--ui-output", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    graph, ui = prepare(read_graph(args.graph), read_graph(args.graph.with_suffix(".t3ui")))
    if not args.apply:
        for path, data in ((args.output, graph), (args.ui_output, ui)):
            if any(p.lower() == "symbols" for p in path.resolve().parts):
                raise ValueError("Stage outside Symbols")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    else:
        if editor_running():
            raise RuntimeError("Save and close TiXL through the bridge before installing")
        if read_graph(args.output) != graph:
            raise ValueError("Staged graph differs from planned update")
        staged_ui = read_graph(args.ui_output)
        expected = copy.deepcopy(staged_ui)
        assert len(expected["SymbolChildUis"]) == len(ui["SymbolChildUis"])
        for actual, planned in zip(expected["SymbolChildUis"], ui["SymbolChildUis"]):
            actual["Position"] = planned["Position"]
        if expected != ui:
            raise ValueError("Layout modified data other than positions")
        BACKUPS.mkdir(parents=True, exist_ok=True)
        for dest, staged in ((args.graph, args.output), (args.graph.with_suffix(".t3ui"), args.ui_output)):
            backup = BACKUPS / (dest.stem + "-before-sdf-ribbons-" + hashlib.sha256(dest.read_bytes()).hexdigest()[:12] + dest.suffix)
            if not backup.exists():
                shutil.copy2(dest, backup)
            incoming = dest.with_name(dest.name + ".incoming")
            shutil.copy2(staged, incoming)
            os.replace(incoming, dest)
    print(json.dumps({"children": len(graph['Children']), "connections": len(graph['Connections']), "installed": args.apply}))


if __name__ == "__main__":
    main()

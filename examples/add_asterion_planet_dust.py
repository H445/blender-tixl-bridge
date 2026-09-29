"""Add native TiXL point-sprite dust to Asterion's ember giant and rings.

Run with the editor closed. This updates the user-owned Home graph, keeps a
backup outside Symbols, and retains all existing Blender mesh/effect routes.
"""

import json
import re
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path


GRAPH = Path.home() / "OneDrive/Documents/TiXL4.3-alpha/AsterionBreakaway/Symbols/AsterionBreakaway.t3"
UI = GRAPH.with_suffix(".t3ui")
BACKUPS = Path(__file__).resolve().parent / ".tixl_cache/AsterionBreakaway/graph_backups"


def read(path):
    return json.loads(re.sub(r'("[0-9a-fA-F-]{36}")/\*.*?\*/', r"\1",
                             path.read_text(encoding="utf-8")))


graph, ui = read(GRAPH), read(UI)
if graph["Id"] != "564f37c0-cb8c-5aff-97b3-683ec4ab5477":
    raise ValueError("This edit belongs only to the Asterion demo Home graph")
names = {child.get("Name"): child for child in graph["Children"]}
if any(name.startswith("Ember Dust |") for name in names):
    raise ValueError("Planet dust is already installed; preserve TiXL editor changes")
for required in ("Main / scene", "Main / clip to scene time"):
    if required not in names:
        raise ValueError(f"Expected render route missing: {required}")


def value(slot, kind, data):
    return {"Id": slot, "Type": kind, "Value": data}


def vec3(x, y, z):
    return {"X": x, "Y": y, "Z": z}


def vec4(x, y, z, w):
    return {"X": x, "Y": y, "Z": z, "W": w}


def add(name, symbol, symbol_name, x, y, values):
    child = {"Id": str(uuid.uuid5(uuid.NAMESPACE_URL, graph["Id"] + "/ember-dust/" + name)),
             "SymbolId": symbol, "SymbolName": symbol_name, "Name": "Ember Dust | " + name,
             "InputValues": values, "Outputs": []}
    graph["Children"].append(child)
    ui["SymbolChildUis"].append({"ChildId": child["Id"],
                                 "Position": {"X": float(x), "Y": float(y)}})
    return child


def link(source, output, target, input_slot):
    graph["Connections"].append({"SourceParentOrChildId": source["Id"],
                                 "SourceSlotId": output,
                                 "TargetParentOrChildId": target["Id"],
                                 "TargetSlotId": input_slot})


curve = {"Curve": {"PreCurve": "Constant", "PostCurve": "Constant",
                   "Keys": [{"Time": float(t), "Value": float(v),
                             "InInterpolation": "Linear", "OutInterpolation": "Linear",
                             "InTangentAngle": 0.0, "OutTangentAngle": 0.0}
                            for t, v in ((0, 0), (108, 360))]}}
phase = add("one orbit per project loop", "b724ea74-d5d7-4928-9cd1-7a7850e4e179",
            "Lib.numbers.curve.SampleCurve", 3150, -1150,
            [value("108cb829-5f9e-4a45-bc6b-7cf40a0a0f89",
                   "T3.Core.DataTypes.Curve", curve)])
link(names["Main / clip to scene time"], "c1dbdb9e-a7ad-424b-b2ba-94bd9ce71daf",
     phase, "2c24d4fe-6c96-4502-bf76-dac756a16215")

surface = add("surface points", "1a241222-200b-417d-a8c7-131e3b48cc36",
              "Lib.point.generate.SpherePoints", 3350, -1290,
              [value("0b42b3e6-a6fd-4edc-88b1-d91f9c775023", "System.Int32", 2600),
               value("0bdc6243-3e52-4b1a-b070-731ed27388c6", "System.Single", 18.2),
               value("21140fe1-9fb5-4a79-b03a-7deac242fba2",
                     "System.Numerics.Vector3", vec3(-55, 8, 57)),
               value("15716b21-9905-4c1e-8330-06afc72552a5", "System.Single", .16)])
link(phase, "fc51bee8-091c-4c66-a7df-12f6f69e3783", surface,
     "813df416-a783-433c-9645-921c885c9840")
surface_draw = add("glowing atmospheric grit", "ffd94e5a-bc98-4e70-84d8-cce831e6925f",
                   "Lib.point.draw.DrawPoints", 3620, -1260,
                   [value("cc442161-e9ca-40ea-be3b-f87189d4e155",
                          "System.Numerics.Vector4", vec4(1.0, .62, .34, .42)),
                    value("414c8045-5086-4449-9d9a-03f28c3966b3", "System.Single", .8),
                    value("814fc516-250f-4383-8f20-c2a358bbe4e1", "System.Boolean", False)])
surface_random = add("surface turbulence", "ec0675d7-6b72-4b15-b141-80bdd2367cd8",
                     "Lib.point.modify.RandomizePoints", 3485, -1280,
                     [value("270bcf23-35ee-4c4f-aae5-192435b1aee3",
                            "System.Numerics.Vector3", vec3(.35, .35, .35)),
                      value("b90a5025-41e0-4bcd-b8d5-764756877dd0", "System.Single", .75),
                      value("dd46595e-01e5-4616-9682-3a4eb7f63016",
                            "System.Numerics.Vector4", vec4(.025, .10, .15, .4)),
                      value("4dffb439-da81-477c-8100-34a9ba59b0ee", "System.Single", .23)])
link(surface, "c20f4675-6387-45da-b14f-8d0a3af5e672", surface_random,
     "cb157c8e-98f1-46e9-b197-d17dea896e30")
link(surface_random, "172dcbd2-a475-4514-8620-38f07a0ea4aa", surface_draw,
     "5df18658-ef86-4c0f-8bb4-4ac3fbbf9a33")

# A many-turn spiral spans the same tilted annulus as Blender's dust rings.
ring = add("ring particle cloud", "3352d3a1-ab04-4d0a-bb43-da69095b73fd",
           "Lib.point.generate.RadialPoints", 3350, -925,
           [value("b654ffe2-d46e-4a62-89b3-a9692d5c6481", "System.Int32", 6800),
            value("acce4779-56d6-47c4-9c52-874fca91a3a1", "System.Single", 20.2),
            value("13cbb509-f90c-4ae7-a9d3-a8fc907794e3", "System.Single", 7.7),
            value("94b2a118-f760-4043-933c-31283e6e7006", "System.Single", 47.0),
            value("ca84209e-d821-40c6-b23c-38fc4bbd47b0",
                  "System.Numerics.Vector3", vec3(-55, 8, 57)),
            value("6df5829e-a534-4620-bcd5-9324f94b4f54",
                  "System.Numerics.Vector3", vec3(-.062361, .800729, .595772)),
            value("5f5394b4-b23e-41bf-8089-b5c063623e66",
                  "System.Numerics.Vector4", vec4(1, .72, .45, .9))])
link(phase, "fc51bee8-091c-4c66-a7df-12f6f69e3783", ring,
     "5a3347a2-ba87-4b38-a1a8-94bd0ef70f48")
ring_draw = add("ring motes and debris", "ffd94e5a-bc98-4e70-84d8-cce831e6925f",
                "Lib.point.draw.DrawPoints", 3620, -890,
                [value("cc442161-e9ca-40ea-be3b-f87189d4e155",
                       "System.Numerics.Vector4", vec4(1.0, .54, .22, .46)),
                 value("414c8045-5086-4449-9d9a-03f28c3966b3", "System.Single", .55),
                 value("814fc516-250f-4383-8f20-c2a358bbe4e1", "System.Boolean", False)])
ring_random = add("ring turbulence", "ec0675d7-6b72-4b15-b141-80bdd2367cd8",
                  "Lib.point.modify.RandomizePoints", 3485, -900,
                  [value("270bcf23-35ee-4c4f-aae5-192435b1aee3",
                         "System.Numerics.Vector3", vec3(.65, .40, .65)),
                   value("b90a5025-41e0-4bcd-b8d5-764756877dd0", "System.Single", .85),
                   value("dd46595e-01e5-4616-9682-3a4eb7f63016",
                         "System.Numerics.Vector4", vec4(.04, .13, .20, .48)),
                   value("4dffb439-da81-477c-8100-34a9ba59b0ee", "System.Single", .71),
                   value("f06e85cc-a9b7-44c6-9f77-28c422db9f41", "System.Int32", 1)])
link(ring, "d7605a96-adc6-4a2b-9ba4-33adef3b7f4c", ring_random,
     "cb157c8e-98f1-46e9-b197-d17dea896e30")
link(ring_random, "172dcbd2-a475-4514-8620-38f07a0ea4aa", ring_draw,
     "5df18658-ef86-4c0f-8bb4-4ac3fbbf9a33")

group = names["Main / scene"]
for draw in (surface_draw, ring_draw):
    link(draw, "b73347d9-9d9f-4929-b9df-e2d6db722856", group,
         "9e961f73-1ee7-4369-9ac7-5c653e570b6f")

BACKUPS.mkdir(parents=True, exist_ok=True)
backup = BACKUPS / ("AsterionBreakaway.before-planet-dust-" +
                    datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + ".t3")
shutil.copy2(GRAPH, backup)
shutil.copy2(UI, backup.with_suffix(".t3ui"))
GRAPH.write_text(json.dumps(graph, indent=2) + "\n", encoding="utf-8")
UI.write_text(json.dumps(ui, indent=2) + "\n", encoding="utf-8")
assert read(GRAPH) == graph and read(UI) == ui
print(json.dumps({"graph": str(GRAPH), "backup": str(backup),
                  "surfacePoints": 2600, "ringPoints": 6800}))

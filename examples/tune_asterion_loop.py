"""Make the saved Asterion TiXL composition repeat its complete 108 s journey.

Run after closing TiXL through the debug bridge. The script edits only known
inputs in the user-owned Home graph and stores a backup outside Symbols.
"""

import json
import re
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path


GRAPH = Path.home() / "OneDrive/Documents/TiXL4.3-alpha/AsterionBreakaway/Symbols/AsterionBreakaway.t3"
BACKUPS = Path(__file__).resolve().parent / ".tixl_cache/AsterionBreakaway/graph_backups"
LOOP_INPUT = "887bf3b5-45fa-4db1-a056-199d0a088931"


def read(path):
    return json.loads(re.sub(r'("[0-9a-fA-F-]{36}")/\*.*?\*/', r"\1",
                             path.read_text(encoding="utf-8")))


def set_input(child, slot, kind, value):
    inputs = child.setdefault("InputValues", [])
    found = next((entry for entry in inputs if entry["Id"] == slot), None)
    if found is None:
        inputs.append({"Id": slot, "Type": kind, "Value": value})
    else:
        found.update(Type=kind, Value=value)


graph = read(GRAPH)
by_name = {child.get("Name"): child for child in graph["Children"]}
for required in ("Blender object: moon", "Edit move timing here", "Main / clips",
                 "Story FX | glow follows the mission",
                 "Story FX | signal disturbance windows"):
    if required not in by_name:
        raise ValueError(f"Expected TiXL chapter missing: {required}")
if graph.get("Id") != "564f37c0-cb8c-5aff-97b3-683ec4ab5477":
    # Avoid applying Asterion-specific timing to another user composition.
    raise ValueError("Home symbol identity changed; inspect before editing")

for name in ("Edit move timing here", "Main / clips"):
    child = by_name[name]
    if child["SymbolName"] != "PrismalLabs.BlenderExport.BlenderClipSequence":
        raise ValueError(f"{name} is no longer a bridge clip lane")
    set_input(child, LOOP_INPUT, "System.Single", 108.0)

set_input(by_name["Blender object: moon"],
          "9e4a2fb0-334e-5567-8f63-e9d1ac3260aa", "System.String",
          "Tethys analogue | cratered moon")


def set_curve(name, changes):
    child = by_name[name]
    entry = next(value for value in child["InputValues"]
                 if value["Id"] == "108cb829-5f9e-4a45-bc6b-7cf40a0a0f89")
    curve = entry["Value"]["Curve"]
    keys = {float(key["Time"]): key for key in curve["Keys"]}
    for second, strength in changes:
        if second in keys:
            keys[second]["Value"] = strength
        else:
            keys[second] = {"Time": float(second), "Value": float(strength),
                            "InInterpolation": "Smooth", "OutInterpolation": "Smooth",
                            "InTangentAngle": 0.0, "OutTangentAngle": 0.0}
    curve["Keys"] = [keys[key] for key in sorted(keys)]


set_curve("Story FX | glow follows the mission",
          [(0, .7), (91, 1.35), (96, 1.65), (103, 1.3),
           (105, 2.8), (107, 1.45), (108, .7)])
set_curve("Story FX | signal disturbance windows",
          [(103, 0), (104.6, .72), (106.1, .82), (107.8, 0), (108, 0)])

# Native fluid feedback is stateful. Reset it for the first tenth of a second
# of each wrapped lap so repeated playback starts from the same seed.
reset_name = "Moon Fluid | reset at project seam"
reset_id = str(uuid.uuid5(uuid.NAMESPACE_URL, graph["Id"] + "/moon-feedback-loop-reset"))
reset = by_name.get(reset_name)
if reset is None:
    reset = {"Id": reset_id, "SymbolId": "026869ee-b62f-481e-aadf-f8a1db77fe65",
             "SymbolName": "Lib.numbers.float.logic.Compare", "Name": reset_name,
             "InputValues": [], "Outputs": []}
    graph["Children"].append(reset)
elif reset["Id"] != reset_id:
    raise ValueError("A different reset node already uses the project seam name")
set_input(reset, "5a39f9ad-f447-493e-94f1-9d2ca7627420",
          "System.Single", .1)
set_input(reset, "f1537faa-1bd2-44c9-b0ae-d06c5af5cdef",
          "System.Int32", 0)
for source, output, target, input_slot in (
    (by_name["Main / clip to scene time"], "c1dbdb9e-a7ad-424b-b2ba-94bd9ce71daf",
     reset, "8d98d88c-7a0e-4282-823e-4889ef286e5a"),
    (reset, "7149c7d2-242f-4d57-ac21-19e86700708a",
     by_name["Moon Fluid | feedback currents"],
     "51621e59-9bdd-4004-a053-d4637278bd92"),
):
    edge = {"SourceParentOrChildId": source["Id"], "SourceSlotId": output,
            "TargetParentOrChildId": target["Id"], "TargetSlotId": input_slot}
    if edge not in graph["Connections"]:
        if any(other["TargetParentOrChildId"] == target["Id"]
               and other["TargetSlotId"] == input_slot
               for other in graph["Connections"]):
            raise ValueError("The lunar feedback reset input was already routed")
        graph["Connections"].append(edge)

UI = GRAPH.with_suffix(".t3ui")
ui = read(UI)
if not any(child["ChildId"] == reset_id for child in ui["SymbolChildUis"]):
    ui["SymbolChildUis"].append({"ChildId": reset_id,
                                 "Position": {"X": 1535.0, "Y": 680.0}})

BACKUPS.mkdir(parents=True, exist_ok=True)
backup = BACKUPS / ("AsterionBreakaway.before-loop-" +
                    datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + ".t3")
shutil.copy2(GRAPH, backup)
shutil.copy2(UI, backup.with_suffix(".t3ui"))
GRAPH.write_text(json.dumps(graph, indent=2) + "\n", encoding="utf-8")
UI.write_text(json.dumps(ui, indent=2) + "\n", encoding="utf-8")
assert read(GRAPH) == graph
assert read(UI) == ui
print(json.dumps({"graph": str(GRAPH), "backup": str(backup),
                  "loopSeconds": 108, "moonSelector": "Tethys analogue | cratered moon"}))

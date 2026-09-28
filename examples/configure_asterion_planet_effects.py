"""Add native TiXL mesh and image distortion to the selected Asterion moon.

Apply to the project's home .t3 while TiXL is closed. The file is user-owned,
so this script refuses to replace any existing effect connection or selection.
"""

from __future__ import annotations

import json
import re
import sys
import uuid
from pathlib import Path


MOON = "Tethys analogue | cratered moon"
MESH_AMOUNT = 2.6
IMAGE_DISPLACEMENT = 0.24
NAMES = {
    "object": "Main / opaque select object",
    "mesh_select": "Main / opaque select mesh",
    "mesh_replace": "Main / opaque replace mesh",
    "texture_select": "Main / opaque select textures",
    "texture_replace": "Main / opaque replace textures",
}


def edge(source, output, target, input_slot):
    return {"SourceParentOrChildId": source, "SourceSlotId": output,
            "TargetParentOrChildId": target, "TargetSlotId": input_slot}


def configure(path: Path) -> None:
    raw = re.sub(r'("[0-9a-fA-F-]{36}")/\*.*?\*/', r"\1",
                 path.read_text(encoding="utf-8"))
    graph = json.loads(raw)
    ui_path = path.with_suffix(".t3ui")
    ui = json.loads(re.sub(r'("[0-9a-fA-F-]{36}")/\*.*?\*/', r"\1",
                           ui_path.read_text(encoding="utf-8")))
    children = {child.get("Name"): child for child in graph["Children"]}
    if any(name not in children for name in NAMES.values()):
        raise ValueError("The editable main-world object ports are missing")
    chosen = {key: children[name] for key, name in NAMES.items()}
    selector = chosen["object"]
    name_slot = "9e4a2fb0-334e-5567-8f63-e9d1ac3260aa"
    name_values = [value for value in selector["InputValues"] if value["Id"] == name_slot]
    if len(name_values) != 1 or name_values[0]["Value"] not in ("", MOON):
        raise ValueError("The object selector already has a user selection")

    mesh_name = "Moon | displace mesh noise"
    image_name = "Moon | displace albedo image"
    if mesh_name in children or image_name in children:
        if mesh_name not in children or image_name not in children:
            raise ValueError("Only one planet effect is installed; preserve user edits")
        settings = (
            (children[mesh_name], "b7559321-2dbe-4fe0-ab86-52532d008980", 0.55, MESH_AMOUNT),
            (children[image_name], "0f2867ab-a65e-4bf3-b1b5-9c241690ba5f", 0.018, IMAGE_DISPLACEMENT),
        )
        for child, slot, previous, current in settings:
            values = [item for item in child["InputValues"] if item["Id"] == slot]
            if len(values) != 1 or values[0]["Value"] not in (previous, current):
                raise ValueError(f"{child['Name']} has user-edited settings")
        for child, slot, _, current in settings:
            next(item for item in child["InputValues"] if item["Id"] == slot)["Value"] = current
        name_values[0]["Value"] = MOON
        path.write_text(json.dumps(graph, indent=2)+"\n", encoding="utf-8")
        print("ASTERION_PLANET_EFFECTS_TUNED " + MOON)
        return
    mesh_id = str(uuid.uuid5(uuid.NAMESPACE_URL, graph["Id"] + "/moon-mesh-noise"))
    image_id = str(uuid.uuid5(uuid.NAMESPACE_URL, graph["Id"] + "/moon-image-displace"))
    mesh_direct = edge(chosen["mesh_select"]["Id"],
                       "62d60908-5865-55cc-b0c6-821b3008c913",
                       chosen["mesh_replace"]["Id"],
                       "259ad7a2-2034-5836-a17a-707ad5905d6d")
    image_direct = edge(chosen["texture_select"]["Id"],
                        "f5d218bb-d055-5800-9971-db0f88b6ead3",
                        chosen["texture_replace"]["Id"],
                        "7ea5475c-6fc4-501b-a9b0-7def755c898b")
    if mesh_direct not in graph["Connections"] or image_direct not in graph["Connections"]:
        raise ValueError("The default effect paths have changed; preserve the existing routing")
    name_values[0]["Value"] = MOON
    graph["Children"].extend([
        {"Id": mesh_id, "SymbolId": "b5709297-c714-4019-9d0b-6982590b5590",
         "SymbolName": "Lib.mesh.modify.DisplaceMeshNoise", "Name": mesh_name,
         "InputValues": [
            {"Id": "b7559321-2dbe-4fe0-ab86-52532d008980", "Type": "System.Single", "Value": MESH_AMOUNT},
             {"Id": "4b1a66a4-b5e4-4bc3-97f5-bd3cda668893", "Type": "System.Single", "Value": 2.2},
             {"Id": "83cb775f-c600-41c9-9435-604f77a426bd", "Type": "System.Boolean", "Value": False},
             {"Id": "f108f6f7-5e6f-43c8-9d0b-c2e7bf5adf9c", "Type": "System.Int32", "Value": 1},
         ], "Outputs": []},
        {"Id": image_id, "SymbolId": "1b149f1f-529c-4418-ac9d-3871f24a9e38",
         "SymbolName": "Lib.image.fx.distort.Displace", "Name": image_name,
         "InputValues": [
            {"Id": "0f2867ab-a65e-4bf3-b1b5-9c241690ba5f", "Type": "System.Single", "Value": IMAGE_DISPLACEMENT},
             {"Id": "6a5c120f-7c04-439b-ad2d-6f78ceb3b378", "Type": "System.Int32", "Value": 2},
         ], "Outputs": []},
    ])
    graph["Connections"].remove(mesh_direct)
    graph["Connections"].remove(image_direct)
    graph["Connections"].extend([
        edge(chosen["mesh_select"]["Id"], "62d60908-5865-55cc-b0c6-821b3008c913",
             mesh_id, "fb86f0d6-1e5c-478f-b723-9f9462e2966c"),
        edge(mesh_id, "b91689eb-4274-4534-9f95-515a93c57ebe",
             chosen["mesh_replace"]["Id"], "259ad7a2-2034-5836-a17a-707ad5905d6d"),
        edge(chosen["texture_select"]["Id"], "f5d218bb-d055-5800-9971-db0f88b6ead3",
             image_id, "d0508dfa-89cf-4713-8f5e-893dd5bfc3f4"),
        edge(chosen["texture_select"]["Id"], "26556e6e-caed-5dff-9266-8665065977c2",
             image_id, "3b5b278d-fd4e-4216-9916-5cd7ffd54ab2"),
        edge(image_id, "0faa056c-b1d6-4e1f-a9be-b0791f3bae84",
             chosen["texture_replace"]["Id"], "7ea5475c-6fc4-501b-a9b0-7def755c898b"),
    ])
    positions = {item["ChildId"]: item["Position"] for item in ui["SymbolChildUis"]}
    mesh_pos = positions[chosen["mesh_select"]["Id"]]
    image_pos = positions[chosen["texture_select"]["Id"]]
    ui["SymbolChildUis"].extend([
        {"ChildId": mesh_id, "Position": {"X": mesh_pos["X"] + 100,
                                             "Y": mesh_pos["Y"] + 170}},
        {"ChildId": image_id, "Position": {"X": image_pos["X"] + 100,
                                              "Y": image_pos["Y"] + 170}},
    ])
    path.write_text(json.dumps(graph, indent=2)+"\n", encoding="utf-8")
    ui_path.write_text(json.dumps(ui, indent=2)+"\n", encoding="utf-8")
    print("ASTERION_PLANET_EFFECTS_INSTALLED " + MOON)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: configure_asterion_planet_effects.py <AsterionBreakaway.t3>")
    configure(Path(sys.argv[1]))

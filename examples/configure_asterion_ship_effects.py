"""Attach editable TiXL mesh and image effects to the three reusable hull sections.

Run against the AsterionBreakaway home graph only while TiXL is closed. The
selectors use Blender object names and primitive labels, never numeric indices.
"""

from __future__ import annotations

import json
import re
import sys
import uuid
from pathlib import Path


HULLS = (
    ("FUSELAGE-00 | pressure shell.001 [primitive 1/3]", "Fuselage 00"),
    ("FUSELAGE-01 | pressure shell.001 [primitive 1/4]", "Fuselage 01"),
    ("FUSELAGE-02 | pressure shell.001 [primitive 1/3]", "Fuselage 02"),
)
SYMBOLS = {
    "select": ("b62fce64-2efe-54ac-9d6f-3db2f83deed4", "PrismalLabs.BlenderExport.BlenderObjectIndex"),
    "mesh_select": ("a8524651-56c7-58fb-94b2-cf9692f95208", "PrismalLabs.BlenderExport.BlenderMeshSelect"),
    "mesh_fx": ("b5709297-c714-4019-9d0b-6982590b5590", "Lib.mesh.modify.DisplaceMeshNoise"),
    "mesh_replace": ("789071a8-bd89-51bf-9f47-b942db0fa875", "PrismalLabs.BlenderExport.BlenderMeshReplace"),
    "texture_select": ("b1dc33bf-f973-5822-b079-e7ed36bb3ab1", "PrismalLabs.BlenderExport.BlenderTextureSelect"),
    "image_fx": ("1fa725a1-dab6-4a2a-8a4d-6efdfba5cf05", "Lib.image.fx.stylize.Pixelate"),
    "texture_replace": ("c25f4c1c-e88d-575e-b8a0-befcf44f208c", "PrismalLabs.BlenderExport.BlenderTextureReplace"),
    "anim": ("ea7b8491-2f8e-4add-b0b1-fd068ccfed0d", "Lib.numbers.anim.animators.AnimValue"),
    "integer": ("06b4728e-852c-491a-a89d-647f7e0b5415", "Lib.numbers.int.process.FloatToInt"),
}


def load(path: Path) -> dict:
    return json.loads(re.sub(r'("[0-9a-fA-F-]{36}")/\*.*?\*/', r"\1", path.read_text(encoding="utf-8")))


def node(graph: dict, key: str, name: str, values=()) -> dict:
    symbol_id, symbol_name = SYMBOLS[key]
    return {"Id": str(uuid.uuid5(uuid.NAMESPACE_URL, graph["Id"] + "/ship-fx/" + name)),
            "SymbolId": symbol_id, "SymbolName": symbol_name, "Name": name,
            "InputValues": list(values), "Outputs": []}


def value(slot: str, kind: str, setting) -> dict:
    return {"Id": slot, "Type": kind, "Value": setting}


def edge(source: dict, output: str, target: dict, input_slot: str) -> dict:
    return {"SourceParentOrChildId": source["Id"], "SourceSlotId": output,
            "TargetParentOrChildId": target["Id"], "TargetSlotId": input_slot}


def configure(path: Path) -> None:
    graph = load(path)
    ui_path = path.with_suffix(".t3ui")
    ui = load(ui_path)
    by_name = {item.get("Name"): item for item in graph["Children"]}
    required = ("Main / opaque motion", "Main / opaque replace textures",
                "Main / opaque draw", "Main / clip to scene time")
    if any(name not in by_name for name in required):
        raise ValueError("Asterion main scene route is missing")
    if any(name.startswith("Ship FX |") for name in by_name):
        raise ValueError("Ship FX nodes already exist; preserve editor changes")
    motion, previous, draw, time = (by_name[name] for name in required)
    old = edge(previous, "8d7ee90b-d479-5c83-9a76-3e1bb0b76143", draw,
               "22ad6256-f741-4e8f-9a47-4b5b82e2cecf")
    if old not in graph["Connections"]:
        raise ValueError("The final opaque draw route was edited")
    graph["Connections"].remove(old)

    connections = graph["Connections"]
    children = graph["Children"]
    positions = ui["SymbolChildUis"]

    def add(item: dict, x: float, y: float) -> dict:
        children.append(item)
        positions.append({"ChildId": item["Id"], "Position": {"X": x, "Y": y}})
        return item

    mesh_anim = add(node(graph, "anim", "Ship FX | AnimValue hull mesh", [
        value("4cf5d20b-7335-4584-b246-c260ac5cdf4f", "System.Int32", 6),
        value("48005727-0158-4795-ad70-8410c27fd01d", "System.Single", 0.45),
        value("79917ef7-64ca-4825-9c6a-c9b2a7f6ff86", "System.Single", 0.09),
        value("ddd93b06-118e-43e0-85f6-c150faf91d04", "System.Single", 0.03),
    ]), 920, 460)
    image_anim = add(node(graph, "anim", "Ship FX | AnimValue image blocks", [
        value("4cf5d20b-7335-4584-b246-c260ac5cdf4f", "System.Int32", 10),
        value("48005727-0158-4795-ad70-8410c27fd01d", "System.Single", 0.8),
        value("79917ef7-64ca-4825-9c6a-c9b2a7f6ff86", "System.Single", 18.0),
        value("ddd93b06-118e-43e0-85f6-c150faf91d04", "System.Single", 12.0),
    ]), 1480, 460)
    blocks = add(node(graph, "integer", "Ship FX | image block size"), 1690, 460)
    connections.extend((
        edge(time, "c1dbdb9e-a7ad-424b-b2ba-94bd9ce71daf", mesh_anim,
             "7b4992ba-30f7-42e5-b04b-ae4ec0be810e"),
        edge(time, "c1dbdb9e-a7ad-424b-b2ba-94bd9ce71daf", image_anim,
             "7b4992ba-30f7-42e5-b04b-ae4ec0be810e"),
        edge(image_anim, "ae4addf0-08cf-4b25-9515-4fef9359d183", blocks,
             "af866a6c-1ab0-43c0-9e8a-5d25c300e128"),
    ))

    for row, (object_name, label) in enumerate(HULLS):
        y = 600 + row * 420
        selector = add(node(graph, "select", f"Ship FX | {label} object", [
            value("9e4a2fb0-334e-5567-8f63-e9d1ac3260aa", "System.String", object_name),
        ]), 600, y)
        mesh_select = add(node(graph, "mesh_select", f"Ship FX | {label} select mesh"), 820, y)
        mesh_fx = add(node(graph, "mesh_fx", f"Ship FX | {label} mesh noise", [
            value("4b1a66a4-b5e4-4bc3-97f5-bd3cda668893", "System.Single", 3.5),
            value("83cb775f-c600-41c9-9435-604f77a426bd", "System.Boolean", False),
            value("f108f6f7-5e6f-43c8-9d0b-c2e7bf5adf9c", "System.Int32", 1),
        ]), 1030, y)
        mesh_replace = add(node(graph, "mesh_replace", f"Ship FX | {label} replace mesh"), 1240, y)
        texture_select = add(node(graph, "texture_select", f"Ship FX | {label} select textures"), 1450, y)
        image_fx = add(node(graph, "image_fx", f"Ship FX | {label} image pixelate", [
            value("824bd327-4c52-422b-bd83-c568db8c0ea9", "T3.Core.DataTypes.Vector.Int2", {"X": 128, "Y": 128}),
        ]), 1660, y)
        texture_replace = add(node(graph, "texture_replace", f"Ship FX | {label} replace textures"), 1870, y)
        connections.extend((
            edge(motion, "cbb6f6a0-27c9-4555-8e5e-fd23e8d3f991", selector,
                 "dc7ae73f-9b1d-54a1-9fc2-d5d7581c4f84"),
            edge(previous, "8d7ee90b-d479-5c83-9a76-3e1bb0b76143", mesh_select,
                 "12bcfca2-ebbc-55f5-a75c-dd53ab356690"),
            edge(selector, "74cf55e0-7b98-5e5a-ae5d-f77a2f72079c", mesh_select,
                 "f47fce56-d58d-51c6-b598-f62d33ce570d"),
            edge(mesh_select, "62d60908-5865-55cc-b0c6-821b3008c913", mesh_fx,
                 "fb86f0d6-1e5c-478f-b723-9f9462e2966c"),
            edge(mesh_anim, "ae4addf0-08cf-4b25-9515-4fef9359d183", mesh_fx,
                 "b7559321-2dbe-4fe0-ab86-52532d008980"),
            edge(previous, "8d7ee90b-d479-5c83-9a76-3e1bb0b76143", mesh_replace,
                 "65a28b5a-632d-566b-ad67-399cb9e4f515"),
            edge(selector, "74cf55e0-7b98-5e5a-ae5d-f77a2f72079c", mesh_replace,
                 "84dc72f4-f0b9-5107-a821-e388dff9b4b3"),
            edge(mesh_fx, "b91689eb-4274-4534-9f95-515a93c57ebe", mesh_replace,
                 "259ad7a2-2034-5836-a17a-707ad5905d6d"),
            edge(mesh_replace, "3012e73d-3204-59e0-a39c-b53aec53de67", texture_select,
                 "ca9a3db9-6466-503a-a8a3-3909c7c30eb3"),
            edge(selector, "74cf55e0-7b98-5e5a-ae5d-f77a2f72079c", texture_select,
                 "d1658e14-8cc0-57ad-8b2e-d98324d90762"),
            edge(texture_select, "f5d218bb-d055-5800-9971-db0f88b6ead3", image_fx,
                 "7db8987c-f128-476f-93bb-d79e761caecc"),
            edge(blocks, "1eb7c5c4-0982-43f4-b14d-524571e3cdda", image_fx,
                 "047db178-dab3-4123-90ec-becb4f439f4e"),
            edge(mesh_replace, "3012e73d-3204-59e0-a39c-b53aec53de67", texture_replace,
                 "a572804f-65b0-5bb6-b17f-207198bc6867"),
            edge(selector, "74cf55e0-7b98-5e5a-ae5d-f77a2f72079c", texture_replace,
                 "233f4c81-bbba-530f-b3fc-604bf1d5a590"),
            edge(image_fx, "47e693ca-a695-4f95-9f02-9b76894ee91c", texture_replace,
                 "7ea5475c-6fc4-501b-a9b0-7def755c898b"),
            edge(texture_select, "26556e6e-caed-5dff-9266-8665065977c2", texture_replace,
                 "d3a68120-5d29-5e2c-b556-0b0ba0c86d97"),
            edge(texture_select, "6ee9ad33-d30e-5592-bab6-c133054fc554", texture_replace,
                 "b30a4fb2-1ce9-5bad-985c-4eff20474ba7"),
            edge(texture_select, "9407cab1-76f5-5e92-af05-0bd3cb06820b", texture_replace,
                 "1cedc4e7-eee9-5690-a7e4-55fb5f73b00f"),
        ))
        previous = texture_replace

    connections.append(edge(previous, "8d7ee90b-d479-5c83-9a76-3e1bb0b76143", draw,
                            "22ad6256-f741-4e8f-9a47-4b5b82e2cecf"))
    if len({item["Id"] for item in children}) != len(children):
        raise ValueError("Duplicate child identifier")
    path.write_text(json.dumps(graph, indent=2) + "\n", encoding="utf-8")
    ui_path.write_text(json.dumps(ui, indent=2) + "\n", encoding="utf-8")
    print(f"Installed ship effects on {len(HULLS)} hull sections; {len(children)} nodes, {len(connections)} links")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: configure_asterion_ship_effects.py <AsterionBreakaway.t3>")
    configure(Path(sys.argv[1]))

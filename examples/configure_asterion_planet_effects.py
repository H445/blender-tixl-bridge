"""Select the Blender moon by name and add animated mesh/glitch effects.

Apply to the user-owned AsterionBreakaway home graph while TiXL is closed.
Recognized direct and earlier moon-displacement routes are migrated; any
unexpected selection or route stops the edit.
"""

from __future__ import annotations

import json
import re
import sys
import uuid
from pathlib import Path


MOON = "Tethys analogue | cratered moon"
SEARCH = "moon"
SELECTOR_NAME = "Blender object: moon"
MESH_NAME = "Moon | animated mesh noise"
GLITCH_NAME = "Moon | glitch albedo"
MESH_ANIM_NAME = "Moon | AnimValue mesh amount"
GLITCH_ANIM_NAME = "Moon | AnimValue glitch amount"
PIXEL_NAME = "Moon | pixel glitch"
BLOCK_NAME = "Moon | glitch block size"
NAMES = {
    "mesh_select": "Main / opaque select mesh",
    "mesh_replace": "Main / opaque replace mesh",
    "texture_select": "Main / opaque select textures",
    "texture_replace": "Main / opaque replace textures",
    "time": "Main / clip to scene time",
}


def edge(source, output, target, input_slot):
    return {"SourceParentOrChildId": source, "SourceSlotId": output,
            "TargetParentOrChildId": target, "TargetSlotId": input_slot}


def load(path):
    raw = re.sub(r'("[0-9a-fA-F-]{36}")/\*.*?\*/', r"\1",
                 path.read_text(encoding="utf-8"))
    return json.loads(raw)


def child(graph, suffix, symbol_id, symbol_name, name, values):
    identifier = str(uuid.uuid5(uuid.NAMESPACE_URL, graph["Id"] + suffix))
    return {"Id": identifier, "SymbolId": symbol_id, "SymbolName": symbol_name,
            "Name": name, "InputValues": values, "Outputs": []}


def value(slot, type_name, setting):
    return {"Id": slot, "Type": type_name, "Value": setting}


def remove_edges(graph, expected):
    if any(connection not in graph["Connections"] for connection in expected):
        raise ValueError("The moon effect route was edited; preserve user changes")
    for connection in expected:
        graph["Connections"].remove(connection)


def use_depth_safe_pixel_glitch(graph, ui):
    """Replace GlitchDisplace's nested render pass with a pure image shader."""
    by_name = {item.get("Name"): item for item in graph["Children"]}
    if PIXEL_NAME in by_name and BLOCK_NAME in by_name:
        return
    old = by_name[GLITCH_NAME]
    anim = by_name[GLITCH_ANIM_NAME]
    selected = by_name[NAMES["texture_select"]]
    replacement = by_name[NAMES["texture_replace"]]
    remove_edges(graph, [
        edge(selected["Id"], "f5d218bb-d055-5800-9971-db0f88b6ead3",
             old["Id"], "7914bb8b-8444-4438-a156-b00d099ce659"),
        edge(old["Id"], "4808ce68-4785-4d25-a2e2-68f6c89ae577",
             replacement["Id"], "7ea5475c-6fc4-501b-a9b0-7def755c898b"),
        edge(anim["Id"], "ae4addf0-08cf-4b25-9515-4fef9359d183",
             old["Id"], "20f149ee-123f-4347-ba8e-f403a3eae7d3"),
    ])
    graph["Children"].remove(old)
    positions = {item["ChildId"]: item["Position"] for item in ui["SymbolChildUis"]}
    old_pos = positions[old["Id"]]
    anim_pos = positions[anim["Id"]]
    ui["SymbolChildUis"] = [item for item in ui["SymbolChildUis"]
                            if item["ChildId"] != old["Id"]]
    pixel = child(graph, "/moon-pixel-glitch", "1fa725a1-dab6-4a2a-8a4d-6efdfba5cf05",
                  "Lib.image.fx.stylize.Pixelate", PIXEL_NAME, [
                      value("824bd327-4c52-422b-bd83-c568db8c0ea9", "T3.Core.DataTypes.Vector.Int2",
                            {"X": 64, "Y": 64}),
                  ])
    block = child(graph, "/moon-glitch-block-size", "06b4728e-852c-491a-a89d-647f7e0b5415",
                  "Lib.numbers.int.process.FloatToInt", BLOCK_NAME, [])
    graph["Children"].extend((pixel, block))
    graph["Connections"].extend([
        edge(selected["Id"], "f5d218bb-d055-5800-9971-db0f88b6ead3",
             pixel["Id"], "7db8987c-f128-476f-93bb-d79e761caecc"),
        edge(pixel["Id"], "47e693ca-a695-4f95-9f02-9b76894ee91c",
             replacement["Id"], "7ea5475c-6fc4-501b-a9b0-7def755c898b"),
        edge(anim["Id"], "ae4addf0-08cf-4b25-9515-4fef9359d183",
             block["Id"], "AF866A6C-1AB0-43C0-9E8A-5D25C300E128"),
        edge(block["Id"], "1EB7C5C4-0982-43F4-B14D-524571E3CDDA",
             pixel["Id"], "047db178-dab3-4123-90ec-becb4f439f4e"),
    ])
    for item in anim["InputValues"]:
        if item["Id"] == "79917ef7-64ca-4825-9c6a-c9b2a7f6ff86":
            item["Value"] = 20.0
        elif item["Id"] == "ddd93b06-118e-43e0-85f6-c150faf91d04":
            item["Value"] = 8.0
    anim["Name"] = "Moon | AnimValue pixel blocks"
    ui["SymbolChildUis"].extend([
        {"ChildId": pixel["Id"], "Position": old_pos},
        {"ChildId": block["Id"], "Position": {"X": anim_pos["X"] + 160,
                                               "Y": anim_pos["Y"]}},
    ])


def configure(path: Path) -> None:
    graph = load(path)
    ui_path = path.with_suffix(".t3ui")
    ui = load(ui_path)
    by_name = {item.get("Name"): item for item in graph["Children"]}
    if any(name not in by_name for name in NAMES.values()):
        raise ValueError("The editable main-world ports are missing")
    selected = {key: by_name[name] for key, name in NAMES.items()}
    selector = by_name.get(SELECTOR_NAME) or by_name.get("Main / opaque select object")
    if selector is None or not selector["SymbolName"].endswith("BlenderObjectIndex"):
        raise ValueError("The Blender object selector is missing")
    selector_values = [item for item in selector["InputValues"]
                       if item["Id"] == "9e4a2fb0-334e-5567-8f63-e9d1ac3260aa"]
    if len(selector_values) != 1 or selector_values[0]["Value"] not in ("", MOON, SEARCH):
        raise ValueError("The selector has a different user selection")
    if PIXEL_NAME in by_name and BLOCK_NAME in by_name:
        print("ASTERION_PLANET_EFFECTS_ALREADY_INSTALLED " + MOON)
        return

    new_names = {MESH_NAME, GLITCH_NAME, MESH_ANIM_NAME, GLITCH_ANIM_NAME}
    if new_names.issubset(by_name):
        tuning = (
            (by_name[GLITCH_NAME], "3fdfce77-8622-4fcf-a7cf-e4bfbabc280c", None, 2, "System.Int32"),
            (by_name[GLITCH_NAME], "502e7ba7-4824-4928-9e15-cbb060e73b05", 0.8, 1.2, "System.Single"),
            (by_name[GLITCH_NAME], "6a1efc82-7ca4-4c79-a3f9-f16b568c3131", None, 0.2, "System.Single"),
            (by_name[GLITCH_ANIM_NAME], "79917ef7-64ca-4825-9c6a-c9b2a7f6ff86", 0.75, 3.0, "System.Single"),
            (by_name[GLITCH_ANIM_NAME], "ddd93b06-118e-43e0-85f6-c150faf91d04", 0.1, 0.4, "System.Single"),
        )
        for effect, slot, previous, current, _ in tuning:
            values = [item for item in effect["InputValues"] if item["Id"] == slot]
            if len(values) > 1 or values and values[0]["Value"] not in (previous, current):
                raise ValueError(f"{effect['Name']} has user-edited settings")
        for effect, slot, _, current, kind in tuning:
            values = [item for item in effect["InputValues"] if item["Id"] == slot]
            if values:
                values[0]["Value"] = current
            else:
                effect["InputValues"].append(value(slot, kind, current))
        use_depth_safe_pixel_glitch(graph, ui)
        path.write_text(json.dumps(graph, indent=2) + "\n", encoding="utf-8")
        ui_path.write_text(json.dumps(ui, indent=2) + "\n", encoding="utf-8")
        print("ASTERION_PLANET_EFFECTS_TUNED " + MOON)
        return
    if new_names.intersection(by_name):
        raise ValueError("Only some new moon effects exist; preserve user changes")

    mesh_select = selected["mesh_select"]["Id"]
    mesh_replace = selected["mesh_replace"]["Id"]
    texture_select = selected["texture_select"]["Id"]
    texture_replace = selected["texture_replace"]["Id"]
    mesh_out = "62d60908-5865-55cc-b0c6-821b3008c913"
    mesh_in = "259ad7a2-2034-5836-a17a-707ad5905d6d"
    albedo_out = "f5d218bb-d055-5800-9971-db0f88b6ead3"
    albedo_in = "7ea5475c-6fc4-501b-a9b0-7def755c898b"
    old_mesh = by_name.get("Moon | displace mesh noise")
    old_image = by_name.get("Moon | displace albedo image")
    if bool(old_mesh) != bool(old_image):
        raise ValueError("Only one old moon effect exists; preserve user changes")
    if old_mesh:
        if (old_mesh["SymbolName"] != "Lib.mesh.modify.DisplaceMeshNoise"
                or old_image["SymbolName"] != "Lib.image.fx.distort.Displace"):
            raise ValueError("The old moon effects have changed type")
        remove_edges(graph, [
            edge(mesh_select, mesh_out, old_mesh["Id"], "fb86f0d6-1e5c-478f-b723-9f9462e2966c"),
            edge(old_mesh["Id"], "b91689eb-4274-4534-9f95-515a93c57ebe", mesh_replace, mesh_in),
            edge(texture_select, albedo_out, old_image["Id"], "d0508dfa-89cf-4713-8f5e-893dd5bfc3f4"),
            edge(texture_select, "26556e6e-caed-5dff-9266-8665065977c2",
                 old_image["Id"], "3b5b278d-fd4e-4216-9916-5cd7ffd54ab2"),
            edge(old_image["Id"], "0faa056c-b1d6-4e1f-a9be-b0791f3bae84", texture_replace, albedo_in),
        ])
        graph["Children"] = [item for item in graph["Children"]
                             if item["Id"] not in (old_mesh["Id"], old_image["Id"])]
        ui["SymbolChildUis"] = [item for item in ui["SymbolChildUis"]
                                if item["ChildId"] not in (old_mesh["Id"], old_image["Id"])]
    else:
        remove_edges(graph, [edge(mesh_select, mesh_out, mesh_replace, mesh_in),
                             edge(texture_select, albedo_out, texture_replace, albedo_in)])

    mesh = child(graph, "/moon-mesh-noise", "b5709297-c714-4019-9d0b-6982590b5590",
                 "Lib.mesh.modify.DisplaceMeshNoise", MESH_NAME, [
                     value("b7559321-2dbe-4fe0-ab86-52532d008980", "System.Single", 2.6),
                     value("4b1a66a4-b5e4-4bc3-97f5-bd3cda668893", "System.Single", 2.2),
                     value("83cb775f-c600-41c9-9435-604f77a426bd", "System.Boolean", False),
                     value("f108f6f7-5e6f-43c8-9d0b-c2e7bf5adf9c", "System.Int32", 1),
                 ])
    glitch = child(graph, "/moon-glitch-albedo", "43f15919-f6c3-4a10-9092-00973fc8e821",
                   "Lib.image.fx.glitch.GlitchDisplace", GLITCH_NAME, [
                       value("de2930b4-bc0a-401f-a8b5-933d0d2297bc", "System.Int32", 120),
                       value("8a966901-645f-4873-a4c5-8d53a75b3c60", "System.Int32", 18),
                       value("502e7ba7-4824-4928-9e15-cbb060e73b05", "System.Single", 1.2),
                       value("3fdfce77-8622-4fcf-a7cf-e4bfbabc280c", "System.Int32", 2),
                       value("6a1efc82-7ca4-4c79-a3f9-f16b568c3131", "System.Single", 0.2),
                   ])
    mesh_anim = child(graph, "/moon-mesh-anim", "ea7b8491-2f8e-4add-b0b1-fd068ccfed0d",
                      "Lib.numbers.anim.animators.AnimValue", MESH_ANIM_NAME, [
                          value("4cf5d20b-7335-4584-b246-c260ac5cdf4f", "System.Int32", 6),
                          value("48005727-0158-4795-ad70-8410c27fd01d", "System.Single", 0.16),
                          value("79917ef7-64ca-4825-9c6a-c9b2a7f6ff86", "System.Single", 1.0),
                          value("ddd93b06-118e-43e0-85f6-c150faf91d04", "System.Single", 2.5),
                          value("738f6cfb-8b71-423c-b897-824c20397e5a", "System.Int32", 0),
                      ])
    glitch_anim = child(graph, "/moon-glitch-anim", "ea7b8491-2f8e-4add-b0b1-fd068ccfed0d",
                        "Lib.numbers.anim.animators.AnimValue", GLITCH_ANIM_NAME, [
                            value("4cf5d20b-7335-4584-b246-c260ac5cdf4f", "System.Int32", 10),
                            value("48005727-0158-4795-ad70-8410c27fd01d", "System.Single", 1.2),
                            value("79917ef7-64ca-4825-9c6a-c9b2a7f6ff86", "System.Single", 3.0),
                            value("ddd93b06-118e-43e0-85f6-c150faf91d04", "System.Single", 0.4),
                            value("738f6cfb-8b71-423c-b897-824c20397e5a", "System.Int32", 0),
                        ])
    graph["Children"].extend((mesh, glitch, mesh_anim, glitch_anim))
    time_output = "c1dbdb9e-a7ad-424b-b2ba-94bd9ce71daf"
    anim_time = "7b4992ba-30f7-42e5-b04b-ae4ec0be810e"
    anim_value = "ae4addf0-08cf-4b25-9515-4fef9359d183"
    graph["Connections"].extend([
        edge(mesh_select, mesh_out, mesh["Id"], "fb86f0d6-1e5c-478f-b723-9f9462e2966c"),
        edge(mesh["Id"], "b91689eb-4274-4534-9f95-515a93c57ebe", mesh_replace, mesh_in),
        edge(texture_select, albedo_out, glitch["Id"], "7914bb8b-8444-4438-a156-b00d099ce659"),
        edge(glitch["Id"], "4808ce68-4785-4d25-a2e2-68f6c89ae577", texture_replace, albedo_in),
        edge(selected["time"]["Id"], time_output, mesh_anim["Id"], anim_time),
        edge(selected["time"]["Id"], time_output, glitch_anim["Id"], anim_time),
        edge(mesh_anim["Id"], anim_value, mesh["Id"], "b7559321-2dbe-4fe0-ab86-52532d008980"),
        edge(glitch_anim["Id"], anim_value, glitch["Id"], "20f149ee-123f-4347-ba8e-f403a3eae7d3"),
    ])
    selector_values[0]["Value"] = SEARCH
    selector["Name"] = SELECTOR_NAME
    positions = {item["ChildId"]: item["Position"] for item in ui["SymbolChildUis"]}
    mesh_pos = positions[mesh_select]
    texture_pos = positions[texture_select]
    ui["SymbolChildUis"].extend([
        {"ChildId": mesh["Id"], "Position": {"X": mesh_pos["X"] + 100, "Y": mesh_pos["Y"] + 170}},
        {"ChildId": mesh_anim["Id"], "Position": {"X": mesh_pos["X"] + 100, "Y": mesh_pos["Y"] - 165}},
        {"ChildId": glitch["Id"], "Position": {"X": texture_pos["X"] + 100, "Y": texture_pos["Y"] + 170}},
        {"ChildId": glitch_anim["Id"], "Position": {"X": texture_pos["X"] + 100, "Y": texture_pos["Y"] - 165}},
    ])
    use_depth_safe_pixel_glitch(graph, ui)
    path.write_text(json.dumps(graph, indent=2) + "\n", encoding="utf-8")
    ui_path.write_text(json.dumps(ui, indent=2) + "\n", encoding="utf-8")
    print("ASTERION_PLANET_ANIMATED_GLITCH_INSTALLED " + MOON)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: configure_asterion_planet_effects.py <AsterionBreakaway.t3>")
    configure(Path(sys.argv[1]))

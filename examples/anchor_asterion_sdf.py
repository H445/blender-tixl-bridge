"""Stage Asterion's animated SDF as a named planet mesh/material effect.

The former final-image overlay becomes a UV surface blend. A depth-tested
world contour shares the main camera. Install only with the saved editor closed.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import os
import shutil
import uuid
from pathlib import Path

from install_asterion_audio import BACKUPS, DEFAULT_GRAPH, GRAPH_ID, read_graph, value
from rebalance_asterion_audio import editor_running


CURVE = "108cb829-5f9e-4a45-bc6b-7cf40a0a0f89"
CURVE_OUT = "fc51bee8-091c-4c66-a7df-12f6f69e3783"
SCENE_OUT = "8d7ee90b-d479-5c83-9a76-3e1bb0b76143"
INDEX_OUT = "74cf55e0-7b98-5e5a-ae5d-f77a2f72079c"
TEXTURE_OUT = "7a4c4feb-be2f-463e-96c6-cd9a6bad77a2"
RAY_OUT = "e178ef02-c9ac-48cd-a8cb-df3aec5941bb"
BLEND_OUT = "536fae14-b814-498c-a6b4-07775de36991"


def vector(*components):
    return dict(zip("XYZW", components))


def set_value(child, slot, kind, data):
    current = next((item for item in child["InputValues"] if item["Id"].lower() == slot.lower()), None)
    if current:
        current["Value"] = data
    else:
        child["InputValues"].append(value(slot, kind, data))


def curve(function):
    return {"Curve": {"PreCurve": "Constant", "PostCurve": "Constant",
                      "Keys": [{"Time": float(t), "Value": round(function(t), 6),
                                "InInterpolation": "Linear", "OutInterpolation": "Linear"}
                               for t in range(109)]}}


def prepare(graph, ui):
    if graph["Id"] != GRAPH_ID or ui["Id"] != GRAPH_ID:
        raise ValueError("Expected the Asterion Home graph")
    names = {child.get("Name"): child for child in graph["Children"]}
    if "Copper SDF | object selector" in names:
        raise ValueError("Planet SDF is already installed; preserve later editor changes")
    edges = graph["Connections"]

    def link(source, output, target, slot):
        return {"SourceParentOrChildId": source["Id"], "SourceSlotId": output.lower(),
                "TargetParentOrChildId": target["Id"], "TargetSlotId": slot.lower()}

    def replace_source(target, slot, source, output):
        matches = [edge for edge in edges if edge["TargetParentOrChildId"] == target["Id"]
                   and edge["TargetSlotId"].lower() == slot.lower()]
        if len(matches) != 1:
            raise ValueError(f"Expected one source on {target['Name']}:{slot}")
        edges.remove(matches[0])
        edges.append(link(source, output, target, slot))

    def add(name, symbol, symbol_name, inputs=()):
        child = {"Id": str(uuid.uuid5(uuid.NAMESPACE_URL, GRAPH_ID + "/planet-sdf/" + name)),
                 "SymbolId": symbol, "SymbolName": symbol_name, "Name": "Copper SDF | " + name,
                 "InputValues": list(inputs), "Outputs": []}
        graph["Children"].append(child)
        # Initial positions only; connected-graph layout arranges the staged DAG.
        ui["SymbolChildUis"].append({"ChildId": child["Id"],
                                     "Position": {"X": 9000.0, "Y": -6000.0 - 290 * len(ui["SymbolChildUis"])}})
        return child

    source = names["Main / opaque motion"]
    previous = names["Main / opaque replace textures"]
    draw = names["Main / opaque draw"]
    blend = names["Signal | SDF contour composite"]
    texture = names["Signal | SDF texture"]
    ray = names["Signal | raymarch SDF contour"]
    field = names["Signal | SDF turbulent rim"]

    selector = add("object selector", "b62fce64-2efe-54ac-9d6f-3db2f83deed4",
                   "PrismalLabs.BlenderExport.BlenderObjectIndex",
                   [value("9e4a2fb0-334e-5567-8f63-e9d1ac3260aa", "System.String", "EMBER | storm giant")])
    textures = add("original surface maps", "b1dc33bf-f973-5822-b079-e7ed36bb3ab1",
                   "PrismalLabs.BlenderExport.BlenderTextureSelect")
    mesh = add("original mesh", "a8524651-56c7-58fb-94b2-cf9692f95208",
               "PrismalLabs.BlenderExport.BlenderMeshSelect")
    displace = add("SDF surface relief", "79c01289-f3a9-4bea-8e95-a6b5f89b752d", "Lib.mesh.modify.DisplaceMesh",
                   [value("ea2df434-7963-4266-bef3-8f71ccfa95c0", "System.Single", .12),
                    value("84c2b0ee-c67d-4eab-88ea-fd95c332da07", "System.Numerics.Vector3", vector(1, 1, 1)),
                    value("c7e1c790-8e52-4064-9ffb-c0b8c2a50320", "System.Numerics.Vector2", vector(1, 1))])
    replace_mesh = add("replace selected mesh", "789071a8-bd89-51bf-9f47-b942db0fa875",
                       "PrismalLabs.BlenderExport.BlenderMeshReplace")
    replace_texture = add("replace selected surface", "c25f4c1c-e88d-575e-b8a0-befcf44f208c",
                          "PrismalLabs.BlenderExport.BlenderTextureReplace")
    local_camera = add("surface texture camera", names["Blender camera"]["SymbolId"],
                       names["Blender camera"]["SymbolName"])
    set_value(local_camera, "313596cc-3854-436b-89da-5fd40164ce76", "System.Numerics.Vector3", vector(0, 0, 2.4141))
    set_value(local_camera, "a7acb25c-d60c-43a6-b1df-2cd5c6e183f3", "System.Numerics.Vector3", vector(0, 0, 0))
    set_value(local_camera, "f66e91a1-b991-48c3-a8c9-33bcad0c2f6f", "System.Single", 1)
    transform = add("field anchored to object", "c44d23c7-bfac-403d-b49e-49d00001a316", "Lib.field.space.TransformField",
                    [value("3b817e6c-f532-4a8c-a2ff-a00dc926eeb2", "System.Numerics.Vector3", vector(-55, 8, 57)),
                     value("58b9dfb6-0596-4f0d-baf6-7fb3ae426c94", "System.Numerics.Vector3", vector(1, 1, 1)),
                     value("566f1619-1de0-4b41-b167-7fc261730d62", "System.Single", 30)])
    world_ray = add("depth-tested atmospheric contour", ray["SymbolId"], ray["SymbolName"])
    for node in (ray, world_ray):
        color = vector(.5, 3.5, 2.4, 1) if node is world_ray else vector(.2, 2, 1.4, 1)
        set_value(node, "9715075b-b02b-4290-9332-9bbfe67933f2", "System.Numerics.Vector4", color)
        set_value(node, "e3a85c27-b94c-4e77-b0c2-4644cd3a22d4", "System.Numerics.Vector4", vector(.25, 2.2, 1, .3))
        set_value(node, "3148d927-8779-47ab-9e0a-fa63206f3002", "System.Single", 180)
        set_value(node, "561768f6-adf6-4d3d-a36a-20b6f35ff151", "System.Single", .65)
    set_value(world_ray, "0700d5cb-6a1e-43ad-b7fb-b9b7b1415584", "System.Boolean", True)
    set_value(world_ray, "adeb374b-bce0-4af2-867b-efb3ce6289c9", "System.Single", 1500)
    set_value(world_ray, "0b4d60de-261f-4dbf-ad44-6395cda3a496", "System.Single", .04)
    set_value(world_ray, "f14e7a2f-cd4e-4399-b137-ea0b87c7dfbd", "System.Single", .06)
    set_value(texture, "03749b41-cc3c-4f38-aea6-d7cea19fc073", "T3.Core.DataTypes.Vector.Int2", vector(1024, 1024))
    set_value(texture, "8bb4a4e5-0c88-4d99-a5b2-2c9e22bd301f", "System.Numerics.Vector4", vector(0, 0, 0, 0))
    set_value(texture, "6ea4f801-ff52-4266-a41f-b9ef02c68510", "System.Boolean", True)
    set_value(names["Techno | SDF radius"], CURVE, "T3.Core.DataTypes.Curve",
              curve(lambda t: .65 + .035 * math.sin(2 * math.pi * t / 27)))
    set_value(names["Techno | SDF thickness"], CURVE, "T3.Core.DataTypes.Curve",
              curve(lambda t: .052 + .012 * math.sin(2 * math.pi * t / 12 + .5)))
    set_value(names["Signal | SDF scan accents"], CURVE, "T3.Core.DataTypes.Curve",
              curve(lambda t: .56 + .11 * math.sin(2 * math.pi * t / 18)))
    blend["Name"] = "Copper SDF | surface color blend"
    set_value(blend, "cad32967-e91b-4bd1-af09-5fdfdeee630e", "System.Int32", 3)
    set_value(blend, "93e63b73-e572-4bb2-bbbd-11bbffad89e7", "T3.Core.DataTypes.Vector.Int2", vector(2048, 1024))
    set_value(blend, "d7b83780-c4be-4337-b1df-0c98310b1926", "System.Boolean", True)
    replace_source(names["Output fit"], "92c66734-dce9-402a-95f6-cde0e58bf32f",
                   names["Signal | restrained ASCII composite"], BLEND_OUT)
    replace_source(blend, "abaa52e9-7d3d-4ae5-89d2-5251f61e5392", textures, "f5d218bb-d055-5800-9971-db0f88b6ead3")
    replace_source(texture, "4da253b7-4953-439a-b03f-1d515a78bddf", local_camera, "2e1742d8-9ba3-4236-a0cd-a2b02c9f5924")
    replace_source(draw, "22ad6256-f741-4e8f-9a47-4b5b82e2cecf", replace_texture, SCENE_OUT)
    edges.extend([
        link(source, "cbb6f6a0-27c9-4555-8e5e-fd23e8d3f991", selector, "dc7ae73f-9b1d-54a1-9fc2-d5d7581c4f84"),
        link(source, "cbb6f6a0-27c9-4555-8e5e-fd23e8d3f991", textures, "ca9a3db9-6466-503a-a8a3-3909c7c30eb3"),
        link(source, "cbb6f6a0-27c9-4555-8e5e-fd23e8d3f991", mesh, "12bcfca2-ebbc-55f5-a75c-dd53ab356690"),
        link(selector, INDEX_OUT, textures, "d1658e14-8cc0-57ad-8b2e-d98324d90762"),
        link(selector, INDEX_OUT, mesh, "f47fce56-d58d-51c6-b598-f62d33ce570d"),
        link(selector, INDEX_OUT, replace_mesh, "84dc72f4-f0b9-5107-a821-e388dff9b4b3"),
        link(selector, INDEX_OUT, replace_texture, "233f4c81-bbba-530f-b3fc-604bf1d5a590"),
        link(mesh, "62d60908-5865-55cc-b0c6-821b3008c913", displace, "f6726946-8ba0-4753-b37a-805c9246d236"),
        link(texture, TEXTURE_OUT, displace, "0211ebf0-d4b6-45aa-8c75-6e745941aa93"),
        link(previous, SCENE_OUT, replace_mesh, "65a28b5a-632d-566b-ad67-399cb9e4f515"),
        link(displace, "d2e47ad5-8830-4e55-97f0-302358b46358", replace_mesh, "259ad7a2-2034-5836-a17a-707ad5905d6d"),
        link(replace_mesh, "3012e73d-3204-59e0-a39c-b53aec53de67", replace_texture, "a572804f-65b0-5bb6-b17f-207198bc6867"),
        link(blend, BLEND_OUT, replace_texture, "7ea5475c-6fc4-501b-a9b0-7def755c898b"),
        link(ray, RAY_OUT, local_camera, "047b8fae-468c-48a7-8f3a-5fac8dd5b3c6"),
        link(field, "dbf31b38-5221-414c-83b1-800770fcfaa6", transform, "7248c680-7279-4c1d-b968-3864cb849c77"),
        link(transform, "9b12e766-9dcd-4c8f-83ee-2a0b78beae43", world_ray, "340ca675-9356-4548-ba64-732181bebeef"),
        link(world_ray, RAY_OUT, names["Main / scene"], "9e961f73-1ee7-4369-9ac7-5c653e570b6f"),
    ])
    ids = {c["Id"] for c in graph["Children"]}
    if len(ids) != len(graph["Children"]) or any(e[k] not in ids for e in edges
                                                 for k in ("SourceParentOrChildId", "TargetParentOrChildId")):
        raise ValueError("Invalid graph endpoints")
    return graph, ui


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--graph", type=Path, default=DEFAULT_GRAPH)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--ui-output", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    original = read_graph(args.graph)
    original_ui = read_graph(args.graph.with_suffix(".t3ui"))
    graph, ui = prepare(copy.deepcopy(original), copy.deepcopy(original_ui))
    if not args.apply:
        for path, data in ((args.output, graph), (args.ui_output, ui)):
            if any(part.lower() == "symbols" for part in path.resolve().parts):
                raise ValueError("Stage outside Symbols")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    else:
        if editor_running():
            raise RuntimeError("Save and close TiXL through its bridge before install")
        if read_graph(args.output) != graph:
            raise ValueError("Staged graph differs from the planned edit")
        staged_ui = read_graph(args.ui_output)
        expected_ui = copy.deepcopy(ui)
        if len(staged_ui["SymbolChildUis"]) != len(expected_ui["SymbolChildUis"]):
            raise ValueError("Layout modified UI child count")
        for new, expected in zip(staged_ui["SymbolChildUis"], expected_ui["SymbolChildUis"]):
            new = dict(new); new["Position"] = expected["Position"]
            if new != expected:
                raise ValueError("Layout modified non-position UI data")
        if {k:v for k,v in staged_ui.items() if k!='SymbolChildUis'} != {k:v for k,v in ui.items() if k!='SymbolChildUis'}:
            raise ValueError("Layout modified project settings")
        BACKUPS.mkdir(parents=True, exist_ok=True)
        for destination, staged in ((args.graph, args.output), (args.graph.with_suffix(".t3ui"), args.ui_output)):
            backup = BACKUPS / (destination.stem + "-before-planet-sdf-" + hashlib.sha256(destination.read_bytes()).hexdigest()[:12] + destination.suffix)
            if not backup.exists():
                shutil.copy2(destination, backup)
            temporary = destination.with_name(destination.name + ".incoming")
            shutil.copy2(staged, temporary)
            os.replace(temporary, destination)
    print(json.dumps({"children": len(graph['Children']), "connections": len(graph['Connections']), "installed": args.apply}))


if __name__ == "__main__":
    main()

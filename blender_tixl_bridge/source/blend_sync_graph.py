"""Generate the replaceable Blender import symbol and its source clip plan."""
import copy
import json
import re
import uuid
from pathlib import Path
from sync_metrics import count, timed

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "templates"


def _write_if_changed(path: Path, content: str) -> None:
    # The save watcher can call generate repeatedly with identical inputs.
    # Preserve mtimes so TiXL does not see a spurious source-code change and
    # start a project rebuild during playback.
    if path.is_file() and path.read_text(encoding="utf-8") == content:
        count("generatedFilesUnchanged")
        return
    path.write_text(content, encoding="utf-8")
    count("generatedFilesWritten")


@timed("graph_generation")
def generate(blend: Path, cache: Path, manifest: dict) -> list[Path]:
    from cache_publication import verify_generation
    data = verify_generation(cache, manifest["generation"]) if "generation" in manifest else cache
    worlds = manifest["worlds"]
    if not worlds:
        raise ValueError("The Blender export contains no worlds")
    label = re.sub(r"[^A-Za-z0-9]", "", blend.stem.title()) or "BlenderScene"
    short = uuid.uuid5(uuid.NAMESPACE_URL, str(blend.resolve()).lower()).hex[:8]
    class_name = f"Blend{label}{short}"
    namespace = "PrismalLabs.BlenderExport.Generated"
    identity = lambda value: str(uuid.uuid5(uuid.NAMESPACE_URL, str(blend.resolve()).lower() + "/" + value))
    template_ids = json.loads((TEMPLATE / "graph_nodes.json").read_text(encoding="utf-8"))
    core_keys = ["timeline", "scene_switch", "lights", "environment", "camera", "render",
                 "tonemap", "output_blit", "output_target"]
    t3 = json.loads((TEMPLATE / "BridgeTemplate.t3").read_text(encoding="utf-8"))
    t3ui = json.loads((TEMPLATE / "BridgeTemplate.t3ui").read_text(encoding="utf-8"))
    template_children = {child["Id"]: child for child in t3["Children"]}
    template_uis = {ui["ChildId"]: ui for ui in t3ui["SymbolChildUis"]}
    template_connections = t3["Connections"]
    core_ids = {template_ids[key]: identity("core/" + key) for key in core_keys}
    t3["Id"] = t3ui["Id"] = identity("symbol")
    old_input = t3["Inputs"][0]["Id"]
    old_output = next(c["TargetSlotId"] for c in t3["Connections"] if c["TargetParentOrChildId"] == "00000000-0000-0000-0000-000000000000")
    new_input = identity("input/resolution")
    new_time = identity("input/source_time_seconds")
    new_override = identity("input/use_source_time")
    new_output = identity("output/image")
    t3["Inputs"][0]["Id"] = new_input
    t3["Inputs"].extend([{"Id": new_time, "DefaultValue": 0.0},
                         {"Id": new_override, "DefaultValue": False}])
    children = []
    uis = []
    def clone_child(old, new, key, name, y_offset=0):
        child = copy.deepcopy(template_children[old])
        child["Id"] = new
        node_names = {
            "timeline": "Blender source / camera and worlds", "scene_switch": "Active Blender world",
            "lights": "Blender lights", "environment": "Environment", "camera": "Blender camera",
            "render": "Render scene", "bloom": "Bloom", "blur": "Camera blur",
            "material_fill": "Material fill", "passage": "Image blend", "tonemap": "Tone mapping",
            "output_blit": "Output fit", "output_target": "Output target",
        }
        child["Name"] = node_names.get(key, f"{name.replace('_', ' ').title()} / " +
                                     ("scene" if key == "world" else key.removeprefix("world_").replace("_", " ")))
        values = {v["Id"]: v for v in child.get("InputValues", [])}
        if key == "timeline":
            values["0713a026-3b7b-5ddf-ac49-e585d8248fa6"]["Value"] = str(data / "camera_60hz.bin")
            values["70bceb8e-15a0-592f-a01b-ff73dfac2a59"]["Value"] = str(data / "camera_timeline.json")
            values["2748faa0-a40e-5a5e-8810-1170aff75f74"] = {
                "Id": "2748faa0-a40e-5a5e-8810-1170aff75f74", "Type": "System.String",
                "Value": ",".join(str((w["active_clip"][0] - 1) / manifest["fps"]) for w in worlds),
            }
            child["InputValues"] = list(values.values())
        elif key.endswith("_load"):
            part = "glass" if "_glass_" in key else "opaque"
            values["292e80cf-ba31-4a50-9bf4-83712430f811"]["Value"] = str(data / "worlds" / f"{name}_{part}.glb")
        elif key.endswith("_motion"):
            part = "glass" if "_glass_" in key else "opaque"
            values["ca02f7a3-a03a-4db0-a05d-3a66b0c9ab11"]["Value"] = str(data / "worlds" / f"{name}_animation.bin")
            values["3a4c36f9-e8c1-4ab7-b370-0f548b054933"]["Value"] = str(data / "worlds" / f"{name}_{part}.glb")
        elif key == "lights":
            for value in child["InputValues"]:
                if value["Id"] == "a17e4d92-6c38-4f0b-b5d1-2e9a7c8f6043":
                    value["Value"] = ",".join(w["world"] for w in worlds)
                elif value["Id"] == "e0a26c9d-fc85-59a7-88b5-1d1b0d8c5c3f":
                    value["Value"] = str(data / "worlds")
        children.append(child)
        ui = copy.deepcopy(template_uis[old])
        ui["ChildId"] = new
        ui["Position"]["Y"] += y_offset
        uis.append(ui)
    for key in core_keys:
        old = template_ids[key]
        clone_child(old, core_ids[old], key, blend.stem)
    branch_maps = []
    branch_y = []
    y_offset = 0
    for index, world in enumerate(worlds):
        name = world["world"]
        keys = ["world"]
        if world["opaque_count"]:
            keys += ["world_opaque_load", "world_opaque_motion", "world_opaque_draw"]
        if world["glass_count"]:
            keys += ["world_glass_load", "world_glass_motion", "world_glass_draw",
                     "world_glass_solid_draw"]
        mapping = {template_ids[key]: identity(f"world/{index}/{key}") for key in keys}
        branch_maps.append(mapping)
        branch_y.append(y_offset)
        for key in keys:
            old = template_ids[key]
            clone_child(old, mapping[old], key, name, y_offset)
        y_offset += max(380, 250 + 185 * len(world.get("sdf_fields", [])))
    t3["Children"] = children
    zero = "00000000-0000-0000-0000-000000000000"
    connections = []
    def mapped_edge(edge, mapping):
        result = copy.deepcopy(edge)
        source, target = result["SourceParentOrChildId"], result["TargetParentOrChildId"]
        result["SourceParentOrChildId"] = mapping.get(source, source)
        result["TargetParentOrChildId"] = mapping.get(target, target)
        if source == zero and result["SourceSlotId"] == old_input:
            result["SourceSlotId"] = new_input
        if target == zero and result["TargetSlotId"] == old_output:
            result["TargetSlotId"] = new_output
        return result
    for edge in template_connections:
        source, target = edge["SourceParentOrChildId"], edge["TargetParentOrChildId"]
        if (source == zero or source in core_ids) and (target == zero or target in core_ids):
            connections.append(mapped_edge(edge, core_ids))
    for mapping in branch_maps:
        combined = {**core_ids, **mapping}
        for edge in template_connections:
            source, target = edge["SourceParentOrChildId"], edge["TargetParentOrChildId"]
            if ((source in mapping and target in mapping)
                or (source == template_ids["timeline"] and target in mapping)
                or (source in mapping and target == template_ids["scene_switch"])):
                if (source in combined and target in combined):
                    connections.append(mapped_edge(edge, combined))
    # Author-declared Blender SDF proxies become editable native TiXL fields.
    # The import graph is replaceable, so object identity drives stable IDs.
    sdf_defs = {
        "sphere": ("fc2a33fc-d957-4113-8096-92d4dcbe14b5",
                   "Lib.field.generate.sdf.SphereSDF",
                   "02f7d494-72ed-4247-88d7-0cbb730edf65"),
        "box": ("860da1cd-b341-4bc5-965a-4a9c295831f4",
                "Lib.field.generate.sdf.BoxSDF",
                "9153c53c-0b19-4ce4-b086-e448d78ef032"),
        "torus": ("a54e0946-71d0-4985-90bc-184cdb1b6b34",
                  "Lib.field.generate.sdf.TorusSDF",
                  "14cd4d1f-0b9b-43c4-93cc-d730c137cee8"),
    }
    def sdf_value(slot, type_name, raw):
        return {"Id": slot, "Type": type_name, "Value": raw}
    def sdf_child(child_id, symbol_id, symbol_name, name, inputs, x, y):
        children.append({"Id": child_id, "SymbolId": symbol_id,
                         "SymbolName": symbol_name, "Name": name,
                         "InputValues": inputs, "Outputs": []})
        uis.append({"ChildId": child_id, "Position": {"X": x, "Y": y}})
    for world_index, world in enumerate(worlds):
        group_id = branch_maps[world_index][template_ids["world"]]
        for field_index, field in enumerate(world.get("sdf_fields", [])):
            shape = field["kind"]
            if shape not in sdf_defs:
                raise ValueError(f"Unsupported exported SDF shape: {shape}")
            base = f"world/{world_index}/sdf/{field['name']}"
            field_id = identity(base + "/field")
            ray_id = identity(base + "/raymarch")
            row = branch_y[world_index] + 255 + field_index * 185
            symbol, symbol_name, result_slot = sdf_defs[shape]
            inputs = []
            if shape == "sphere":
                inputs = [sdf_value("ca582e39-37d7-4df6-b942-e2330f2bf2c6",
                                    "System.Numerics.Vector3", field["center"]),
                          sdf_value("3dd7c779-7982-4e7c-b4ce-f1915f477ad0",
                                    "System.Single", field["radius"])]
            elif shape == "box":
                inputs = [sdf_value("951b2983-1359-41e4-8fb0-8d97c50ed8d6",
                                    "System.Numerics.Vector3", field["center"]),
                          sdf_value("c4ef07b4-853b-48d4-9ade-c93ee849071a",
                                    "System.Numerics.Vector3", field["size"]),
                          sdf_value("734179fa-aaf8-46d0-b827-e71555dad6a0",
                                    "System.Single", 1.0)]
            else:
                inputs = [sdf_value("dbc72bd7-6191-4145-a69f-d17b3808b3ab",
                                    "System.Numerics.Vector3", field["center"]),
                          sdf_value("5fe2ab92-f8e5-400d-b5a3-197f20570d6f",
                                    "System.Single", field["radius"]),
                          sdf_value("6a392bc1-2adf-4a50-bb3f-5d4f2a63bf0b",
                                    "System.Single", field["thickness"]),
                          sdf_value("522a9640-ca8c-47e6-ad36-5c316a9092ae",
                                    "System.Int32", field["axis"])]
            sdf_child(field_id, symbol, symbol_name, f"{world['world']} / {field['name']} SDF",
                      inputs, -245, row)
            sdf_child(ray_id, "9323e32f-078c-4156-941b-203f4c265ff5",
                      "Lib.field.render.RaymarchField", f"{world['world']} / {field['name']} raymarch",
                      [sdf_value("9715075b-b02b-4290-9332-9bbfe67933f2",
                                 "System.Numerics.Vector4", field["color"]),
                       sdf_value("adeb374b-bce0-4af2-867b-efb3ce6289c9",
                                 "System.Single", 10000.0),
                       sdf_value("0700d5cb-6a1e-43ad-b7fb-b9b7b1415584",
                                 "System.Boolean", True)], 515, row)
            connections.extend([
                {"SourceParentOrChildId": field_id, "SourceSlotId": result_slot,
                 "TargetParentOrChildId": ray_id,
                 "TargetSlotId": "340ca675-9356-4548-ba64-732181bebeef"},
                {"SourceParentOrChildId": ray_id,
                 "SourceSlotId": "e178ef02-c9ac-48cd-a8cb-df3aec5941bb",
                 "TargetParentOrChildId": group_id,
                 "TargetSlotId": "9e961f73-1ee7-4369-9ac7-5c653e570b6f"},
            ])
    # Keep the import neutral: the old template's glow/blur/cover look belonged
    # to its source film. Users can add those effects in the editable home graph.
    render_to_bloom = next(edge for edge in template_connections
                           if edge["SourceParentOrChildId"] == template_ids["render"]
                           and edge["TargetParentOrChildId"] == template_ids["bloom"])
    passage_to_tonemap = next(edge for edge in template_connections
                              if edge["SourceParentOrChildId"] == template_ids["passage"]
                              and edge["TargetParentOrChildId"] == template_ids["tonemap"])
    connections.append({"SourceParentOrChildId": core_ids[template_ids["render"]],
                        "SourceSlotId": render_to_bloom["SourceSlotId"],
                        "TargetParentOrChildId": core_ids[template_ids["tonemap"]],
                        "TargetSlotId": passage_to_tonemap["TargetSlotId"]})
    t3["Connections"] = connections
    t3["Connections"].extend([
        {"SourceParentOrChildId": zero, "SourceSlotId": new_time,
         "TargetParentOrChildId": core_ids[template_ids["timeline"]],
         "TargetSlotId": "df42be73-5639-53e6-82f4-f72a9b15aba6"},
        {"SourceParentOrChildId": zero, "SourceSlotId": new_override,
         "TargetParentOrChildId": core_ids[template_ids["timeline"]],
         "TargetSlotId": "8e21625b-2c15-5b6c-8b42-78aa3500bf8b"},
    ])
    ordered = sorted(enumerate(worlds), key=lambda pair: pair[1]["active_clip"][0])
    if ordered[0][1]["active_clip"][0] != 1:
        raise ValueError("The first TiXL world must start at source frame 1")
    for (_, before), (_, after) in zip(ordered, ordered[1:]):
        if after["active_clip"][0] > before["active_clip"][1] + 1:
            raise ValueError("Gap between TiXL world clips")
    t3["Animator"] = []
    t3["ProjectSettings"]["Export"]["Title"] = blend.stem
    t3ui["Description"] = f"Replaceable Blender import from {blend.name}. Edit the project home for TiXL timing and effects."
    t3ui["SymbolChildUis"] = uis
    t3ui["Sections"] = []
    t3ui["InputUis"][0]["InputId"] = new_input
    t3ui["InputUis"].extend([
        {"InputId": new_time, "GroupTitle": "Playback", "Description": "Blender source time in seconds."},
        {"InputId": new_override, "GroupTitle": "Playback", "Description": "Use the editable project time clips."},
    ])
    t3ui["OutputUis"][0]["OutputId"] = new_output
    t3ui["Settings"]["Timeline"]["SourceExtentEnd"] = max(
        1.0, (max(w["active_clip"][1] for w in worlds) - 1) / manifest["fps"] / 2)
    out = cache / "native_source"
    out.mkdir(parents=True, exist_ok=True)
    files = [out / f"{class_name}.t3", out / f"{class_name}.t3ui", out / f"{class_name}.cs",
             out / "clip_plan.json"]
    _write_if_changed(files[0], json.dumps(t3, indent=2))
    _write_if_changed(files[1], json.dumps(t3ui, indent=2))
    _write_if_changed(files[2], f'''using T3.Core.Operator;
using T3.Core.Operator.Attributes;
using T3.Core.Operator.Slots;
using T3.Core.DataTypes.Vector;
using T3.Core.Resource;
using System.Runtime.InteropServices;
namespace {namespace};
[Guid("{t3['Id']}")]
internal sealed class {class_name} : Instance<{class_name}>
{{
    [Input(Guid="{new_input}")] public readonly InputSlot<Int2> OutputResolution = new(new Int2(960, 540));
    [Input(Guid="{new_time}")] public readonly InputSlot<float> SourceTimeSeconds = new();
    [Input(Guid="{new_override}")] public readonly InputSlot<bool> UseSourceTime = new();
    [Output(Guid="{new_output}")] public readonly Slot<Texture2D> Output = new();
}}
''')
    timeline = json.loads((data / "camera_timeline.json").read_text(encoding="utf-8"))
    duration = (max(w["active_clip"][1] for w in worlds) - 1) / manifest["fps"]
    shots = sorted(timeline.get("shots", []), key=lambda shot: shot["start"])
    starts = [float(shot["start"]) for shot in shots] or [
        (world["active_clip"][0] - 1) / manifest["fps"] for _, world in ordered]
    plan = [{"start": start, "end": starts[index + 1] if index + 1 < len(starts) else duration,
             "label": (shots[index].get("label") or f"Section {index + 1:02d}") if shots else
                      f"Section {index + 1:02d}"}
            for index, start in enumerate(starts)]
    plan_worlds = [{"name": world["world"],
                    "start": (world["active_clip"][0] - 1) / manifest["fps"],
                    "end": (world["active_clip"][1] - 1) / manifest["fps"]}
                   for world in worlds]
    _write_if_changed(files[3], json.dumps({"duration_seconds": duration, "clips": plan,
                                             "worlds": plan_worlds,
                                             "project_name": manifest.get("project_name", "")}, indent=2))
    _write_if_changed(out / "graph_summary.json", json.dumps({"blend": str(blend), "symbol": t3["Id"],
        "class": namespace + "." + class_name, "operators": len(t3["Children"]),
        "connections": len(t3["Connections"])}, indent=2))
    return files

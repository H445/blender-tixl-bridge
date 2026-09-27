"""Install generated Blender imports inside an editable TiXL project."""
import copy
import json
import re
import shutil
import subprocess
import time
import uuid
from pathlib import Path


def project_name_for(blend: Path, requested: str = "") -> str:
    """Allow a saved scene to choose a stable project name without changing defaults."""
    if requested:
        if not isinstance(requested, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", requested):
            raise ValueError("tixl_project_name must be a valid C# identifier")
        keywords = set(("abstract as base bool break byte case catch char checked class const continue "
                        "decimal default delegate do double else enum event explicit extern false finally "
                        "fixed float for foreach goto if implicit in int interface internal is lock long "
                        "namespace new null object operator out override params private protected public "
                        "readonly ref return sbyte sealed short sizeof stackalloc static string struct "
                        "switch this throw true try typeof uint ulong unchecked unsafe ushort using "
                        "virtual void volatile while").split())
        if requested in keywords:
            raise ValueError("tixl_project_name cannot be a C# keyword")
        if requested.lower() in {"con", "prn", "aux", "nul", *[f"com{i}" for i in range(1, 10)],
                                *[f"lpt{i}" for i in range(1, 10)]}:
            raise ValueError("tixl_project_name cannot be a reserved Windows filename")
        return requested
    label = "".join(c for c in blend.stem.title() if c.isalnum()) or "BlenderScene"
    suffix = uuid.uuid5(uuid.NAMESPACE_URL, str(blend.resolve()).lower()).hex[:8]
    return f"Blend{label}{suffix}"


def create_scaffold(project: Path, name: str, template: Path, blend: Path) -> None:
    """Create a TiXL project from a TiXL-created project, without the editor API."""
    csproj = project / f"{name}.csproj"
    if csproj.is_file():
        return
    if project.exists() and any(project.iterdir()):
        raise FileExistsError(f"Refusing to replace nonempty TiXL project: {project}")
    template_csproj = next(template.glob("*.csproj"), None)
    if template_csproj is None:
        raise FileNotFoundError(f"No TiXL project template in {template}")
    text = template_csproj.read_text(encoding="utf-8")
    values = {
        "RootNamespace": f"PrismalLabs.{name}",
        "HomeGuid": str(uuid.uuid5(uuid.NAMESPACE_URL, str(blend.resolve()).lower() + "/home")),
        "PackageId": str(uuid.uuid5(uuid.NAMESPACE_URL, str(blend.resolve()).lower() + "/package")),
    }
    for key, value in values.items():
        text, count = re.subn(rf"<{key}>[^<]*</{key}>", f"<{key}>{value}</{key}>", text, count=1)
        if count != 1:
            raise ValueError(f"TiXL template is missing {key}: {template_csproj}")
    project.mkdir(parents=True, exist_ok=True)
    for folder in ("Symbols", "Assets", "dependencies"):
        (project / folder).mkdir(exist_ok=True)
    props = template / "Directory.Build.props"
    if props.is_file():
        shutil.copy2(props, project / props.name)
    csproj.write_text(text, encoding="utf-8")


def _read_tixl_json(path: Path) -> dict:
    # TiXL writes C-style name comments after GUIDs. They are outside strings.
    content = re.sub(r'("[0-9a-fA-F-]{36}")/\*.*?\*/', r"\1", path.read_text(encoding="utf-8"))
    return json.loads(content)


def _connection(source: str, source_slot: str, target: str, target_slot: str) -> dict:
    return {"SourceParentOrChildId": source, "SourceSlotId": source_slot,
            "TargetParentOrChildId": target, "TargetSlotId": target_slot}


def _build_home(graph: dict, ui: dict, plan: dict, home_id: str, project_name: str,
                scene_id: str, scene_class: str, input_id: str, output_id: str) -> tuple[dict, dict]:
    zero = "00000000-0000-0000-0000-000000000000"
    import_id = str(uuid.uuid5(uuid.NAMESPACE_URL, graph["Id"] + "/import"))
    sequence_id = str(uuid.uuid5(uuid.NAMESPACE_URL, graph["Id"] + "/sequence"))
    source_slot = "f6cf5a61-eae9-54cd-b02f-94b0a19d48f6"
    sequence_input = "36bf79ae-84ac-5691-b8cb-a65d2e055d1a"
    sequence_output = "0b2900ec-dd39-55a7-8738-2e07d265f78c"
    clip_symbol = "622c47f1-a7f4-59ea-a9d0-9bd245842da3"
    sequence_symbol = "6defae81-c198-5bee-91e6-3160d17651dd"
    source_time_input = next(item["Id"] for item in graph["Inputs"] if item["DefaultValue"] == 0.0)
    use_time_input = next(item["Id"] for item in graph["Inputs"] if item["DefaultValue"] is False)
    home = copy.deepcopy(graph)
    home["Id"] = home_id
    home["Inputs"] = [copy.deepcopy(graph["Inputs"][0])]
    home["Children"] = [
        {"Id": import_id, "SymbolId": scene_id, "SymbolName": scene_class,
         "Name": "Blender scene / edit mesh and render", "InputValues": [
             {"Id": use_time_input, "Type": "System.Boolean", "Value": True}], "Outputs": []},
        {"Id": sequence_id, "SymbolId": sequence_symbol,
         "SymbolName": "PrismalLabs.BlenderExport.BlenderClipSequence",
         "Name": "Edit move timing here", "InputValues": [], "Outputs": []},
    ]
    home["Connections"] = [
        _connection(zero, input_id, import_id, input_id),
        _connection(sequence_id, sequence_output, import_id, source_time_input),
        _connection(import_id, output_id, zero, output_id),
    ]
    home["Animator"] = []
    home["ProjectSettings"]["Export"]["Title"] = project_name
    home_ui = copy.deepcopy(ui)
    home_ui["Id"] = home_id
    home_ui["Description"] = ("Editable TiXL project. Move or trim the source clips for timing. "
                              "Mesh, material, texture, and render paths are directly editable in this graph. "
                              "Sync refreshes Blender cache files without replacing those edits.")
    home_ui["InputUis"] = [copy.deepcopy(ui["InputUis"][0])]
    home_ui["SymbolChildUis"] = [
        {"ChildId": import_id, "Position": {"X": 420, "Y": 0}},
        {"ChildId": sequence_id, "Position": {"X": 0, "Y": 0}},
    ]
    home_ui["Sections"] = []
    home_ui["Settings"]["Timeline"]["SourceExtentEnd"] = max(1.0, plan["duration_seconds"] / 2)
    for index, clip in enumerate(plan["clips"]):
        start, end = float(clip["start"]), float(clip["end"])
        if end <= start:
            continue
        child_id = str(uuid.uuid5(uuid.NAMESPACE_URL, graph["Id"] + f"/clip/{index}"))
        label = re.sub(r"^\d+\s*[|/-]\s*", "", str(clip["label"])).replace("Camera | ", "")
        home["Children"].append({
            "Id": child_id, "SymbolId": clip_symbol,
            "SymbolName": "PrismalLabs.BlenderExport.BlenderSourceClip",
            "Name": f"{index + 1:02d} / {label}", "InputValues": [],
            "Outputs": [{"Id": source_slot, "OutputData": {
                "Type": "T3.Core.Animation.TimeClip", "TimeClip": {
                    "TimeRange": {"Start": start / 2, "End": end / 2},
                    "SourceRange": {"Start": start, "End": end},
                    "LayerIndex": 0, "SourceUnit": "Seconds"}}}],
        })
        home["Connections"].append(_connection(child_id, source_slot, sequence_id, sequence_input))
        home_ui["SymbolChildUis"].append({"ChildId": child_id,
                                          "Position": {"X": -320, "Y": index * 95}})
    return home, home_ui


def _flatten_scene(home: dict, home_ui: dict, scene: dict, scene_ui: dict) -> bool:
    """Move the editable scene into the home graph so typed wires are visible."""
    zero = "00000000-0000-0000-0000-000000000000"
    wrapper = next((child for child in home["Children"]
                    if child.get("SymbolId") == scene["Id"]), None)
    if wrapper is None:
        return False
    wrapper_id = wrapper["Id"]
    outside_inputs = {edge["TargetSlotId"]: edge for edge in home["Connections"]
                      if edge["TargetParentOrChildId"] == wrapper_id}
    outside_outputs = {}
    for edge in home["Connections"]:
        if edge["SourceParentOrChildId"] == wrapper_id:
            outside_outputs.setdefault(edge["SourceSlotId"], []).append(edge)
    wrapper_values = {value["Id"]: value for value in wrapper.get("InputValues", [])}
    scene_inputs = {value["Id"]: value for value in scene.get("Inputs", [])}
    # TiXL keeps child instances in a global registry. A copied child cannot
    # retain the ID it has in the archived scene symbol.
    id_map = {child["Id"]: str(uuid.uuid5(uuid.NAMESPACE_URL,
                                          home["Id"] + "/flat/" + child["Id"]))
              for child in scene["Children"]}
    old_ids = {child["Id"] for child in home["Children"] if child["Id"] != wrapper_id}
    overlap = old_ids.intersection(id_map.values())
    if overlap:
        raise ValueError(f"Scene children collide with home children: {sorted(overlap)}")
    home["Children"] = [child for child in home["Children"] if child["Id"] != wrapper_id]
    for source_child in scene["Children"]:
        child = copy.deepcopy(source_child)
        child["Id"] = id_map[source_child["Id"]]
        home["Children"].append(child)
    home["Connections"] = [edge for edge in home["Connections"]
                           if edge["SourceParentOrChildId"] != wrapper_id
                           and edge["TargetParentOrChildId"] != wrapper_id]
    children = {child["Id"]: child for child in home["Children"]}
    for edge in scene["Connections"]:
        source, target = edge["SourceParentOrChildId"], edge["TargetParentOrChildId"]
        mapped_source, mapped_target = id_map.get(source, source), id_map.get(target, target)
        if source == zero:
            outside = outside_inputs.get(edge["SourceSlotId"])
            if outside:
                home["Connections"].append(_connection(
                    outside["SourceParentOrChildId"], outside["SourceSlotId"],
                    mapped_target, edge["TargetSlotId"]))
            else:
                value = wrapper_values.get(edge["SourceSlotId"])
                if value is None and edge["SourceSlotId"] in scene_inputs:
                    definition = scene_inputs[edge["SourceSlotId"]]
                    value = {"Id": edge["TargetSlotId"],
                             "Type": "System.Boolean" if isinstance(definition["DefaultValue"], bool)
                             else "System.Single", "Value": definition["DefaultValue"]}
                if value is not None:
                    child = children[mapped_target]
                    child["InputValues"] = [item for item in child.get("InputValues", [])
                                            if item["Id"] != edge["TargetSlotId"]]
                    child["InputValues"].append({**copy.deepcopy(value), "Id": edge["TargetSlotId"]})
        elif target == zero:
            for outside in outside_outputs.get(edge["TargetSlotId"], []):
                home["Connections"].append(_connection(
                    mapped_source, edge["SourceSlotId"], outside["TargetParentOrChildId"],
                    outside["TargetSlotId"]))
        else:
            home["Connections"].append(_connection(mapped_source, edge["SourceSlotId"],
                                                     mapped_target, edge["TargetSlotId"]))
    home_ui["SymbolChildUis"] = [entry for entry in home_ui["SymbolChildUis"]
                                 if entry["ChildId"] != wrapper_id]
    scene_children = {child["Id"]: child for child in scene["Children"]}
    source_positions = {item["ChildId"]: item["Position"] for item in scene_ui["SymbolChildUis"]}
    branches = sorted((child for child in scene["Children"]
                       if child["SymbolName"].endswith("LoadGltfScene")),
                      key=lambda child: source_positions.get(child["Id"], {}).get("Y", 0))
    branch_rows = {}
    for child in branches:
        branch_rows.setdefault(child["Name"].split(" / ")[0], len(branch_rows))
    branch_x = {"LoadGltfScene": 420, "BlenderAnimationScene": 640,
                "BlenderMeshSelect": 860, "BlenderMeshReplace": 1080,
                "BlenderTextureSelect": 1300, "BlenderTextureReplace": 1520,
                "DrawScene": 1740, "Group": 1960}
    core_x = {"BlenderCameraTimeline": 200, "Switch": 2300,
              "BlenderExportLights": 2530, "SetEnvironment": 2760,
              "Camera": 2990, "ToneMapping": 3450, "DrawScreenQuad": 3680}
    for entry in scene_ui["SymbolChildUis"]:
        item = copy.deepcopy(entry)
        source_id = item["ChildId"]
        child = scene_children[source_id]
        item["ChildId"] = id_map[source_id]
        kind = child["SymbolName"].split(".")[-1]
        prefix = child["Name"].split(" / ")[0]
        if prefix in branch_rows and kind in branch_x:
            row = branch_rows[prefix]
            item["Position"] = {"X": branch_x[kind], "Y": row * 420 + (145 if "glass" in child["Name"].lower() else 0)}
        elif kind == "RenderTarget":
            item["Position"] = {"X": 3910 if child["Name"] == "Output target" else 3220,
                                "Y": 1050}
        elif kind in core_x:
            item["Position"] = {"X": core_x[kind],
                                "Y": -180 if kind == "BlenderCameraTimeline" else 1050}
        else:
            item["Position"]["X"] += 800
        home_ui["SymbolChildUis"].append(item)
    for item in home_ui.get("OutputUis", []):
        if "Position" in item:
            item["Position"] = {"X": 4160, "Y": 1050}
    home_ui["Description"] = ("Editable Blender/TiXL graph. TimeClips, mesh buffers, material textures, "
                              "and render textures are available directly here. Sync preserves these edits.")
    return True


def _rekey_shared_scene_children(home: dict, home_ui: dict, scene: dict) -> bool:
    """Repair homes flattened before child IDs were made globally unique."""
    scene_ids = {child["Id"] for child in scene["Children"]}
    shared = scene_ids.intersection(child["Id"] for child in home["Children"])
    if not shared:
        return False
    id_map = {old: str(uuid.uuid5(uuid.NAMESPACE_URL, home["Id"] + "/flat/" + old))
              for old in shared}
    occupied = {child["Id"] for child in home["Children"]}
    if occupied.intersection(id_map.values()):
        raise ValueError("A remapped scene child collides with a home child")
    for child in home["Children"]:
        child["Id"] = id_map.get(child["Id"], child["Id"])
    for edge in home["Connections"]:
        for field in ("SourceParentOrChildId", "TargetParentOrChildId"):
            edge[field] = id_map.get(edge[field], edge[field])
    for item in home_ui["SymbolChildUis"]:
        item["ChildId"] = id_map.get(item["ChildId"], item["ChildId"])
    return True


def _add_texture_ports(scene: dict, scene_ui: dict) -> None:
    """Expose Blender material maps as editable TiXL Texture2D connections."""
    mesh_result = "3012e73d-3204-59e0-a39c-b53aec53de67"
    draw_scene = "22ad6256-f741-4e8f-9a47-4b5b82e2cecf"
    select_symbol = "b1dc33bf-f973-5822-b079-e7ed36bb3ab1"
    replace_symbol = "c25f4c1c-e88d-575e-b8a0-befcf44f208c"
    select_scene = "ca9a3db9-6466-503a-a8a3-3909c7c30eb3"
    replace_scene = "a572804f-65b0-5bb6-b17f-207198bc6867"
    replace_result = "8d7ee90b-d479-5c83-9a76-3e1bb0b76143"
    maps = [
        ("f5d218bb-d055-5800-9971-db0f88b6ead3", "7ea5475c-6fc4-501b-a9b0-7def755c898b"),
        ("26556e6e-caed-5dff-9266-8665065977c2", "d3a68120-5d29-5e2c-b556-0b0ba0c86d97"),
        ("6ee9ad33-d30e-5592-bab6-c133054fc554", "b30a4fb2-1ce9-5bad-985c-4eff20474ba7"),
        ("9407cab1-76f5-5e92-af05-0bd3cb06820b", "1cedc4e7-eee9-5690-a7e4-55fb5f73b00f"),
    ]
    children = {child["Id"]: child for child in scene["Children"]}
    positions = {item["ChildId"]: item["Position"] for item in scene_ui["SymbolChildUis"]}
    affected = {}
    for edge in list(scene["Connections"]):
        if edge["SourceSlotId"] != mesh_result or edge["TargetSlotId"] != draw_scene:
            continue
        child = children.get(edge["SourceParentOrChildId"])
        if child and child["SymbolName"].endswith("BlenderMeshReplace"):
            affected.setdefault(child["Id"], []).append(edge)
    for mesh_id, edges in affected.items():
        select_id = str(uuid.uuid5(uuid.NAMESPACE_URL, mesh_id + "/texture-select"))
        replace_id = str(uuid.uuid5(uuid.NAMESPACE_URL, mesh_id + "/texture-replace"))
        if select_id in children or replace_id in children:
            continue
        mesh = children[mesh_id]
        base_name = mesh["Name"].replace("replace mesh", "")
        scene["Children"].extend([
            {"Id": select_id, "SymbolId": select_symbol,
             "SymbolName": "PrismalLabs.BlenderExport.BlenderTextureSelect",
             "Name": base_name + "select textures", "InputValues": [], "Outputs": []},
            {"Id": replace_id, "SymbolId": replace_symbol,
             "SymbolName": "PrismalLabs.BlenderExport.BlenderTextureReplace",
             "Name": base_name + "replace textures", "InputValues": [], "Outputs": []},
        ])
        position = positions.get(mesh_id, {"X": 0, "Y": 0})
        scene_ui["SymbolChildUis"].extend([
            {"ChildId": select_id, "Position": {"X": position["X"] + 250,
                                                  "Y": position["Y"] - 110}},
            {"ChildId": replace_id, "Position": {"X": position["X"] + 500,
                                                   "Y": position["Y"] - 110}},
        ])
        for edge in edges:
            scene["Connections"].remove(edge)
        scene["Connections"].extend([
            _connection(mesh_id, mesh_result, select_id, select_scene),
            _connection(mesh_id, mesh_result, replace_id, replace_scene),
        ])
        scene["Connections"].extend(_connection(select_id, output, replace_id, input_slot)
                                    for output, input_slot in maps)
        for edge in edges:
            scene["Connections"].append(_connection(replace_id, replace_result,
                                                     edge["TargetParentOrChildId"], draw_scene))


def _add_world_preloader(graph: dict, graph_ui: dict) -> bool:
    """Warm every glTF/animation branch before the command switch can play it."""
    if any(child.get("SymbolName", "").endswith("BlenderWorldPreload")
           for child in graph["Children"]):
        return False
    children = {child["Id"]: child for child in graph["Children"]}
    switch_edge = next((edge for edge in graph["Connections"]
                        if children.get(edge["SourceParentOrChildId"], {}).get("SymbolName", "").endswith("Switch")
                        and children.get(edge["TargetParentOrChildId"], {}).get("SymbolName", "").endswith("BlenderExportLights")), None)
    if switch_edge is None:
        raise ValueError("Blender scene has no world switch to preload")
    preload_id = str(uuid.uuid5(uuid.NAMESPACE_URL, graph["Id"] + "/world-preload"))
    if preload_id in children:
        raise ValueError("World preloader child ID collides with another child")
    preload_output = "507e7775-3442-4271-a7fe-6cfa86462e22"
    preload_worlds = "ebcd2d78-2b80-4b36-bd74-d074868b86dc"
    preload_command = "8bf57a9c-25a2-4a41-a349-4a1769ff904b"
    motion_output = "cbb6f6a0-27c9-4555-8e5e-fd23e8d3f991"
    graph["Children"].append({
        "Id": preload_id, "SymbolId": "f3cf6968-ad60-41e4-a900-32566c8f0f2d",
        "SymbolName": "PrismalLabs.BlenderExport.BlenderWorldPreload",
        "Name": "Preload all Blender worlds", "InputValues": [], "Outputs": [],
    })
    graph["Connections"].remove(switch_edge)
    graph["Connections"].extend([
        _connection(switch_edge["SourceParentOrChildId"], switch_edge["SourceSlotId"],
                    preload_id, preload_command),
        _connection(preload_id, preload_output,
                    switch_edge["TargetParentOrChildId"], switch_edge["TargetSlotId"]),
    ])
    graph["Connections"].extend(
        _connection(child["Id"], motion_output, preload_id, preload_worlds)
        for child in graph["Children"]
        if child["SymbolName"].endswith("BlenderAnimationScene")
    )
    lights_ui = next((item for item in graph_ui["SymbolChildUis"]
                      if item["ChildId"] == switch_edge["TargetParentOrChildId"]), None)
    position = lights_ui["Position"] if lights_ui else {"X": 2500, "Y": 1000}
    graph_ui["SymbolChildUis"].append({
        "ChildId": preload_id,
        "Position": {"X": position["X"] - 130, "Y": position["Y"] - 220},
    })
    return True


def _link_world_clips(home: dict, home_ui: dict, plan: dict, import_symbol_id: str) -> bool:
    """Give each world an editable clip-to-animation time lane in the home graph."""
    worlds = plan.get("worlds", [])
    if not worlds:
        return False
    children = {child["Id"]: child for child in home["Children"]}
    timeline = next((child for child in home["Children"]
                     if child["SymbolName"].endswith("BlenderCameraTimeline")), None)
    global_sequence = next((child for child in home["Children"]
                            if child["SymbolName"].endswith("BlenderClipSequence")
                            and child["Name"] == "Edit move timing here"), None)
    if global_sequence is None:
        expected = str(uuid.uuid5(uuid.NAMESPACE_URL, import_symbol_id + "/sequence"))
        global_sequence = children.get(expected)
    if global_sequence is None and timeline is not None:
        source_ids = {edge["SourceParentOrChildId"] for edge in home["Connections"]
                      if edge["SourceSlotId"] == "0b2900ec-dd39-55a7-8738-2e07d265f78c"
                      and edge["TargetParentOrChildId"] == timeline["Id"]
                      and edge["TargetSlotId"] == "df42be73-5639-53e6-82f4-f72a9b15aba6"}
        matches = [children[child_id] for child_id in source_ids
                   if child_id in children
                   and children[child_id]["SymbolName"].endswith("BlenderClipSequence")]
        if len(matches) == 1:
            global_sequence = matches[0]
    if global_sequence is None:
        # TiXL can assign different child IDs to a saved home, and users may
        # rename the sequence. The global lane is the one fed by the most
        # source clips; per-world lanes have only their own subset.
        clip_ids = {child["Id"] for child in home["Children"]
                    if child["SymbolName"].endswith("BlenderSourceClip")}
        sequence_inputs = {}
        for edge in home["Connections"]:
            if (edge["SourceParentOrChildId"] in clip_ids
                and edge["TargetSlotId"] == "36bf79ae-84ac-5691-b8cb-a65d2e055d1a"):
                target = children.get(edge["TargetParentOrChildId"])
                if target and target["SymbolName"].endswith("BlenderClipSequence"):
                    sequence_inputs[target["Id"]] = sequence_inputs.get(target["Id"], 0) + 1
        if sequence_inputs:
            most_inputs = max(sequence_inputs.values())
            matches = [child_id for child_id, count in sequence_inputs.items()
                       if count == most_inputs]
            if len(matches) == 1:
                global_sequence = children[matches[0]]
    global_id = global_sequence["Id"] if global_sequence else None
    if global_id is None or timeline is None:
        return False
    clip_children = [child for child in home["Children"]
                     if child["SymbolName"].endswith("BlenderSourceClip")]
    clip_by_index = {}
    for child in clip_children:
        match = re.match(r"^\s*(\d+)\s*/", child["Name"])
        if match:
            clip_by_index[int(match.group(1)) - 1] = child
    for index, planned in enumerate(plan["clips"]):
        if index in clip_by_index:
            continue
        expected = str(uuid.uuid5(uuid.NAMESPACE_URL, import_symbol_id + f"/clip/{index}"))
        if expected in children:
            clip_by_index[index] = children[expected]
            continue
        # Older projects can have different generated IDs and edited names.
        # Their saved TimeClip source range still identifies the intended clip.
        for child in clip_children:
            if child in clip_by_index.values():
                continue
            outputs = child.get("Outputs", [])
            source_range = (outputs[0].get("OutputData", {}).get("TimeClip", {})
                            .get("SourceRange", {})) if outputs else {}
            if (abs(float(source_range.get("Start", -1)) - planned["start"]) < 0.001
                and abs(float(source_range.get("End", -1)) - planned["end"]) < 0.001):
                clip_by_index[index] = child
                break
    positions = {item["ChildId"]: item["Position"] for item in home_ui["SymbolChildUis"]}
    clip_output = "f6cf5a61-eae9-54cd-b02f-94b0a19d48f6"
    sequence_input = "36bf79ae-84ac-5691-b8cb-a65d2e055d1a"
    sequence_time = "0b2900ec-dd39-55a7-8738-2e07d265f78c"
    sequence_active = "8ac94bb7-59c9-486b-9f8a-47e0ec25110e"
    timeline_time = "dcc2da87-6bd5-5e0b-87ac-2cb31a95ee76"
    motion_time = "ee2eaef9-6e5a-48b3-9df0-91b2f9ab7dc7"
    router_global = "784572bb-8070-4ebb-89e8-959caaaaff76"
    router_world = "ffef5b73-69cb-47f9-ae33-638d2659322b"
    router_mapped = "375451d0-393d-49c4-9cf8-c2010c034894"
    router_active = "f67fb4a9-149c-4b49-84b8-f177bf653e9e"
    router_time = "c1dbdb9e-a7ad-424b-b2ba-94bd9ce71daf"
    changed = False
    for world_index, world in enumerate(worlds):
        name = world["name"]
        # Camera markers need not line up with world boundaries. A clip that
        # spans two worlds must feed both animation lanes.
        clip_indices = [index for index, clip in enumerate(plan["clips"])
                        if clip["start"] < world["end"] - 0.0001
                        and clip["end"] > world["start"] + 0.0001]
        clip_ids = [clip_by_index[index]["Id"] for index in clip_indices if index in clip_by_index]
        if not clip_indices or len(clip_ids) != len(clip_indices):
            continue
        motions = [child for child in home["Children"]
                   if child["SymbolName"].endswith("BlenderAnimationScene")
                   and any(str(value.get("Value", "")).replace("\\", "/").lower().endswith(
                       f"/{name}_animation.bin".lower()) for value in child.get("InputValues", [])
                           if value["Id"] == "ca02f7a3-a03a-4db0-a05d-3a66b0c9ab11")]
        default_edges = [edge for edge in home["Connections"]
                         if edge["SourceParentOrChildId"] == timeline["Id"]
                         and edge["SourceSlotId"] == timeline_time
                         and edge["TargetSlotId"] == motion_time
                         and any(motion["Id"] == edge["TargetParentOrChildId"] for motion in motions)]
        if not default_edges:
            continue  # User-supplied timing wires remain untouched.
        sequence_id = str(uuid.uuid5(uuid.NAMESPACE_URL,
                                     home["Id"] + f"/world-clip/{world_index}/sequence"))
        router_id = str(uuid.uuid5(uuid.NAMESPACE_URL,
                                   home["Id"] + f"/world-clip/{world_index}/time"))
        if sequence_id in children or router_id in children:
            continue
        label = name.replace("_", " ").title()
        home["Children"].extend([
            {"Id": sequence_id, "SymbolId": "6defae81-c198-5bee-91e6-3160d17651dd",
             "SymbolName": "PrismalLabs.BlenderExport.BlenderClipSequence",
             "Name": f"{label} / clips", "InputValues": [], "Outputs": []},
            {"Id": router_id, "SymbolId": "a34b77c3-9eb5-41cd-86f6-6d8eba4fe0a0",
             "SymbolName": "PrismalLabs.BlenderExport.BlenderWorldClipTime",
             "Name": f"{label} / clip to scene time", "InputValues": [], "Outputs": []},
        ])
        children[sequence_id], children[router_id] = home["Children"][-2:]
        home["Connections"] = [edge for edge in home["Connections"] if edge not in default_edges]
        home["Connections"].extend(_connection(clip_id, clip_output, sequence_id, sequence_input)
                                   for clip_id in clip_ids)
        home["Connections"].extend([
            _connection(global_id, sequence_time, router_id, router_global),
            _connection(sequence_id, sequence_time, router_id, router_world),
            _connection(sequence_id, sequence_active, router_id, router_active),
            _connection(timeline["Id"], timeline_time, router_id, router_mapped),
        ])
        home["Connections"].extend(_connection(router_id, router_time,
                                                edge["TargetParentOrChildId"], motion_time)
                                   for edge in default_edges)
        row_y = world_index * 420
        home_ui["SymbolChildUis"].extend([
            {"ChildId": sequence_id, "Position": {"X": 0, "Y": row_y + 20}},
            {"ChildId": router_id, "Position": {"X": 420, "Y": row_y - 190}},
        ])
        for clip_offset, (clip_index, clip_id) in enumerate(zip(clip_indices, clip_ids)):
            position = positions.get(clip_id)
            if position == {"X": -320, "Y": clip_index * 95}:
                position.update({"X": -320, "Y": row_y + clip_offset * 95})
        changed = True
    if changed:
        # Move only nodes still at the bridge's old default positions. Respect
        # TiXL layouts the user has already rearranged.
        if positions.get(global_id) == {"X": 0, "Y": 0}:
            positions[global_id].update({"X": -320, "Y": -600})
        if positions.get(timeline["Id"]) == {"X": 200, "Y": -180}:
            positions[timeline["Id"]].update({"X": 200, "Y": -600})
    return changed


def _editable_scene(graph: dict, ui: dict, source: str, name: str) -> tuple[dict, dict, str]:
    """Seed a user-owned scene once. Subsequent syncs never replace it."""
    scene = copy.deepcopy(graph)
    scene_ui = copy.deepcopy(ui)
    scene_id = str(uuid.uuid5(uuid.NAMESPACE_URL, graph["Id"] + "/editable-scene"))
    scene["Id"] = scene_ui["Id"] = scene_id
    scene_ui["Description"] = ("Edit mesh loaders, select/replace mesh buffers, materials, camera, "
                               "lighting, render target, and tone mapping here. Sync leaves this graph intact.")

    # Give every opaque world a native mesh editing port after its Blender animation.
    # Mesh modifiers can be inserted between Select and Replace without touching the
    # export or breaking the rest of the character's animated draw dispatches.
    select_symbol = "a8524651-56c7-58fb-94b2-cf9692f95208"
    replace_symbol = "789071a8-bd89-51bf-9f47-b942db0fa875"
    select_scene = "12bcfca2-ebbc-55f5-a75c-dd53ab356690"
    select_mesh = "62d60908-5865-55cc-b0c6-821b3008c913"
    replace_scene = "65a28b5a-632d-566b-ad67-399cb9e4f515"
    replace_mesh = "259ad7a2-2034-5836-a17a-707ad5905d6d"
    replace_result = "3012e73d-3204-59e0-a39c-b53aec53de67"
    motion_result = "cbb6f6a0-27c9-4555-8e5e-fd23e8d3f991"
    draw_scene = "22ad6256-f741-4e8f-9a47-4b5b82e2cecf"
    child_by_id = {child["Id"]: child for child in scene["Children"]}
    positions = {entry["ChildId"]: entry["Position"] for entry in scene_ui["SymbolChildUis"]}
    editable_motions = {}
    for edge in list(scene["Connections"]):
        if edge["SourceSlotId"] == motion_result and edge["TargetSlotId"] == draw_scene:
            motion = child_by_id[edge["SourceParentOrChildId"]]
            if motion["SymbolName"].endswith("BlenderAnimationScene"):
                editable_motions.setdefault(motion["Id"], []).append(edge)
    for motion_id, draw_edges in editable_motions.items():
        motion = child_by_id[motion_id]
        seed = motion["Id"]
        select_id = str(uuid.uuid5(uuid.NAMESPACE_URL, seed + "/mesh-select"))
        replace_id = str(uuid.uuid5(uuid.NAMESPACE_URL, seed + "/mesh-replace"))
        scene["Children"].extend([
            {"Id": select_id, "SymbolId": select_symbol,
             "SymbolName": "PrismalLabs.BlenderExport.BlenderMeshSelect",
             "Name": motion["Name"].replace("motion", "select mesh"),
             "InputValues": [], "Outputs": []},
            {"Id": replace_id, "SymbolId": replace_symbol,
             "SymbolName": "PrismalLabs.BlenderExport.BlenderMeshReplace",
             "Name": motion["Name"].replace("motion", "replace mesh"),
             "InputValues": [], "Outputs": []},
        ])
        position = positions.get(motion["Id"], {"X": 0, "Y": 0})
        x, y = position["X"], position["Y"]
        scene_ui["SymbolChildUis"].extend([
            {"ChildId": select_id, "Position": {"X": x + 250, "Y": y - 110}},
            {"ChildId": replace_id, "Position": {"X": x + 500, "Y": y - 110}},
        ])
        for edge in draw_edges:
            scene["Connections"].remove(edge)
        scene["Connections"].extend([
            _connection(motion["Id"], motion_result, select_id, select_scene),
            _connection(motion["Id"], motion_result, replace_id, replace_scene),
            _connection(select_id, select_mesh, replace_id, replace_mesh),
        ])
        for edge in draw_edges:
            scene["Connections"].append(_connection(replace_id, replace_result,
                                                     edge["TargetParentOrChildId"], draw_scene))
    _add_texture_ports(scene, scene_ui)
    _add_world_preloader(scene, scene_ui)
    class_name = name + "Scene"
    scene_source = source.replace("namespace PrismalLabs.BlenderExport.Generated;",
                                  f"namespace PrismalLabs.{name};")
    old_class = re.search(r"internal sealed class (\w+) :", scene_source).group(1)
    scene_source = scene_source.replace(f"class {old_class} : Instance<{old_class}>",
                                        f"class {class_name} : Instance<{class_name}>")
    scene_source = scene_source.replace(f'[Guid("{graph["Id"]}")]', f'[Guid("{scene_id}")]')
    return scene, scene_ui, scene_source


def _make_portless_home(home: dict, ui: dict) -> None:
    """Keep resolution inside the home; only generated import symbols expose ports."""
    zero = "00000000-0000-0000-0000-000000000000"
    template = json.loads((Path(__file__).resolve().parents[1] / "templates"
                           / "home_resolution.json").read_text(encoding="utf-8"))
    child = copy.deepcopy(template["child"])
    child["Id"] = str(uuid.uuid5(uuid.NAMESPACE_URL, home["Id"] + "/resolution"))
    width, height = template["default_resolution"]
    for value in child["InputValues"]:
        value["Value"] = width if value["Id"] == "579e72d6-638e-4b17-bb4e-88a55e3a1d4d" else height
    input_ids = {item["Id"] for item in home.get("Inputs", [])}
    connections = []
    for edge in home["Connections"]:
        if edge["TargetParentOrChildId"] == zero:
            continue
        if edge["SourceParentOrChildId"] == zero:
            if edge["SourceSlotId"] not in input_ids:
                raise ValueError("Unknown home input while creating portless home")
            edge = {**edge, "SourceParentOrChildId": child["Id"],
                    "SourceSlotId": template["output_slot"]}
        connections.append(edge)
    resolution_slot = "03749b41-cc3c-4f38-aea6-d7cea19fc073"
    for target in home["Children"]:
        if not target["SymbolName"].endswith(".RenderTarget"):
            continue
        if not any(edge["TargetParentOrChildId"] == target["Id"]
                   and edge["TargetSlotId"] == resolution_slot for edge in connections):
            connections.append(_connection(child["Id"], template["output_slot"],
                                           target["Id"], resolution_slot))
    home["Children"].append(child)
    home["Connections"] = connections
    home["Inputs"] = []
    home.pop("Outputs", None)
    ui["InputUis"] = []
    ui["OutputUis"] = []
    ui["SymbolChildUis"].append({"ChildId": child["Id"], "Position": {"X": 0, "Y": 0}})


def populate(project: Path, graph_files: list[Path], backup_root: Path, editor: Path,
             build: bool = True) -> None:
    from retention_lifecycle import new_backup
    project = project.resolve()
    csproj = next(project.glob("*.csproj"), None)
    if csproj is None:
        raise FileNotFoundError(f"No TiXL project scaffold in {project}")
    name = csproj.stem
    symbols = project / "Symbols"
    symbols.mkdir(parents=True, exist_ok=True)
    text = csproj.read_text(encoding="utf-8")
    match = re.search(r"<HomeGuid>([^<]+)</HomeGuid>", text)
    if match is None:
        raise ValueError("The TiXL project has no release HomeGuid")
    home_id = match.group(1)
    graph = json.loads(graph_files[0].read_text(encoding="utf-8"))
    ui = json.loads(graph_files[1].read_text(encoding="utf-8"))
    plan = json.loads(graph_files[3].read_text(encoding="utf-8"))
    zero = "00000000-0000-0000-0000-000000000000"
    output_id = next(edge["TargetSlotId"] for edge in graph["Connections"]
                     if edge["TargetParentOrChildId"] == zero)
    input_id = graph["Inputs"][0]["Id"]
    scene_class = f"PrismalLabs.{name}.{name}Scene"
    scene, scene_ui, scene_source = _editable_scene(
        graph, ui, graph_files[2].read_text(encoding="utf-8"), name)
    scene_files = [symbols / f"{name}Scene{suffix}" for suffix in (".cs", ".t3", ".t3ui")]
    if not any(path.is_file() for path in scene_files):
        scene_files[0].write_text(scene_source, encoding="utf-8")
        scene_files[1].write_text(json.dumps(scene, indent=2), encoding="utf-8")
        scene_files[2].write_text(json.dumps(scene_ui, indent=2), encoding="utf-8")
    elif not all(path.is_file() for path in scene_files):
        raise FileNotFoundError(f"Incomplete editable TiXL scene symbol: {scene_files}")
    # Use the saved editable graph, including any mesh/render edits made in TiXL.
    scene = _read_tixl_json(scene_files[1])
    scene_ui = _read_tixl_json(scene_files[2])
    scene_for_home = copy.deepcopy(scene)
    scene_ui_for_home = copy.deepcopy(scene_ui)
    _add_texture_ports(scene_for_home, scene_ui_for_home)
    _add_world_preloader(scene_for_home, scene_ui_for_home)
    home_files = [symbols / f"{name}{suffix}" for suffix in (".cs", ".t3", ".t3ui")]
    existing_home = _read_tixl_json(home_files[1]) if home_files[1].is_file() else None
    old_import = next((child for child in existing_home.get("Children", [])
                       if child.get("SymbolId") == graph["Id"]), None) if existing_home else None
    has_scene_wrapper = existing_home is not None and any(
        child.get("SymbolId") == scene["Id"] for child in existing_home.get("Children", []))
    has_flat_scene = existing_home is not None and any(
        child.get("SymbolName", "").endswith(("BlenderMeshSelect", "BlenderTextureSelect",
                                                 "BlenderCameraTimeline", "LoadGltfScene"))
        for child in existing_home.get("Children", []))
    if old_import or has_scene_wrapper:
        backup = new_backup(backup_root, "home")
        for path in home_files:
            if path.is_file():
                shutil.copy2(path, backup / path.name)
        if old_import:
            old_import["SymbolId"] = scene["Id"]
            old_import["SymbolName"] = scene_class
            old_import["Name"] = "Blender scene / edit mesh and render"
        home_ui = _read_tixl_json(home_files[2])
        _flatten_scene(existing_home, home_ui, scene_for_home, scene_ui_for_home)
        _link_world_clips(existing_home, home_ui, plan, graph["Id"])
        home_files[1].write_text(json.dumps(existing_home, indent=2), encoding="utf-8")
        home_files[2].write_text(json.dumps(home_ui, indent=2), encoding="utf-8")
    elif has_flat_scene:
        home_ui = _read_tixl_json(home_files[2])
        changed = _rekey_shared_scene_children(existing_home, home_ui, scene_for_home)
        changed |= _add_world_preloader(existing_home, home_ui)
        changed |= _link_world_clips(existing_home, home_ui, plan, graph["Id"])
        if changed:
            backup = new_backup(backup_root, "home")
            for path in home_files:
                if path.is_file():
                    shutil.copy2(path, backup / path.name)
            home_files[1].write_text(json.dumps(existing_home, indent=2), encoding="utf-8")
            home_files[2].write_text(json.dumps(home_ui, indent=2), encoding="utf-8")
    else:
        if any(path.is_file() for path in home_files):
            backup = new_backup(backup_root, "home")
            for path in home_files:
                if path.is_file():
                    shutil.copy2(path, backup / path.name)
        home, home_ui = _build_home(graph, ui, plan, home_id, name,
                                    scene["Id"], scene_class, input_id, output_id)
        _flatten_scene(home, home_ui, scene_for_home, scene_ui_for_home)
        _link_world_clips(home, home_ui, plan, graph["Id"])
        _make_portless_home(home, home_ui)
        from blend_sync_layout import layout_home
        layout_home(home, home_ui, plan, graph["Id"])
        source = f'''using T3.Core.Operator;
using T3.Core.Operator.Attributes;
using T3.Core.Operator.Interfaces;
using T3.Core.Operator.Slots;
using T3.Core.DataTypes.Vector;
using T3.Core.Resource;
using System.Runtime.InteropServices;
namespace PrismalLabs.{name};
[Guid("{home_id}")]
internal sealed class {name} : Instance<{name}>
{{
}}
public sealed class ShareDefinition : IShareResources
{{ public bool ShouldShareResources => true; }}
'''
        home_files[0].write_text(source, encoding="utf-8")
        home_files[1].write_text(json.dumps(home, indent=2), encoding="utf-8")
        home_files[2].write_text(json.dumps(home_ui, indent=2), encoding="utf-8")
    # This import is refreshed; home and scene are user-owned after their initial creation.
    generated_dir = symbols / "PrismalLabs" / "BlenderExport" / "Generated"
    generated_dir.mkdir(parents=True, exist_ok=True)
    legacy_graph = symbols / graph_files[0].name
    legacy_is_import = (legacy_graph.is_file()
                        and _read_tixl_json(legacy_graph).get("Id") == graph["Id"])
    for path in graph_files[:3]:
        legacy = symbols / path.name
        if legacy_is_import and legacy.is_file():
            backup = new_backup(backup_root, "generated_root_duplicate")
            shutil.copy2(legacy, backup / path.name)
            legacy.unlink()
        shutil.copy2(path, generated_dir / path.name)
    if build:
        subprocess.run(["dotnet", "build", str(csproj),
                        f"-p:T3_ASSEMBLY_PATH={editor}", "--nologo"], check=True)

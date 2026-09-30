"""Stage removal of Asterion's Ship FX mesh/texture chain from a TiXL Home graph.

Run offline on the saved ``AsterionBreakaway.t3`` while preserving the source.
Install the staged .t3/.t3ui only after TiXL editor work is saved and closed.
"""

import json
import re
import sys
from pathlib import Path


def load(path):
    source = Path(path).read_text(encoding="utf-8")
    return json.loads(re.sub(r'("[0-9a-fA-F-]{36}")/\*.*?\*/',
                             r"\1", source))


def remove(source, output_dir):
    source = Path(source)
    output_dir = Path(output_dir)
    graph = load(source)
    ui = load(source.with_suffix(".t3ui"))
    if graph["Id"] != ui["Id"]:
        raise ValueError("TiXL graph/UI symbol IDs disagree")
    names = {node["Id"]: node.get("Name", "") for node in graph["Children"]}
    removed_ids = {node_id for node_id, name in names.items()
                   if name.startswith("Ship FX |")}
    if len(removed_ids) != 24:
        raise ValueError(f"Expected 24 Ship FX nodes, found {len(removed_ids)}")
    by_name = {node.get("Name"): node for node in graph["Children"]}
    upstream = by_name["Main / opaque replace textures"]
    downstream = by_name["Main / opaque draw"]
    source_slot = "8d7ee90b-d479-5c83-9a76-3e1bb0b76143"
    target_slot = "22ad6256-f741-4e8f-9a47-4b5b82e2cecf"
    boundary = [edge for edge in graph["Connections"]
                if (edge["SourceParentOrChildId"] in removed_ids) !=
                (edge["TargetParentOrChildId"] in removed_ids)]
    exits = [edge for edge in boundary
             if edge["SourceParentOrChildId"] in removed_ids]
    if len(boundary) != 8 or len(exits) != 1 or (
            exits[0]["TargetParentOrChildId"] != downstream["Id"] or
            exits[0]["TargetSlotId"] != target_slot):
        raise ValueError("Ship FX boundary differs from the installed chain")
    direct = {"SourceParentOrChildId": upstream["Id"],
              "SourceSlotId": source_slot,
              "TargetParentOrChildId": downstream["Id"],
              "TargetSlotId": target_slot}
    if direct in graph["Connections"]:
        raise ValueError("Direct opaque route already exists")

    graph["Children"] = [node for node in graph["Children"]
                         if node["Id"] not in removed_ids]
    graph["Connections"] = [edge for edge in graph["Connections"]
                            if edge["SourceParentOrChildId"] not in removed_ids
                            and edge["TargetParentOrChildId"] not in removed_ids]
    graph["Connections"].append(direct)
    ui["SymbolChildUis"] = [entry for entry in ui["SymbolChildUis"]
                            if entry["ChildId"] not in removed_ids]
    surviving = {node["Id"] for node in graph["Children"]}
    if any(edge["SourceParentOrChildId"] not in surviving or
           edge["TargetParentOrChildId"] not in surviving
           for edge in graph["Connections"]):
        raise ValueError("A graph edge lost its endpoint")
    if {entry["ChildId"] for entry in ui["SymbolChildUis"]} != surviving:
        raise ValueError("Graph and UI child sets disagree")
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / source.name).write_text(
        json.dumps(graph, indent=2) + "\n", encoding="utf-8")
    (output_dir / source.with_suffix(".t3ui").name).write_text(
        json.dumps(ui, indent=2) + "\n", encoding="utf-8")
    print({"removedShipFxNodes": len(removed_ids),
           "remainingNodes": len(graph["Children"]),
           "remainingConnections": len(graph["Connections"]),
           "restoredOpaqueRoute": direct})


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("Usage: remove_asterion_ship_effects.py <home.t3> <stage-dir>")
    remove(sys.argv[1], sys.argv[2])

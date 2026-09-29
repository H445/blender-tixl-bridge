"""Set the AsterionBreakaway TiXL Home render size with the editor closed.

The Blender scene has its own render settings. This changes the saved TiXL
Resolution Int2, which feeds both the scene and final output render targets.
The script stages a candidate and backs up the original outside Symbols.
"""

from __future__ import annotations

import argparse
import copy
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path


GRAPH_ID = "564f37c0-cb8c-5aff-97b3-683ec4ab5477"
RESOLUTION_ID = "362cb9ab-fb24-5178-a03c-29a888d501be"
HEIGHT_ID = "53602af2-48d9-42ab-80c3-ae1f1e600d28"
WIDTH_ID = "579e72d6-638e-4b17-bb4e-88a55e3a1d4d"
RENDER_TARGETS = {
    "071fed5d-a904-5f4a-8d35-0737aaccd2f0",
    "2cb060f4-9cad-58f6-acbc-e386b2c12efb",
}
STAGING = Path(__file__).resolve().parent / ".tixl_cache/AsterionBreakaway/resolution"
BACKUPS = Path(__file__).resolve().parent / ".tixl_cache/AsterionBreakaway/graph_backups"


def read_graph(path: Path) -> dict:
    return json.loads(re.sub(r"/\*.*?\*/", "", path.read_text(encoding="utf-8"), flags=re.S))


def plan(graph: dict, width: int, height: int) -> tuple[dict, bool]:
    if graph["Id"] != GRAPH_ID:
        raise ValueError("Selected graph is not AsterionBreakaway")
    nodes = [node for node in graph["Children"] if node["Id"] == RESOLUTION_ID]
    if len(nodes) != 1 or nodes[0]["SymbolName"] != "Types.Values.Int2":
        raise ValueError("Expected TiXL Resolution Int2 is missing")
    targets = {edge["TargetParentOrChildId"] for edge in graph["Connections"]
               if edge["SourceParentOrChildId"] == RESOLUTION_ID}
    if not RENDER_TARGETS.issubset(targets):
        raise ValueError("Resolution is not wired to both render targets")
    candidate = copy.deepcopy(graph)
    node = next(child for child in candidate["Children"] if child["Id"] == RESOLUTION_ID)
    values = {item["Id"]: item for item in node["InputValues"]}
    if not {WIDTH_ID, HEIGHT_ID}.issubset(values):
        raise ValueError("Expected Width/Height inputs are missing")
    old = (values[WIDTH_ID]["Value"], values[HEIGHT_ID]["Value"])
    if old not in {(960, 540), (width, height)}:
        raise ValueError(f"Resolution changed in TiXL since planning: {old}")
    values[WIDTH_ID]["Value"] = width
    values[HEIGHT_ID]["Value"] = height
    check = copy.deepcopy(candidate)
    updated = next(child for child in check["Children"] if child["Id"] == RESOLUTION_ID)
    for item in updated["InputValues"]:
        if item["Id"] == WIDTH_ID:
            item["Value"] = old[0]
        elif item["Id"] == HEIGHT_ID:
            item["Value"] = old[1]
    if check != graph:
        raise AssertionError("Unrelated graph data changed")
    return candidate, old != (width, height)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--graph", type=Path, required=True)
    parser.add_argument("--width", type=int, default=1920)
    parser.add_argument("--height", type=int, default=1080)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if args.width <= 0 or args.height <= 0:
        raise ValueError("Resolution dimensions must be positive")
    graph_path = args.graph.resolve()
    graph = read_graph(graph_path)
    candidate, changed = plan(graph, args.width, args.height)
    print(f"TiXL resolution: {args.width}x{args.height}; change required: {changed}")
    if not changed:
        return
    STAGING.mkdir(parents=True, exist_ok=True)
    staged = STAGING / graph_path.name
    staged.write_text(json.dumps(candidate, indent=2) + "\n", encoding="utf-8")
    if read_graph(staged) != candidate:
        raise AssertionError("Staged graph failed validation")
    print(f"Staged: {staged}")
    if not args.apply:
        return
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = BACKUPS / f"before-1080p-{stamp}"
    backup.mkdir(parents=True, exist_ok=False)
    shutil.copy2(graph_path, backup / graph_path.name)
    shutil.copy2(staged, graph_path)
    if read_graph(graph_path) != candidate:
        raise AssertionError("Installed graph failed validation")
    print(f"Installed: {graph_path}; backup: {backup}")


if __name__ == "__main__":
    main()

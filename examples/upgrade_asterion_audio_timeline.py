"""Replace legacy Asterion graph audio with native TiXL AudioClip/AudioBus.

Run with TiXL closed through the debug bridge. Preserves every unrelated graph
node and connection, and replaces only the scan WAV with the revised cue.
"""

from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from install_asterion_audio import (AUDIO, BACKUPS, CLIPS, CLIP_SYMBOL,
                                    DEFAULT_GRAPH, GRAPH_ID, TARGET_COMMAND,
                                    inspect_audio, install, link, read_graph, uid)


OLD_NAMES = {"Audio | 120 BPM project time", "Audio | mission audio bus",
             *(f"Audio | {name} clip" for name, _, _ in CLIPS)}


def upgrade(graph, ui):
    if graph["Id"] != GRAPH_ID or ui["Id"] != GRAPH_ID:
        raise ValueError("This is not the AsterionBreakaway graph")
    children = graph["Children"]
    old = {child.get("Name"): child for child in children
           if child.get("Name") in OLD_NAMES}
    if set(old) != OLD_NAMES:
        raise ValueError(f"Unexpected old audio graph: {sorted(old)}")
    expected_ids = {old[name]["Id"] for name in OLD_NAMES}
    if expected_ids != {uid(name.removeprefix("Audio | ")) for name in OLD_NAMES}:
        raise ValueError("Old audio node identities changed; preserving edits")
    native = [child for child in children if child.get("SymbolId") == CLIP_SYMBOL]
    if len(native) != 1:
        raise ValueError("Expected one user-added native AudioClip to adopt")
    scan = native[0]
    if scan.get("Name") or scan.get("InputValues") or len(scan.get("Outputs", [])) != 1:
        raise ValueError("The native AudioClip was edited; preserving it")
    if any(edge["SourceParentOrChildId"] == scan["Id"]
           or edge["TargetParentOrChildId"] == scan["Id"]
           for edge in graph["Connections"]):
        raise ValueError("The native AudioClip is wired; preserving it")
    fit = next(child for child in children if child.get("Name") == "Output fit")
    target = next(child for child in children if child.get("Name") == "Output target")
    bus = old["Audio | mission audio bus"]
    fit_bus = link(fit["Id"], "3c8116a2-2686-41ba-8bfd-d1b3fb929b02",
                   bus["Id"], "2786a789-4527-45a4-aeb8-581ee93a621e")
    bus_target = link(bus["Id"], "6c6b994d-5fba-4c04-94a4-95a20314caf5",
                      target["Id"], TARGET_COMMAND)
    if fit_bus not in graph["Connections"] or bus_target not in graph["Connections"]:
        raise ValueError("Old audio output route changed; preserving edits")
    old_edges = [edge for edge in graph["Connections"]
                 if edge["SourceParentOrChildId"] in expected_ids
                 or edge["TargetParentOrChildId"] in expected_ids]
    if len(old_edges) != 10:
        raise ValueError("The old audio graph has unexpected wiring; preserving it")
    graph["Children"] = [child for child in children if child["Id"] not in expected_ids]
    graph["Connections"] = [edge for edge in graph["Connections"]
                            if edge["SourceParentOrChildId"] not in expected_ids
                            and edge["TargetParentOrChildId"] not in expected_ids]
    graph["Connections"].append(link(fit["Id"], fit_bus["SourceSlotId"],
                                     target["Id"], TARGET_COMMAND))
    ui["SymbolChildUis"] = [item for item in ui["SymbolChildUis"]
                            if item["ChildId"] not in expected_ids]
    return install(graph, ui, existing_scan=scan)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--graph", type=Path, default=DEFAULT_GRAPH)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    graph_path = args.graph.resolve()
    ui_path = graph_path.with_suffix(".t3ui")
    scan = AUDIO / "asterion_fx_scan.wav"
    inspect_audio(scan)
    graph, ui = upgrade(read_graph(graph_path), read_graph(ui_path))
    ids = {child["Id"] for child in graph["Children"]}
    assert all(edge["SourceParentOrChildId"] in ids
               and edge["TargetParentOrChildId"] in ids
               for edge in graph["Connections"])
    print("ASTERION_NATIVE_AUDIO_PLAN", len(ids), "children",
          len(graph["Connections"]), "connections", "4 AudioClip lanes")
    if args.dry_run:
        return
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = BACKUPS / f"before-audio-timeline-{stamp}"
    backup.mkdir(parents=True)
    shutil.copy2(graph_path, backup / graph_path.name)
    shutil.copy2(ui_path, backup / ui_path.name)
    installed_scan = graph_path.parent.parent / "Assets/audio" / scan.name
    if not installed_scan.exists():
        raise ValueError(f"Missing project scan WAV: {installed_scan}")
    shutil.copy2(scan, installed_scan)
    graph_path.write_text(json.dumps(graph, indent=2) + "\n", encoding="utf-8")
    ui_path.write_text(json.dumps(ui, indent=2) + "\n", encoding="utf-8")
    print("ASTERION_NATIVE_AUDIO_INSTALLED", graph_path, "backup", backup)


if __name__ == "__main__":
    main()

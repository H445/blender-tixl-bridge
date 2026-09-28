"""Add mission-paced glow and intermittent signal glitches to TiXL's home graph.

Run only after inspecting the live graph through the TiXL debug bridge and
closing the editor. The script preserves all existing scene and moon branches,
backs up the saved home graph outside Symbols, and refuses an unexpected route.
"""

from __future__ import annotations

import json
import re
import shutil
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path


PREFIX = "Story FX | "
SYMBOLS = {
    "star": ("ecbb40c4-aef4-49a8-ac89-e82c3a09862f", "Lib.image.fx.stylize.StarGlowStreaks"),
    "curve": ("b724ea74-d5d7-4928-9cd1-7a7850e4e179", "Lib.numbers.curve.SampleCurve"),
    "blend": ("9f43f769-d32a-4f49-92ac-e0be3ba250cf", "Lib.image.use.Blend"),
    "vec4": ("f2e323bd-f881-41a8-81e2-e8f2ac1984dc", "Types.Values.Vector4"),
    "multiply": ("17b60044-9125-4961-8a79-ca94697b3726", "Lib.numbers.float.basic.Multiply"),
}


def load(path: Path) -> dict:
    return json.loads(re.sub(r'("[0-9a-fA-F-]{36}")/\*.*?\*/', r"\1", path.read_text(encoding="utf-8")))


def val(slot: str, kind: str, value) -> dict:
    return {"Id": slot, "Type": kind, "Value": value}


def edge(source: dict, output: str, target: dict, input_slot: str) -> dict:
    return {"SourceParentOrChildId": source["Id"], "SourceSlotId": output,
            "TargetParentOrChildId": target["Id"], "TargetSlotId": input_slot}


def curve_value(points: list[tuple[float, float]]) -> dict:
    return {"Curve": {"PreCurve": "Constant", "PostCurve": "Constant",
                      "Keys": [{"Time": float(t), "Value": float(v),
                                "InInterpolation": "Smooth", "OutInterpolation": "Smooth",
                                "InTangentAngle": 0.0, "OutTangentAngle": 0.0}
                               for t, v in points]}}


def set_value(child: dict, slot: str, kind: str, value) -> None:
    values = child.setdefault("InputValues", [])
    match = next((item for item in values if item["Id"] == slot), None)
    if match is None:
        values.append(val(slot, kind, value))
    else:
        match["Type"] = kind
        match["Value"] = value


def configure(path: Path, backup_dir: Path) -> None:
    graph, ui_path = load(path), path.with_suffix(".t3ui")
    ui = load(ui_path)
    children = graph["Children"]
    by_name = {child.get("Name"): child for child in children}
    if any(name and name.startswith(PREFIX) for name in by_name):
        raise ValueError("Story FX already installed; preserve editor edits")
    names = (
        "Post FX | 01 spectral bloom", "Post FX | 02 chromatic fracture",
        "Post FX | 03 scanline signal", "Post FX | 04 torn frames + pixel sort",
        "Post FX | 05 rhythmic glitch composite", "Post FX | glitch blend RGB + alpha",
        "Post FX | beat × irregular energy", "Moon Fluid | spectral breathing",
        "Main / clip to scene time",
    )
    if any(name not in by_name for name in names):
        raise ValueError("Expected post-effect and time routes are missing")
    bloom, fringe, signal, glitch, composite, rgba, energy, spectral, time = (
        by_name[name] for name in names)
    links = graph["Connections"]

    def require_remove(source: dict, output: str, target: dict, input_slot: str) -> None:
        connection = edge(source, output, target, input_slot)
        if connection not in links:
            raise ValueError(f"Expected route was edited: {source.get('Name')} -> {target.get('Name')}")
        links.remove(connection)

    require_remove(bloom, "f3fa372d-f037-48fd-8a8d-a0135b4c20cb", fringe,
                   "b62aece4-8098-475b-a4d3-469f81a58207")
    require_remove(signal, "22eac013-881d-486a-8041-5cae32b8dca1", composite,
                   "abaa52e9-7d3d-4ae5-89d2-5251f61e5392")
    require_remove(energy, "e011dd8c-1b9c-458f-8960-e6c38e83ca74", rgba,
                   "6ce53000-34d6-4d9a-aef3-164fd223f6d2")
    require_remove(energy, "e011dd8c-1b9c-458f-8960-e6c38e83ca74", fringe,
                   "361a838a-7bf1-4fd2-8e0e-77edcef11965")

    def add(key: str, name: str, x: float, y: float, values=()) -> dict:
        symbol_id, symbol_name = SYMBOLS[key]
        child = {"Id": str(uuid.uuid5(uuid.NAMESPACE_URL, graph["Id"] + "/story-fx/" + name)),
                 "SymbolId": symbol_id, "SymbolName": symbol_name,
                 "Name": PREFIX + name, "InputValues": list(values), "Outputs": []}
        children.append(child)
        ui["SymbolChildUis"].append({"ChildId": child["Id"], "Position": {"X": x, "Y": y}})
        return child

    star = add("star", "ion starburst", 2590, -110, [
        val("8c1d41ff-02e8-481b-a21a-56d1c519d920", "System.Single", .5),
        val("c643292c-5612-408a-9fd6-ce31e4de3f56", "System.Single", .16),
        val("069a3776-3084-4a13-aee3-dd9fe6c6c9e1", "System.Int32", 2),
    ])
    glow = add("curve", "glow follows the mission", 2450, -360, [
        val("108cb829-5f9e-4a45-bc6b-7cf40a0a0f89", "T3.Core.DataTypes.Curve", curve_value([
            (0, .7), (9, .7), (12, 2.5), (16, 1.2), (24, .8),
            (29, 1.8), (36, .8), (46, 1.3), (53, 1.0), (62, 1.8),
            (72, 1.0), (78, 2.3), (83, 1.2), (86, 2.7),
            (91, .8), (100, 1.7), (108, .9),
        ])),
    ])
    gate = add("curve", "signal disturbance windows", 2900, 930, [
        val("108cb829-5f9e-4a45-bc6b-7cf40a0a0f89", "T3.Core.DataTypes.Curve", curve_value([
            (0, 0), (10, 0), (11.5, .85), (15, .75), (17, 0),
            (24, 0), (27, .55), (30, .4), (35, 0),
            (42, 0), (46, .45), (50, .65), (56, .25), (59, 0),
            (60, 0), (63, .7), (68, .45), (72, 0),
            (76, 0), (79, .5), (82, 0), (83, 0),
            (85, 1), (89, .85), (91, 0),
            (96, 0), (99, .55), (103, .25), (108, 0),
        ])),
    ])
    tint = add("vec4", "clean-to-corrupt alpha", 3090, 930, [
        val("bdd35cdd-2220-4c58-9ec8-a5e48d7aaf7e", "System.Single", 1.0),
        val("46a4ee87-ab2b-406b-a9ae-c000f887d99f", "System.Single", 1.0),
        val("59908ecc-1822-4aba-a2d9-cfe97168b3b3", "System.Single", 1.0),
    ])
    clean = add("blend", "clean and corrupted signal", 3090, -100)
    gated_energy = add("multiply", "rhythmic tears within windows", 3100, 735)

    links.extend((
        edge(bloom, "f3fa372d-f037-48fd-8a8d-a0135b4c20cb", star,
             "afcba3d4-b7db-40bd-919a-d4f49b1bf7fc"),
        edge(star, "a256b06b-1500-4189-9820-906addbf387e", fringe,
             "b62aece4-8098-475b-a4d3-469f81a58207"),
        edge(time, "c1dbdb9e-a7ad-424b-b2ba-94bd9ce71daf", glow,
             "2c24d4fe-6c96-4502-bf76-dac756a16215"),
        edge(glow, "fc51bee8-091c-4c66-a7df-12f6f69e3783", star,
             "68e16fd7-fabf-446e-9553-a737422c026b"),
        edge(time, "c1dbdb9e-a7ad-424b-b2ba-94bd9ce71daf", gate,
             "2c24d4fe-6c96-4502-bf76-dac756a16215"),
        edge(gate, "fc51bee8-091c-4c66-a7df-12f6f69e3783", tint,
             "6ce53000-34d6-4d9a-aef3-164fd223f6d2"),
        edge(fringe, "8af0d916-9708-422b-8fb7-39ef59c82d7f", clean,
             "abaa52e9-7d3d-4ae5-89d2-5251f61e5392"),
        edge(signal, "22eac013-881d-486a-8041-5cae32b8dca1", clean,
             "c7c524cf-e31e-4bac-8f77-58bd61b337de"),
        edge(tint, "14cdc3dd-f229-4f8f-b953-4f9d587d6f58", clean,
             "70dc133e-800a-4cd0-a159-2cbab4c322cb"),
        edge(clean, "536fae14-b814-498c-a6b4-07775de36991", composite,
             "abaa52e9-7d3d-4ae5-89d2-5251f61e5392"),
        edge(energy, "e011dd8c-1b9c-458f-8960-e6c38e83ca74", gated_energy,
             "372288fa-3794-47ba-9f91-59240513217a"),
        edge(gate, "fc51bee8-091c-4c66-a7df-12f6f69e3783", gated_energy,
             "5ae4bb07-4214-4ec3-a499-24d9f6d404a5"),
        edge(gated_energy, "e011dd8c-1b9c-458f-8960-e6c38e83ca74", rgba,
             "6ce53000-34d6-4d9a-aef3-164fd223f6d2"),
        edge(gated_energy, "e011dd8c-1b9c-458f-8960-e6c38e83ca74", fringe,
             "361a838a-7bf1-4fd2-8e0e-77edcef11965"),
    ))
    set_value(bloom, "2064aba1-658e-4795-a4fc-5be1026d7064", "System.Int32", 7)
    set_value(bloom, "28e0b719-0888-4ef6-85d9-bbd75f7a4537", "System.Single", .35)
    set_value(bloom, "c6a0cadc-9e1c-40ac-97f1-d9271b5376df", "System.Single", 1.15)
    set_value(spectral, "79917ef7-64ca-4825-9c6a-c9b2a7f6ff86", "System.Single", 1.2)
    set_value(spectral, "ddd93b06-118e-43e0-85f6-c150faf91d04", "System.Single", 3.1)
    if len({child["Id"] for child in children}) != len(children):
        raise ValueError("Duplicate node ID")
    if len({(e["SourceParentOrChildId"], e["SourceSlotId"],
             e["TargetParentOrChildId"], e["TargetSlotId"]) for e in links}) != len(links):
        raise ValueError("Duplicate connection")

    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    for source in (path, ui_path):
        shutil.copy2(source, backup_dir / f"{source.stem}.before-story-fx.{timestamp}{source.suffix}")
    for destination, value in ((path, graph), (ui_path, ui)):
        temp = destination.with_name(destination.name + ".story-tmp")
        temp.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
        temp.replace(destination)
    print("ASTERION_STORY_FX", {"nodes": len(children), "links": len(links),
                                 "backup": str(backup_dir)})


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("Usage: tune_asterion_story_fx.py <AsterionBreakaway.t3> <backup-directory>")
    configure(Path(sys.argv[1]), Path(sys.argv[2]))

"""Color-cycle the moon's native fluid feedback in the TiXL home graph.

Run while TiXL is closed, after configure_asterion_moon_fluid_fx.py. Back up
the home .t3/.t3ui outside Symbols before applying this scene-specific patch.
"""

from __future__ import annotations

import json
import re
import sys
import uuid
from pathlib import Path


def load(path: Path) -> dict:
    return json.loads(re.sub(r'("[0-9a-fA-F-]{36}")/\*.*?\*/', r"\1", path.read_text(encoding="utf-8")))


def val(slot: str, kind: str, setting) -> dict:
    return {"Id": slot, "Type": kind, "Value": setting}


def edge(source: dict, output: str, target: dict, input_slot: str) -> dict:
    return {"SourceParentOrChildId": source["Id"], "SourceSlotId": output,
            "TargetParentOrChildId": target["Id"], "TargetSlotId": input_slot}


def configure(path: Path) -> None:
    graph, ui = load(path), load(path.with_suffix(".t3ui"))
    by_name = {c.get("Name"): c for c in graph["Children"]}
    required = ("Main / opaque select textures", "Main / clip to scene time",
                "Moon Fluid | seed with moon albedo", "Moon Fluid | albedo and currents")
    if any(name not in by_name for name in required):
        raise ValueError("Expected moon fluid route is missing")
    if any(name and name.startswith("Moon Psychedelic |") for name in by_name):
        raise ValueError("Psychedelic moon nodes already exist; preserve editor changes")
    select, time, layer, blend = (by_name[name] for name in required)
    select_albedo = "f5d218bb-d055-5800-9971-db0f88b6ead3"
    old = [edge(select, select_albedo, layer, "2a95ac54-5ef7-4d3c-a90b-ecd5b422bddc"),
           edge(select, select_albedo, blend, "abaa52e9-7d3d-4ae5-89d2-5251f61e5392")]
    if any(link not in graph["Connections"] for link in old):
        raise ValueError("Moon albedo route was edited")
    for link in old:
        graph["Connections"].remove(link)

    def add(symbol_id: str, symbol_name: str, name: str, x: float, y: float, values=()) -> dict:
        child = {"Id": str(uuid.uuid5(uuid.NAMESPACE_URL, graph["Id"] + "/psychedelic-moon/" + name)),
                 "SymbolId": symbol_id, "SymbolName": symbol_name,
                 "Name": name, "InputValues": list(values), "Outputs": []}
        graph["Children"].append(child)
        ui["SymbolChildUis"].append({"ChildId": child["Id"], "Position": {"X": x, "Y": y}})
        return child

    colors = [
        (0.0, (0.08, 0.02, 0.34)),
        (0.18, (0.7, 0.02, 1.0)),
        (0.39, (0.0, 0.88, 1.0)),
        (0.60, (0.55, 1.0, 0.02)),
        (0.81, (1.0, 0.02, 0.52)),
        (1.0, (1.0, 0.55, 0.04)),
    ]
    gradient = {"Gradient": {"Interpolation": "Spline", "Steps": [
        {"Id": str(uuid.uuid5(uuid.NAMESPACE_URL, graph["Id"] + f"/psychedelic-gradient/{i}")),
         "NormalizedPosition": pos,
         "Color": {"R": rgb[0], "G": rgb[1], "B": rgb[2], "A": 1.0}}
        for i, (pos, rgb) in enumerate(colors)
    ]}}
    blur = add("946da16c-f536-4887-b764-af9468f22c0f", "Lib.image.fx.blur.Blur",
               "Moon Psychedelic | soften crater pattern", 1160, 420, [
                   val("99188668-b6ac-468b-a892-cd020a3862b2", "System.Single", 3.0),
                   val("3c8b43be-430f-4afe-8244-5282be49bfbc", "System.Single", 10.0),
               ])
    remap = add("da93f7d1-ef91-4b4a-9708-2d9b1baa4c14", "Lib.image.color.RemapColor",
                "Moon Psychedelic | spectral palette", 1340, 420, [
                    val("c45d487b-3221-44c7-bf9e-b982a65280f6", "T3.Core.DataTypes.Gradient", gradient),
                    val("e3363c0e-819a-45e2-8202-439bcce64d69", "System.Int32", 0),
                    val("8a2cc68c-ec38-4bb5-a201-e5c06f0a38d1", "System.Single", 1.6),
                    val("7023f71c-1c13-4d66-85e7-b0918cb8b02c", "System.Single", 1.75),
                    val("eb070a0b-703d-43cc-a877-cf9e371ebd05",
                        "SharpDX.Direct3D11.TextureAddressMode", "Wrap"),
                    val("7777f86d-dbf7-44d4-9da4-99a819038095", "System.Boolean", True),
                ])
    cycle = add("ea7b8491-2f8e-4add-b0b1-fd068ccfed0d",
                "Lib.numbers.anim.animators.AnimValue", "Moon Psychedelic | hue cycle", 1160, 760, [
                    val("4cf5d20b-7335-4584-b246-c260ac5cdf4f", "System.Int32", 0),
                    val("48005727-0158-4795-ad70-8410c27fd01d", "System.Single", 0.42),
                    val("79917ef7-64ca-4825-9c6a-c9b2a7f6ff86", "System.Single", 1.0),
                    val("ddd93b06-118e-43e0-85f6-c150faf91d04", "System.Single", 0.0),
                    val("738f6cfb-8b71-423c-b897-824c20397e5a", "System.Int32", 0),
                ])
    graph["Connections"].extend((
        edge(select, select_albedo, blur, "c115fd60-86c5-425f-975b-0b5e92c0f42b"),
        edge(blur, "fa46b9f0-46d6-4ab3-8406-409e1dc5e9a4", remap,
             "876f6f64-7cb4-4060-8571-e0b78b437d41"),
        edge(remap, "16e37306-05e1-4de6-babd-80a8d1472a2f", layer,
             "2a95ac54-5ef7-4d3c-a90b-ecd5b422bddc"),
        edge(remap, "16e37306-05e1-4de6-babd-80a8d1472a2f", blend,
             "abaa52e9-7d3d-4ae5-89d2-5251f61e5392"),
        edge(time, "c1dbdb9e-a7ad-424b-b2ba-94bd9ce71daf", cycle,
             "7b4992ba-30f7-42e5-b04b-ae4ec0be810e"),
        edge(cycle, "ae4addf0-08cf-4b25-9515-4fef9359d183", remap,
             "b1763a8b-aa98-4e00-a47c-a5d0d750ae6e"),
    ))
    positions = {item["ChildId"]: item for item in ui["SymbolChildUis"]}
    for name, x, y in (
        ("Moon Fluid | seed with moon albedo", 1540, 420),
        ("Moon Fluid | feedback currents", 1740, 420),
        ("Moon Fluid | albedo and currents", 1930, 200),
        ("Moon Fluid | beat-gated pixel fracture", 2130, 200),
        ("Main / opaque replace textures", 2340, 50),
    ):
        positions[by_name[name]["Id"]]["Position"] = {"X": x, "Y": y}
    if len({c["Id"] for c in graph["Children"]}) != len(graph["Children"]):
        raise ValueError("Duplicate child identifier")
    path.write_text(json.dumps(graph, indent=2) + "\n", encoding="utf-8")
    path.with_suffix(".t3ui").write_text(json.dumps(ui, indent=2) + "\n", encoding="utf-8")
    print(f"Installed moon palette; {len(graph['Children'])} nodes, {len(graph['Connections'])} links")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: configure_asterion_psychedelic_moon.py <AsterionBreakaway.t3>")
    configure(Path(sys.argv[1]))

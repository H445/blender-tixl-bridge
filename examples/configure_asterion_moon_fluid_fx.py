"""Give the named moon a native TiXL fluid-feedback texture and vary post FX.

Run against the AsterionBreakaway home graph while TiXL is closed. The graph
must already contain the moon object route and music-video post-processing.
Keep backups outside the live Symbols directory.
"""

from __future__ import annotations

import json
import re
import sys
import uuid
from pathlib import Path


SYMBOLS = {
    "layer": ("d8c5330f-59b5-4907-b845-a02def3042fa", "Lib.render.basic.Layer2d"),
    "fluid": ("f9d453d1-04d9-43ef-9189-50008f93bcc2", "Lib.image.fx.feedback.FluidFeedback"),
    "blend": ("9f43f769-d32a-4f49-92ac-e0be3ba250cf", "Lib.image.use.Blend"),
    "vec4": ("f2e323bd-f881-41a8-81e2-e8f2ac1984dc", "Types.Values.Vector4"),
    "anim": ("ea7b8491-2f8e-4add-b0b1-fd068ccfed0d", "Lib.numbers.anim.animators.AnimValue"),
}


def load(path: Path) -> dict:
    return json.loads(re.sub(r'("[0-9a-fA-F-]{36}")/\*.*?\*/', r"\1", path.read_text(encoding="utf-8")))


def val(slot: str, kind: str, value) -> dict:
    return {"Id": slot, "Type": kind, "Value": value}


def edge(source: dict, output: str, target: dict, input_slot: str) -> dict:
    return {"SourceParentOrChildId": source["Id"], "SourceSlotId": output,
            "TargetParentOrChildId": target["Id"], "TargetSlotId": input_slot}


def configure(path: Path) -> None:
    graph, ui = load(path), load(path.with_suffix(".t3ui"))
    by_name = {child.get("Name"): child for child in graph["Children"]}
    required = ("Moon | pixel glitch", "Main / opaque select textures",
                "Main / opaque replace textures", "Main / clip to scene time",
                "Post FX | 01 spectral bloom", "Post FX | 03 scanline signal",
                "Post FX | glitch blend RGB + alpha")
    if any(name not in by_name for name in required):
        raise ValueError("Expected moon and post-processing routes are missing")
    if any(name and name.startswith("Moon Fluid |") for name in by_name):
        raise ValueError("Moon fluid nodes already exist; preserve editor changes")
    pixel, select, replace, time, bloom, signal, beat_rgba = (by_name[name] for name in required)
    original = edge(pixel, "47e693ca-a695-4f95-9f02-9b76894ee91c", replace,
                    "7ea5475c-6fc4-501b-a9b0-7def755c898b")
    if original not in graph["Connections"]:
        raise ValueError("The moon albedo route was edited")
    graph["Connections"].remove(original)

    def add(key: str, name: str, x: float, y: float, values=()) -> dict:
        symbol_id, symbol_name = SYMBOLS[key]
        child = {"Id": str(uuid.uuid5(uuid.NAMESPACE_URL, graph["Id"] + "/moon-fluid/" + name)),
                 "SymbolId": symbol_id, "SymbolName": symbol_name,
                 "Name": name, "InputValues": list(values), "Outputs": []}
        graph["Children"].append(child)
        ui["SymbolChildUis"].append({"ChildId": child["Id"], "Position": {"X": x, "Y": y}})
        return child

    layer = add("layer", "Moon Fluid | seed with moon albedo", 1370, 390, [
        val("1d9ccc5d-bed4-4d07-b664-0903442e4f58", "System.Int32", 4),
        val("ed4f8c30-7b71-4649-97e6-710a718039b0", "System.Numerics.Vector4",
            {"X": 1.0, "Y": 1.0, "Z": 1.0, "W": 0.12}),
    ])
    fluid = add("fluid", "Moon Fluid | feedback currents", 1560, 370, [
        val("297a2220-0648-47d3-82a1-c1077a1326a4", "System.Single", 90.0),
        val("41c080de-575f-4041-b605-8f55e4bcf797", "System.Single", 0.12),
        val("78b314b8-f9d2-4723-9b11-c07ba926db86", "System.Single", 0.28),
        val("8060756f-72a4-490b-9677-872b70e73b3a", "System.Single", 1.6),
        val("806221f8-6e31-45ec-b62e-5baac6c1fd54", "System.Single", 0.04),
        val("98662eab-90b9-4af1-8ff3-ba6709b5038e", "System.Single", 1.0),
        val("a7669abe-65c7-4745-97a6-d0d80f6a3150", "System.Single", 1.2),
    ])
    blend = add("blend", "Moon Fluid | albedo and currents", 1800, 190, [
        val("fc5f1d08-3997-4ba3-ac59-d86e4e501fb0", "System.Int32", 1),
    ])
    beat_glitch = add("blend", "Moon Fluid | beat-gated pixel fracture", 2020, 190)
    rgba = add("vec4", "Moon Fluid | mix RGB and alpha", 1800, 490, [
        val("bdd35cdd-2220-4c58-9ec8-a5e48d7aaf7e", "System.Single", 1.0),
        val("46a4ee87-ab2b-406b-a9ae-c000f887d99f", "System.Single", 1.0),
        val("59908ecc-1822-4aba-a2d9-cfe97168b3b3", "System.Single", 1.0),
    ])
    moon_mix = add("anim", "Moon Fluid | slow tidal mix", 1560, 690, [
        val("4cf5d20b-7335-4584-b246-c260ac5cdf4f", "System.Int32", 6),
        val("48005727-0158-4795-ad70-8410c27fd01d", "System.Single", 0.085),
        val("79917ef7-64ca-4825-9c6a-c9b2a7f6ff86", "System.Single", 0.4),
        val("ddd93b06-118e-43e0-85f6-c150faf91d04", "System.Single", 0.3),
        val("738f6cfb-8b71-423c-b897-824c20397e5a", "System.Int32", 0),
    ])
    current = add("anim", "Moon Fluid | evolving twist", 1340, 690, [
        val("4cf5d20b-7335-4584-b246-c260ac5cdf4f", "System.Int32", 6),
        val("48005727-0158-4795-ad70-8410c27fd01d", "System.Single", 0.07),
        val("79917ef7-64ca-4825-9c6a-c9b2a7f6ff86", "System.Single", 70.0),
        val("ddd93b06-118e-43e0-85f6-c150faf91d04", "System.Single", 45.0),
        val("738f6cfb-8b71-423c-b897-824c20397e5a", "System.Int32", 0),
    ])
    scan_drift = add("anim", "Moon Fluid | irregular signal drift", 2830, 850, [
        val("4cf5d20b-7335-4584-b246-c260ac5cdf4f", "System.Int32", 8),
        val("48005727-0158-4795-ad70-8410c27fd01d", "System.Single", 0.31),
        val("79917ef7-64ca-4825-9c6a-c9b2a7f6ff86", "System.Single", 0.1),
        val("ddd93b06-118e-43e0-85f6-c150faf91d04", "System.Single", 0.01),
        val("738f6cfb-8b71-423c-b897-824c20397e5a", "System.Int32", 0),
    ])
    spectral = add("anim", "Moon Fluid | spectral breathing", 2450, 750, [
        val("4cf5d20b-7335-4584-b246-c260ac5cdf4f", "System.Int32", 6),
        val("48005727-0158-4795-ad70-8410c27fd01d", "System.Single", 0.12),
        val("79917ef7-64ca-4825-9c6a-c9b2a7f6ff86", "System.Single", 0.45),
        val("ddd93b06-118e-43e0-85f6-c150faf91d04", "System.Single", 0.15),
        val("738f6cfb-8b71-423c-b897-824c20397e5a", "System.Int32", 0),
    ])

    links = graph["Connections"]
    links.extend((
        edge(select, "f5d218bb-d055-5800-9971-db0f88b6ead3", layer,
             "2a95ac54-5ef7-4d3c-a90b-ecd5b422bddc"),
        edge(layer, "e4a8d926-7abd-4d2a-82a1-b7d140cb457f", fluid,
             "ebd35d33-dc73-46ae-a82c-2060d750018a"),
        edge(select, "f5d218bb-d055-5800-9971-db0f88b6ead3", blend,
             "abaa52e9-7d3d-4ae5-89d2-5251f61e5392"),
        edge(fluid, "b9baba42-18b6-4792-929d-bf628ce8a488", blend,
             "c7c524cf-e31e-4bac-8f77-58bd61b337de"),
        edge(blend, "536fae14-b814-498c-a6b4-07775de36991", beat_glitch,
             "abaa52e9-7d3d-4ae5-89d2-5251f61e5392"),
        edge(pixel, "47e693ca-a695-4f95-9f02-9b76894ee91c", beat_glitch,
             "c7c524cf-e31e-4bac-8f77-58bd61b337de"),
        edge(beat_rgba, "14cdc3dd-f229-4f8f-b953-4f9d587d6f58", beat_glitch,
             "70dc133e-800a-4cd0-a159-2cbab4c322cb"),
        edge(beat_glitch, "536fae14-b814-498c-a6b4-07775de36991", replace,
             "7ea5475c-6fc4-501b-a9b0-7def755c898b"),
        edge(time, "c1dbdb9e-a7ad-424b-b2ba-94bd9ce71daf", moon_mix,
             "7b4992ba-30f7-42e5-b04b-ae4ec0be810e"),
        edge(time, "c1dbdb9e-a7ad-424b-b2ba-94bd9ce71daf", current,
             "7b4992ba-30f7-42e5-b04b-ae4ec0be810e"),
        edge(moon_mix, "ae4addf0-08cf-4b25-9515-4fef9359d183", rgba,
             "6ce53000-34d6-4d9a-aef3-164fd223f6d2"),
        edge(rgba, "14cdc3dd-f229-4f8f-b953-4f9d587d6f58", blend,
             "70dc133e-800a-4cd0-a159-2cbab4c322cb"),
        edge(current, "ae4addf0-08cf-4b25-9515-4fef9359d183", fluid,
             "297a2220-0648-47d3-82a1-c1077a1326a4"),
        edge(time, "c1dbdb9e-a7ad-424b-b2ba-94bd9ce71daf", scan_drift,
             "7b4992ba-30f7-42e5-b04b-ae4ec0be810e"),
        edge(scan_drift, "ae4addf0-08cf-4b25-9515-4fef9359d183", signal,
             "f76c6202-34dc-4c10-adab-c10cb7665fed"),
        edge(time, "c1dbdb9e-a7ad-424b-b2ba-94bd9ce71daf", spectral,
             "7b4992ba-30f7-42e5-b04b-ae4ec0be810e"),
        edge(spectral, "ae4addf0-08cf-4b25-9515-4fef9359d183", bloom,
             "bb706662-2555-4f3b-a81e-60e04f052f36"),
    ))
    ui_by_id = {item["ChildId"]: item for item in ui["SymbolChildUis"]}
    ui_by_id[replace["Id"]]["Position"] = {"X": 2260, "Y": 50}
    if len({c["Id"] for c in graph["Children"]}) != len(graph["Children"]):
        raise ValueError("Duplicate child identifier")
    path.write_text(json.dumps(graph, indent=2) + "\n", encoding="utf-8")
    path.with_suffix(".t3ui").write_text(json.dumps(ui, indent=2) + "\n", encoding="utf-8")
    print(f"Installed 9 moon fluid/variation nodes; {len(graph['Children'])} nodes, {len(links)} links")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: configure_asterion_moon_fluid_fx.py <AsterionBreakaway.t3>")
    configure(Path(sys.argv[1]))

"""Replace heavy break flashes with restrained ASCII and native SDF accents.

Run only after comparing the live graph with the saved home and shutting down
TiXL through its debug bridge. This deliberately edits the user home graph.
"""

from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from install_asterion_audio import BACKUPS, DEFAULT_GRAPH, GRAPH_ID, link, read_graph, uid, value
from install_asterion_break import CURVE_INPUT, CURVE_OUTPUT, CURVE_SYMBOL, CURVE_TIME_INPUT, SCENE_TIME_OUTPUT
from advanced_spaceship.audio.break_pattern import chops


SLOT = {
    "ascii_image": "b7d24c9b-ad9e-4ba5-82d9-15414868cdd9",
    "ascii_output": "b0b6a771-e1a4-4681-a8be-8ed7ac1f66c4",
    "blend_a": "abaa52e9-7d3d-4ae5-89d2-5251f61e5392",
    "blend_b": "c7c524cf-e31e-4bac-8f77-58bd61b337de",
    "blend_color_b": "70dc133e-800a-4cd0-a159-2cbab4c322cb",
    "blend_output": "536fae14-b814-498c-a6b4-07775de36991",
    "color_a": "6ce53000-34d6-4d9a-aef3-164fd223f6d2",
    "color_r": "bdd35cdd-2220-4c58-9ec8-a5e48d7aaf7e",
    "color_g": "46a4ee87-ab2b-406b-a9ae-c000f887d99f",
    "color_b": "59908ecc-1822-4aba-a2d9-cfe97168b3b3",
    "color_output": "14cdc3dd-f229-4f8f-b953-4f9d587d6f58",
    "sdf_torus_output": "14cd4d1f-0b9b-43c4-93cc-d730c137cee8",
    "sdf_noise_input": "1799f18f-92c5-4885-b6c1-6a196eee805f",
    "sdf_noise_output": "dbf31b38-5221-414c-83b1-800770fcfaa6",
    "sdf_render_input": "340ca675-9356-4548-ba64-732181bebeef",
    "sdf_render_output": "e178ef02-c9ac-48cd-a8cb-df3aec5941bb",
    "target_command": "4da253b7-4953-439a-b03f-1d515a78bddf",
    "target_image": "7a4c4feb-be2f-463e-96c6-cd9a6bad77a2",
}


def curve(keys):
    return {"Curve": {"PreCurve": "Constant", "PostCurve": "Constant",
                      "Keys": [{"Time": round(t, 5), "Value": round(v, 5),
                                "InInterpolation": "Linear", "OutInterpolation": "Linear"}
                               for t, v in sorted(keys)]}}


def accent_keys(*, sdf=False):
    result = [(0.0, 0.0)]
    for hit in chops():
        # Sparse macro accents let the footage breathe between edit points.
        if hit.source_step not in ((0, 12) if sdf else (0, 4, 12)):
            continue
        peak = min((0.28 if sdf else 0.42), hit.accent * (0.60 if sdf else 0.75))
        if peak < 0.035:
            continue
        t = hit.time
        result.extend(((t - 0.025, 0), (t, peak), (t + 0.12, peak * 0.42),
                       (t + 0.24, 0)))
    result.append((108.0, 0.0))
    return curve(result)


def refine(graph, ui):
    if graph["Id"] != GRAPH_ID or ui["Id"] != GRAPH_ID:
        raise ValueError("Expected AsterionBreakaway home")
    names = {c.get("Name"): c for c in graph["Children"]}
    if "Signal | ASCII on sparse chops" in names:
        raise ValueError("Visual refinement already installed")
    by_id = {c["Id"]: c for c in graph["Children"]}

    def add(name, symbol, symbol_name, x, y, inputs=()):
        c = {"Id": uid("visual/" + name), "SymbolId": symbol,
             "SymbolName": symbol_name, "Name": name,
             "InputValues": list(inputs), "Outputs": []}
        if c["Id"] in by_id:
            raise ValueError("Child id collision")
        graph["Children"].append(c)
        by_id[c["Id"]] = c
        ui["SymbolChildUis"].append({"ChildId": c["Id"],
                                     "Position": {"X": x, "Y": y}})
        return c

    # The previous beat curve drove a complete pixel-sort frame. Reserve that
    # effect for a faint, rare tear; readable ASCII now carries the break cuts.
    for name, factor in (("Break | 120 BPM chop accents", 0.16),
                         ("Break | scanline glitch on chops", 0.24)):
        c = names[name]
        entry = next(v for v in c["InputValues"] if v["Id"] == CURVE_INPUT)
        for key in entry["Value"]["Curve"]["Keys"]:
            key["Value"] = round(key["Value"] * factor, 5)
    disturbance = next(v for v in names["Story FX | signal disturbance windows"]["InputValues"]
                       if v["Id"] == CURVE_INPUT)
    for key in disturbance["Value"]["Curve"]["Keys"]:
        key["Value"] = round(key["Value"] * 0.55, 5)
    for name, changes in {
        "Post FX | 04 torn frames + pixel sort": {
            "2a28f084-bc2f-4458-8ad8-f3bf11086fc4": False,
            "b7b21d3c-80e1-450e-a1c7-b8720b550924": 0.11,
            "80c6ed94-e5e5-480b-b69e-2c4f9b2935c7": 0.002,
            "bcadf77c-be02-482d-9cd7-87085831e9cd": 0.06},
        "Post FX | 03 scanline signal": {
            "38529a44-4622-4c87-886e-72f4400ec468": 0.045},
        "Post FX | beat pulse | 120 BPM": {
            "79917ef7-64ca-4825-9c6a-c9b2a7f6ff86": 0.5},
        "Post FX | off-grid random accents": {
            "79917ef7-64ca-4825-9c6a-c9b2a7f6ff86": 0.45},
    }.items():
        vals = {v["Id"]: v for v in names[name]["InputValues"]}
        for slot, number in changes.items():
            vals[slot]["Value"] = number

    time = names["Main / clip to scene time"]
    original = names["Post FX | 05 rhythmic glitch composite"]
    fit = names["Output fit"]
    old_edge = link(original["Id"], SLOT["blend_output"], fit["Id"],
                    "92c66734-dce9-402a-95f6-cde0e58bf32f")
    if graph["Connections"].count(old_edge) != 1:
        raise ValueError("Output path changed; refusing visual insertion")
    graph["Connections"].remove(old_edge)

    ascii_fx = add("Signal | ASCII on sparse chops",
                   "42e6319e-669c-4524-8d0d-9416a86afdb3",
                   "Lib.image.fx.stylize.AsciiRender", 20980, -2340,
                   [value("4623488a-cef2-4aaa-bfea-54e39e0b5653", "System.Single", 6.0),
                    value("68801326-950b-4675-8450-56abf64e8518", "System.Single", 0.35),
                    value("9e093ac2-0dc0-4791-bb27-36d1f6ea1c47", "System.Numerics.Vector4",
                          {"X": 0.56, "Y": 0.9, "Z": 1.0, "W": 1.0})])
    ascii_curve = add("Signal | ASCII accents at 120 BPM", CURVE_SYMBOL,
                      "Lib.numbers.curve.SampleCurve", 20560, -3260,
                      [value(CURVE_INPUT, "T3.Core.DataTypes.Curve", accent_keys())])
    ascii_color = add("Signal | ASCII accent tint", "f2e323bd-f881-41a8-81e2-e8f2ac1984dc",
                      "Types.Values.Vector4", 21400, -2790,
                      [value(SLOT["color_r"], "System.Single", 1.0),
                       value(SLOT["color_g"], "System.Single", 1.0),
                       value(SLOT["color_b"], "System.Single", 1.0)])
    ascii_blend = add("Signal | restrained ASCII composite",
                      "9f43f769-d32a-4f49-92ac-e0be3ba250cf",
                      "Lib.image.use.Blend", 21820, -650)

    torus = add("Signal | torus signed distance",
                "a54e0946-71d0-4985-90bc-184cdb1b6b34",
                "Lib.field.generate.sdf.TorusSDF", 20560, -4020,
                [value("5fe2ab92-f8e5-400d-b5a3-197f20570d6f", "System.Single", 0.55),
                 value("6a392bc1-2adf-4a50-bb3f-5d4f2a63bf0b", "System.Single", 0.025)])
    noise = add("Signal | SDF turbulent rim",
                "54f28d0a-d367-4b59-8480-5b762b8f2a9c",
                "Lib.field.adjust.NoiseDisplaceSDF", 20980, -4020,
                [value("285d7cd9-1057-4ea8-bd0b-20ff52adc562", "System.Single", 0.045),
                 value("b7a2e12b-9e55-43a5-be79-510f4a28a1f4", "System.Single", 0.13)])
    sdf_render = add("Signal | raymarch SDF contour",
                     "9323e32f-078c-4156-941b-203f4c265ff5",
                     "Lib.field.render.RaymarchField", 21820, -4020,
                     [value("9715075b-b02b-4290-9332-9bbfe67933f2",
                            "System.Numerics.Vector4",
                            {"X": 0.1, "Y": 0.75, "Z": 1.0, "W": 1.0}),
                      value("adeb374b-bce0-4af2-867b-efb3ce6289c9", "System.Single", 15.0),
                      value("0700d5cb-6a1e-43ad-b7fb-b9b7b1415584", "System.Boolean", False)])
    sdf_target = add("Signal | SDF texture",
                     "f9fe78c5-43a6-48ae-8e8c-6cdbbc330dd1",
                     "Lib.image.generate.basic.RenderTarget", 22240, -4020,
                     [value("6ea4f801-ff52-4266-a41f-b9ef02c68510", "System.Boolean", False),
                      value("e882e0f0-03f9-46e6-ac7a-709e6fa66613", "System.Int32", 1)])
    sdf_curve = add("Signal | SDF scan accents", CURVE_SYMBOL,
                    "Lib.numbers.curve.SampleCurve", 22240, -3260,
                    [value(CURVE_INPUT, "T3.Core.DataTypes.Curve", accent_keys(sdf=True))])
    sdf_tint = add("Signal | SDF accent tint", "f2e323bd-f881-41a8-81e2-e8f2ac1984dc",
                   "Types.Values.Vector4", 22660, -2790,
                   [value(SLOT["color_r"], "System.Single", 1.0),
                    value(SLOT["color_g"], "System.Single", 1.0),
                    value(SLOT["color_b"], "System.Single", 1.0)])
    sdf_blend = add("Signal | SDF contour composite",
                    "9f43f769-d32a-4f49-92ac-e0be3ba250cf",
                    "Lib.image.use.Blend", 23080, -650)
    edges = graph["Connections"]
    edges.extend((
        link(time["Id"], SCENE_TIME_OUTPUT, ascii_curve["Id"], CURVE_TIME_INPUT),
        link(original["Id"], SLOT["blend_output"], ascii_fx["Id"], SLOT["ascii_image"]),
        link(original["Id"], SLOT["blend_output"], ascii_blend["Id"], SLOT["blend_a"]),
        link(ascii_fx["Id"], SLOT["ascii_output"], ascii_blend["Id"], SLOT["blend_b"]),
        link(ascii_curve["Id"], CURVE_OUTPUT, ascii_color["Id"], SLOT["color_a"]),
        link(ascii_color["Id"], SLOT["color_output"], ascii_blend["Id"], SLOT["blend_color_b"]),
        link(torus["Id"], SLOT["sdf_torus_output"], noise["Id"], SLOT["sdf_noise_input"]),
        link(noise["Id"], SLOT["sdf_noise_output"], sdf_render["Id"], SLOT["sdf_render_input"]),
        link(sdf_render["Id"], SLOT["sdf_render_output"], sdf_target["Id"], SLOT["target_command"]),
        link(time["Id"], SCENE_TIME_OUTPUT, sdf_curve["Id"], CURVE_TIME_INPUT),
        link(ascii_blend["Id"], SLOT["blend_output"], sdf_blend["Id"], SLOT["blend_a"]),
        link(sdf_target["Id"], SLOT["target_image"], sdf_blend["Id"], SLOT["blend_b"]),
        link(sdf_curve["Id"], CURVE_OUTPUT, sdf_tint["Id"], SLOT["color_a"]),
        link(sdf_tint["Id"], SLOT["color_output"], sdf_blend["Id"], SLOT["blend_color_b"]),
        link(sdf_blend["Id"], SLOT["blend_output"], fit["Id"],
             "92c66734-dce9-402a-95f6-cde0e58bf32f"),
    ))
    return graph, ui


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--graph", type=Path, default=DEFAULT_GRAPH)
    p.add_argument("--dry-run", action="store_true")
    a = p.parse_args()
    graph_path = a.graph.resolve()
    ui_path = graph_path.with_suffix(".t3ui")
    g, u = refine(read_graph(graph_path), read_graph(ui_path))
    ids = {c["Id"] for c in g["Children"]}
    assert len(ids) == len(g["Children"])
    assert all(e["SourceParentOrChildId"] in ids and e["TargetParentOrChildId"] in ids
               for e in g["Connections"])
    print("VISUAL_PLAN", len(g["Children"]), "children", len(g["Connections"]), "edges")
    if a.dry_run:
        return
    backup = BACKUPS / ("before-ascii-sdf-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
    backup.mkdir(parents=True)
    shutil.copy2(graph_path, backup / graph_path.name)
    shutil.copy2(ui_path, backup / ui_path.name)
    graph_path.write_text(json.dumps(g, indent=2) + "\n", encoding="utf-8")
    ui_path.write_text(json.dumps(u, indent=2) + "\n", encoding="utf-8")
    print("VISUAL_INSTALLED", graph_path, "backup", backup)


if __name__ == "__main__":
    main()

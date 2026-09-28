"""Add editable TiXL post FX inspired by the bundled VJ and image-effect examples.

The chain uses Bloom, ChromaticAbberation, RgbTV, GlitchQuick and Blend.
Beat and irregular AnimValue nodes drive short glitch composites. Run on the
AsterionBreakaway home graph while TiXL is closed; keep backups outside Symbols.
"""

from __future__ import annotations

import json
import re
import sys
import uuid
from pathlib import Path


PREFIX = "Post FX | "
SYMBOLS = {
    "bloom": ("f634e126-8834-46ea-bd6e-5ebfdc8b0733", "Lib.image.fx.blur.Bloom"),
    "fringe": ("8a203866-148d-4785-ae0e-61328b7646bb", "Lib.image.fx.stylize.ChromaticAbberation"),
    "signal": ("5972a57b-73cd-49b2-8b24-96636a4c294b", "Lib.image.fx.glitch.RgbTV"),
    "glitch": ("53c8b5f4-fd3b-4a7c-a22a-dea37c45b6d4", "Lib.image.fx.glitch.GlitchQuick"),
    "blend": ("9f43f769-d32a-4f49-92ac-e0be3ba250cf", "Lib.image.use.Blend"),
    "anim": ("ea7b8491-2f8e-4add-b0b1-fd068ccfed0d", "Lib.numbers.anim.animators.AnimValue"),
    "multiply": ("17b60044-9125-4961-8a79-ca94697b3726", "Lib.numbers.float.basic.Multiply"),
    "vec4": ("f2e323bd-f881-41a8-81e2-e8f2ac1984dc", "Types.Values.Vector4"),
}


def load(path: Path) -> dict:
    raw = re.sub(r'("[0-9a-fA-F-]{36}")/\*.*?\*/', r"\1", path.read_text(encoding="utf-8"))
    return json.loads(raw)


def value(slot: str, kind: str, setting) -> dict:
    return {"Id": slot, "Type": kind, "Value": setting}


def node(graph: dict, key: str, name: str, values=()) -> dict:
    symbol_id, symbol_name = SYMBOLS[key]
    return {"Id": str(uuid.uuid5(uuid.NAMESPACE_URL, graph["Id"] + "/music-video/" + name)),
            "SymbolId": symbol_id, "SymbolName": symbol_name, "Name": PREFIX + name,
            "InputValues": list(values), "Outputs": []}


def edge(source: dict, output: str, target: dict, input_slot: str) -> dict:
    return {"SourceParentOrChildId": source["Id"], "SourceSlotId": output,
            "TargetParentOrChildId": target["Id"], "TargetSlotId": input_slot}


def configure(path: Path) -> None:
    graph = load(path)
    ui_path = path.with_suffix(".t3ui")
    ui = load(ui_path)
    by_name = {item.get("Name"): item for item in graph["Children"]}
    if any(name.startswith(PREFIX) for name in by_name if name):
        raise ValueError("Post FX nodes already exist; preserve editor changes")
    required = ("Tone mapping", "Output fit", "Output target", "Main / clip to scene time")
    if any(name not in by_name for name in required):
        raise ValueError("The rendered output path is missing")
    tone, fit, target, time = (by_name[name] for name in required)
    old = edge(tone, "05c886f7-2c2c-4fe8-8b66-d6967dc43367", fit,
               "92c66734-dce9-402a-95f6-cde0e58bf32f")
    if old not in graph["Connections"]:
        raise ValueError("Tone mapping to Output fit was edited")
    graph["Connections"].remove(old)

    def add(key: str, name: str, x: float, y: float, values=()) -> dict:
        child = node(graph, key, name, values)
        graph["Children"].append(child)
        ui["SymbolChildUis"].append({"ChildId": child["Id"],
                                     "Position": {"X": x, "Y": y}})
        return child

    bloom = add("bloom", "01 spectral bloom", 2440, 180, [
        value("2064aba1-658e-4795-a4fc-5be1026d7064", "System.Int32", 5),
        value("28e0b719-0888-4ef6-85d9-bbd75f7a4537", "System.Single", 0.9),
        value("bb706662-2555-4f3b-a81e-60e04f052f36", "System.Single", 0.45),
        value("c6a0cadc-9e1c-40ac-97f1-d9271b5376df", "System.Single", 0.45),
    ])
    fringe = add("fringe", "02 chromatic fracture", 2640, 180, [
        value("4c51b5f5-5307-45a7-9641-25f572627926", "System.Single", 3.2),
        value("4e03d06a-d19b-463f-bbbd-b64d24c04b9e", "System.Int32", 3),
        value("6dd98990-82a7-4f68-aef1-ff34d1825b3b", "System.Single", -0.035),
    ])
    signal = add("signal", "03 scanline signal", 2840, 180, [
        value("38529a44-4622-4c87-886e-72f4400ec468", "System.Single", 0.12),
        value("3ef09b89-b3e8-432b-bed3-f7c9033acefa", "System.Single", 2.2),
        value("50cab12f-535c-4651-98d2-5c8b3c18cc81", "System.Single", -0.02),
        value("88258a10-d5e4-4a4e-80b3-eacaebe75abf", "System.Single", 1.08),
        value("e29b1dad-d3ef-405f-99c0-4552caedaf7c", "System.Single", 0.06),
        value("f76c6202-34dc-4c10-adab-c10cb7665fed", "System.Single", 0.04),
        value("a13b757c-62ed-478b-b0fe-70cceb43586e", "System.Single", 0.025),
        value("a24de125-eb69-4c44-afa6-69dfdbf16087", "System.Single", 0.16),
        value("e3e3f393-0c43-4c71-b134-adc094ca2965", "System.Single", 0.01),
    ])
    glitch = add("glitch", "04 torn frames + pixel sort", 3050, 320, [
        value("2a28f084-bc2f-4458-8ad8-f3bf11086fc4", "System.Boolean", True),
        value("b7b21d3c-80e1-450e-a1c7-b8720b550924", "System.Single", 0.3),
        value("80c6ed94-e5e5-480b-b69e-2c4f9b2935c7", "System.Single", 0.035),
        value("bcadf77c-be02-482d-9cd7-87085831e9cd", "System.Single", 0.16),
    ])
    blend = add("blend", "05 rhythmic glitch composite", 3270, 180)

    # KickSaws produce a short onset every half-second at 120 BPM; random
    # modulation makes successive onsets uneven, like an IDM break pattern.
    kick = add("anim", "beat pulse | 120 BPM", 2850, 570, [
        value("4cf5d20b-7335-4584-b246-c260ac5cdf4f", "System.Int32", 3),
        value("48005727-0158-4795-ad70-8410c27fd01d", "System.Single", 2.0),
        value("8327e7ec-4370-4a3e-bd69-db3f4aa4b1d7", "System.Single", 0.3),
        value("79917ef7-64ca-4825-9c6a-c9b2a7f6ff86", "System.Single", 0.86),
        value("ddd93b06-118e-43e0-85f6-c150faf91d04", "System.Single", 0.03),
        value("738f6cfb-8b71-423c-b897-824c20397e5a", "System.Int32", 0),
    ])
    irregular = add("anim", "off-grid random accents", 2850, 690, [
        value("4cf5d20b-7335-4584-b246-c260ac5cdf4f", "System.Int32", 10),
        value("48005727-0158-4795-ad70-8410c27fd01d", "System.Single", 0.73),
        value("79917ef7-64ca-4825-9c6a-c9b2a7f6ff86", "System.Single", 0.72),
        value("ddd93b06-118e-43e0-85f6-c150faf91d04", "System.Single", 0.28),
        value("738f6cfb-8b71-423c-b897-824c20397e5a", "System.Int32", 0),
    ])
    energy = add("multiply", "beat × irregular energy", 3060, 590)
    rgba = add("vec4", "glitch blend RGB + alpha", 3260, 580, [
        value("bdd35cdd-2220-4c58-9ec8-a5e48d7aaf7e", "System.Single", 1.0),
        value("46a4ee87-ab2b-406b-a9ae-c000f887d99f", "System.Single", 1.0),
        value("59908ecc-1822-4aba-a2d9-cfe97168b3b3", "System.Single", 1.0),
    ])

    links = graph["Connections"]
    links.extend((
        edge(tone, "05c886f7-2c2c-4fe8-8b66-d6967dc43367", bloom,
             "97d8f330-5957-4309-8c56-d94c1266f6cb"),
        edge(bloom, "f3fa372d-f037-48fd-8a8d-a0135b4c20cb", fringe,
             "b62aece4-8098-475b-a4d3-469f81a58207"),
        edge(fringe, "8af0d916-9708-422b-8fb7-39ef59c82d7f", signal,
             "2dbfdd5d-8b4b-447c-bd19-326d46657ea1"),
        edge(signal, "22eac013-881d-486a-8041-5cae32b8dca1", glitch,
             "5f073394-8bb6-4406-b25e-6556734c8284"),
        edge(signal, "22eac013-881d-486a-8041-5cae32b8dca1", blend,
             "abaa52e9-7d3d-4ae5-89d2-5251f61e5392"),
        edge(glitch, "1b4f3472-4542-4b22-96fb-970a60234799", blend,
             "c7c524cf-e31e-4bac-8f77-58bd61b337de"),
        edge(blend, "536fae14-b814-498c-a6b4-07775de36991", fit,
             "92c66734-dce9-402a-95f6-cde0e58bf32f"),
        edge(time, "c1dbdb9e-a7ad-424b-b2ba-94bd9ce71daf", kick,
             "7b4992ba-30f7-42e5-b04b-ae4ec0be810e"),
        edge(time, "c1dbdb9e-a7ad-424b-b2ba-94bd9ce71daf", irregular,
             "7b4992ba-30f7-42e5-b04b-ae4ec0be810e"),
        edge(kick, "ae4addf0-08cf-4b25-9515-4fef9359d183", energy,
             "372288fa-3794-47ba-9f91-59240513217a"),
        edge(irregular, "ae4addf0-08cf-4b25-9515-4fef9359d183", energy,
             "5ae4bb07-4214-4ec3-a499-24d9f6d404a5"),
        edge(energy, "e011dd8c-1b9c-458f-8960-e6c38e83ca74", rgba,
             "6ce53000-34d6-4d9a-aef3-164fd223f6d2"),
        edge(rgba, "14cdc3dd-f229-4f8f-b953-4f9d587d6f58", blend,
             "70dc133e-800a-4cd0-a159-2cbab4c322cb"),
        edge(energy, "e011dd8c-1b9c-458f-8960-e6c38e83ca74", fringe,
             "361a838a-7bf1-4fd2-8e0e-77edcef11965"),
    ))
    # Keep the final image route visible beside the added post-processing island.
    positions = {item["ChildId"]: item for item in ui["SymbolChildUis"]}
    positions[fit["Id"]]["Position"] = {"X": 3500, "Y": 180}
    positions[target["Id"]]["Position"] = {"X": 3740, "Y": 140}
    if len({item["Id"] for item in graph["Children"]}) != len(graph["Children"]):
        raise ValueError("Duplicate child identifier")
    path.write_text(json.dumps(graph, indent=2) + "\n", encoding="utf-8")
    ui_path.write_text(json.dumps(ui, indent=2) + "\n", encoding="utf-8")
    print(f"Installed {len(SYMBOLS) + 1} post nodes; {len(graph['Children'])} nodes, {len(links)} links")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: configure_asterion_music_video_fx.py <AsterionBreakaway.t3>")
    configure(Path(sys.argv[1]))

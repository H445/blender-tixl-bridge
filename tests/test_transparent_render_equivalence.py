"""Offline checks for the transparent-render harness's fixture and route guards."""
import json
import struct
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import transparent_render_equivalence as harness


def _glb(alpha_mode="BLEND", alpha=0.35):
    document = {"asset": {"version": "2.0"},
                "materials": [{"alphaMode": alpha_mode,
                               "pbrMetallicRoughness": {"baseColorFactor": [1, 1, 1, alpha]}}],
                "meshes": [{"primitives": [{"material": 0, "attributes": {"POSITION": 0}}]}]}
    payload = json.dumps(document, separators=(",", ":")).encode("utf-8")
    payload += b" " * ((4 - len(payload) % 4) % 4)
    return b"glTF" + struct.pack("<II", 2, 20 + len(payload)) + struct.pack(
        "<II", len(payload), 0x4E4F534A) + payload


class TransparentRenderHarnessTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.glb = self.root / "cube_alpha.glb"
        self.animation = self.root / "cube_animation.bin"
        self.glb.write_bytes(_glb())
        self.animation.write_bytes(b"TIXLANIM\x01" + b"test")
        self.animation.with_suffix(".json").write_text(
            json.dumps({"records": [{"export_name": "Cube", "count": 2}]}), encoding="utf-8")

    def test_fixture_requires_real_transparent_primitive_and_sampled_track(self):
        harness._assert_fixture(self.glb, self.animation)
        self.glb.write_bytes(_glb(alpha_mode="OPAQUE"))
        with self.assertRaisesRegex(ValueError, "BLEND primitive"):
            harness._assert_fixture(self.glb, self.animation)
        self.glb.write_bytes(_glb())
        self.animation.with_suffix(".json").write_text(
            json.dumps({"records": [{"export_name": "Cube", "count": 1}]}), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "sampled Cube track"):
            harness._assert_fixture(self.glb, self.animation)

    def _graph(self):
        motion = {"childId": "motion", "name": "Cube / opaque motion",
                  "symbolId": "8cc13ea4-9e0d-4b61-9b1f-b72f6c470a7a",
                  "inputs": [{"id": "glb", "name": "GlbPath", "value": str(self.glb)},
                             {"id": "bin", "name": "DataPath", "value": str(self.animation)}]}
        old_draw = {"childId": "old-draw", "name": "Cube / opaque draw", "symbolName": "DrawScene",
                    "inputs": [{"id": "old-color", "name": "Color", "value": {"X": 1, "Y": 1, "Z": 1, "W": 0}},
                               {"id": "old-blend", "name": "BlendMode", "value": harness.ALPHA_BLEND_MODE},
                               {"id": "old-zwrite", "name": "EnableZWrite", "value": False}]}
        native_load = {"childId": "native-load", "name": "Cube / opaque load",
                       "inputs": [{"id": "path", "name": "Path", "value": str(self.glb)}]}
        temporary_draw = {"childId": "new-draw", "name": "DrawScene", "symbolId": harness.DRAW_SCENE_SYMBOL_ID,
                          "inputs": [{"id": "scene", "name": "Scene", "value": {}},
                                     {"id": "color", "name": "Color", "value": {"X": 1, "Y": 1, "Z": 1, "W": 1}},
                                     {"id": "blend", "name": "BlendMode", "value": harness.ALPHA_BLEND_MODE},
                                     {"id": "zwrite", "name": "EnableZWrite", "value": False}]}
        group = {"childId": "cube-group", "name": "Cube / scene", "symbolName": "Group",
                 "inputs": [{"id": "commands", "name": "Commands", "value": None}]}
        original_edge = {"sourceParentOrChildId": "old-draw", "sourceSlotId": harness.DRAW_COMMAND_ID,
                         "targetParentOrChildId": "cube-group", "targetSlotId": "commands"}
        temporary_edges = [original_edge,
                           {"sourceParentOrChildId": "motion", "sourceSlotId": harness.TRANSPARENT_RESULT_ID,
                            "targetParentOrChildId": "new-draw", "targetSlotId": "scene"},
                           {"sourceParentOrChildId": "new-draw", "sourceSlotId": harness.DRAW_COMMAND_ID,
                            "targetParentOrChildId": "cube-group", "targetSlotId": "commands"}]
        graph = {"children": [motion, old_draw, native_load, temporary_draw, group], "connections": temporary_edges}
        original_graph = {"connections": [original_edge]}
        return motion, temporary_draw, old_draw, native_load, group, graph, original_graph

    def test_temporary_graph_keeps_original_wire_and_routes_transparent_output(self):
        motion, draw, old_draw, native_load, group, graph, original = self._graph()
        harness._verify_temporary_graph(graph, motion, "new-draw", old_draw, native_load, group,
                                        self.glb, self.animation, harness.ALPHA_BLEND_MODE,
                                        original)

    def test_temporary_graph_rejects_lost_original_connection(self):
        motion, draw, old_draw, native_load, group, graph, original = self._graph()
        graph["connections"] = graph["connections"][1:]
        with self.assertRaisesRegex(AssertionError, "pre-existing graph connection"):
            harness._verify_temporary_graph(graph, motion, "new-draw", old_draw, native_load, group,
                                            self.glb, self.animation, harness.ALPHA_BLEND_MODE,
                                            original)

    def test_temporary_graph_rejects_wrong_transparent_route(self):
        motion, draw, old_draw, native_load, group, graph, original = self._graph()
        graph["connections"][1]["sourceSlotId"] = "wrong-output"
        with self.assertRaisesRegex(AssertionError, "TransparentResult"):
            harness._verify_temporary_graph(graph, motion, "new-draw", old_draw, native_load, group,
                                            self.glb, self.animation, harness.ALPHA_BLEND_MODE,
                                            original)


if __name__ == "__main__":
    unittest.main()

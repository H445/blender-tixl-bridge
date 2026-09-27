"""Unit tests for restoring native scenes after the render comparison."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from tixl_animation_bake_validation import LOAD_COUNTERS, bindings, load_counters, reload_original_scenes


def graph():
    return {"children": [
        {"childId": "loader-a", "symbolName": "Lib.render.scene.LoadGltfScene",
         "inputs": [{"id": "path-a", "name": "Path", "value": "/old/a.glb"}]},
        {"childId": "animation-a", "symbolName": "PrismalLabs.BlenderExport.BlenderAnimationScene",
         "inputs": [{"id": "glb-a", "name": "GlbPath", "value": "/old/a.glb"}]},
        {"childId": "loader-b", "symbolName": "Lib.render.scene.LoadGltfScene",
         "inputs": [{"id": "path-b", "name": "Path", "value": "/old/b.glb"}]},
    ]}


class BakeRenderFixtureTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.baseline = Path(self.temp.name) / "baseline"
        self.optimized = Path(self.temp.name) / "optimized"
        self.baseline.mkdir()
        self.optimized.mkdir()
        self.graph = {"children": []}
        for world in ("cube", "prism", "cylinder", "sphere"):
            for suffix in ("animation.bin", "animation.json", "channels.json"):
                for folder in (self.baseline, self.optimized):
                    (folder / f"{world}_{suffix}").write_bytes((world + suffix).encode())
            self.graph["children"].append({
                "childId": world, "symbolName": "PrismalLabs.BlenderExport.BlenderAnimationScene",
                "inputs": [{"id": "data", "name": "DataPath", "value": f"/existing/{world}_animation.bin"}]})

    def test_all_four_worlds_resolve_without_changing_graph(self):
        result = bindings(self.graph, self.baseline, self.optimized)
        self.assertEqual([row[2] for row in result],
                         [world + "_animation.bin" for world in ("cube", "prism", "cylinder", "sphere")])
        self.assertEqual(self.graph["children"][0]["inputs"][0]["value"], "/existing/cube_animation.bin")

    def test_changed_channels_are_rejected_before_rendering(self):
        (self.optimized / "prism_channels.json").write_bytes(b"different")
        with self.assertRaisesRegex(ValueError, "prism_channels.json"):
            bindings(self.graph, self.baseline, self.optimized)

    def test_missing_metadata_is_rejected(self):
        (self.optimized / "sphere_animation.json").unlink()
        with self.assertRaisesRegex(ValueError, "sphere_animation.json"):
            bindings(self.graph, self.baseline, self.optimized)

    def test_incomplete_graph_is_rejected(self):
        self.graph["children"].pop()
        with self.assertRaisesRegex(ValueError, "four animation bindings"):
            bindings(self.graph, self.baseline, self.optimized)

    def test_loading_counters_reject_missing_invalid_and_saturated_values(self):
        valid = {key: 12 for key in LOAD_COUNTERS}
        self.assertEqual(load_counters(valid), valid)
        for value in (None, True, -1, 2**31 - 1, 1.5):
            with self.subTest(value=value):
                invalid = {**valid, LOAD_COUNTERS[0]: value}
                with self.assertRaisesRegex(ValueError, "unsaturated"):
                    load_counters(invalid)


class ReloadOriginalScenesTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.payload = Path(self.temp.name)
        (self.payload / "a.glb").write_bytes(b"a")
        (self.payload / "b.glb").write_bytes(b"b")
        self.graph = graph()

    def test_refreshes_only_native_loaders_then_undoes_and_pumps(self):
        calls = []

        def protocol(method, port, **kwargs):
            calls.append((method, port, kwargs))
            return {}

        result = reload_original_scenes(self.graph, self.payload, protocol, 9042)

        self.assertEqual(result, ["loader-a", "loader-b"])
        self.assertEqual([row[0] for row in calls],
                         ["setInput", "pumpFrames", "undo", "pumpFrames"] * 2)
        self.assertEqual([row[2].get("childId") for row in calls if row[0] == "setInput"],
                         ["loader-a", "loader-b"])
        for method, port, kwargs in calls:
            self.assertEqual(port, 9042)
            if method == "setInput":
                self.assertEqual(kwargs["inputId"], "path-" + kwargs["childId"][-1])
                self.assertEqual(Path(kwargs["value"]).read_bytes(),
                                 kwargs["childId"][-1].encode())
            elif method == "pumpFrames":
                self.assertEqual(kwargs, {"count": 3})
            else:
                self.assertEqual(method, "undo")
                self.assertEqual(kwargs, {})
        self.assertFalse(any(row[2].get("childId", "").startswith("animation") for row in calls))

    def test_pump_failure_attempts_undo_and_preserves_original_error(self):
        calls = []
        original = RuntimeError("refresh pump failed")

        def protocol(method, port, **kwargs):
            calls.append(method)
            if method == "pumpFrames":
                raise original
            return {}

        with self.assertRaises(RuntimeError) as raised:
            reload_original_scenes(self.graph, self.payload, protocol, 9042)

        self.assertIs(raised.exception, original)
        self.assertEqual(calls, ["setInput", "pumpFrames", "undo", "pumpFrames"])

    def test_failed_set_input_does_not_issue_a_false_undo(self):
        calls = []
        original = OSError("setInput rejected")

        def protocol(method, port, **kwargs):
            calls.append(method)
            if method == "setInput":
                raise original
            return {}

        with self.assertRaises(OSError) as raised:
            reload_original_scenes(self.graph, self.payload, protocol, 9042)

        self.assertIs(raised.exception, original)
        self.assertEqual(calls, ["setInput"])

    def test_cleanup_undo_failure_propagates(self):
        calls = []
        cleanup = RuntimeError("undo rejected")

        def protocol(method, port, **kwargs):
            calls.append(method)
            if method == "undo":
                raise cleanup
            return {}

        with self.assertRaises(RuntimeError) as raised:
            reload_original_scenes(self.graph, self.payload, protocol, 9042)

        self.assertIs(raised.exception, cleanup)
        self.assertEqual(calls, ["setInput", "pumpFrames", "undo"])


if __name__ == "__main__":
    unittest.main()

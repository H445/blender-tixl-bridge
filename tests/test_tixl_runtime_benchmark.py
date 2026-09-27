"""Failure-path tests for benchmark restoration and counter validity."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import tixl_runtime_benchmark as benchmark


class RuntimeBenchmarkRestoreTest(unittest.TestCase):
    def setUp(self):
        self.context = {
            "compositionName": "BlendShapeExample",
            "time": {"timeInSecs": 3.25, "playbackSpeed": 1.5, "isPlaying": False},
        }
        self.graph = {"children": [{"childId": "child-1"}], "connections": []}

    def _run_restore(self, fail_at=None, applied=2):
        calls = []
        report = {}
        failed = False

        def protocol(method, port, **params):
            nonlocal failed
            calls.append((method, params))
            should_fail = (
                fail_at == "undo" and method == "undo" and not failed
                or fail_at == "setTime" and method == "setTime"
                or fail_at == "pumpFrames" and method == "pumpFrames"
                or fail_at == "getGraphState" and method == "getGraphState"
                or fail_at == "playback_speed" and method == "setPlayback" and "speed" in params
                or fail_at == "playback_state" and method == "setPlayback" and "playing" in params
                or fail_at == "getContext" and method == "getContext"
            )
            if should_fail:
                failed = True
                raise RuntimeError(f"injected {fail_at} failure")
            if method == "getGraphState":
                return self.graph
            if method == "getContext":
                return self.context
            return {}

        result = benchmark._restore_state(protocol, 9042, self.context, self.graph, applied, report)
        return result, report, calls

    def test_successful_cleanup_restores_full_graph_and_context(self):
        evidence, report, calls = self._run_restore(fail_at=None, applied=2)
        self.assertTrue(evidence["verified"])
        self.assertTrue(evidence["graphMatchesOriginal"])
        self.assertTrue(evidence["contextMatchesOriginal"])
        self.assertTrue(report["stateRestored"])
        self.assertEqual(report["cleanupFailures"], [])
        self.assertEqual([method for method, _ in calls], [
            "undo", "undo", "setTime", "pumpFrames", "getGraphState",
            "setPlayback", "setPlayback", "getContext",
        ])

    def test_playback_mode_precedes_exact_speed_restore(self):
        for playing, speed in ((True, 2.0), (False, -0.5)):
            with self.subTest(playing=playing, speed=speed):
                self.context["time"]["isPlaying"] = playing
                self.context["time"]["playbackSpeed"] = speed
                evidence, _, calls = self._run_restore(fail_at=None, applied=0)
                playback = [params for method, params in calls if method == "setPlayback"]
                self.assertEqual(playback, [{"playing": playing}, {"speed": speed}])
                self.assertTrue(evidence["verified"])

    def test_each_cleanup_failure_still_attempts_later_restoration_steps(self):
        for failure in ("undo", "setTime", "pumpFrames", "getGraphState",
                        "playback_speed", "playback_state", "getContext"):
            with self.subTest(failure=failure):
                evidence, report, calls = self._run_restore(fail_at=failure)
                methods = [method for method, _ in calls]
                self.assertEqual(methods[-1], "getContext")
                self.assertIn("setTime", methods)
                self.assertIn("pumpFrames", methods)
                self.assertIn("getGraphState", methods)
                self.assertEqual(sum(method == "undo" for method in methods), 2)
                self.assertTrue(any(method == "setPlayback" and "playing" in params
                                    for method, params in calls))
                self.assertFalse(evidence["verified"])
                self.assertFalse(report["stateRestored"])
                self.assertTrue(report["cleanupFailures"])
                self.assertTrue(all("step" in attempt and "status" in attempt
                                    for attempt in report["restoration"]["attempts"]))

    def test_failed_benchmark_report_is_persisted_before_original_error_is_raised(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache = root / "example-cache"
            worlds = cache / "worlds"
            worlds.mkdir(parents=True)
            (worlds / "manifest.json").write_text(json.dumps({
                "fps": 60,
                "worlds": [{"world": "main", "active_clip": [1, 121]}],
            }), encoding="utf-8")
            (cache / "camera_60hz.bin").write_bytes(b"camera")
            (cache / "camera_timeline.json").write_text("{}", encoding="utf-8")
            private_root = root / "private-generation"
            (private_root / "worlds").mkdir(parents=True)
            (private_root / "worlds" / "scene.glb").write_bytes(b"private payload")
            folder = root / "report"
            child = {"childId": "child-1", "symbolName": "BlenderAnimationScene",
                     "inputs": [{"id": "ca02f7a3-a03a-4db0-a05d-3a66b0c9ab11",
                                  "value": str(cache / "worlds" / "scene.glb")} ]}
            graph = {"children": [child], "connections": []}
            context = {"compositionName": "BlendShapeExample",
                       "time": {"timeInSecs": 3.25, "playbackSpeed": 1.5, "isPlaying": False}}
            calls = []

            def protocol(method, port, **params):
                calls.append(method)
                if method == "getContext":
                    return context
                if method == "getGraphState":
                    return graph
                if method == "getVersion":
                    return {"version": "test"}
                if method == "getMetrics":
                    raise RuntimeError("original benchmark failure")
                return {}

            with patch("cache_publication.active_root", return_value=cache), \
                    patch.object(benchmark, "publish_generation", return_value={"generation": "private"}), \
                    patch.object(benchmark, "verify_generation", return_value=private_root), \
                    patch.object(benchmark, "validate_export_payload"), \
                    patch.object(benchmark, "_managed_relative", return_value=Path("worlds/scene.glb")), \
                    patch.object(benchmark, "call", side_effect=protocol):
                with self.assertRaisesRegex(RuntimeError, "original benchmark failure"):
                    benchmark.benchmark(cache, folder, 9042, 10, "BlendShapeExample")

            saved = json.loads((folder / "runtime_report.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["status"], "failed")
            self.assertEqual(saved["benchmarkFailure"], {
                "errorType": "RuntimeError", "error": "original benchmark failure"})
            self.assertTrue(saved["stateRestored"])
            self.assertIn("setPlayback", calls)
            self.assertEqual(calls[-1], "getContext")


class RuntimeBenchmarkCounterTest(unittest.TestCase):
    def setUp(self):
        self.stats = {
            "Blender cumulative scene loads": 0,
            "Blender cumulative scene load us": 0,
            "Blender cumulative morph uploads": 0,
            "Blender cumulative material uploads": 0,
            "Blender cumulative upload bytes": 0,
        }

    def snapshot(self, stats=None, frame=None):
        values = dict(self.stats if stats is None else stats)
        values.update(frame or {
            "Blender morph uploads": 0,
            "Blender material uploads": 0,
            "Blender upload bytes": 0,
        })
        return {"renderStats": values}

    def test_below_saturation_baseline_is_valid(self):
        stats = dict(self.stats)
        stats["Blender cumulative upload bytes"] = 2**31 - 2
        benchmark._validate_cumulative_metrics([
            ("before", self.snapshot(stats)), ("after", self.snapshot(stats))])
        benchmark._validate_held_frame_metrics(self.snapshot())

    def test_cumulative_saturation_negative_and_decrease_are_rejected(self):
        for key in self.stats:
            with self.subTest(key=key):
                stats = dict(self.stats)
                stats[key] = 2**31 - 1
                with self.assertRaises(ValueError):
                    benchmark._validate_cumulative_metrics([("saturated", self.snapshot(stats))])
                stats[key] = -1
                with self.assertRaises(ValueError):
                    benchmark._validate_cumulative_metrics([("negative", self.snapshot(stats))])
        earlier, later = dict(self.stats), dict(self.stats)
        earlier["Blender cumulative material uploads"] = 10
        later["Blender cumulative material uploads"] = 9
        with self.assertRaisesRegex(ValueError, "decreased"):
            benchmark._validate_cumulative_metrics([
                ("first", self.snapshot(earlier)), ("second", self.snapshot(later))])

    def test_nonzero_held_frame_upload_counter_is_rejected(self):
        for key in benchmark._HELD_FRAME_STATS:
            with self.subTest(key=key):
                frame = {name: 0 for name in benchmark._HELD_FRAME_STATS}
                frame[key] = 1
                with self.assertRaisesRegex(AssertionError, "Unchanged source frame"):
                    benchmark._validate_held_frame_metrics(
                        self.snapshot(frame=frame))


if __name__ == "__main__":
    unittest.main()

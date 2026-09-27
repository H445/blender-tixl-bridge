"""Cache-validation regressions for the read-only bridge diagnostics helper."""
import hashlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "blender_tixl_bridge" / "source"
sys.path.insert(0, str(ROOT / ".agents"))
sys.path.insert(0, str(SOURCE))
import cache_publication as publication
import bridge_diagnostics as diagnostics


class BridgeDiagnosticsCacheTest(unittest.TestCase):
    def setUp(self):
        # Windows runners keep TEMP and the checkout on different drives.
        # These fixtures explicitly test paths relative to the checkout.
        self.temporary = tempfile.TemporaryDirectory(dir=Path.cwd())
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.source = self.root / "scene.blend"
        self.source.write_bytes(b"authored scene snapshot")
        self.cache = self.root / "cache"
        self.active = self._publish("baseline")

    def _stage(self, label):
        stage = self.root / ("stage_" + label)
        (stage / "worlds").mkdir(parents=True)
        (stage / "camera_60hz.bin").write_bytes((label + " camera").encode())
        (stage / "camera_timeline.json").write_text("{}", encoding="utf-8")
        (stage / "worlds" / "main_opaque.glb").write_bytes((label + " glb").encode())
        (stage / "worlds" / "main_animation.bin").write_bytes((label + " animation").encode())
        manifest = {
            "source_blend": str(self.source),
            "source_sha256": hashlib.sha256(self.source.read_bytes()).hexdigest(),
            "worlds": [{"world": "main", "glbs": {"opaque": "pending"}}],
        }
        (stage / "worlds" / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        return stage, manifest

    def _publish(self, label):
        stage, manifest = self._stage(label)
        return publication.publish_generation(
            stage, self.cache, manifest, "generic", self.source,
            hashlib.sha256(self.source.read_bytes()).hexdigest(),
        )

    def _assert_valid(self, result):
        self.assertEqual(result["status"], "verified")
        self.assertEqual(result["generation"], self.active["generation"])
        self.assertEqual(result["worlds"], ["main"])

    def _inspect_graph_path(self, value):
        context = {
            "hasOpenProject": True,
            "compositionSymbolId": "composition",
            "compositionName": "Fixture",
            "compositionPath": [],
            "selectedChildren": [],
            "outputView": {"isPinned": True, "childId": "target", "symbolName": "RenderTarget"},
            "time": {"timeInSecs": 0.0, "isPlaying": False, "playbackSpeed": 0.0},
        }
        graph = {
            "symbolId": "composition", "symbolName": "Fixture",
            "children": [{
                "childId": "animation-scene", "symbolId": "animation-scene-symbol",
                "symbolName": "BlenderAnimationScene", "inputs": [{
                    "id": "data-path", "name": "DataPath", "value": str(value),
                }],
            }],
            "connections": [],
        }
        logs = {"entries": [], "latestSeq": 4, "oldestAvailableSeq": 0}

        def envelope(method, result):
            response = {"ok": True, "result": result}
            if method == "getContext":
                response["structureVersion"] = 7
            request = {"id": "fixture", "method": method}
            request_line = json.dumps(request) + "\n"
            response_line = json.dumps(response) + "\n"
            return {"request": request, "response": response,
                    "requestLine": request_line, "responseLine": response_line}

        responses = {
            "getVersion": {"editorVersion": "4.3.0.2", "protocolVersion": 1},
            "getContext": context,
            "getStructureVersion": {"symbolStructureVersion": 3},
            "getGraphState": graph,
            "getLogTail": logs,
        }

        def caller(method, _port, **_params):
            return envelope(method, responses[method])

        return diagnostics.collect_diagnostics(self.root / "path-diagnostics", mode="inspect",
                                               cache=self.cache, caller=caller)

    def test_valid_committed_generation_is_reported_with_identity_and_inventory(self):
        result, detail = diagnostics.cache_evidence(self.cache)
        self._assert_valid(result)
        self.assertEqual(result["fileCount"], 6)
        self.assertEqual(result["worldCount"], 1)
        self.assertEqual(detail["identity"]["generation"], self.active["generation"])
        self.assertEqual(detail["manifest"]["generation"], self.active["generation"])

    def test_legacy_flat_cache_without_committed_pointer_is_not_generation_verified(self):
        legacy = self.root / "legacy"
        (legacy / "worlds").mkdir(parents=True)
        (legacy / "worlds" / "manifest.json").write_text("{}", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "No verified committed export generation"):
            diagnostics.cache_evidence(legacy)

    def test_pointer_to_manifest_generation_mismatch_is_rejected(self):
        generation_root = publication.generation_root(self.cache, self.active["generation"])
        manifest_path = generation_root / "worlds" / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["generation"] = "f" * 32
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        marker_path = generation_root / publication.MARKER
        marker = json.loads(marker_path.read_text(encoding="utf-8"))
        marker["files"]["worlds/manifest.json"] = {
            "size": manifest_path.stat().st_size,
            "sha256": diagnostics.file_digest(manifest_path),
        }
        marker_path.write_text(json.dumps(marker), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Manifest generation does not match"):
            diagnostics.cache_evidence(self.cache)

    def test_tampered_committed_payload_is_rejected(self):
        payload = publication.generation_root(self.cache, self.active["generation"]) / "worlds" / "main_opaque.glb"
        payload.write_bytes(b"tampered")
        with self.assertRaisesRegex(ValueError, "verified committed export generation"):
            diagnostics.cache_evidence(self.cache)

    def test_changed_authored_source_is_rejected_even_when_generation_files_are_intact(self):
        self.source.write_bytes(b"new saved source")
        with self.assertRaisesRegex(ValueError, "Authored source is missing or changed"):
            diagnostics.cache_evidence(self.cache)

    def test_generation_change_during_inspection_is_reported_and_errors_remain_visible(self):
        output = self.root / "diagnostics"
        context = {
            "hasOpenProject": True,
            "compositionSymbolId": "composition",
            "compositionName": "Fixture",
            "compositionPath": [],
            "selectedChildren": [],
            "outputView": {"isPinned": True, "childId": "target", "symbolName": "RenderTarget"},
            "time": {"timeInSecs": 0.0, "isPlaying": False, "playbackSpeed": 0.0},
        }
        generation_root = publication.generation_root(self.cache, self.active["generation"])
        graph = {
            "symbolId": "composition", "symbolName": "Fixture",
            "children": [{
                "childId": "animation-scene", "symbolId": "animation-scene-symbol",
                "symbolName": "BlenderAnimationScene", "inputs": [{
                    "id": "data-path", "name": "DataPath",
                    "value": str(generation_root / "worlds" / "main_animation.bin"),
                }],
            }],
            "connections": [],
        }
        logs = {"entries": [{"seq": 4, "level": "Error", "message": "fixture render error"}],
                "latestSeq": 4, "oldestAvailableSeq": 0}
        published = False

        def envelope(method, result):
            response = {"ok": True, "result": result}
            if method == "getContext":
                response["structureVersion"] = 7
            request = {"id": "fixture", "method": method}
            request_line = json.dumps(request) + "\n"
            response_line = json.dumps(response) + "\n"
            return {"request": request, "response": response,
                    "requestLine": request_line, "responseLine": response_line}

        def caller(method, _port, **_params):
            nonlocal published
            if method == "getGraphState" and not published:
                self._publish("concurrent")
                published = True
            responses = {
                "getVersion": {"editorVersion": "4.3.0.2", "protocolVersion": 1},
                "getContext": context,
                "getStructureVersion": {"symbolStructureVersion": 3},
                "getGraphState": graph,
                "getLogTail": logs,
            }
            return envelope(method, responses[method])

        result = diagnostics.collect_diagnostics(output, mode="inspect", cache=self.cache, caller=caller)
        self.assertFalse(result["ok"])
        self.assertEqual(result["logs"]["retainedErrors"], 1)
        self.assertTrue(any("Committed generation changed" in error for error in result["errors"]))
        receipt = json.loads(Path(result["evidence"]).read_text(encoding="utf-8"))
        self.assertEqual(receipt["cache"]["identity"]["generation"], self.active["generation"])
        self.assertEqual(receipt["summary"]["logs"]["retainedErrors"], 1)
        self.assertFalse((output / "cursor.json").exists(), "inconsistent evidence must not advance the cursor")

    def test_live_animation_path_must_exist_as_a_committed_generation_member(self):
        generation_root = publication.generation_root(self.cache, self.active["generation"])
        missing = generation_root / "worlds" / "missing_animation.bin"
        result = self._inspect_graph_path(missing)
        self.assertFalse(result["ok"])
        self.assertTrue(any("expected kind" in error for error in result["errors"]))

    def test_live_animation_path_rejects_a_committed_member_of_the_wrong_kind(self):
        generation_root = publication.generation_root(self.cache, self.active["generation"])
        manifest = generation_root / "worlds" / "manifest.json"
        self.assertTrue(manifest.is_file())
        result = self._inspect_graph_path(manifest)
        self.assertFalse(result["ok"])
        self.assertTrue(any("expected kind" in error for error in result["errors"]))

    def test_receipt_output_stays_under_resolved_directory_without_touching_generation(self):
        output = self.root / "private" / "nested" / ".." / "diagnostics"
        output.mkdir(parents=True)
        resolved = output.resolve()
        generation_root = publication.generation_root(self.cache, self.active["generation"])
        marker_before = diagnostics.file_digest(generation_root / publication.MARKER)
        result = diagnostics.collect_diagnostics(output, mode="cache", cache=self.cache)
        evidence = Path(result["evidence"]).resolve()
        self.assertTrue(result["ok"])
        self.assertTrue(evidence.is_relative_to(resolved))
        self.assertTrue(evidence.is_relative_to(self.root))
        self.assertEqual(marker_before, diagnostics.file_digest(generation_root / publication.MARKER))
        self.assertEqual(publication.active_root(self.cache).name, self.active["generation"])

    def test_output_inside_generation_payload_is_rejected_with_or_without_cache_argument(self):
        generation_root = publication.generation_root(self.cache, self.active["generation"])
        absolute_output = generation_root / "diagnostics"
        relative_output = Path(os.path.relpath(absolute_output, Path.cwd()))
        for output in (absolute_output, relative_output):
            for cache_argument in (self.cache, None):
                with self.subTest(relative=not output.is_absolute(), cache_argument=cache_argument is not None):
                    resolved_output = output.resolve()
                    with self.assertRaisesRegex(ValueError, "generation"):
                        diagnostics.collect_diagnostics(output, mode="cache", cache=cache_argument)
                    self.assertFalse(resolved_output.exists())


if __name__ == "__main__":
    unittest.main()

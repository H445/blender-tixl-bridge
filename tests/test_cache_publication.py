"""Failure injection at the complete-generation publication boundary."""
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "blender_tixl_bridge" / "source"))
import cache_publication as publication


class PublicationTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.cache = self.root / "cache"
        self.source = self.root / "scene.blend"
        self.source.write_bytes(b"saved source")
        self.sha = hashlib.sha256(self.source.read_bytes()).hexdigest()
        self.old = self.publish("old")

    def stage(self, label):
        stage = self.root / ("stage_" + label)
        (stage / "worlds").mkdir(parents=True)
        for file in ("camera_60hz.bin", "camera_timeline.json", "worlds/main_opaque.glb",
                     "worlds/main_animation.bin"):
            (stage / file).write_bytes(label.encode())
        manifest = {"source_blend": str(self.source), "source_sha256": self.sha,
                    "worlds": [{"world": "main", "glbs": {"opaque": "pending"}}]}
        (stage / "worlds" / "manifest.json").write_text(json.dumps(manifest))
        return stage, manifest

    def publish(self, label):
        stage, manifest = self.stage(label)
        return publication.publish_generation(stage, self.cache, manifest, "generic", self.source, self.sha)

    def assert_old(self):
        root = publication.active_root(self.cache)
        self.assertEqual(root.name, self.old["generation"])
        for file in ("camera_60hz.bin", "camera_timeline.json", "worlds/main_opaque.glb",
                     "worlds/main_animation.bin"):
            self.assertEqual((root / file).read_bytes(), b"old")

    def test_failures_at_each_preparation_write_preserve_old_generation(self):
        original = publication._json
        for name in ("manifest.json", "blend_sync_state.json", publication.MARKER):
            with self.subTest(step=name):
                stage, manifest = self.stage(name)
                def fail(path, value):
                    if path.name == name:
                        raise OSError("injected write failure")
                    return original(path, value)
                with patch.object(publication, "_json", side_effect=fail):
                    with self.assertRaises(OSError):
                        publication.publish_generation(stage, self.cache, manifest, "generic")
                self.assert_old()

    def test_generation_rename_failure_preserves_old(self):
        stage, manifest = self.stage("rename")
        original = Path.replace
        def fail(path, target):
            if path == stage:
                raise OSError("injected rename failure")
            return original(path, target)
        with patch.object(Path, "replace", fail):
            with self.assertRaises(OSError):
                publication.publish_generation(stage, self.cache, manifest, "generic")
        self.assert_old()

    def test_commit_and_recovery_pointer_failures_do_not_publish_orphans(self):
        original = publication._atomic_json
        for name in (publication.RECOVERY, publication.POINTER):
            with self.subTest(step=name):
                stage, manifest = self.stage(name)
                def fail(path, value):
                    if path.name == name:
                        raise OSError("injected pointer failure")
                    return original(path, value)
                with patch.object(publication, "_atomic_json", side_effect=fail):
                    with self.assertRaises(OSError):
                        publication.publish_generation(stage, self.cache, manifest, "generic")
                self.assert_old()

    def test_atomic_pointer_replace_failure_keeps_existing_pointer(self):
        original = publication.os.replace
        def fail(source, target):
            if Path(target).name == publication.POINTER:
                raise OSError("injected atomic replace failure")
            return original(source, target)
        with patch.object(publication.os, "replace", side_effect=fail):
            with self.assertRaises(OSError):
                self.publish("replace")
        self.assert_old()
        self.assertEqual(list(self.cache.glob("*.tmp")), [])

    def test_source_save_during_export_retains_last_good(self):
        self.source.write_bytes(b"new saved source")
        with self.assertRaisesRegex(RuntimeError, "source changed"):
            self.publish("changed_source")
        self.assert_old()

    def test_success_pins_all_paths_and_retains_previous(self):
        new = self.publish("new")
        root = publication.active_root(self.cache)
        self.assertEqual(root.name, new["generation"])
        self.assertEqual(Path(new["worlds"][0]["glbs"]["opaque"]).parent.parent, root)
        state = json.loads((root / "blend_sync_state.json").read_text())
        self.assertEqual(Path(state["camera_rail"]).parent, root)
        self.assertEqual(state["generation"], new["generation"])
        publication.verify_generation(self.cache, self.old["generation"])

    def test_corrupted_active_file_recovers_previous_complete_generation(self):
        new = self.publish("new")
        root = publication.generation_root(self.cache, new["generation"])
        (root / "camera_timeline.json").write_bytes(b"corrupt")
        self.assert_old()

    def test_corrupted_pointer_recovers_previous_never_orphan(self):
        self.publish("new")
        original = publication._atomic_json
        def fail(path, value):
            if path.name == publication.POINTER:
                raise OSError("failure")
            return original(path, value)
        with patch.object(publication, "_atomic_json", side_effect=fail):
            with self.assertRaises(OSError):
                self.publish("orphan")
        (self.cache / publication.POINTER).write_text("partial")
        # Recovery was advanced to the last complete current generation only.
        root = publication.active_root(self.cache)
        self.assertEqual((root / "camera_60hz.bin").read_bytes(), b"new")

    def test_incomplete_generation_and_path_escape_rejected(self):
        root = publication.active_root(self.cache)
        (root / "camera_timeline.json").unlink()
        with self.assertRaises(ValueError):
            publication.active_root(self.cache)
        with self.assertRaises(ValueError):
            publication.generation_root(self.cache, "../outside")


if __name__ == "__main__":
    unittest.main()

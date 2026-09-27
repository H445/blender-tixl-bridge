"""Export contract integration at the host's real cache reuse boundary."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "blender_tixl_bridge" / "source"))
import blend_sync
from export_contract import build_contract


class CacheValidityTest(unittest.TestCase):
    def fixture(self, root):
        blend, blender, texture = root / "Scene.blend", root / "blender.exe", root / "texture.png"
        for path, content in ((blend, b"saved scene"), (blender, b"runtime"), (texture, b"texture")):
            path.write_bytes(content)
        gltf = root / "gltf"
        gltf.mkdir()
        (gltf / "__init__.py").write_text("version = 1")
        cache = root / "cache"
        worlds = cache / "worlds"
        worlds.mkdir(parents=True)
        (cache / "camera_60hz.bin").write_bytes(b"camera")
        for suffix in ("animation.bin", "animation.json", "channels.json", "manifest.json", "opaque.glb"):
            (worlds / ("main_" + suffix)).write_bytes(b"data")
        contract = build_contract(blender, gltf, {"sampleRate": 60, "profile": "generic"}, [{"kind": "file", "path": str(texture)}])
        manifest = {"source_blend": str(blend), "source_sha256": blend_sync.digest(blend), "export_contract": contract,
                    "worlds": [{"world": "main", "glbs": {"opaque": "main_opaque.glb"}}]}
        (worlds / "manifest.json").write_text(json.dumps(manifest))
        (cache / "camera_timeline.json").write_text("{}")
        stage = root / "stage"
        cache.rename(stage)
        cache.mkdir()
        manifest = blend_sync.publish(stage, cache, manifest, "generic")
        return blend, blender, texture, cache, manifest

    def test_unchanged_valid_export_reuses_cache_without_starting_blender(self):
        with tempfile.TemporaryDirectory() as folder:
            blend, blender, texture, cache, manifest = self.fixture(Path(folder))
            with patch.object(blend_sync, "editor_running", return_value=False), \
                    patch.object(blend_sync, "generic_finish") as finish, \
                    patch.object(blend_sync.subprocess, "run") as worker:
                result = blend_sync.sync(blend, "generic", cache, blender, False, False)
                self.assertEqual(result["status"], "up_to_date")
                worker.assert_not_called()
                finish.assert_called_once()

    def test_external_resource_edit_invalidates_unchanged_saved_scene(self):
        with tempfile.TemporaryDirectory() as folder:
            blend, blender, texture, cache, manifest = self.fixture(Path(folder))
            sha = blend_sync.digest(blend)
            self.assertTrue(blend_sync.valid_cache(cache, sha, blender))
            texture.write_bytes(b"changed")  # Same byte length; content matters.
            self.assertEqual(blend_sync.digest(blend), sha)
            self.assertFalse(blend_sync.valid_cache(cache, sha, blender))

    def test_legacy_and_incomplete_cache_cannot_be_reused(self):
        with tempfile.TemporaryDirectory() as folder:
            blend, blender, texture, cache, manifest = self.fixture(Path(folder))
            sha = blend_sync.digest(blend)
            (blend_sync.active_root(cache) / "worlds" / "main_opaque.glb").unlink()
            self.assertFalse(blend_sync.valid_cache(cache, sha, blender))
            # Corrupt committed payloads always fail generation verification.
            manifest.pop("export_contract")
            (cache / "legacy_manifest.json").write_text(json.dumps(manifest))
            self.assertFalse(blend_sync.valid_cache(cache, sha, blender))


if __name__ == "__main__":
    unittest.main()

"""Two-generation editable-project installation and binding rollback."""
import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "blender_tixl_bridge" / "source"))
import blend_sync
import cache_bindings
from blend_sync_graph import generate


class BindingTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.cache = self.root / "cache"
        self.cache.mkdir()
        self.blend = self.root / "scene.blend"
        self.blend.write_bytes(b"saved scene")
        self.template = self.root / "Operators"
        self.template.mkdir()
        (self.template / "Operators.csproj").write_text(
            "<Project><RootNamespace>X</RootNamespace><HomeGuid>X</HomeGuid><PackageId>X</PackageId></Project>")
        self.project = self.root / "GenerationExample"
        self.old = self.export("old")
        self.install(self.old)

    def export(self, label):
        stage = self.root / label
        (stage / "worlds").mkdir(parents=True)
        (stage / "camera_timeline.json").write_text(json.dumps({
            "shots": [{"id": 1, "start": 0, "label": "Cube"}], "passages": []}))
        (stage / "camera_60hz.bin").write_bytes(b"camera")
        for name in ("main_opaque.glb", "main_animation.bin"):
            (stage / "worlds" / name).write_bytes(label.encode())
        manifest = {"source_blend": str(self.blend), "source_sha256": blend_sync.digest(self.blend),
                    "fps": 60, "project_name": "GenerationExample", "worlds": [{
                        "world": "main", "active_clip": [1, 241], "opaque_count": 1,
                        "glass_count": 0, "glbs": {"opaque": "pending"}}]}
        return blend_sync.publish(stage, self.cache, manifest, "generic")

    def install(self, manifest):
        files = generate(self.blend, self.cache, manifest)
        with patch.object(blend_sync, "TIXL_PROJECT", self.template), \
                patch.object(blend_sync, "TIXL_EDITOR", self.root):
            blend_sync.ensure_generic_project(self.blend, self.cache, files, build=False, manifest=manifest)

    def test_second_generation_updates_home_scene_and_nested_paths_preserving_edits(self):
        home_path = self.project / "Symbols" / "GenerationExample.t3"
        home = json.loads(home_path.read_text())
        clip = next(child for child in home["Children"] if child["SymbolName"].endswith("BlenderSourceClip"))
        clip["Name"] = "My edited clip"
        clip["UserNote"] = "keep timing"
        home["UserMetadata"] = {"keep": True}
        home_path.write_text(json.dumps(home))
        nested_path = self.project / "Symbols" / "Nested.t3"
        nested = copy.deepcopy(home)
        nested["Id"] = "nested-id"
        nested_path.write_text(json.dumps(nested))
        before = {path: json.loads(path.read_text()) for path in (home_path, nested_path)}
        ui_before = (self.project / "Symbols" / "GenerationExample.t3ui").read_bytes()
        new = self.export("new")
        self.install(new)
        for path in (home_path, nested_path, self.project / "Symbols" / "GenerationExampleScene.t3"):
            text = path.read_text()
            self.assertIn(new["generation"], text)
            self.assertNotIn(self.old["generation"], text)
        for path, original in before.items():
            updated = json.loads(path.read_text())
            # Apart from managed path values, every editable graph field survives.
            normalized = json.loads(json.dumps(updated).replace(new["generation"], self.old["generation"]))
            self.assertEqual(normalized, original)
        self.assertEqual((self.project / "Symbols" / "GenerationExample.t3ui").read_bytes(), ui_before)

    def test_custom_external_file_path_is_preserved(self):
        home_path = self.project / "Symbols" / "GenerationExample.t3"
        home = json.loads(home_path.read_text())
        child = next(child for child in home["Children"] if child["SymbolName"].endswith("LoadGltfScene"))
        item = next(item for item in child["InputValues"] if item["Id"] in cache_bindings.PATH_INPUTS["LoadGltfScene"])
        custom = str(self.root / "custom.glb")
        item["Value"] = custom
        home_path.write_text(json.dumps(home))
        self.install(self.export("new"))
        self.assertIn(custom.replace("\\", "\\\\"), home_path.read_text())

    def test_write_failure_rolls_back_all_applied_symbols(self):
        new = self.export("new")
        symbols = self.project / "Symbols"
        original = {path: path.read_bytes() for path in symbols.rglob("*.t3")}
        replace = cache_bindings.os.replace
        count = 0
        def fail(source, target):
            nonlocal count
            count += 1
            if count == 2:
                raise OSError("injected binding write failure")
            return replace(source, target)
        with patch.object(cache_bindings.os, "replace", side_effect=fail):
            with self.assertRaises(OSError):
                cache_bindings.rebind_project_paths(self.project, self.cache, new["generation"])
        self.assertEqual({path: path.read_bytes() for path in original}, original)
        self.assertEqual(list(symbols.rglob("*.tmp")), [])


if __name__ == "__main__":
    unittest.main()

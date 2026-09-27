"""Tests for export-cache toolchain and external-input evidence."""
import sys
import ast
import os
import re
from types import SimpleNamespace
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "blender_tixl_bridge" / "source"))
from export_contract import build_contract, valid_contract
import export_contract


class ExportContractTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        # Windows runners can expose TEMP through an 8.3 alias. Keep fixture
        # paths consistent with the resolved glob paths used by these mocks.
        self.root = Path(self.temp.name).resolve()
        self.blender = self.root / "blender.exe"
        self.blender.write_bytes(b"binary-v1")
        self.source = self.root / "source"
        self.source.mkdir()
        for name in ("export_contract.py", "blend_sync_worker.py", "tixl_animation_export.py", "animation_writer.py"):
            (self.source / name).write_text(f"# {name} v1\n", encoding="utf-8")
        self.gltf = self.root / "gltf"
        (self.gltf / "nested").mkdir(parents=True)
        (self.gltf / "__init__.py").write_text("# package v1\n", encoding="utf-8")
        (self.gltf / "nested" / "exporter.py").write_text("# module v1\n", encoding="utf-8")
        self.texture = self.root / "texture.png"
        self.texture.write_bytes(b"texture-v1")
        self.sequence = self.root / "tiles"
        self.sequence.mkdir()
        (self.sequence / "tile_1001.exr").write_bytes(b"tile-a")
        self.settings = {"quality": "default"}
        self.specs = [
            {"kind": "file", "path": str(self.texture.resolve())},
            {"kind": "glob", "path": str((self.sequence / "tile_*.exr").resolve())},
        ]

    def contract(self, settings=None, specs=None):
        return build_contract(self.blender, self.gltf,
                              self.settings if settings is None else settings,
                              self.specs if specs is None else specs,
                              source_dir=self.source)

    def valid(self, contract):
        return valid_contract(contract, self.blender, source_dir=self.source)

    def test_unchanged_inputs_are_reusable(self):
        contract = self.contract()
        self.assertTrue(contract["reusable"])
        self.assertTrue(self.valid(contract))
        self.assertEqual(contract["sampleRate"], 60)
        self.assertEqual(contract["profile"], "generic")

    def test_retargeted_dependency_alias_invalidates_contract(self):
        # Model link resolution independently of Windows symlink privileges.
        alias = self.root / "asset-alias.png"
        alias.write_bytes(b"placeholder")
        target = self.texture
        original = export_contract._resolved_file

        def resolve(path):
            return original(target if Path(path) == alias else path)

        with patch.object(export_contract, "_resolved_file", side_effect=resolve):
            contract = self.contract(specs=[{"kind": "file", "path": str(alias)}])
            self.assertEqual(contract["dependencies"]["specs"][0]["path"], str(alias))
            self.assertTrue(self.valid(contract))
            target = self.root / "replacement.png"
            target.write_bytes(self.texture.read_bytes())
            self.assertFalse(self.valid(contract))

    def test_sequence_collector_normalizes_parent_segments_without_resolving(self):
        worker = Path(export_contract.__file__).with_name("blend_sync_worker.py")
        tree = ast.parse(worker.read_text(encoding="utf-8"))
        function = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                        and node.name == "external_dependency_specs")
        declared = str(self.root / "subfolder" / ".." / "img0001.png")
        normalized = os.path.normpath(declared)
        image = SimpleNamespace(source="SEQUENCE", filepath=declared, library=None)
        bpy = SimpleNamespace(utils=SimpleNamespace(blend_paths=lambda **kwargs: [normalized]),
                              data=SimpleNamespace(images=[image]),
                              path=SimpleNamespace(abspath=lambda value, **kwargs: value))
        namespace = {"Path": Path, "os": os, "re": re, "bpy": bpy}
        exec(compile(ast.Module(body=[function], type_ignores=[]), str(worker), "exec"), namespace)
        rows = namespace["external_dependency_specs"]()
        self.assertEqual(rows, [{"kind": "glob", "path": str(self.root / ("img" + "[0-9]" * 4 + ".png"))}])

    def test_swapped_sequence_alias_targets_invalidate_contract(self):
        first = self.sequence / "tile_1001.exr"
        second = self.sequence / "tile_1002.exr"
        second.write_bytes(b"tile-b")
        targets = [self.texture, self.blender]
        original = export_contract._resolved_file
        swapped = False
        def resolve(path):
            if path in (first, second):
                index = int(path == second) ^ int(swapped)
                return original(targets[index])
            return original(path)
        with patch.object(export_contract, "_resolved_file", side_effect=resolve):
            contract = self.contract()
            self.assertTrue(self.valid(contract))
            swapped = True
            self.assertFalse(self.valid(contract))

    def test_export_source_changes_invalidate_contract(self):
        contract = self.contract()
        path = self.source / "tixl_animation_export.py"
        path.write_text("# exporter changed\n", encoding="utf-8")
        self.assertFalse(self.valid(contract))

    def test_matrix_writer_changes_invalidate_contract(self):
        contract = self.contract()
        path = self.source / "animation_writer.py"
        before = path.stat()
        payload = path.read_bytes()
        path.write_bytes(payload.replace(b"v1", b"v2"))
        os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
        self.assertFalse(self.valid(contract))

    def test_settings_change_changes_contract_fingerprint(self):
        original = self.contract({"quality": "default"})
        changed = self.contract({"quality": "high"})
        self.assertNotEqual(original["settings"], changed["settings"])
        self.assertTrue(self.valid(original))
        self.assertTrue(self.valid(changed))

    def test_settings_tampering_fails_closed(self):
        contract = self.contract()
        contract["settings"]["values"]["quality"] = "high"
        self.assertFalse(self.valid(contract))

    def test_graph_or_operator_edits_are_outside_export_contract(self):
        contract = self.contract()
        graph = self.root / "BridgeTemplate.t3"
        operator = self.root / "BlenderMeshSelect.cs"
        graph.write_text("graph v1", encoding="utf-8")
        operator.write_text("operator v1", encoding="utf-8")
        graph.write_text("graph v2", encoding="utf-8")
        operator.write_text("operator v2", encoding="utf-8")
        self.assertTrue(self.valid(contract))

    def test_blender_content_or_resolved_path_change_invalidates(self):
        contract = self.contract()
        self.blender.write_bytes(b"binary-v2")
        self.assertFalse(self.valid(contract))
        self.blender.write_bytes(b"binary-v1")
        other_blender = self.root / "other-blender.exe"
        other_blender.write_bytes(b"binary-v1")
        self.assertFalse(valid_contract(contract, other_blender, source_dir=self.source))

    def test_gltf_exporter_content_and_tree_membership_invalidate(self):
        contract = self.contract()
        module = self.gltf / "nested" / "exporter.py"
        module.write_text("# module changed\n", encoding="utf-8")
        self.assertFalse(self.valid(contract))
        contract = self.contract()
        added = self.gltf / "new_module.py"
        added.write_text("# added module\n", encoding="utf-8")
        self.assertFalse(self.valid(contract))
        added.unlink()
        self.assertTrue(self.valid(contract))

    def test_dependency_same_size_content_change_invalidates(self):
        contract = self.contract()
        self.texture.write_bytes(b"texture-v2")
        self.assertEqual(len(self.texture.read_bytes()), len(b"texture-v1"))
        self.assertFalse(self.valid(contract))

    def test_glob_membership_addition_and_removal_invalidate(self):
        contract = self.contract()
        added = self.sequence / "tile_1002.exr"
        added.write_bytes(b"tile-b")
        self.assertFalse(self.valid(contract))
        added.unlink()
        self.assertTrue(self.valid(contract))
        contract = self.contract()
        (self.sequence / "tile_1001.exr").unlink()
        self.assertFalse(self.valid(contract))

    def test_missing_and_unsupported_dependencies_disable_reuse_but_stable_export_can_publish(self):
        missing = self.root / "absent.exr"
        specs = [
            {"kind": "file", "path": str(missing.resolve())},
            {"kind": "unsupported", "path": str(self.root / "sequence.udim")},
        ]
        contract = self.contract(specs=specs)
        self.assertFalse(contract["reusable"])
        self.assertFalse(self.valid(contract))
        self.assertTrue(valid_contract(contract, self.blender, source_dir=self.source,
                                       require_reusable=False))
        (self.root / "absent.exr").write_bytes(b"now present")
        self.assertFalse(valid_contract(contract, self.blender, source_dir=self.source,
                                        require_reusable=False))

    def test_invalid_settings_or_missing_toolchain_cannot_reuse(self):
        bad_rate = self.contract({"sampleRate": 30})
        bad_profile = self.contract({"profile": "custom"})
        self.assertFalse(bad_rate["reusable"])
        self.assertFalse(bad_profile["reusable"])
        self.assertFalse(valid_contract(bad_rate, self.blender, source_dir=self.source,
                                        require_reusable=False))
        (self.source / "blend_sync_worker.py").unlink()
        missing_source = self.contract()
        self.assertFalse(missing_source["reusable"])
        self.assertFalse(valid_contract(missing_source, self.blender, source_dir=self.source,
                                        require_reusable=False))

    def test_unknown_or_malformed_contract_fails_without_raising(self):
        self.assertFalse(self.valid({"schema": 999}))
        self.assertFalse(self.valid(None))
        contract = self.contract()
        contract["dependencies"] = {"reusable": True, "specs": "invalid"}
        self.assertFalse(self.valid(contract))

    def test_partially_unreadable_tile_family_is_not_reusable(self):
        inaccessible = self.sequence / "tile_1002.exr"
        inaccessible.write_bytes(b"unreadable")
        original = export_contract._resolved_file
        def read(path):
            return None if path == inaccessible else original(path)
        with patch.object(export_contract, "_resolved_file", side_effect=read):
            contract = self.contract()
            self.assertFalse(contract["dependencies"]["reusable"])
            self.assertFalse(self.valid(contract))

    def test_empty_gltf_implementation_cannot_reuse_or_publish(self):
        for path in self.gltf.rglob("*.py"):
            path.unlink()
        contract = self.contract()
        self.assertFalse(self.valid(contract))
        self.assertFalse(valid_contract(contract, self.blender, source_dir=self.source, require_reusable=False))


if __name__ == "__main__":
    unittest.main()

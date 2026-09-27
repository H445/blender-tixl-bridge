"""Loaded structural changes must not be trusted after an editor reload."""
import copy
import hashlib
import json
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "blender_tixl_bridge" / "source"))
import blend_sync


class GraphActivationTest(unittest.TestCase):
    def fixture(self, root):
        operators, editor, cache, project = (root / name for name in ("Operators", "Editor", "cache", "Scene"))
        target = operators / "Symbols" / "PrismalLabs" / "BlenderExport"
        for path in (target, editor, cache, project):
            path.mkdir(parents=True)
        (operators / "Operators.csproj").write_text("<Project />")
        (project / "Symbols").mkdir()
        (project / "Symbols" / "Scene.t3").write_text(json.dumps({"Id": "home-id", "Children": [], "Connections": []}))
        for path in (blend_sync.ROOT / "operators").glob("Blender*.*"):
            shutil.copy2(path, target / path.name)
        files = [cache / f"generated{index}.json" for index in range(4)]
        for path in files:
            path.write_text("{}")
        graph_sha = hashlib.sha256(("world-clip-lanes-v6|" + "|".join(blend_sync.digest(path) for path in files)).encode()).hexdigest()
        (cache / "tixl_project.json").write_text(json.dumps({"name": "Scene", "path": str(project), "graph_sha256": graph_sha}))
        return operators, editor, cache, project, target, files

    def run_live_finish(self, root, fixture):
        operators, editor, cache, project, target, files = fixture
        with ExitStack() as stack:
            stack.enter_context(patch.dict(os.environ, {"TIXL_BRIDGE_OPERATOR_PROJECT": str(operators), "TIXL_BRIDGE_EDITOR": str(editor)}))
            for name, value in (("TIXL_PROJECT", operators), ("TIXL_EDITOR", editor), ("MODE", "debug")):
                stack.enter_context(patch.object(blend_sync, name, value))
            stack.enter_context(patch("blend_sync_graph.generate", return_value=files))
            stack.enter_context(patch.object(blend_sync, "wait_for_editor_pause"))
            stack.enter_context(patch.object(blend_sync, "editor_running", return_value=True))
            stack.enter_context(patch.object(blend_sync, "bridge_available", return_value=True))
            bridge = stack.enter_context(patch.object(blend_sync, "bridge_call", return_value={"symbolId": "home-id", "children": [], "connections": []}))
            populate = stack.enter_context(patch.object(blend_sync, "ensure_generic_project"))
            verify = stack.enter_context(patch.object(blend_sync, "verify_project_graph"))
            before = {str(path): path.read_bytes() for folder in (operators, project) for path in folder.rglob("*") if path.is_file()}
            if self.defer:
                with self.assertRaisesRegex(RuntimeError, "save your editor work, close TiXL manually"):
                    blend_sync.generic_finish(root / "Scene.blend", cache, {}, True, refresh_runtime=True)
                bridge.assert_not_called()
                populate.assert_not_called()
                verify.assert_not_called()
                after = {str(path): path.read_bytes() for folder in (operators, project) for path in folder.rglob("*") if path.is_file()}
                self.assertEqual(before, after)
            else:
                blend_sync.generic_finish(root / "Scene.blend", cache, {}, True, refresh_runtime=True)
                self.assertTrue(any(call.args == ("reload",) for call in bridge.call_args_list))
                verify.assert_called_once_with("Scene", live_states={"home-id": {"symbolId": "home-id", "children": [], "connections": []}})
                self.assertFalse(any(call.args == ("openProject",) for call in bridge.call_args_list))

    def test_generated_structure_change_is_deferred_even_with_live_paused_editor(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            fixture = self.fixture(root)
            fixture[-1][0].write_text('{"changed": true}')
            self.defer = True
            self.run_live_finish(root, fixture)

    def test_operator_t3_and_ui_changes_are_deferred_without_mutation(self):
        for suffix in (".t3", ".t3ui"):
            with self.subTest(suffix=suffix), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                fixture = self.fixture(root)
                (fixture[4] / ("BlenderAnimationScene" + suffix)).write_text("old structure")
                self.defer = True
                self.run_live_finish(root, fixture)

    def test_data_only_refresh_uses_live_reload_and_readback(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.defer = False
            self.run_live_finish(root, self.fixture(root))

    def test_code_only_update_uses_live_reload_and_readback(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            fixture = self.fixture(root)
            (fixture[4] / "BlenderAnimationScene.cs").write_text("old code")
            self.defer = False
            self.run_live_finish(root, fixture)

    def test_readback_checks_home_and_generated_imports_and_rejects_stale_graphs(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            symbols = root / "Scene" / "Symbols"
            imports = symbols / "PrismalLabs" / "BlenderExport" / "Generated"
            imports.mkdir(parents=True)
            expected = {"Id": "home-id", "Children": [{"Id": "child-id", "SymbolId": "type-id"}],
                        "Connections": [{"SourceParentOrChildId": "child-id", "SourceSlotId": "out-id", "TargetParentOrChildId": "child-id", "TargetSlotId": "in-id"}]}
            expected["Connections"].append({"SourceParentOrChildId": "child-id", "SourceSlotId": "out-two", "TargetParentOrChildId": "child-id", "TargetSlotId": "in-id"})
            (symbols / "Scene.t3").write_text(json.dumps(expected))
            imported = copy.deepcopy(expected)
            imported["Id"] = "import-id"
            (imports / "Import.t3").write_text(json.dumps(imported))
            archived = copy.deepcopy(imported)
            archived["Id"] = "unused-id"
            (imports / "Archived.t3").write_text(json.dumps(archived))
            expected["Children"].append({"Id": "import-ref", "SymbolId": "import-id"})
            (symbols / "Scene.t3").write_text(json.dumps(expected))
            actual = {"symbolId": "home-id", "children": [{"childId": "child-id", "symbolId": "type-id"}],
                      "connections": [{key[0].lower() + key[1:]: value for key, value in edge.items()} for edge in expected["Connections"]]}
            actual["children"].append({"childId": "import-ref", "symbolId": "import-id"})
            def response(method, **kwargs):
                if method == "pumpFrames":
                    return {}
                self.assertNotEqual(kwargs["compositionId"], "unused-id")
                state = copy.deepcopy(actual)
                state["symbolId"] = kwargs["compositionId"]
                if kwargs["compositionId"] == "import-id":
                    state["children"] = state["children"][:1]
                return state
            with patch.object(blend_sync, "TIXL_PROJECT", root / "Operators"), \
                    patch.object(blend_sync, "bridge_call", side_effect=response) as bridge:
                blend_sync.verify_project_graph("Scene")
                self.assertEqual([c.kwargs.get("compositionId") for c in bridge.call_args_list[1:]], ["home-id", "import-id"])
                # Unsaved additions and routes are accepted on live refresh,
                # provided reload preserves the exact pre-refresh state.
                actual["children"].append({"childId": "user-added", "symbolId": "user-type", "inputs": [{"id": "user-input", "value": 3}]})
                before = copy.deepcopy(actual)
                def live_response(method, **kwargs):
                    state = response(method, **kwargs)
                    if method == "getGraphState" and kwargs["compositionId"] == "import-id":
                        state["children"] = state["children"][:1]
                    return state
                bridge.side_effect = live_response
                blend_sync.verify_project_graph("Scene", home_state=before)
                actual["children"][-1]["inputs"][0]["value"] = 4
                with self.assertRaisesRegex(RuntimeError, "changed user graph state"):
                    blend_sync.verify_project_graph("Scene", home_state=before)
                actual["children"] = actual["children"][:2]
                bridge.side_effect = response
                before = copy.deepcopy(actual)
                actual["connections"].reverse()
                with self.assertRaisesRegex(RuntimeError, "graph activation failed"):
                    blend_sync.verify_project_graph("Scene", home_state=before)
                actual["connections"].reverse()
                for damage in ("symbol", "child", "edge", "duplicate_edge", "reverse_edges", "unresolved_child", "unresolved_edge"):
                    with self.subTest(damage=damage):
                        def broken(method, **kwargs):
                            state = response(method, **kwargs)
                            if method == "getGraphState":
                                if damage == "symbol": state["symbolId"] = "wrong-id"
                                if damage == "child": state["children"][0]["symbolId"] = "old-type"
                                if damage == "edge": state["connections"] = []
                                if damage == "duplicate_edge": state["connections"] *= 2
                                if damage == "reverse_edges": state["connections"].reverse()
                                if damage == "unresolved_child": state["missingChildren"] = [{"childId": "missing"}]
                                if damage == "unresolved_edge": state["missingConnections"] = [{}]
                            return state
                        bridge.side_effect = broken
                        with self.assertRaisesRegex(RuntimeError, "graph activation failed"):
                            blend_sync.verify_project_graph("Scene")
                        bridge.side_effect = response

    def test_startup_does_not_report_success_without_graph_readback(self):
        with patch.object(blend_sync, "open_project") as opened, \
                patch.object(blend_sync, "verify_project_graph", side_effect=RuntimeError("stale structure")), \
                patch.object(blend_sync.time, "sleep"):
            with self.assertRaisesRegex(RuntimeError, "could not open generated project"):
                blend_sync.open_project_when_ready("Scene")
            self.assertEqual(opened.call_count, 45)

    def test_live_refresh_preserves_unsaved_nested_user_compound(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            symbols = root / "Scene" / "Symbols"
            symbols.mkdir(parents=True)
            home = {"Id": "home-id", "Children": [{"Id": "compound-child", "SymbolId": "compound-id"}], "Connections": []}
            compound = {"Id": "compound-id", "Children": [], "Connections": []}
            (symbols / "Scene.t3").write_text(json.dumps(home))
            (symbols / "UserCompound.t3").write_text(json.dumps(compound))
            states = {
                "home-id": {"symbolId": "home-id", "children": [{"childId": "compound-child", "symbolId": "compound-id"}], "connections": []},
                "compound-id": {"symbolId": "compound-id", "children": [{"childId": "unsaved-child", "symbolId": "native-op", "inputs": [{"id": "value", "value": 42}]}], "connections": []},
            }
            def response(method, **kwargs):
                return copy.deepcopy(states[kwargs["compositionId"]]) if method == "getGraphState" else {}
            with patch.object(blend_sync, "TIXL_PROJECT", root / "Operators"), \
                    patch.object(blend_sync, "bridge_call", side_effect=response):
                baseline = blend_sync.capture_project_graph("Scene")
                self.assertEqual(set(baseline), {"home-id", "compound-id"})
                blend_sync.verify_project_graph("Scene", live_states=baseline)
                self.assertEqual(json.loads((symbols / "UserCompound.t3").read_text()), compound)
                states["compound-id"]["children"][0]["inputs"][0]["value"] = 0
                with self.assertRaisesRegex(RuntimeError, "changed user graph state"):
                    blend_sync.verify_project_graph("Scene", live_states=baseline)



if __name__ == "__main__":
    unittest.main()

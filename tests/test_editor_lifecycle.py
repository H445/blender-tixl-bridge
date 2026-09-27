"""Safety regressions for automatic sync with an editor of unknown save state."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "blender_tixl_bridge" / "source"))
import blend_sync


class EditorLifecycleTest(unittest.TestCase):
    def test_running_editor_requires_manual_saved_work_handoff(self):
        with patch.object(blend_sync, "editor_running", return_value=True), \
                patch.object(blend_sync.subprocess, "run") as run, \
                patch.object(blend_sync, "bridge_call") as bridge:
            with self.assertRaisesRegex(RuntimeError, "save your editor work, close TiXL manually"):
                blend_sync.require_editor_closed()
            run.assert_not_called()
            bridge.assert_not_called()  # No shutdown: save state is unknown.

    def test_already_closed_editor_needs_no_shutdown(self):
        with patch.object(blend_sync, "editor_running", return_value=False), \
                patch.object(blend_sync.subprocess, "run") as run:
            blend_sync.require_editor_closed()
            run.assert_not_called()

    def test_unavailable_debug_bridge_hands_off_without_closing(self):
        with patch.object(blend_sync, "editor_running", return_value=True), \
                patch.object(blend_sync, "bridge_available", return_value=False), \
                patch.object(blend_sync.subprocess, "run") as run:
            with self.assertRaisesRegex(RuntimeError, "Save your editor work and close TiXL manually"):
                blend_sync.wait_for_editor_pause()
            run.assert_not_called()

    def test_paused_live_editor_does_not_trigger_shutdown(self):
        with patch.object(blend_sync, "editor_running", return_value=True), \
                patch.object(blend_sync, "bridge_available", return_value=True), \
                patch.object(blend_sync, "bridge_call", return_value={"time": {"isPlaying": False}}) as bridge:
            blend_sync.wait_for_editor_pause()
            self.assertEqual(bridge.call_args.args, ("getContext",))

    def test_install_deferred_before_operator_or_project_changes_then_retried(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            project, editor, cache = (root / name for name in ("Operators", "Editor", "cache"))
            for path in (project / "Symbols", editor, cache):
                path.mkdir(parents=True)
            (project / "Operators.csproj").write_text("<Project />")
            sentinel = project / "Symbols" / "UserGraph.t3"
            sentinel.write_text("user-owned work")
            files = []
            for index in range(4):
                path = cache / f"generated{index}.json"
                path.write_text("{}")
                files.append(path)
            # Existing validated cache/project state must survive the handoff.
            marker = cache / "tixl_project.json"
            marker.write_text(json.dumps({"name": "Scene", "path": str(project), "graph_sha256": "old"}))
            prior_marker = marker.read_bytes()
            with patch.dict(os.environ, {"TIXL_BRIDGE_OPERATOR_PROJECT": str(project), "TIXL_BRIDGE_EDITOR": str(editor)}), \
                    patch.object(blend_sync, "TIXL_PROJECT", project), \
                    patch.object(blend_sync, "TIXL_EDITOR", editor), \
                    patch.object(blend_sync, "wait_for_editor_pause"), \
                    patch("blend_sync_graph.generate", return_value=files), \
                    patch.object(blend_sync, "bridge_available", return_value=False), \
                    patch.object(blend_sync, "editor_running", return_value=True) as running, \
                    patch.object(blend_sync, "ensure_generic_project") as populate, \
                    patch.object(blend_sync.subprocess, "run") as run, \
                    patch.object(blend_sync, "start_editor", return_value=True) as start:
                with self.assertRaisesRegex(RuntimeError, "installation deferred"):
                    blend_sync.generic_finish(root / "Scene.blend", cache, {}, True)
                populate.assert_not_called()
                run.assert_not_called()
                start.assert_not_called()
                self.assertEqual(marker.read_bytes(), prior_marker)
                self.assertEqual(list((project / "Symbols").iterdir()), [sentinel])
                # The user's manual close is authoritative; retry can install.
                running.return_value = False
                blend_sync.generic_finish(root / "Scene.blend", cache, {}, True)
                populate.assert_called_once()
                self.assertEqual(run.call_args.args[0][:2], ["dotnet", "build"])
                start.assert_called_once()
                self.assertEqual(sentinel.read_text(), "user-owned work")

    def test_failed_install_does_not_launch_editor(self):
        # Covered using the same real installation path with a controlled build failure.
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            project, cache = root / "Operators", root / "cache"
            (project / "Symbols").mkdir(parents=True)
            cache.mkdir()
            (project / "Operators.csproj").write_text("<Project />")
            files = [cache / str(index) for index in range(4)]
            for path in files:
                path.write_text("{}")
            with patch.dict(os.environ, {"TIXL_BRIDGE_OPERATOR_PROJECT": str(project), "TIXL_BRIDGE_EDITOR": str(root)}), \
                    patch.object(blend_sync, "TIXL_PROJECT", project), \
                    patch.object(blend_sync, "TIXL_EDITOR", root), \
                    patch.object(blend_sync, "wait_for_editor_pause"), \
                    patch("blend_sync_graph.generate", return_value=files), \
                    patch.object(blend_sync, "bridge_available", return_value=False), \
                    patch.object(blend_sync, "editor_running", return_value=False), \
                    patch.object(blend_sync.subprocess, "run", side_effect=RuntimeError("build failed")), \
                    patch.object(blend_sync, "start_editor") as start:
                with self.assertRaisesRegex(RuntimeError, "build failed"):
                    blend_sync.generic_finish(root / "Scene.blend", cache, {}, True)
                start.assert_not_called()


if __name__ == "__main__":
    unittest.main()

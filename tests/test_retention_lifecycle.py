"""Recovery references and log ownership take precedence over storage limits."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "blender_tixl_bridge" / "source"))
from logged_process import BoundedLog, run_to_log
from process_lock import process_lock
from retention_lifecycle import atomic_json, cleanup, new_backup, retention_run, track_generation, track_stage


class RetentionLifecycleTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.cache = Path(temp.name).resolve() / "cache"
        self.cache.mkdir()
        self.policy = {key: {"max_count": 0, "max_bytes": 0, "max_age_days": 0}
                       for key in ("generations", "backups", "staging", "reports", "logs")}
        atomic_json(self.cache / "retention_policy.json", self.policy)

    def generation(self, number):
        name = f"{number:032x}"
        root = self.cache / "generations" / name
        (root / "worlds").mkdir(parents=True)
        (root / "export.log").write_text("failure detail " + name)
        atomic_json(root / "worlds" / "manifest.json", {"generation": name})
        atomic_json(root / "generation_commit.json", {"schema": 1, "generation": name,
                                                     "files": {"export.log": {"size": 1}}})
        return name

    def test_active_previous_failed_and_saved_graph_references_survive_zero_budget(self):
        names = [self.generation(i) for i in range(1, 7)]
        atomic_json(self.cache / "current_generation.json", {"schema": 1, "generation": names[5], "previous": names[4]})
        atomic_json(self.cache / "previous_generation.json", {"schema": 1, "generation": names[4]})
        atomic_json(self.cache / "sync_logs" / "failed_run.json", {"schema": 1, "status": "failed", "runId": "failed", "generation": names[1], "backups": []})
        project = self.cache.parent / "UserProject"
        graph = project / "Symbols" / "Home.t3"
        atomic_json(graph, {"TimeClips": [{"StartTime": 4, "Duration": 12}],
                            "Children": [{"InputValues": [{"Value": str(self.cache / "generations" / names[2] / "worlds" / "mesh.glb")}]}]})
        original = graph.read_bytes()
        atomic_json(self.cache / "tixl_project.json", {"path": str(project)})
        report = cleanup(self.cache, editor_is_running=False)
        kept = {path.name for path in (self.cache / "generations").iterdir()}
        self.assertEqual(kept, set(names[1:3] + names[4:6]))
        self.assertEqual(graph.read_bytes(), original)
        self.assertGreater(report["categories"]["generations"]["budgetExceeded"]["count"], 0)

    def test_retained_backup_reference_protects_generation_and_legacy_backup_is_not_deleted(self):
        names = [self.generation(i) for i in range(1, 4)]
        backup = new_backup(self.cache / "project_backups", "home")
        atomic_json(backup / "Home.t3", {"Value": str(self.cache / "generations" / names[0] / "mesh.glb")})
        legacy = self.cache / "project_backups" / "20200101_000000"
        legacy.mkdir()
        (legacy / "Home.t3").write_text("{}")
        report = cleanup(self.cache, editor_is_running=False)
        self.assertTrue((self.cache / "generations" / names[0]).is_dir())
        self.assertTrue(legacy.is_dir())
        self.assertEqual(report["categories"]["backups"]["kept"], [backup.name])

    def test_open_editor_and_unreadable_saved_graph_both_defer_generation_deletion(self):
        names = [self.generation(i) for i in range(1, 4)]
        report = cleanup(self.cache, editor_is_running=True)
        self.assertEqual(report["categories"]["generations"]["status"], "deferred")
        self.assertEqual(len(list((self.cache / "generations").iterdir())), 3)
        project = self.cache.parent / "project"
        (project / "Symbols").mkdir(parents=True)
        (project / "Symbols" / "Home.t3").write_text("broken graph")
        atomic_json(self.cache / "tixl_project.json", {"path": str(project)})
        with self.assertRaises(ValueError):
            cleanup(self.cache, editor_is_running=False)
        self.assertTrue(all((self.cache / "generations" / name).is_dir() for name in names))

    def test_failed_run_preserves_stage_log_original_exception_and_previous_success(self):
        atomic_json(self.cache / "sync_logs" / "last_successful_run.json", {"schema": 1, "status": "passed", "runId": "prior", "backups": []})
        error = RuntimeError("original export failed")
        stage = self.cache / ".staging" / ("f" * 32)
        stage.mkdir(parents=True)
        with self.assertRaises(RuntimeError) as caught:
            with retention_run(self.cache, "failed", editor_is_running=lambda: False):
                track_stage(stage)
                (stage / "export.log").write_text("useful worker error")
                raise error
        self.assertIs(caught.exception, error)
        failed = json.loads((self.cache / "sync_logs" / "failed_run.json").read_text())
        self.assertEqual(Path(failed["exportLog"]).read_text(), "useful worker error")
        self.assertEqual(json.loads((self.cache / "sync_logs" / "last_successful_run.json").read_text())["runId"], "prior")

    def test_cleanup_failure_cannot_replace_sync_result_or_original_exception(self):
        with patch("retention_lifecycle.cleanup", side_effect=OSError("inaccessible evidence")):
            with retention_run(self.cache, "passed", editor_is_running=lambda: False):
                pass
            self.assertEqual(json.loads((self.cache / "sync_logs" / "retention.json").read_text())["status"], "deferred")
            error = ValueError("original")
            with self.assertRaises(ValueError) as caught:
                with retention_run(self.cache, "failed", editor_is_running=lambda: False):
                    raise error
            self.assertIs(caught.exception, error)

    def test_running_log_writer_lease_defers_log_deletion(self):
        folder = self.cache / "sync_logs"
        folder.mkdir()
        for i in range(3):
            (folder / (f"{i:032x}" + ".log")).write_text("evidence")
        with patch.dict(os.environ, {"TIXL_LOG_GROUP_LOCK": ""}):
            with process_lock(folder / ".logging.process.lock"):
                report = cleanup(self.cache, editor_is_running=False)
        self.assertEqual(report["categories"]["logs"]["status"], "deferred")
        self.assertEqual(len(list(folder.glob("*.log"))), 3)

    def test_malformed_failure_backup_list_and_pointer_abort_before_deleting_backups(self):
        backup = new_backup(self.cache / "project_backups", "failed")
        new_backup(self.cache / "project_backups", "newest")
        failed = self.cache / "sync_logs" / "failed_run.json"
        atomic_json(failed, {"schema": 1, "status": "failed", "runId": "failed", "backups": backup.name})
        with self.assertRaisesRegex(ValueError, "backup pin"):
            cleanup(self.cache, editor_is_running=False)
        self.assertTrue(backup.is_dir())
        failed.unlink()
        atomic_json(self.cache / "current_generation.json", {"schema": 1})
        with self.assertRaisesRegex(ValueError, "pointer"):
            cleanup(self.cache, editor_is_running=False)
        self.assertTrue(backup.is_dir())

    def test_invalid_graph_object_and_reparse_directory_abort_before_pruning(self):
        backup = new_backup(self.cache / "project_backups", "old")
        new_backup(self.cache / "project_backups", "new")
        graph = backup / "Home.t3"
        graph.write_text("[]")
        with self.assertRaisesRegex(ValueError, "Graph evidence must be an object"):
            cleanup(self.cache, editor_is_running=False)
        self.assertTrue(backup.is_dir())
        graph.write_text("{}")
        real_check = __import__("retention_lifecycle")._is_reparse
        with patch("retention_lifecycle._is_reparse", side_effect=lambda p: p == backup or real_check(p)):
            with self.assertRaisesRegex(ValueError, "reparse"):
                cleanup(self.cache, editor_is_running=False)
        self.assertTrue(backup.is_dir())

    def test_mixed_case_graph_extension_retains_generation_reference(self):
        names = [self.generation(i) for i in range(1, 4)]
        project = self.cache.parent / "UserProject"
        atomic_json(project / "Symbols" / "Home.T3", {"Value": str(self.cache / "generations" / names[0] / "mesh.glb")})
        atomic_json(self.cache / "tixl_project.json", {"path": str(project)})
        cleanup(self.cache, editor_is_running=False)
        self.assertTrue((self.cache / "generations" / names[0]).is_dir())

    def test_explicit_install_failure_retains_its_backups_and_original_error(self):
        import blend_sync
        generation = self.generation(1)
        source = self.cache.parent / "source.blend"
        source.write_bytes(b"saved authored source")
        error = RuntimeError("installation failed after backup")
        created = []
        def fail_install(*args, **kwargs):
            backup = new_backup(self.cache / "project_backups", "install")
            atomic_json(backup / "Home.t3", {"TimeClips": [{"StartTime": 7}]})
            created.append(backup)
            raise error
        with patch.object(blend_sync, "cached_manifest", return_value={"generation": generation}), \
                patch.object(blend_sync, "generic_finish", side_effect=fail_install), \
                patch.object(blend_sync, "editor_running", return_value=False), \
                patch("sync_metrics.sys.stderr"):
            with self.assertRaises(RuntimeError) as caught:
                blend_sync.install_cache(source, "generic", self.cache, Path(sys.executable), False, True)
        self.assertIs(caught.exception, error)
        summary = json.loads((self.cache / "sync_logs" / "failed_run.json").read_text())
        self.assertEqual(summary["backups"], [created[0].name])
        self.assertTrue(created[0].is_dir())
        self.assertTrue(Path(error.metrics_path).is_file())


class BoundedProcessLogTest(unittest.TestCase):
    def test_success_marker_is_detected_even_when_discarded_from_middle_of_log(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "run.log"
            code = "import sys;sys.stdout.buffer.write(b'x'*2000+b'BLEND_SYNC_STAGE_COMPLETE'+b'y'*2000)"
            result = run_to_log([sys.executable, "-c", code], path, max_bytes=1024,
                                completion_marker=b"BLEND_SYNC_STAGE_COMPLETE")
            self.assertTrue(result.completion_marker_seen)
            self.assertNotIn(b"BLEND_SYNC_STAGE_COMPLETE", path.read_bytes())
            self.assertEqual(result.returncode, 0)

    def test_read_exception_waits_for_nested_worker_without_killing_orchestrator(self):
        from unittest.mock import Mock
        for error in (OSError("pipe read failed"), KeyboardInterrupt()):
            with self.subTest(error=type(error).__name__), tempfile.TemporaryDirectory() as directory:
                marker = Path(directory) / "nested_worker_finished"
                worker = "import time;from pathlib import Path;time.sleep(.05);Path(" + repr(str(marker)) + ").write_text('done')"
                orchestrator = "import subprocess,sys;subprocess.run([sys.executable,'-c'," + repr(worker) + "],check=True)"
                real_popen = subprocess.Popen
                children = []
                def child_factory(*args, **kwargs):
                    child = real_popen(*args, **kwargs)
                    real_stdout = child.stdout
                    child.stdout = Mock()
                    child.stdout.read1.side_effect = error
                    child.stdout.close.side_effect = real_stdout.close
                    children.append(child)
                    return child
                with patch("logged_process.subprocess.Popen", side_effect=child_factory):
                    with self.assertRaises(type(error)) as caught:
                        run_to_log([sys.executable, "-c", orchestrator], Path(directory) / "run.log")
                self.assertIs(caught.exception, error)
                self.assertEqual(marker.read_text(), "done")
                self.assertIsNotNone(children[0].poll())

    def test_auxiliary_stat_failure_preserves_completed_child_exit_code(self):
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "run.log"
            real_stat = Path.stat
            def fail_stat(path, *args, **kwargs):
                if path == log:
                    raise OSError("auxiliary stat failed")
                return real_stat(path, *args, **kwargs)
            with patch.object(Path, "stat", fail_stat):
                result = run_to_log([sys.executable, "-c", "print('completed')"], log)
            self.assertEqual(result.returncode, 0)
    def test_real_large_child_retains_head_tail_and_exit_code_with_bounded_storage(self):
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "run.log"
            code = "import sys;sys.stdout.buffer.write(b'HEAD'+b'x'*200000+b'FINAL FAILURE');sys.exit(7)"
            result = run_to_log([sys.executable, "-c", code], log, max_bytes=4096)
            data = log.read_bytes()
            self.assertEqual(result.returncode, 7)
            self.assertLessEqual(len(data), 4096)
            self.assertTrue(data.startswith(b"HEAD"))
            self.assertTrue(data.endswith(b"FINAL FAILURE"))
            metadata = json.loads(log.with_name(log.name + ".meta.json").read_text())
            self.assertGreater(metadata["omittedBytes"], 190000)
            self.assertIn(b"middle bytes omitted", data)

    def test_small_child_output_is_complete_and_latest_completed_copy_matches(self):
        with tempfile.TemporaryDirectory() as directory:
            log, latest = Path(directory) / "run.log", Path(directory) / "latest.log"
            result = run_to_log([sys.executable, "-c", "print('complete evidence')"], log, latest_log=latest)
            self.assertEqual(result.returncode, 0)
            self.assertEqual(log.read_bytes(), latest.read_bytes())
            self.assertEqual(log.read_text().strip(), "complete evidence")

    def test_log_write_failure_still_waits_for_child_before_returning_error(self):
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / "finished"
            code = "import sys,time;from pathlib import Path;print('output',flush=True);time.sleep(.05);Path(" + repr(str(marker)) + ").write_text('completed')"
            with patch.object(BoundedLog, "write", side_effect=OSError("disk full")):
                with self.assertRaisesRegex(OSError, "disk full"):
                    run_to_log([sys.executable, "-c", code], Path(directory) / "run.log")
            self.assertEqual(marker.read_text(), "completed")


if __name__ == "__main__":
    unittest.main()

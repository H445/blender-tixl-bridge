"""Measurement must preserve sync results, failures and nested process evidence."""
import json
import os
import sys
import subprocess
import time
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "blender_tixl_bridge" / "source"))
from sync_metrics import RunMetrics, count, current_run, measured_sync, phase, worker_metrics
import blend_sync


class MetricsTest(unittest.TestCase):
    def test_metadata_failure_preserves_result_exception_and_context(self):
        with tempfile.TemporaryDirectory() as folder:
            for fails in (False, True):
                run = RunMetrics(Path(folder))
                original = ValueError("original export failure")
                with patch("sync_metrics.Path.glob", side_effect=OSError("unreadable directory")):
                    if fails:
                        with self.assertRaises(ValueError) as caught:
                            with run:
                                raise original
                        self.assertIs(caught.exception, original)
                    else:
                        with run:
                            pass
                self.assertIsNone(run.path)
                self.assertIsNone(current_run())

    def test_failed_diagnostic_write_preserves_original_exception(self):
        with tempfile.TemporaryDirectory() as folder:
            original = ValueError("original export failure")
            @measured_sync
            def sync(*args):
                raise original
            with patch("sync_metrics.sys.stderr.write", side_effect=OSError("full log")):
                with self.assertRaises(ValueError) as caught:
                    sync(Path(folder) / "source.blend", "generic", Path(folder), Path("blender"), False, False)
            self.assertIs(caught.exception, original)
            self.assertTrue(Path(original.metrics_path).is_file())
            self.assertIsNone(current_run())

    def test_failed_phase_is_recorded_without_swallowing_original_error(self):
        with tempfile.TemporaryDirectory() as folder:
            run = RunMetrics(Path(folder))
            with self.assertRaisesRegex(RuntimeError, "export rejected"):
                with run:
                    with phase("publication"):
                        count("blenderProcesses")
                        raise RuntimeError("export rejected")
            report = json.loads(run.path.read_text())
            self.assertEqual(report["status"], "failed")
            self.assertEqual(report["errorType"], "RuntimeError")
            self.assertEqual(report["phases"]["publication"]["failures"], 1)
            self.assertEqual(report["counters"]["blenderProcesses"], 1)
            self.assertIsNone(current_run())

    def test_worker_report_correlates_with_parent_without_overwriting_it(self):
        with tempfile.TemporaryDirectory() as folder:
            with RunMetrics(Path(folder)) as parent:
                with patch.dict(os.environ, parent.environment()):
                    with worker_metrics() as worker:
                        with phase("geometry_export"):
                            count("worlds", 3)
                self.assertIs(current_run(), parent)
                with phase("publication"):
                    pass
            parent_report = json.loads(parent.path.read_text())
            worker_report = json.loads(worker.path.read_text())
            self.assertEqual(parent_report["runId"], worker_report["runId"])
            self.assertEqual(worker_report["counters"]["worlds"], 3)
            self.assertIn(str(worker.path.resolve()), parent_report["workerReports"])
            self.assertGreaterEqual(worker_report["startupSeconds"], 0)
            self.assertNotIn("geometry_export", parent_report["phases"])

    def test_unwritable_metrics_do_not_change_successful_sync_result(self):
        with tempfile.TemporaryDirectory() as folder:
            @measured_sync
            def sync(blend, profile, cache, blender, force, install):
                return {"status": "up_to_date", "preserved": True}
            with patch("sync_metrics.os.replace", side_effect=OSError("disk full")):
                result = sync(Path(folder) / "source.blend", "generic", Path(folder), Path("blender"), False, False)
            self.assertEqual(result, {"status": "up_to_date", "preserved": True, "metrics": None})
            self.assertIsNone(current_run())

    def test_repeated_phases_aggregate_and_bad_run_id_cannot_escape_directory(self):
        with tempfile.TemporaryDirectory() as folder:
            with RunMetrics(Path(folder), run_id="../escape") as run:
                for _ in range(4):
                    with phase("hashing"):
                        count("hashBytes", 10)
            report = json.loads(run.path.read_text())
            self.assertEqual(run.path.parent, Path(folder))
            self.assertEqual(report["phases"]["hashing"]["calls"], 4)
            self.assertEqual(report["counters"]["hashBytes"], 40)
            self.assertEqual(list(Path(folder).glob("*.tmp")), [])

    def test_real_failed_child_retains_parent_and_worker_reports_and_startup_delay(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            blend = root / "scene.blend"
            blend.write_bytes(b"saved scene")
            source = str(Path(blend_sync.__file__).parent)
            code = ("import sys,time; sys.path.insert(0," + repr(source) + "); "
                    "from sync_metrics import worker_metrics; time.sleep(.1)\n"
                    "with worker_metrics():\n raise RuntimeError('worker fixture rejected')\n")
            from logged_process import run_to_log
            def failed_worker(command, path, **kwargs):
                return run_to_log([sys.executable, "-c", code], path, **kwargs)
            with patch.object(blend_sync, "wait_for_editor_pause"), \
                    patch.object(blend_sync, "run_to_log", side_effect=failed_worker), \
                    patch("sync_metrics.sys.stderr") as stderr:
                with self.assertRaisesRegex(RuntimeError, "Blender export failed") as raised:
                    blend_sync.sync(blend, "generic", root / "cache", Path(sys.executable), False, False)
            parent_path = Path(raised.exception.metrics_path)
            parent = json.loads(parent_path.read_text())
            self.assertEqual(parent["status"], "failed")
            self.assertEqual(parent["phases"]["blender_process"]["failures"], 1)
            self.assertEqual(parent["counters"]["blenderProcesses"], 1)
            worker_path = next(Path(path) for path in parent["workerReports"] if path.endswith(".worker.json"))
            worker = json.loads(worker_path.read_text())
            self.assertEqual(worker["status"], "failed")
            self.assertEqual(worker["errorType"], "RuntimeError")
            self.assertIn("worker fixture rejected", worker["errorMessage"])
            self.assertGreaterEqual(worker["startupSeconds"], .1)
            self.assertTrue(stderr.write.called)

    def test_bad_or_missing_worker_timestamp_does_not_fabricate_startup(self):
        with tempfile.TemporaryDirectory() as folder:
            for value in (None, "invalid", "NaN", "Infinity"):
                with self.subTest(value=value), patch.dict(os.environ, {"TIXL_SYNC_METRICS_DIR": folder}, clear=True):
                    if value is not None:
                        os.environ["TIXL_SYNC_WORKER_STARTED_AT"] = value
                    with worker_metrics() as run:
                        pass
                    self.assertNotIn("startupSeconds", json.loads(run.path.read_text()))


if __name__ == "__main__":
    unittest.main()

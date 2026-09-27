"""Real subprocesses verify lock exclusion and recovery after abrupt exits."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SOURCE = Path(__file__).resolve().parents[1] / "blender_tixl_bridge" / "source"
sys.path.insert(0, str(SOURCE))
from process_lock import process_lock
from blend_sync import export_lock


class ProcessLockTest(unittest.TestCase):
    def test_legacy_lock_defers_new_export_and_releases_new_lease(self):
        with tempfile.TemporaryDirectory() as folder:
            cache = Path(folder)
            legacy = cache / ".blend_sync.lock"
            legacy.write_text("pid=123 started=0\n")
            with self.assertRaisesRegex(RuntimeError, "older-version sync lock"):
                with export_lock(cache):
                    self.fail("Legacy exporter must not be bypassed")
            self.assertTrue(legacy.exists())
            legacy.unlink()
            with export_lock(cache):
                pass

    def test_abrupt_worker_exit_releases_lock(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "sync.lock"
            code = ("import sys,os; sys.path.insert(0,sys.argv[1]); "
                    "from process_lock import process_lock; "
                    "lease=process_lock(__import__('pathlib').Path(sys.argv[2])); "
                    "lease.__enter__(); os._exit(7)")
            child = subprocess.run([sys.executable, "-c", code, str(SOURCE), str(path)], timeout=10)
            self.assertEqual(child.returncode, 7)
            with process_lock(path, timeout=.5):
                self.assertTrue(path.is_file())
            # The same persistent file is reused, so lock owners cannot split
            # across an unlinked/recreated inode on Unix.
            self.assertTrue(path.is_file())

    def test_second_process_cannot_enter_until_owner_exits(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "sync.lock"
            code = ("import sys; sys.path.insert(0,sys.argv[1]); "
                    "from process_lock import process_lock; "
                    "lease=process_lock(__import__('pathlib').Path(sys.argv[2]),timeout=.2); "
                    "lease.__enter__()")
            with process_lock(path):
                child = subprocess.run([sys.executable, "-c", code, str(SOURCE), str(path)],
                                       capture_output=True, text=True, timeout=10)
                self.assertNotEqual(child.returncode, 0)
                self.assertIn("TimeoutError", child.stderr)
            with process_lock(path, timeout=.5):
                pass

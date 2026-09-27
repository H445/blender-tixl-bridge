"""Safety and policy tests for cache-scoped retention primitives."""
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "blender_tixl_bridge" / "source"))
import cache_retention
from cache_retention import RetentionPolicy, prune_directories, prune_files


class CacheRetentionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.cache = Path(self.temp.name) / "cache"
        self.cache.mkdir()
        self.root = self.cache / "project_backups"
        self.root.mkdir()
        self.now = time.time()

    def directory(self, name, size, age_seconds=0):
        folder = self.root / name
        folder.mkdir()
        payload = folder / "payload.bin"
        payload.write_bytes(b"x" * size)
        stamp = self.now - age_seconds
        os.utime(payload, (stamp, stamp))
        os.utime(folder, (stamp, stamp))
        return folder

    def test_default_policy_is_finite_and_invalid_limits_fail(self):
        policy = RetentionPolicy()
        self.assertGreater(policy.max_count, 0)
        self.assertGreater(policy.max_bytes, 0)
        self.assertGreater(policy.max_age_days, 0)
        with self.assertRaises(ValueError):
            RetentionPolicy(max_count=-1)
        with self.assertRaises(ValueError):
            RetentionPolicy(max_bytes=-1)
        with self.assertRaises(ValueError):
            RetentionPolicy(max_age_days=float("inf"))

    def test_directory_pruning_obeys_age_count_bytes_and_dry_run(self):
        self.directory("backup_a", 4, age_seconds=5)
        self.directory("backup_b", 5, age_seconds=4)
        self.directory("backup_c", 6, age_seconds=3)
        self.directory("backup_old", 2, age_seconds=5 * 86400)
        policy = RetentionPolicy(max_count=2, max_bytes=10, max_age_days=1)

        planned = prune_directories(self.root, self.cache, policy,
                                   name_pattern=r"backup_[a-z]+", newest_always_keep=1,
                                   dry_run=True, now=self.now)

        self.assertEqual(planned["status"], "planned")
        self.assertEqual(set(planned["kept"]), {"backup_a", "backup_c"})
        self.assertEqual(set(planned["wouldDelete"]), {"backup_b", "backup_old"})
        self.assertEqual(planned["bytesAfter"], 10)
        self.assertTrue((self.root / "backup_b").exists())

        applied = prune_directories(self.root, self.cache, policy,
                                    name_pattern=r"backup_[a-z]+", newest_always_keep=1,
                                    dry_run=False, now=self.now)
        self.assertEqual(applied["status"], "pruned")
        self.assertEqual(set(applied["deleted"]), {"backup_b", "backup_old"})
        self.assertFalse((self.root / "backup_b").exists())
        self.assertTrue((self.root / "backup_a").exists())
        self.assertEqual(applied["bytesAfter"], 10)

    def test_pinned_referenced_failed_and_newest_survive_budget_excess(self):
        self.directory("backup_reference", 8, age_seconds=9 * 86400)
        self.directory("backup_failed", 7, age_seconds=8 * 86400)
        self.directory("backup_active", 5, age_seconds=0)
        self.directory("backup_evict", 1, age_seconds=6 * 86400)
        result = prune_directories(
            self.root, self.cache,
            RetentionPolicy(max_count=1, max_bytes=5, max_age_days=1),
            name_pattern=r"backup_[a-z]+",
            referenced_names=("backup_reference",),
            failed_names=("backup_failed",),
            pinned_names=("backup_active",),
            newest_always_keep=1, dry_run=True, now=self.now)

        self.assertEqual(set(result["kept"]), {
            "backup_reference", "backup_failed", "backup_active"})
        self.assertEqual(result["wouldDelete"], ["backup_evict"])
        self.assertEqual(result["budgetExceeded"]["count"], 2)
        self.assertGreater(result["budgetExceeded"]["bytes"], 0)
        self.assertEqual(result["pinnedBudgetExceeded"]["count"], 2)
        self.assertGreater(result["pinnedBudgetExceeded"]["bytes"], 0)
        self.assertEqual(set(result["budgetExceeded"]["ageProtected"]), {
            "backup_reference", "backup_failed"})

    def test_invalid_or_missing_pin_aborts_before_any_deletion(self):
        self.directory("backup_old", 1, age_seconds=100 * 86400)
        for pins in (("../outside",), ("missing_backup",)):
            with self.subTest(pins=pins):
                result = prune_directories(
                    self.root, self.cache, RetentionPolicy(max_age_days=1),
                    name_pattern=r"backup_[a-z]+", pinned_names=pins,
                    newest_always_keep=0, dry_run=False, now=self.now)
                self.assertEqual(result["status"], "aborted")
                self.assertTrue((self.root / "backup_old").exists())

    def test_outside_cache_root_and_invalid_name_filter_fail_closed(self):
        outside = Path(self.temp.name) / "outside"
        outside.mkdir()
        result = prune_directories(outside, self.cache, RetentionPolicy(), dry_run=False)
        self.assertEqual(result["status"], "aborted")
        invalid_pattern = prune_directories(self.root, self.cache, RetentionPolicy(),
                                            name_pattern="[", dry_run=False)
        self.assertEqual(invalid_pattern["status"], "aborted")
        invalid_time = prune_directories(self.root, self.cache, RetentionPolicy(),
                                          name_pattern=r"backup_[a-z]+", now=float("nan"),
                                          dry_run=False)
        self.assertEqual(invalid_time["status"], "aborted")

    def test_symlink_and_junction_candidates_abort_without_following(self):
        outside = Path(self.temp.name) / "outside"
        outside.mkdir()
        (outside / "keep.bin").write_bytes(b"must remain")
        link = self.root / "backup_link"
        try:
            link.symlink_to(outside, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("symlink creation is not available")
        result = prune_directories(self.root, self.cache, RetentionPolicy(),
                                   name_pattern=r"backup_[a-z]+", dry_run=False)
        self.assertEqual(result["status"], "aborted")
        self.assertTrue((outside / "keep.bin").exists())

    def test_nested_symlink_aborts_whole_directory_prune(self):
        target = Path(self.temp.name) / "outside.bin"
        target.write_bytes(b"safe")
        candidate = self.directory("backup_nested", 1)
        try:
            (candidate / "escape.bin").symlink_to(target)
        except (OSError, NotImplementedError):
            self.skipTest("symlink creation is not available")
        result = prune_directories(self.root, self.cache, RetentionPolicy(max_age_days=0),
                                   name_pattern=r"backup_[a-z]+", newest_always_keep=0,
                                   dry_run=False, now=self.now + 10)
        self.assertEqual(result["status"], "aborted")
        self.assertTrue(candidate.exists())
        self.assertEqual(target.read_bytes(), b"safe")

    def test_parent_junction_is_rejected_before_resolution(self):
        self.directory("backup_old", 1, age_seconds=100 * 86400)
        with patch("cache_retention._is_junction", side_effect=lambda path: Path(path) == self.cache):
            result = prune_directories(self.root, self.cache, RetentionPolicy(max_age_days=1),
                                       name_pattern=r"backup_[a-z]+", newest_always_keep=0,
                                       dry_run=False, now=self.now)
        self.assertEqual(result["status"], "aborted")
        self.assertTrue((self.root / "backup_old").exists())

    def test_windows_reparse_attribute_is_rejected_without_junction_api(self):
        info = SimpleNamespace(st_file_attributes=0x400)
        with patch.object(Path, "lstat", return_value=info), \
             patch.object(Path, "is_symlink", return_value=False), \
             patch.object(cache_retention, "_is_junction", return_value=False):
            self.assertTrue(cache_retention._is_reparse(Path("C:/cache/item")))

    def test_cache_root_itself_is_rejected_even_when_missing(self):
        missing_cache = Path(self.temp.name) / "missing-cache"
        result = prune_directories(missing_cache, missing_cache, RetentionPolicy(), dry_run=False)
        self.assertEqual(result["status"], "aborted")
        self.assertIn("child of the cache root", result["reason"])

    def test_missing_generated_folder_and_missing_parents_are_empty(self):
        for root in (self.cache / "not-created-yet",
                     self.cache / "not-created-yet" / "nested" / "backups"):
            with self.subTest(root=root):
                result = prune_directories(root, self.cache, RetentionPolicy(), dry_run=False)
                self.assertEqual(result["status"], "empty")
                self.assertEqual(result["deleted"], [])
                self.assertFalse(root.exists())

    def test_root_replacement_between_deletes_stops_before_following_redirect(self):
        for name in ("backup_a", "backup_b", "backup_c"):
            self.directory(name, 1, age_seconds=20)
        outside = Path(self.temp.name) / "redirect-target"
        outside.mkdir()
        (outside / "backup_b").mkdir()
        (outside / "backup_b" / "sentinel").write_text("keep", encoding="utf-8")
        moved_root = self.cache / "project_backups_moved"
        real_rmtree = cache_retention.shutil.rmtree
        calls = []

        def replace_after_first(path):
            real_rmtree(path)
            calls.append(Path(path).name)
            if len(calls) == 1:
                self.root.rename(moved_root)
                try:
                    self.root.symlink_to(outside, target_is_directory=True)
                except (OSError, NotImplementedError):
                    self.skipTest("symlink creation is not available")

        with patch.object(cache_retention.shutil, "rmtree", side_effect=replace_after_first):
            result = prune_directories(
                self.root, self.cache,
                RetentionPolicy(max_count=0, max_bytes=0, max_age_days=0),
                name_pattern=r"backup_[a-z]+", newest_always_keep=0,
                dry_run=False, now=self.now + 30)

        self.assertEqual(result["status"], "aborted")
        self.assertEqual(len(result["deleted"]), 1)
        self.assertEqual((outside / "backup_b" / "sentinel").read_text(encoding="utf-8"), "keep")
        self.assertEqual(len(list(moved_root.iterdir())), 2)

    def test_flat_log_pruning_keeps_newest_and_pinned_active_file(self):
        logs = self.cache / "sync_logs"
        logs.mkdir()
        for index, age in enumerate((4, 3, 2, 1)):
            path = logs / f"sync_{index}.log"
            path.write_bytes(bytes([index]) * 3)
            stamp = self.now - age
            os.utime(path, (stamp, stamp))
        result = prune_files(
            logs, self.cache, RetentionPolicy(max_count=1, max_bytes=3, max_age_days=0),
            name_pattern=r"sync_\d+\.log", pinned_names=("sync_0.log",),
            newest_always_keep=1, dry_run=False, now=self.now + 10)
        self.assertEqual(result["status"], "pruned")
        self.assertEqual(set(result["kept"]), {"sync_0.log", "sync_3.log"})
        self.assertTrue((logs / "sync_0.log").exists())
        self.assertTrue((logs / "sync_3.log").exists())
        self.assertEqual(result["budgetExceeded"]["count"], 1)


if __name__ == "__main__":
    unittest.main()

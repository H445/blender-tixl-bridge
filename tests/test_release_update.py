"""Security-focused tests for release lookup and package application."""

import hashlib
import importlib.util
import io
import stat
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "blender_tixl_bridge" / "source" / "release_update.py"


def load_module():
    spec = importlib.util.spec_from_file_location("test_release_update_module", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def archive_bytes(entries):
    """Build an in-memory ZIP from (name, content[, unix_mode]) tuples."""
    output = io.BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        for entry in entries:
            name, content = entry[:2]
            info = ZipInfo(name)
            info.compress_type = ZIP_DEFLATED
            if len(entry) > 2:
                info.create_system = 3
                info.external_attr = entry[2] << 16
            archive.writestr(info, content)
    return output.getvalue()


def valid_package(version=(1, 2, 4)):
    return archive_bytes([
        ("blender_tixl_bridge/__init__.py",
         f"bl_info = {{'version': ({version[0]}, {version[1]}, {version[2]})}}\n".encode()),
        ("blender_tixl_bridge/source/release_update.py", b"# updater\n"),
    ])


class ReleaseMetadataTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.updater = load_module()

    def payload(self, tag="v1.2.4", *, prerelease=False, draft=False, name=None,
                asset_name="blender-tixl-bridge-1.2.4.zip", asset_url=None,
                size=123, digest="sha256:" + "a" * 64):
        return {
            "tag_name": tag,
            "prerelease": prerelease,
            "draft": draft,
            "name": name or tag,
            "assets": [{
                "name": asset_name,
                "browser_download_url": asset_url or
                    "https://github.com/H445/blender-tixl-bridge/releases/download/v1.2.4/" + asset_name,
                "size": size,
                "digest": digest,
            }],
        }

    def test_accepts_newer_release_and_normalizes_version_asset_metadata(self):
        release = self.updater.validate_release(self.payload(), (1, 2, 3))
        self.assertEqual(release["version"], (1, 2, 4))
        self.assertEqual(release["tag"], "v1.2.4")
        self.assertEqual(release["asset_url"], self.payload()["assets"][0]["browser_download_url"])
        self.assertEqual(release["asset_size"], 123)
        self.assertEqual(release["digest"], "a" * 64)

    def test_same_or_older_version_means_no_update(self):
        self.assertIsNone(self.updater.validate_release(self.payload(tag="v1.2.3"), (1, 2, 3)))
        self.assertIsNone(self.updater.validate_release(self.payload(tag="v1.2.2"), (1, 2, 3)))

    def test_rejects_draft_prerelease_and_malformed_or_mismatched_tags(self):
        invalid = [
            self.payload(draft=True), self.payload(prerelease=True),
            self.payload(tag="latest"), self.payload(tag="v1.2.4-rc1"),
            self.payload(tag="v1.2.5", asset_name="blender-tixl-bridge-1.2.4.zip"),
        ]
        for payload in invalid:
            with self.subTest(payload=payload):
                with self.assertRaises((ValueError, TypeError)):
                    self.updater.validate_release(payload, (1, 2, 3))

    def test_rejects_unsafe_asset_metadata(self):
        invalid = [
            self.payload(asset_name="other.zip"),
            self.payload(asset_url="http://example.invalid/addon.zip"),
            self.payload(asset_url="https://example.invalid/addon.zip"),
            self.payload(size=-1),
            self.payload(size=True),
            self.payload(digest="md5:" + "a" * 32),
        ]
        for payload in invalid:
            with self.subTest(asset=payload["assets"][0]):
                with self.assertRaises((ValueError, TypeError)):
                    self.updater.validate_release(payload, (1, 2, 3))

    def test_latest_endpoint_without_any_release_is_not_an_error(self):
        def no_release(request, timeout):
            raise urllib.error.HTTPError(request.full_url, 404, "no releases", {}, None)

        self.assertIsNone(self.updater.fetch_latest_release((1, 2, 3), opener=no_release))

    def test_download_checks_published_asset_size(self):
        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self, limit):
                return b"short"

            def geturl(self):
                return "https://github.com/H445/blender-tixl-bridge/releases/download/v1.2.4/file.zip"

        release = {"asset_url": "https://github.com/H445/blender-tixl-bridge/releases/download/v1.2.4/file.zip",
                   "asset_size": 6}
        with self.assertRaises(ValueError):
            self.updater.download_release(release, opener=lambda request, timeout: Response())


class ReleaseArchiveTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.updater = load_module()

    def test_extracts_only_package_files_and_checks_digest_and_embedded_version(self):
        data = valid_package()
        files = self.updater.validate_archive(data, (1, 2, 4), hashlib.sha256(data).hexdigest())
        self.assertEqual(set(files), {"__init__.py", "source/release_update.py"})
        self.assertEqual(files["source/release_update.py"], b"# updater\n")
        with self.assertRaises((ValueError, TypeError)):
            self.updater.validate_archive(data, (1, 2, 4), "0" * 64)
        with self.assertRaises((ValueError, TypeError)):
            self.updater.validate_archive(data, (1, 2, 5))

    def test_rejects_traversal_absolute_backslash_and_non_package_paths(self):
        bad_names = [
            "blender_tixl_bridge/../escape.py",
            "../blender_tixl_bridge/escape.py",
            "/blender_tixl_bridge/escape.py",
            "C:/blender_tixl_bridge/escape.py",
            "blender_tixl_bridge\\source\\evil.py",
            "outside.txt",
        ]
        for name in bad_names:
            data = archive_bytes([
                ("blender_tixl_bridge/__init__.py", b"bl_info = {'version': (1, 2, 4)}\n"),
                (name, b"bad"),
            ])
            with self.subTest(name=name):
                with self.assertRaises((ValueError, OSError)):
                    self.updater.validate_archive(data, (1, 2, 4))

    def test_rejects_symlinks_duplicate_names_and_casefold_collisions(self):
        symlink = archive_bytes([
            ("blender_tixl_bridge/__init__.py", b"bl_info = {'version': (1, 2, 4)}\n"),
            ("blender_tixl_bridge/source/link.py", b"target", stat.S_IFLNK | 0o777),
        ])
        duplicate = archive_bytes([
            ("blender_tixl_bridge/__init__.py", b"bl_info = {'version': (1, 2, 4)}\n"),
            ("blender_tixl_bridge/source/x.py", b"one"),
            ("blender_tixl_bridge/source/x.py", b"two"),
        ])
        collision = archive_bytes([
            ("blender_tixl_bridge/__init__.py", b"bl_info = {'version': (1, 2, 4)}\n"),
            ("blender_tixl_bridge/source/X.py", b"one"),
            ("blender_tixl_bridge/source/x.py", b"two"),
        ])
        for data in (symlink, duplicate, collision):
            with self.subTest(length=len(data)):
                with self.assertRaises((ValueError, OSError)):
                    self.updater.validate_archive(data, (1, 2, 4))

    def test_rejects_missing_root_init_and_malformed_zip(self):
        for data in (b"not a zip", archive_bytes([("blender_tixl_bridge/a.py", b"x")])):
            with self.subTest(data=data[:12]):
                with self.assertRaises((ValueError, OSError)):
                    self.updater.validate_archive(data, (1, 2, 4))

    def test_rejects_archive_entry_count_over_limit(self):
        entries = [("blender_tixl_bridge/__init__.py", b"bl_info = {'version': (1, 2, 4)}\n")]
        entries.extend((f"blender_tixl_bridge/f{index}.py", b"")
                       for index in range(self.updater.MAX_FILES))
        with self.assertRaises(ValueError):
            self.updater.validate_archive(archive_bytes(entries), (1, 2, 4))

    def test_rejects_unpacked_size_limits(self):
        data = archive_bytes([
            ("blender_tixl_bridge/__init__.py", b"bl_info = {'version': (1, 2, 4)}\n"),
            ("blender_tixl_bridge/source/release_update.py", b"12345"),
        ])
        with patch.object(self.updater, "MAX_ENTRY", 4):
            with self.assertRaises(ValueError):
                self.updater.validate_archive(data, (1, 2, 4))
        with patch.object(self.updater, "MAX_ENTRY", 100), patch.object(self.updater, "MAX_UNPACKED", 30):
            with self.assertRaises(ValueError):
                self.updater.validate_archive(data, (1, 2, 4))


class InstallPackageTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.updater = load_module()

    def test_updates_known_files_and_preserves_user_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "blender_tixl_bridge"
            (root / "source").mkdir(parents=True)
            (root / "__init__.py").write_bytes(b"old init")
            (root / "source" / "old.py").write_bytes(b"old")
            (root / "preferences.json").write_text("user settings", encoding="utf-8")
            files = {"__init__.py": b"new init", "source/new.py": b"new"}

            self.updater.install_package(files, root)

            self.assertEqual((root / "__init__.py").read_bytes(), b"new init")
            self.assertEqual((root / "source" / "new.py").read_bytes(), b"new")
            self.assertEqual((root / "source" / "old.py").read_bytes(), b"old")
            self.assertEqual((root / "preferences.json").read_text(encoding="utf-8"), "user settings")

    def test_rolls_back_files_when_a_copy_fails_mid_install(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "blender_tixl_bridge"
            (root / "source").mkdir(parents=True)
            original = {"__init__.py": b"old init", "source/a.py": b"old a",
                        "source/old.py": b"old"}
            for name, content in original.items():
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content)
            files = {"__init__.py": b"new init", "source/a.py": b"new a",
                     "source/z.py": b"new z"}

            # Fail on the second publication after an existing file has been
            # replaced, so rollback has to restore its original contents.
            real_replace = self.updater.os.replace
            replace_count = 0

            def fail_second_replace(source, destination):
                nonlocal replace_count
                replace_count += 1
                if replace_count == 2:
                    raise OSError("simulated disk failure")
                return real_replace(source, destination)

            with patch.object(self.updater.os, "replace", side_effect=fail_second_replace):
                with self.assertRaises(OSError):
                    self.updater.install_package(files, root)

            self.assertEqual((root / "__init__.py").read_bytes(), original["__init__.py"])
            self.assertEqual((root / "source/a.py").read_bytes(), original["source/a.py"])
            self.assertEqual((root / "source/old.py").read_bytes(), original["source/old.py"])
            self.assertFalse((root / "source/z.py").exists())

    def test_rejects_unsafe_package_paths_before_writing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "blender_tixl_bridge"
            root.mkdir()
            (root / "__init__.py").write_bytes(b"old init")
            with self.assertRaises(ValueError):
                self.updater.install_package({"__init__.py": b"new", "../escape.py": b"bad"}, root)
            self.assertEqual((root / "__init__.py").read_bytes(), b"old init")
            self.assertFalse((Path(directory) / "escape.py").exists())


if __name__ == "__main__":
    unittest.main()

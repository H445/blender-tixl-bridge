"""Tests for version-derived release archive metadata."""

from pathlib import Path
import tempfile
import unittest

from build_addon_zip import addon_version, archive_name, version_text


class BuildAddonZipTest(unittest.TestCase):
    def test_repository_version_controls_archive_name(self):
        version = addon_version()
        self.assertEqual(version, (1, 3, 1))
        self.assertEqual(version_text(version), "1.3.1")
        self.assertEqual(archive_name(version), "blender-tixl-bridge-1.3.1.zip")

    def test_invalid_version_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            init_path = Path(directory) / "__init__.py"
            init_path.write_text("bl_info = {'version': ('1', 2, 3)}", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Invalid bl_info version"):
                addon_version(init_path)


if __name__ == "__main__":
    unittest.main()

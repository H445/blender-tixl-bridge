"""Tests for version-derived release archive metadata."""

import posixpath
import re
import shutil
from pathlib import Path
import tempfile
import unittest
from zipfile import ZipFile

from build_addon_zip import (ROOT, BRIDGE_SKILLS, OFFLINE_HELPERS, agent_bundle_files,
                             addon_version, archive_name, build_archive, version_text)


class BuildAddonZipTest(unittest.TestCase):
    def test_repository_version_controls_archive_name(self):
        version = addon_version()
        self.assertEqual(len(version), 3)
        self.assertTrue(all(isinstance(part, int) and part >= 0 for part in version))
        release = ".".join(map(str, version))
        self.assertEqual(version_text(version), release)
        self.assertEqual(archive_name(version), f"blender-tixl-bridge-{release}.zip")

    def test_invalid_version_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            init_path = Path(directory) / "__init__.py"
            init_path.write_text("bl_info = {'version': ('0', 4, 0)}", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Invalid bl_info version"):
                addon_version(init_path)

    def test_archive_contains_resolvable_task_routes_without_local_notes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            package = root / "blender_tixl_bridge"
            package.mkdir()
            shutil.copy2(ROOT / "blender_tixl_bridge" / "__init__.py", package / "__init__.py")
            example = root / "examples"
            (example / "screenshots").mkdir(parents=True)
            for name in ("BlendShapeExample.blend", "README.md", "build_blend_shape_example.py",
                         "validate_blend_shape_example.py"):
                if name.endswith(".blend"):
                    (example / name).write_bytes(b"BLENDER" + b"fixture")
                else:
                    shutil.copy2(ROOT / "examples" / name, example / name)
            for screenshot in (ROOT / "examples" / "screenshots").glob("*.png"):
                shutil.copy2(screenshot, example / "screenshots" / screenshot.name)

            files = [path.relative_to(ROOT).as_posix() for path in agent_bundle_files(ROOT)]
            for relative in files:
                destination = root / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                source = ROOT / relative
                self.assertTrue(source.is_file(), f"required archive source is missing: {source}")
                shutil.copy2(source, destination)

            # Synthetic private checkout settings prove the archive allowlist
            # leaves local guidance and preferences behind without reading any
            # user-local configuration.
            local_agents = root / ".agents"
            local_agents.mkdir(exist_ok=True)
            (local_agents / "AGENTS.md").write_text("private note\n", encoding="utf-8")
            (local_agents / "preferences.json").write_text("{}\n", encoding="utf-8")
            (local_agents / "capability_automation.json").write_text("{}\n", encoding="utf-8")

            archive_path = build_archive(root)
            with ZipFile(archive_path) as archive:
                names = set(archive.namelist())
                self.assertIn("blender_tixl_bridge/AGENTS.md", names)
                self.assertIn("blender_tixl_bridge/.agents/skills/blender-tixl-bridge/references/sync.md", names)
                self.assertIn("blender_tixl_bridge/.agents/skills/blender-tixl-release-refresh/references/refresh.md", names)
                self.assertNotIn("blender_tixl_bridge/.agents/AGENTS.md", names)
                self.assertNotIn("blender_tixl_bridge/.agents/preferences.json", names)
                self.assertNotIn("blender_tixl_bridge/.agents/capability_automation.json", names)
                self.assertFalse(any("/.agents/" in name and "preference" in name.lower() for name in names))

                for skill in BRIDGE_SKILLS:
                    self.assertIn(f"blender_tixl_bridge/.agents/skills/{skill}/SKILL.md", names)
                for helper in OFFLINE_HELPERS:
                    self.assertIn(f"blender_tixl_bridge/tools/{helper}", names)

                route_entries = [name for name in names if name.endswith(".md")]
                self.assertTrue(route_entries)
                for entry in route_entries:
                    text = archive.read(entry).decode("utf-8")
                    for target in re.findall(r"!?\[[^\]]*\]\(([^)]+)\)", text):
                        target = target.strip().split()[0].split("#", 1)[0].split("?", 1)[0]
                        if not target or target.startswith(("http://", "https://", "mailto:")):
                            continue
                        resolved = posixpath.normpath(posixpath.join(posixpath.dirname(entry), target))
                        self.assertIn(resolved, names, f"unresolved route link from {entry}: {target}")

            (example / "BlendShapeExample.blend").write_text(
                "version https://git-lfs.github.com/spec/v1\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "check Git LFS"):
                build_archive(root)


if __name__ == "__main__":
    unittest.main()

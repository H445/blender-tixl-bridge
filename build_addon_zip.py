"""Build the versioned Blender install-from-disk ZIP from committed sources."""

import argparse
import ast
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


ROOT = Path(__file__).resolve().parent
PACKAGE = ROOT / "blender_tixl_bridge"


def addon_version(init_path=PACKAGE / "__init__.py"):
    """Read bl_info.version without importing Blender's bpy module."""
    tree = ast.parse(init_path.read_text(encoding="utf-8"), filename=str(init_path))
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(target, ast.Name) and target.id == "bl_info"
                   for target in node.targets):
            continue
        info = ast.literal_eval(node.value)
        version = info.get("version") if isinstance(info, dict) else None
        if (not isinstance(version, tuple) or len(version) != 3
                or any(isinstance(part, bool) or not isinstance(part, int) or part < 0
                       for part in version)):
            raise ValueError(f"Invalid bl_info version in {init_path}: {version!r}")
        return version
    raise ValueError(f"bl_info was not found in {init_path}")


def version_text(version):
    return ".".join(str(part) for part in version)


def archive_name(version):
    return f"blender-tixl-bridge-{version_text(version)}.zip"


def build_archive(root=ROOT):
    package = root / "blender_tixl_bridge"
    version = addon_version(package / "__init__.py")
    output = root / archive_name(version)
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        for path in sorted(package.rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc":
                archive.write(path, path.relative_to(root))
        for name in ("BlendShapeExample.blend", "README.md", "build_blend_shape_example.py",
                     "validate_blend_shape_example.py"):
            archive.write(root / "examples" / name,
                          "blender_tixl_bridge/examples/" + name)
        for path in sorted((root / "examples" / "screenshots").glob("*.png")):
            archive.write(path, "blender_tixl_bridge/examples/screenshots/" + path.name)
        # A ZIP install has no checkout path. Bundle the non-AI capability refresh
        # under the add-on so install/update/register/manual triggers still work.
        agent_files = [
            root / "AGENTS.md",
            root / ".agents" / "CAPABILITIES.md",
            root / ".agents" / "CAPABILITIES_DETAIL.md",
            root / ".agents" / "README.md",
            root / ".agents" / "capability_automation.py",
            root / ".agents" / "capability_automation.example.json",
            root / ".agents" / "rebuild_capabilities.py",
            root / ".agents" / "probes" / "blender_runtime_probe.py",
            root / ".agents" / "skills" / "blender-tixl-bridge" / "SKILL.md",
            root / ".agents" / "skills" / "blender-tixl-release-refresh" / "SKILL.md",
        ]
        # Keep the task routes usable in ZIP installations, without bundling
        # unrelated local notes, generated logs, or personal configuration.
        for skill in ("blender-tixl-bridge", "blender-tixl-release-refresh"):
            agent_files.extend(sorted(
                (root / ".agents" / "skills" / skill / "references").glob("*.md")))
        for path in agent_files:
            archive.write(path, "blender_tixl_bridge/" + path.relative_to(root).as_posix())
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", action="store_true",
                        help="print the add-on release version without building")
    args = parser.parse_args()
    version = addon_version()
    if args.version:
        print(version_text(version))
        return
    print(build_archive())


if __name__ == "__main__":
    main()

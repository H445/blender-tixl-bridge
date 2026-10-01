"""Build the versioned Blender install-from-disk ZIP from committed sources."""

import argparse
import ast
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


ROOT = Path(__file__).resolve().parent
PACKAGE = ROOT / "blender_tixl_bridge"
BRIDGE_SKILLS = (
    "blender-tixl-bridge", "blender-tixl-release-refresh", "blender-tixl-audio",
    "blender-tixl-offline-sync", "blender-tixl-graph-edit", "blender-tixl-graph-layout",
)
OFFLINE_HELPERS = (
    "layout_tixl_graph.py", "connected_graph_layout.py",
    "audit_tixl_audio.py", "music_stem_mastering.py",
)


def agent_bundle_files(root):
    """Allowlist reusable routes and their dependencies; omit local settings."""
    files = [root / relative for relative in (
        "AGENTS.md", ".agents/CAPABILITIES.md", ".agents/CAPABILITIES_DETAIL.md",
        ".agents/README.md", ".agents/capability_automation.py", ".agents/bridge_diagnostics.py",
        ".agents/capability_automation.example.json", ".agents/rebuild_capabilities.py",
        ".agents/probes/blender_runtime_probe.py",
        "docs/USER_GUIDE.md", "docs/BRIDGE_REFERENCE.md", "docs/AGENTIC_WORKFLOW.md",
        "examples/advanced_spaceship/audio/README.md",
    )]
    for skill in BRIDGE_SKILLS:
        folder = root / ".agents" / "skills" / skill
        files.append(folder / "SKILL.md")
        files.extend(sorted((folder / "references").glob("*.md")))
    files.extend(root / "tools" / name for name in OFFLINE_HELPERS)
    files.extend(root / "docs" / "screenshots" / name for name in (
        "blender-plugin.png", "blender-preferences.png", "tixl-graph.png",
        "tixl-graph-detail.png", "sdf-probe.png",
    ))
    return files


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


def verify_blend_example(path):
    with path.open("rb") as source:
        header = source.read(7)
        if header != b"BLENDER" and not header.startswith(b"\x28\xb5\x2f\xfd"):
            raise ValueError(f"Bundled example is not a Blender file (check Git LFS): {path}")


def build_archive(root=ROOT):
    package = root / "blender_tixl_bridge"
    version = addon_version(package / "__init__.py")
    verify_blend_example(root / "examples" / "BlendShapeExample.blend")
    output = root / archive_name(version)
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        for path in sorted(package.rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc":
                archive.write(path, path.relative_to(root))
        for name in ("BlendShapeExample.blend", "README.md", "build_blend_shape_example.py",
                     "validate_blend_shape_example.py"):
            path = root / "examples" / name
            target = "blender_tixl_bridge/examples/" + name
            if name == "README.md" and "## BlendShapeExample" in path.read_text(encoding="utf-8"):
                # The large scene demos and their recipes are checkout assets.
                example_text = path.read_text(encoding="utf-8").partition("## BlendShapeExample")[2]
                archive.writestr(target, "# Bundled example\n\nAdditional scene demos and recipes are available in the "
                                 f"[source workspace](https://github.com/H445/blender-tixl-bridge/tree/v{version_text(version)}/examples)."
                                 "\n\n## BlendShapeExample" + example_text)
            else:
                archive.write(path, target)
        for path in sorted((root / "examples" / "screenshots").glob("*.png")):
            archive.write(path, "blender_tixl_bridge/examples/screenshots/" + path.name)
        # A ZIP install has no checkout path. Bundle the non-AI capability refresh
        # under the add-on so install/update/register/manual triggers still work.
        agent_files = agent_bundle_files(root)
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

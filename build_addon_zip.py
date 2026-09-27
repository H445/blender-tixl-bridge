"""Build the Blender install-from-disk ZIP from the committed package."""
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

root = Path(__file__).resolve().parent
package = root / "blender_tixl_bridge"
output = root / "blender_tixl_bridge.zip"
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
        root / ".agents" / "CAPABILITIES.md",
        root / ".agents" / "README.md",
        root / ".agents" / "capability_automation.py",
        root / ".agents" / "capability_automation.example.json",
        root / ".agents" / "rebuild_capabilities.py",
        root / ".agents" / "probes" / "blender_runtime_probe.py",
        root / ".agents" / "skills" / "blender-tixl-bridge" / "SKILL.md",
        root / ".agents" / "skills" / "blender-tixl-release-refresh" / "SKILL.md",
    ]
    for path in agent_files:
        archive.write(path, "blender_tixl_bridge/" + path.relative_to(root).as_posix())
print(output)

"""Copy this checkout's bridge add-on into Blender and enable it.

Run with Blender itself:
    blender --background --python install_blender_addon.py -- [options]
"""

import argparse
import hashlib
import importlib
import os
import shutil
import sys
import traceback
from pathlib import Path

import addon_utils
import bpy


def arguments():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--operator-project", type=Path, help="Folder containing a TiXL .csproj")
    parser.add_argument("--editor-dir", type=Path, help="Folder containing TiXL.exe")
    parser.add_argument("--connection-mode", choices=("AUTO", "OFFLINE", "DEBUG"))
    return parser.parse_args(argv)


def package_files(folder):
    return sorted(path for path in folder.rglob("*") if path.is_file()
                  and "__pycache__" not in path.parts and path.suffix != ".pyc")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    args = arguments()
    source = Path(__file__).resolve().parent / "blender_tixl_bridge"
    if not (source / "__init__.py").is_file():
        raise RuntimeError(f"Add-on source missing: {source}")

    addons = Path(bpy.utils.user_resource("SCRIPTS", path="addons", create=True)).resolve()
    target = addons / source.name
    if target.parent.resolve() != addons or target.name != "blender_tixl_bridge":
        raise RuntimeError(f"Unexpected add-on destination: {target}")

    # Migrate the former module name before disabling its save handlers.
    legacy = bpy.context.preferences.addons.get("tixl_blender_bridge")
    migrated = {}
    if legacy is not None:
        for prop in legacy.preferences.bl_rna.properties:
            if prop.identifier != "rna_type" and not prop.is_readonly:
                migrated[prop.identifier] = getattr(legacy.preferences, prop.identifier)
        addon_utils.disable("tixl_blender_bridge", default_set=True)

    # Disable an older loaded copy before replacing its Python files.
    previously_enabled = source.name in bpy.context.preferences.addons
    if previously_enabled:
        addon_utils.disable(source.name, default_set=False)
    target.mkdir(parents=True, exist_ok=True)
    source_files = package_files(source)
    updated = 0
    for file in source_files:
        installed = target / file.relative_to(source)
        if not installed.is_file() or digest(file) != digest(installed):
            installed.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(file, installed)
            updated += 1
        if digest(file) != digest(installed):
            raise RuntimeError(f"Installed file differs from source: {installed}")

    bpy.utils.refresh_script_paths()
    importlib.invalidate_caches()
    for name in list(sys.modules):
        if name == source.name or name.startswith(source.name + "."):
            del sys.modules[name]
    addon_utils.modules_refresh()
    addon_utils.enable(source.name, default_set=True, persistent=True)
    addon = bpy.context.preferences.addons.get(source.name)
    if addon is None:
        raise RuntimeError("Blender did not enable the installed add-on")

    preferences = addon.preferences
    if not previously_enabled:
        for name, value in migrated.items():
            if hasattr(preferences, name):
                setattr(preferences, name, value)
    if args.operator_project:
        project = args.operator_project.resolve()
        if not any(project.glob("*.csproj")):
            raise RuntimeError(f"No .csproj found in {project}")
        preferences.operator_project = str(project)
    if args.editor_dir:
        editor = args.editor_dir.resolve()
        if not (editor / "TiXL.exe").is_file():
            raise RuntimeError(f"TiXL.exe not found in {editor}")
        preferences.editor_directory = str(editor)
    if args.connection_mode:
        preferences.connection_mode = args.connection_mode
    repository = Path(__file__).resolve().parent
    if (repository / ".agents" / "capability_automation.py").is_file():
        preferences.capability_repository = str(repository)
    if (migrated or not previously_enabled or args.operator_project or args.editor_dir
            or args.connection_mode or preferences.capability_repository):
        bpy.ops.wm.save_userpref()

    module = sys.modules[source.name]
    loaded = Path(module.__file__).resolve()
    if loaded != (target / "__init__.py").resolve():
        raise RuntimeError(f"Blender loaded the wrong copy: {loaded}")
    print(f"Installed and enabled {module.bl_info['name']} {module.bl_info['version']}")
    print(f"Blender add-on: {loaded}")
    print(f"Verified {len(source_files)} package files against this checkout ({updated} updated)")
    print(f"TiXL operator project: {preferences.operator_project}")
    print(f"TiXL Editor folder: {preferences.editor_directory}")
    print(f"TiXL connection: {preferences.connection_mode}")
    print(f"Agent capability repository: {preferences.capability_repository}")
    if hasattr(module, "queue_capability_refresh"):
        ok, message = module.queue_capability_refresh(force=True)
        print(f"Agent capabilities: {message}")
        if not ok:
            raise RuntimeError(message)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(1)  # Blender otherwise exits successfully after a Python exception.

"""Read-only Blender capability probe. Execute this file through Blender MCP."""

import json
import importlib
import tomllib
from pathlib import Path

import bpy


def _version(value):
    return ".".join(str(part) for part in value)


addon = bpy.context.preferences.addons.get("blender_tixl_bridge")
module = None
if addon is not None:
    try:
        module = __import__("blender_tixl_bridge")
    except Exception:
        module = None

operator_namespace = getattr(bpy.ops, "tixl_bridge", None)
operators = []
if operator_namespace is not None:
    operators = sorted(name for name in dir(operator_namespace) if not name.startswith("_"))

mcp_extension = None
for enabled_addon in bpy.context.preferences.addons:
    addon_name = enabled_addon.module
    if addon_name == "mcp" or addon_name.endswith(".mcp"):
        extension_module = importlib.import_module(addon_name)
        manifest_path = Path(extension_module.__file__).resolve().parent / "blender_manifest.toml"
        manifest = tomllib.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.is_file() else {}
        extension_preferences = enabled_addon.preferences
        mcp_extension = {
            "module": addon_name,
            "version": manifest.get("version", "unknown"),
            "host": getattr(extension_preferences, "host", None),
            "port": getattr(extension_preferences, "port", None),
            "autostart": getattr(extension_preferences, "use_autostart", None),
        }
        break

payload = {
    "blenderVersion": bpy.app.version_string,
    "blenderVersionTuple": list(bpy.app.version),
    "pythonVersion": _version(__import__("sys").version_info[:3]),
    "background": bool(bpy.app.background),
    "addonEnabled": addon is not None,
    "addonVersion": list(getattr(module, "bl_info", {}).get("version", ())) if module else None,
    "bridgeOperators": operators,
    "sceneHasAutosyncProperty": hasattr(bpy.context.scene, "tixl_bridge_autosync"),
    "canExecutePython": True,
    "canReadScene": bpy.context.scene is not None,
    "canOpenAndSaveBlend": hasattr(bpy.ops.wm, "open_mainfile") and hasattr(bpy.ops.wm, "save_mainfile"),
    "canRender": hasattr(bpy.ops.render, "render"),
    "blenderMcpTcpExtension": mcp_extension,
}

result = payload

print("BLENDER_TIXL_CAPABILITIES_BEGIN")
print(json.dumps(payload, indent=2, sort_keys=True))
print("BLENDER_TIXL_CAPABILITIES_END")

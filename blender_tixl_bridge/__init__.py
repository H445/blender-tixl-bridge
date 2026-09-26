"""Save-driven Blender to TiXL bridge. The .blend is the authored source."""

bl_info = {
    "name": "Prismal Labs Blender → TiXL Bridge",
    "author": "Prismal Labs",
    "version": (1, 3, 0),
    "blender": (4, 3, 0),
    "location": "Scene Properties > TiXL Bridge",
    "description": "Build TiXL geometry, animation, camera and graph from a saved .blend",
    "category": "Import-Export",
}

import os
import subprocess
from pathlib import Path

import bpy
from bpy.app.handlers import persistent
from bpy.props import BoolProperty, EnumProperty, IntProperty, StringProperty

ROOT = Path(__file__).resolve().parent
SYNC = ROOT / "source" / "blend_sync.py"
CAPABILITY_SCRIPT = Path(".agents") / "capability_automation.py"


def settings():
    return bpy.context.preferences.addons[__package__].preferences


def bundled_python():
    version = f"{bpy.app.version[0]}.{bpy.app.version[1]}"
    suffix = "python.exe" if os.name == "nt" else "python3"
    candidate = Path(bpy.app.binary_path).parent / version / "python" / "bin" / suffix
    return candidate if candidate.is_file() else None


def capability_repository():
    """Return the checkout containing the non-AI capability automation."""
    try:
        configured = Path(bpy.path.abspath(settings().capability_repository))
    except (KeyError, AttributeError, TypeError):
        configured = Path()
    candidates = [configured] if str(configured) not in ("", ".") else []
    candidates.extend((ROOT, ROOT.parent))
    environment = os.environ.get("BLENDER_TIXL_BRIDGE_REPOSITORY")
    if environment:
        candidates.insert(0, Path(environment))
    for candidate in candidates:
        if (candidate / CAPABILITY_SCRIPT).is_file():
            return candidate.resolve()
    return None


def tixl_source_for(editor):
    """Find a source checkout above an Editor build directory when present."""
    editor = editor.resolve()
    for candidate in (editor, *editor.parents):
        if (candidate / "Editor" / "App" / "DebugProtocol" / "DebugServer.cs").is_file():
            return candidate
    return None


def queue_capability_refresh(force=False):
    """Start a fingerprinted capability refresh without blocking Blender."""
    repository = capability_repository()
    if repository is None:
        return False, "Set Agent capability repository to this bridge checkout"
    python = bundled_python()
    if python is None:
        return False, "Blender's bundled Python was not found"
    script = repository / CAPABILITY_SCRIPT
    command = [str(python), str(script), "once"]
    if force:
        command.append("--force")
    env = dict(os.environ)
    env["BLENDER_EXECUTABLE"] = bpy.app.binary_path
    try:
        prefs = settings()
        editor = Path(bpy.path.abspath(prefs.editor_directory))
        if (editor / "TiXL.exe").is_file():
            env["TIXL_EXECUTABLE"] = str(editor / "TiXL.exe")
            source = tixl_source_for(editor)
            if source:
                env["TIXL_SOURCE"] = str(source)
        env["TIXL_BRIDGE_PORT"] = str(prefs.debug_port)
    except (KeyError, AttributeError, TypeError):
        pass
    log = repository / ".agents" / "capability_plugin.log"
    output = log.open("a", encoding="utf-8")
    try:
        subprocess.Popen(command, cwd=str(repository), env=env, stdout=output,
                         stderr=subprocess.STDOUT,
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                         close_fds=True)
    finally:
        output.close()
    return True, f"Agent capability refresh queued; log: {log}"


def refresh_after_register():
    ok, message = queue_capability_refresh()
    print(f"TiXL Bridge: {message}")
    return None


def queue_sync():
    blend = Path(bpy.data.filepath)
    if not blend.is_file():
        return False, "Save the Blender file first"
    prefs = settings()
    python = bundled_python()
    if python is None:
        return False, "Blender's bundled Python was not found"
    project = Path(bpy.path.abspath(prefs.operator_project))
    editor = Path(bpy.path.abspath(prefs.editor_directory))
    if not next(project.glob("*.csproj"), None) or not (editor / "TiXL.exe").is_file():
        return False, "Set the TiXL operator project and Editor folder in add-on preferences"
    queue_capability_refresh()
    logdir = blend.parent / ".tixl_cache" / blend.stem / "sync_logs"
    logdir.mkdir(parents=True, exist_ok=True)
    output = (logdir / "latest.log").open("a", encoding="utf-8")
    env = dict(os.environ)
    env.update(TIXL_BRIDGE_OPERATOR_PROJECT=str(project), TIXL_BRIDGE_EDITOR=str(editor),
               TIXL_BRIDGE_BLENDER=bpy.app.binary_path,
               TIXL_BRIDGE_MODE=prefs.connection_mode.lower(),
               TIXL_BRIDGE_PORT=str(prefs.debug_port))
    try:
        subprocess.Popen([str(python), str(SYNC), "sync", "--blend", str(blend)],
                         cwd=str(ROOT), env=env, stdout=output, stderr=subprocess.STDOUT,
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), close_fds=True)
    finally:
        output.close()
    return True, f"TiXL sync queued; log: {logdir / 'latest.log'}"


@persistent
def on_save(_):
    if any(scene.tixl_bridge_autosync for scene in bpy.data.scenes):
        ok, message = queue_sync()
        print(f"TiXL Bridge: {message}")


class TIXLBRIDGE_preferences(bpy.types.AddonPreferences):
    bl_idname = __package__
    connection_mode: EnumProperty(name="TiXL connection", default="AUTO", items=(
        ("AUTO", "Auto", "Use live reload when a debug bridge is available; otherwise build offline"),
        ("OFFLINE", "Offline", "Build without a debug bridge; works with release builds"),
        ("DEBUG", "Debug bridge", "Use live reload; launch TiXL with its debug server when needed")))
    debug_port: IntProperty(name="Debug port", default=9042, min=1, max=65535)
    operator_project: StringProperty(name="TiXL operator project", subtype="DIR_PATH",
        description="TiXL project folder containing a .csproj and Symbols directory")
    editor_directory: StringProperty(name="TiXL Editor folder", subtype="DIR_PATH",
        description="Built TiXL Editor folder containing TiXL.exe")
    capability_repository: StringProperty(name="Agent capability repository", subtype="DIR_PATH",
        description="Bridge checkout containing .agents/capability_automation.py")

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "operator_project")
        layout.prop(self, "editor_directory")
        layout.prop(self, "connection_mode")
        if self.connection_mode != "OFFLINE":
            layout.prop(self, "debug_port")
        layout.label(text="Set these once; each .blend gets its own generated TiXL project.")
        layout.separator()
        layout.prop(self, "capability_repository")
        layout.operator("tixl_bridge.refresh_agent_capabilities")
        layout.label(text="Refresh is automatic on add-on load and before sync.")


class TIXLBRIDGE_OT_sync_now(bpy.types.Operator):
    bl_idname = "tixl_bridge.sync_saved_blend"
    bl_label = "Sync saved .blend to TiXL"
    bl_description = "Queue a background rebuild of the saved Blender project"

    def execute(self, context):
        ok, message = queue_sync()
        self.report({"INFO" if ok else "ERROR"}, message)
        return {"FINISHED"} if ok else {"CANCELLED"}


class TIXLBRIDGE_OT_refresh_capabilities(bpy.types.Operator):
    bl_idname = "tixl_bridge.refresh_agent_capabilities"
    bl_label = "Refresh agent capabilities"
    bl_description = "Re-probe Blender, Blender MCP, TiXL, and the TiXL debug bridge"

    def execute(self, context):
        ok, message = queue_capability_refresh(force=True)
        self.report({"INFO" if ok else "ERROR"}, message)
        return {"FINISHED"} if ok else {"CANCELLED"}


class TIXLBRIDGE_PT_scene(bpy.types.Panel):
    bl_label = "TiXL Bridge"
    bl_idname = "TIXLBRIDGE_PT_scene"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "scene"

    def draw(self, context):
        self.layout.prop(context.scene, "tixl_bridge_autosync", text="Sync after save")
        self.layout.operator("tixl_bridge.sync_saved_blend")
        self.layout.operator("tixl_bridge.refresh_agent_capabilities")
        self.layout.label(text="The .blend is the source; exports are generated.")


CLASSES = (TIXLBRIDGE_preferences, TIXLBRIDGE_OT_sync_now,
           TIXLBRIDGE_OT_refresh_capabilities, TIXLBRIDGE_PT_scene)


def register():
    bpy.types.Scene.tixl_bridge_autosync = BoolProperty(name="Sync after save", default=False)
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    if on_save not in bpy.app.handlers.save_post:
        bpy.app.handlers.save_post.append(on_save)
    if not bpy.app.background and not bpy.app.timers.is_registered(refresh_after_register):
        bpy.app.timers.register(refresh_after_register, first_interval=2.0)


def unregister():
    if bpy.app.timers.is_registered(refresh_after_register):
        bpy.app.timers.unregister(refresh_after_register)
    if on_save in bpy.app.handlers.save_post:
        bpy.app.handlers.save_post.remove(on_save)
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
    del bpy.types.Scene.tixl_bridge_autosync

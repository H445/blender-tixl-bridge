"""Save-driven Blender to TiXL bridge. The .blend is the authored source."""

bl_info = {
    "name": "Prismal Labs Blender → TiXL Bridge",
    "author": "Prismal Labs",
    "version": (0, 4, 0),
    "blender": (4, 3, 0),
    "location": "Scene Properties > TiXL Bridge",
    "description": "Build TiXL geometry, animation, camera and graph from a saved .blend",
    "category": "Import-Export",
}

import os
import subprocess
import sys
import time
import types
import uuid
from pathlib import Path

import bpy
from .source.sync_metrics import RunMetrics, count, phase
from .source.sync_queue import LatestRequestQueue, get_or_create_queue, normalize_pending_log_paths
from bpy.app.handlers import persistent
from bpy.props import BoolProperty, EnumProperty, IntProperty, StringProperty

ROOT = Path(__file__).resolve().parent
SYNC = ROOT / "source" / "blend_sync.py"
CAPABILITY_SCRIPT = Path(".agents") / "capability_automation.py"
_SYNC_QUEUE_KEY = "tixl_bridge.latest_request_queue.v1"
_SYNC_RUNTIME_MODULE = "_tixl_bridge_sync_runtime_v1"


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


def queue_capability_refresh(force=False, metrics_env=None):
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
    if metrics_env:
        env.update(metrics_env)
    env["BLENDER_EXECUTABLE"] = bpy.app.binary_path
    for enabled_addon in bpy.context.preferences.addons:
        if enabled_addon.module == "mcp" or enabled_addon.module.endswith(".mcp"):
            mcp_preferences = enabled_addon.preferences
            env["BLENDER_MCP_TRANSPORT"] = "tcp"
            env["BLENDER_MCP_HOST"] = str(getattr(mcp_preferences, "host", "127.0.0.1"))
            env["BLENDER_MCP_PORT"] = str(getattr(mcp_preferences, "port", 9876))
            break
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
    detail = repository / ".agents" / "capability_logs" / (uuid.uuid4().hex + ".log")
    command = [str(python), str(ROOT / "source" / "logged_process.py"),
               "--log", str(detail), "--latest-log", str(log), "--prune-logs", "--", *command]
    subprocess.Popen(command, cwd=str(repository), env=env, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL,
                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), close_fds=True)
    count("discoveryProcesses")
    return True, f"Agent capability refresh queued; log: {log}"


def _launch_sync_request(request):
    """Launch one sync child when the per-source queue makes it active."""
    # Pending requests can have been captured by a previous add-on version.
    request["logPath"] = str(Path(request["logPath"]).parent / (request["runId"] + ".log"))
    env = dict(request["env"])
    env["TIXL_SYNC_LOG"] = request["logPath"]
    with RunMetrics(Path(request["metricsDirectory"]), "queue", request["runId"]) as run:
        env.update(run.environment())
        env["TIXL_SYNC_QUEUED_AT"] = str(request["queuedAt"])
        with phase("discovery_launch"):
            queue_capability_refresh(metrics_env=env)
        with phase("queue"):
            command = [request["command"][0], str(ROOT / "source" / "logged_process.py"),
                       "--log", request["logPath"], "--latest-log",
                       str(Path(request["logPath"]).parent / "latest.log"), "--prune-logs", "--", *request["command"]]
            child = subprocess.Popen(command, cwd=request["cwd"], env=env,
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), close_fds=True)
            count("orchestratorProcesses")
    return child



def _sync_queue():
    """Get the queue retained across add-on reloads and .blend file loads."""
    runtime = sys.modules.get(_SYNC_RUNTIME_MODULE)
    if runtime is None:
        runtime = types.ModuleType(_SYNC_RUNTIME_MODULE)
        sys.modules[_SYNC_RUNTIME_MODULE] = runtime
    queue = get_or_create_queue(runtime.__dict__, _SYNC_QUEUE_KEY,
                               lambda: LatestRequestQueue(_launch_sync_request, max_launch_attempts=3),
                               launch=_launch_sync_request)
    normalize_pending_log_paths(queue)
    return queue


def _poll_sync_queue():
    runtime = sys.modules.get(_SYNC_RUNTIME_MODULE)
    queue = runtime.__dict__.get(_SYNC_QUEUE_KEY) if runtime else None
    if queue is None:
        return None
    if queue.poll():
        return 0.5
    # Keep the manager in a private runtime module, but let Blender discard
    # this timer when all children and retryable requests have drained.
    queue.timer_registered = False
    return None


def _ensure_sync_queue_timer(queue):
    runtime = sys.modules.get(_SYNC_RUNTIME_MODULE)
    if runtime is None:
        return
    if queue.timer_registered:
        return
    callback = runtime.__dict__.get("timer_callback")
    if callback and bpy.app.timers.is_registered(callback):
        queue.timer_registered = True
        return
    callback = callback or _poll_sync_queue
    runtime.__dict__["timer_callback"] = callback
    bpy.app.timers.register(callback, first_interval=0.1, persistent=True)
    queue.timer_registered = True


def refresh_after_register():
    ok, message = queue_capability_refresh()
    print(f"TiXL Bridge: {message}")
    return None


def queue_sync():
    queued_at = time.time()
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
    logdir = blend.parent / ".tixl_cache" / blend.stem / "sync_logs"
    logdir.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env.update(TIXL_BRIDGE_OPERATOR_PROJECT=str(project), TIXL_BRIDGE_EDITOR=str(editor),
               TIXL_BRIDGE_BLENDER=bpy.app.binary_path,
               TIXL_BRIDGE_MODE=prefs.connection_mode.lower(),
               TIXL_BRIDGE_PORT=str(prefs.debug_port))
    run_id = uuid.uuid4().hex
    request = {
        "source": str(blend.resolve()),
        "command": [str(python), str(SYNC), "sync", "--blend", str(blend)],
        "cwd": str(ROOT),
        "env": env,
        "queuedAt": queued_at,
        "runId": run_id,
        "metricsDirectory": str(logdir.parent / "sync_metrics"),
        "logPath": str(logdir / (run_id + ".log")),
        "statusPath": str(logdir / "sync_status.json"),
    }
    queue = _sync_queue()
    status = queue.submit(request)
    _ensure_sync_queue_timer(queue)
    if status["status"] == "error":
        return True, (f"TiXL sync request retained after a launch error; status: "
                      f"{logdir / 'sync_status.json'}; log: {logdir / 'latest.log'}")
    if status["pending"] is not None:
        return True, (f"TiXL sync queued behind the active sync; the newest save will run next. "
                      f"Status: {logdir / 'sync_status.json'}; log: {logdir / 'latest.log'}")
    return True, f"TiXL sync queued; status: {logdir / 'sync_status.json'}; log: {logdir / 'latest.log'}"


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
        blend = bpy.data.filepath
        if blend:
            status = _sync_queue().snapshot(blend)
            if status:
                self.layout.label(text=f"Last sync: {status['status']}")
                if status["pending"]:
                    self.layout.label(text="A newer saved version is queued")
        self.layout.label(text="The .blend is the source; exports are generated.")


CLASSES = (TIXLBRIDGE_preferences, TIXLBRIDGE_OT_sync_now,
           TIXLBRIDGE_OT_refresh_capabilities, TIXLBRIDGE_PT_scene)


def register():
    _sync_queue()  # Refresh launch code while retaining in-flight save ownership.
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
    # Do not unregister the sync queue timer or terminate its child. The queue
    # lives in a private sys.modules runtime and remains polled through add-on
    # unregister/re-register and saved-file loads.
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
    del bpy.types.Scene.tixl_bridge_autosync

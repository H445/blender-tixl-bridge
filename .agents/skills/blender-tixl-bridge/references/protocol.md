## TiXL debug bridge

TiXL must be running with `--debug-server 9042` or the configured port. The server binds to `127.0.0.1`. The repository client sends one JSON-lines request per connection and raises on any `{ok:false}` response.

```python
import sys
from pathlib import Path

source = Path(r"<repository>\blender_tixl_bridge\source")
sys.path.insert(0, str(source))
from tixl_bridge import call

port = 9042
print(call("getVersion", port))
```

Use a generous timeout for compilation or screenshots: `call("reload", port, timeout=300, project="ProjectName")`.

### Read-only inspection and diagnostics

| Method | Important parameters | Use |
| --- | --- | --- |
| `ping` | none | Confirm that the main-thread request queue responds. |
| `getVersion` | none | Read protocol and editor versions; always call first. |
| `getStructureVersion` | none | Detect symbol-structure changes. |
| `getContext` | none | Read open composition, path, selection, output pin, time, BPM, and playback state. |
| `getGraphState` | `compositionId?`, `includeDefaults?` | Read children, positions, inputs, connections, unresolved children, and unresolved connections. |
| `getGraphView` | none | Read canvas scale, scroll, visible area, and window bounds. |
| `getOutput` | `childId?`, `outputName?` or `outputId?`, `update?`, `dumpObj?` | Evaluate scalar/vector/string/bool outputs or inspect mesh counts, bounds, manifoldness, and volume. |
| `getLogTail` | `sinceSeq?`, `minLevel?`, `maxCount?` | Read incremental debug/info/warning/error entries. Track `latestSeq`. |
| `getMetrics` | none | Read FPS, frame delta, managed memory, render stats, and GPU memory. |
| `screenshot` | `path`, `target="output"|"ui"` | Save the rendered output texture or editor-rendered UI without OS screen capture. |
| `screenshotWindow` | `path`, `region?="graph"` | Capture the editor client area or graph canvas. |

`screenshot target="output"` requires a renderable pinned output. Use PNG unless a smaller JPEG is deliberately desired. A screenshot is evidence to inspect, never an input-control mechanism.

### Project, graph-view, and evaluation control

| Method | Important parameters | Use |
| --- | --- | --- |
| `openProject` | `name` or `symbolId`, `pinOutput?` | Open a project; short names match display names with namespaces. |
| `select` | `childId?`, `childIds?`, `add?` | Replace/add selection; no IDs clears it. |
| `focusGraphView` | `childIds?`, `all?`, `includeMissing?`, `padding?`, `smooth?` | Frame specific nodes, selection, or the whole graph. |
| `setGraphView` | `area?`; or `centerX?`, `centerY?`, `scale?`, `zoomBy?`, `scrollByX?`, `scrollByY?`, `smooth?` | Set the graph camera exactly. |
| `pin` | `childId` | Pin a child instance in the output window. |
| `setTime` | `timeInSecs` or `timeInBars` | Move the playhead. |
| `setPlayback` | `playing` or `speed` | Pause, play, or change playback speed. |
| `pumpFrames` | `count` (1–100000) | Advance deterministic editor frames after state changes. |
| `outputSetup` | `entity?`, `mode?` | Drive the output window's setup state through the protocol. |
| `resetView` | none | Reset the output view. |

After `openProject`, `setTime`, `pin`, graph-view changes, or graph mutations, pump two or three frames before evaluating or capturing. Preserve the original time and playback state from `getContext` and restore them when a diagnostic task is complete.

### Graph creation and mutation

| Method | Important parameters | Use |
| --- | --- | --- |
| `setInput` | `childId`, `inputName` or `inputId`, `value`, `compositionId?` | Set typed input values with undo support. |
| `addOp` | `symbolName` or `symbolId`, `posX?`, `posY?`, `compositionId?` | Add an operator. Prefer `symbolId` when a name is ambiguous. |
| `connect` | `sourceChildId`, `sourceOutput?`, `targetChildId`, `targetInput?`, `multiInputIndex?`, `compositionId?` | Add a type-checked, cycle-checked connection. |
| `deleteOp` | `childId`, `compositionId?` | Delete an operator with undo support. |
| `setBypass` | `childId`, `bypassed?`, `compositionId?` | Bypass or re-enable a compatible operator. |
| `undo` / `redo` | none | Traverse the TiXL undo stack. |
| `reload` | `project` | Recompile an editable project. This can block and does not reliably replace a loaded graph structure. |
| `newProject` | `name` | Create and compile a shared-resource project. Use only after collecting the user's namespace and project choices. |

For graph edits: capture `getGraphState`, make one logical mutation, pump frames, read `getGraphState` again, evaluate the affected output, and inspect `getLogTail`. If verification fails, use `undo` and confirm the rollback. Do not assume an in-memory edit has been persisted when there is no explicit save command; coordinate saving with the end user.

`shutdown` exits TiXL and discards unsaved changes. Never call it without explicit user authorization and a confirmed save. `stallMainThread` is a test-only fault-injection command and must not be used in normal operation. `setAgentState(state="busy"|"ready", note=...)` may advertise agent activity in the editor; clear it when finished.

### TiXL bridge call patterns

```python
# Inspect the current graph and fail on unresolved structure.
state = call("getGraphState", port, includeDefaults=False)
if state.get("missingChildren") or state.get("missingConnections"):
    raise RuntimeError("Generated graph contains unresolved structure")

# Evaluate and capture a stable frame.
context = call("getContext", port)
call("setPlayback", port, playing=False)
call("setTime", port, timeInSecs=4.0)
call("pumpFrames", port, count=3)
call("screenshot", port, path=r"<absolute-path>\output.png", target="output")
call("focusGraphView", port, all=True, padding=80)
call("pumpFrames", port, count=2)
call("screenshotWindow", port, path=r"<absolute-path>\graph.png", region="graph")

# Restore playback mode first, then its exact speed and playhead.
call("setPlayback", port, playing=context["time"]["playbackSpeed"] != 0)
call("setPlayback", port, speed=context["time"]["playbackSpeed"])
call("setTime", port, timeInSecs=context["time"]["timeInSecs"])
```

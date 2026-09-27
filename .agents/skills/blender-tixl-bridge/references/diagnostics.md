# Bounded bridge diagnostics

Use this CLI when a repeatable, compact protocol snapshot or restart-safe log follow is useful. It is separate from the Blender MCP workflow and does not replace live graph, render, or scene validation.

From the repository root, choose a private evidence directory outside the generated cache, for example:

```powershell
$evidence = Join-Path $env:LOCALAPPDATA 'TiXLBridge\diagnostics'
python .agents/bridge_diagnostics.py --mode inspect --output $evidence --port 9042
```

The default inspect mode reads the protocol version, editor context, structure counters, a fresh graph snapshot, and retained logs. It summarizes selected nodes (selection, pinned output, or the first node by default) and one-hop neighbors. Use --node <child-id> more than once to focus nodes, --node-limit and --log-limit to bound displayed records, and --port for a non-default debug port. It does not call getOutput, alter graph inputs, open projects, or change playback/time. The request/response sequence is recorded so the summary can be checked against its source evidence.

```powershell
# Follow logs without claiming that the graph was inspected again.
python .agents/bridge_diagnostics.py --mode logs --output $evidence --port 9042

# Verify a committed export cache and source blend without querying the live graph.
python .agents/bridge_diagnostics.py --mode cache --output $evidence --cache '<cache-root>'

# Explicitly capture the pinned output at two source times.
python .agents/bridge_diagnostics.py --mode inspect --output $evidence --port 9042 --capture-time 0 --capture-time 1.5
```

Every run writes a timestamped, immutable receipt.json under the evidence directory. The normal stdout result is compact and budget-limited; --full explicitly prints the full receipt, including raw graph values and local paths. Keep the evidence directory private and use --full only when the additional detail is needed. Each receipt records RPC methods, arguments, exact wire lines, response envelopes, errors, and any capture artifacts. The separate cursor.json advances after log/inspect collection completes and the receipt is durable, even when the summary is false only because retained errors or a reported gap need attention. This lets later follows proceed from the recorded tail while the earlier receipt preserves the failure.

logs mode labels the graph as not inspected. It follows a sequence anchor inferred from the last saved entry, not a server-session identifier: protocol 1 has no session ID. It rescans all warnings and errors still in the server's 4096-entry ring on each follow, so these may predate the current task. If the anchor is missing or changed, it rereads the retained tail; a sequence gap is reported and fails the summary rather than implying complete history. An initial read also reports a gap if the server has already discarded earlier entries. Cursor continuity is therefore best-effort evidence, not proof that no messages were lost.

inspect obtains a fresh graph on every run; it does not reuse a previous graph snapshot. It compares editor context and UI/symbol structure counters before and after the snapshot and fails closed if they change or are malformed. If --cache is supplied in inspect mode, the CLI verifies the committed current/previous generation marker and payload hashes, checks the source blend hash, and requires relevant live graph asset paths to resolve inside that verified generation. Cache mode verifies the committed artifacts only; it does not inspect graph state. Missing or invalid commit evidence fails closed and never falls back to an unverified legacy cache.

--capture-time is opt-in and requires an already pinned output. For each requested time, the CLI pauses playback when needed, sets the time, pumps three frames, and saves a PNG. It then attempts to restore playing mode, exact playback speed, and original time, even after capture failure. A restoration error makes the run fail and is recorded. The helper reads context immediately after restoration and fails if the observed time, playing state, or speed differs from the original (with a conservative tolerance while playback is running). Capture checks file signature, dimensions, and hash only; every capture remains marked needs visual review. Inspect the image and verify the graph and relevant logs before claiming the rendered result is correct. Do not treat PNG existence or non-empty pixels as proof of correct geometry, materials, camera, or animation.

Keep default inspection read-only. Capture temporarily changes editor state; use it only when that limited state change is appropriate, and retain the receipt so restoration evidence can be reviewed. This helper does not launch or control Blender, alter graph structure, save the project, or replace the bridge's Blender MCP / debug-client operating procedures.
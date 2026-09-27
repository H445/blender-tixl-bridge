## Automatic capability discovery

Agents do not assemble capability inputs. `.agents/capability_automation.py` performs deterministic local discovery and invokes the lower-level generator. The Blender add-on queues it:

- with `--force` after checkout installation or update;
- without force when the add-on registers after Blender starts;
- before every sync;
- with `--force` when the user clicks **Refresh agent capabilities**.

The automation fingerprints Blender, Blender MCP, TiXL, the TiXL debug bridge client/server, this add-on, and its operator contracts. It connects directly to Blender's official MCP TCP extension, using the saved extension host and port passed by the bridge add-on. It can also speak stdio MCP to obtain server version, tool descriptions, and input schemas. It speaks TiXL's local debug protocol directly and parses matching source when present. A lock prevents overlapping plugin triggers, and the state fingerprint prevents unnecessary rewrites. Both generated files must be present and match recorded hashes before cached evidence can be reused. It is a one-shot process and must not be replaced with a scheduled task, watcher, or background service.

Complete evidence can be reused for at most 30 seconds when a cheap screen finds no config, environment, endpoint, executable/source path, or monitored bridge/operator tree change. Missing or unavailable components are retried on every trigger. Cached responses state their age and expiry; a partial probe does not advance the last fully verified time. Every cache miss, manual force, and TTL expiry re-hashes all files, including files whose size and timestamp appear unchanged.

The official Blender MCP TCP extension requires no local automation configuration. For a different MCP implementation whose stdio command cannot be discovered from supported user configuration, configure it once in the ignored `.agents/capability_automation.json` using `.agents/capability_automation.example.json`. Do not place credentials in the checked-in example or capability snapshot.

Read `.agents/CAPABILITIES.md` for coverage and warnings; load `.agents/CAPABILITIES_DETAIL.md` for full schemas/contracts and investigate any new **unclassified** method. It may ask the user to click the manual refresh button if the snapshot reports a missing configured component, but it must not fabricate probe results or use Computer Use. Developers can force the same non-AI path with:

```powershell
python .agents/capability_automation.py once --force
```

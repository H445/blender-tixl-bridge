# Blender–TiXL capabilities

> Generated automatically. Do not hand-edit. The detailed evidence and complete inventories are in [CAPABILITIES_DETAIL.md](CAPABILITIES_DETAIL.md).

## Discovery coverage

| Source | Status | Evidence |
| --- | --- | --- |
| Bridge checkout | complete | add-on 0.5.5; source SHA-256 `1818c4694c60c0ac` |
| Blender installation | complete | Blender 5.2.2 LTS via MCP runtime |
| Blender runtime via MCP | complete | 5.2.2 LTS |
| Blender MCP | complete | 1 tool(s); Blender MCP TCP extension 1.0.3 |
| TiXL installation | unavailable | TiXL 4.3.0.2 |
| TiXL source | complete | matching `Editor/App/DebugProtocol/DebugServer.cs`; SHA-256 `1b3dae492cd919b4` |
| TiXL debug bridge | complete | client `1fef203b064fecf4`; server `1b3dae492cd919b4` |
| Live TiXL debug server | cached | last known {"editorVersion": "4.3.0.2", "protocolVersion": 1}; editor currently unavailable |

Unavailable live probes are retried on refresh. A `missing` component is not configured or discoverable and is not yet monitored.

## Available surface

- Blender bridge add-on: **Prismal Labs Blender → TiXL Bridge 0.5.5** (minimum Blender 4.3.0).
- Blender MCP tools: **1** discovered.
- TiXL protocol methods: **33** discovered.
- Reusable TiXL bridge operators: **12** discovered.

Warning: live TiXL probe failed: ConnectionRefusedError: [WinError 10061] No connection could be made because the target machine actively refused it.

No unclassified TiXL methods were discovered.

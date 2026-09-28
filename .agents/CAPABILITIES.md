# Blender–TiXL capabilities

> Generated automatically. Do not hand-edit. The detailed evidence and complete inventories are in [CAPABILITIES_DETAIL.md](CAPABILITIES_DETAIL.md).

## Discovery coverage

| Source | Status | Evidence |
| --- | --- | --- |
| Bridge checkout | complete | add-on 0.5.2; source SHA-256 `1a45aaa27800a5fa` |
| Blender installation | complete | Blender 5.2.2 LTS via MCP runtime |
| Blender runtime via MCP | complete | 5.2.2 LTS |
| Blender MCP | complete | 1 tool(s); Blender MCP TCP extension 1.0.3 |
| TiXL installation | complete | TiXL 4.3.0.2 |
| TiXL source | complete | matching `Editor/App/DebugProtocol/DebugServer.cs`; SHA-256 `1b3dae492cd919b4` |
| TiXL debug bridge | complete | client `1fef203b064fecf4`; server `1b3dae492cd919b4` |
| Live TiXL debug server | complete | TiXL 4.3.0.2; protocol 1; port 9042; not supported by this protocol version |

Unavailable live probes are retried on refresh. A `missing` component is not configured or discoverable and is not yet monitored.

## Available surface

- Blender bridge add-on: **Prismal Labs Blender → TiXL Bridge 0.5.2** (minimum Blender 4.3.0).
- Blender MCP tools: **1** discovered.
- TiXL protocol methods: **33** discovered.
- Reusable TiXL bridge operators: **11** discovered.

No unclassified TiXL methods were discovered.

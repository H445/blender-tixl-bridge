"""Refresh CAPABILITIES.md when Blender, Blender MCP, TiXL, or its bridge changes.

This program is deliberately independent of any AI agent. The Blender add-on
invokes ``once`` after install/update, on registration, before sync, or from its
manual refresh operator. It discovers Blender package metadata, speaks MCP
directly to the configured Blender MCP server, probes TiXL's local debug protocol,
fingerprints both bridge implementations, and only rebuilds the snapshot when
stable evidence changes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import queue
import shlex
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import tomllib
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import rebuild_capabilities as rebuild


AGENTS_DIR = Path(__file__).resolve().parent
REPOSITORY = AGENTS_DIR.parent
BRIDGE_PACKAGE = (REPOSITORY / "blender_tixl_bridge"
                  if (REPOSITORY / "blender_tixl_bridge" / "__init__.py").is_file()
                  else REPOSITORY)
DEFAULT_CONFIG = AGENTS_DIR / "capability_automation.json"
DEFAULT_STATE = AGENTS_DIR / ".capability-automation-state.json"
DEFAULT_LOG = AGENTS_DIR / "capability_automation.log"
DEFAULT_LOCK = AGENTS_DIR / ".capability-automation.lock"
DEFAULT_OUTPUT = AGENTS_DIR / "CAPABILITIES.md"
PROBE_SCRIPT = AGENTS_DIR / "probes" / "blender_runtime_probe.py"
SCHEMA_VERSION = 1
DEFAULT_BLENDER_MCP_HOST = "127.0.0.1"
DEFAULT_BLENDER_MCP_PORT = 9876


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def log(message: str, path: Path = DEFAULT_LOG) -> None:
    line = f"{utc_now()} {message}"
    print(line, flush=True)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as stream:
            stream.write(line + "\n")
    except OSError:
        pass


def read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(text, encoding="utf-8", newline="\n")
    temporary.replace(path)


def atomic_write_json(path: Path, value: Any) -> None:
    atomic_write(path, json.dumps(value, indent=2, sort_keys=True) + "\n")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def file_evidence(path: Path | None, previous: dict[str, Any] | None = None) -> dict[str, Any]:
    if path is None or not path.is_file():
        return {"status": "missing"}
    resolved = path.resolve()
    stat = resolved.stat()
    quick = {"size": stat.st_size, "mtimeNs": stat.st_mtime_ns}
    previous = previous or {}
    digest = previous.get("sha256") if all(previous.get(key) == value for key, value in quick.items()) else None
    return {
        "status": "ok",
        "path": str(resolved),
        **quick,
        "sha256": digest or sha256_file(resolved),
    }


def tree_evidence(paths: list[Path]) -> dict[str, Any]:
    digest = hashlib.sha256()
    files = sorted({path.resolve() for path in paths if path.is_file()}, key=lambda path: str(path).lower())
    for path in files:
        try:
            relative = path.relative_to(REPOSITORY.resolve()).as_posix()
        except ValueError:
            relative = path.name
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return {"status": "ok" if files else "missing", "fileCount": len(files), "sha256": digest.hexdigest()}


def command_spec(value: Any) -> dict[str, Any] | None:
    if isinstance(value, list) and value:
        return {"command": [str(part) for part in value]}
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list) and parsed:
                return {"command": [str(part) for part in parsed]}
        except ValueError:
            pass
        return {"command": shlex.split(value, posix=os.name != "nt")}
    if isinstance(value, dict):
        command = value.get("command")
        args = value.get("args", [])
        if isinstance(command, list) and command:
            return {
                "command": [str(part) for part in command],
                "cwd": value.get("cwd"),
                "env": value.get("env", {}),
            }
        if isinstance(command, str) and command:
            return {
                "command": [command, *[str(part) for part in args]],
                "cwd": value.get("cwd"),
                "env": value.get("env", {}),
            }
    return None


def _mcp_specs_in_json(value: Any) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            if key in {"mcpServers", "servers"} and isinstance(child, dict):
                for name, server in child.items():
                    spec = command_spec(server)
                    searchable = f"{name} {json.dumps(server, default=str)}".lower()
                    if spec and "blender" in searchable:
                        found.append(spec)
            found.extend(_mcp_specs_in_json(child))
    elif isinstance(value, list):
        for child in value:
            found.extend(_mcp_specs_in_json(child))
    return found


def discover_mcp_spec(config: dict[str, Any]) -> dict[str, Any] | None:
    explicit = command_spec(config.get("blenderMcp"))
    if explicit:
        explicit["source"] = "capability_automation.json"
        return explicit
    environment = os.environ.get("BLENDER_MCP_COMMAND")
    if environment:
        spec = command_spec(environment)
        if spec:
            spec["source"] = "BLENDER_MCP_COMMAND"
            return spec

    home = Path.home()
    appdata = Path(os.environ.get("APPDATA", home / "AppData/Roaming"))
    candidates = [
        home / ".claude.json",
        appdata / "Claude" / "claude_desktop_config.json",
        home / ".cursor" / "mcp.json",
    ]
    for configured in config.get("mcpDiscoveryFiles", []):
        candidates.append(Path(configured).expanduser())
    for path in candidates:
        if not path.is_file():
            continue
        try:
            specs = _mcp_specs_in_json(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            continue
        if specs:
            specs[0]["source"] = path.name
            return specs[0]

    codex_config = home / ".codex" / "config.toml"
    if codex_config.is_file():
        try:
            servers = tomllib.loads(codex_config.read_text(encoding="utf-8")).get("mcp_servers", {})
        except (OSError, ValueError):
            servers = {}
        for name, server in servers.items() if isinstance(servers, dict) else ():
            searchable = f"{name} {json.dumps(server, default=str)}".lower()
            spec = command_spec(server)
            if spec and "blender" in searchable:
                spec["source"] = "config.toml"
                return spec
    return None


def tcp_extension_spec(config: dict[str, Any]) -> dict[str, Any] | None:
    mcp_config = config.get("blenderMcp", {}) if isinstance(config.get("blenderMcp"), dict) else {}
    transport = str(mcp_config.get("transport") or os.environ.get("BLENDER_MCP_TRANSPORT") or "auto").lower()
    if transport == "stdio":
        return None
    host = str(mcp_config.get("host") or os.environ.get("BLENDER_MCP_HOST") or DEFAULT_BLENDER_MCP_HOST)
    if host.lower() == "localhost":
        host = DEFAULT_BLENDER_MCP_HOST
    port = int(mcp_config.get("port") or os.environ.get("BLENDER_MCP_PORT") or DEFAULT_BLENDER_MCP_PORT)
    return {"host": host, "port": port, "source": "Blender MCP TCP extension"}


class BlenderTcpExtensionClient:
    """Client for Blender's official null-delimited MCP extension bridge."""

    def __init__(self, host: str, port: int, timeout: float = 20.0):
        self.host = host
        self.port = port
        self.timeout = timeout

    def execute(self, code: str) -> dict[str, Any]:
        request = {"type": "execute", "strict_json": True, "code": code}
        encoded = (json.dumps(request, separators=(",", ":")) + "\0").encode("utf-8")
        with socket.create_connection((self.host, self.port), timeout=min(3, self.timeout)) as connection:
            connection.settimeout(self.timeout)
            connection.sendall(encoded)
            response = bytearray()
            while b"\0" not in response:
                chunk = connection.recv(65536)
                if not chunk:
                    raise ConnectionError("Blender MCP TCP extension closed without a response")
                response.extend(chunk)
                if len(response) > 10 * 1024 * 1024:
                    raise ValueError("Blender MCP TCP extension response exceeds 10 MiB")
        value = json.loads(bytes(response).split(b"\0", 1)[0])
        if not isinstance(value, dict):
            raise ValueError("Blender MCP TCP extension returned a non-object response")
        if value.get("status") != "ok":
            raise RuntimeError(str(value.get("message") or "Blender MCP TCP extension execution failed"))
        return value


class StdioMcpClient:
    def __init__(self, spec: dict[str, Any], timeout: float = 20.0):
        self.timeout = timeout
        command = spec["command"]
        environment = dict(os.environ)
        environment.update({str(key): str(value) for key, value in spec.get("env", {}).items()})
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        self.process = subprocess.Popen(
            command,
            cwd=spec.get("cwd") or None,
            env=environment,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            creationflags=creationflags,
        )
        self.messages: queue.Queue[dict[str, Any] | None] = queue.Queue()
        self._counter = 0
        self._reader = threading.Thread(target=self._read, daemon=True)
        self._reader.start()

    def _read(self) -> None:
        assert self.process.stdout is not None
        for line in self.process.stdout:
            try:
                message = json.loads(line)
            except ValueError:
                continue
            if isinstance(message, dict):
                self.messages.put(message)
        self.messages.put(None)

    def send(self, message: dict[str, Any]) -> None:
        if self.process.poll() is not None:
            raise RuntimeError(f"MCP server exited with code {self.process.returncode}")
        assert self.process.stdin is not None
        self.process.stdin.write(json.dumps(message, separators=(",", ":")) + "\n")
        self.process.stdin.flush()

    def request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self._counter += 1
        request_id = self._counter
        self.send({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params or {}})
        deadline = time.monotonic() + self.timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f"Timed out waiting for MCP {method}")
            try:
                message = self.messages.get(timeout=remaining)
            except queue.Empty as error:
                raise TimeoutError(f"Timed out waiting for MCP {method}") from error
            if message is None:
                raise RuntimeError("MCP server closed its stdout")
            if message.get("id") != request_id:
                continue
            if "error" in message:
                raise RuntimeError(f"MCP {method} failed: {message['error']}")
            result = message.get("result", {})
            return result if isinstance(result, dict) else {"value": result}

    def initialize(self) -> dict[str, Any]:
        result = self.request("initialize", {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "blender-tixl-capability-refresh", "version": "1"},
        })
        self.send({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})
        return result

    def list_tools(self) -> list[dict[str, Any]]:
        tools: list[dict[str, Any]] = []
        cursor = None
        while True:
            params = {"cursor": cursor} if cursor else {}
            result = self.request("tools/list", params)
            tools.extend(tool for tool in result.get("tools", []) if isinstance(tool, dict))
            cursor = result.get("nextCursor")
            if not cursor:
                return tools

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return self.request("tools/call", {"name": name, "arguments": arguments})

    def close(self) -> None:
        try:
            if self.process.stdin:
                self.process.stdin.close()
        except OSError:
            pass
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=3)


def marker_json(text: str) -> dict[str, Any] | None:
    begin = "BLENDER_TIXL_CAPABILITIES_BEGIN"
    end = "BLENDER_TIXL_CAPABILITIES_END"
    if begin not in text or end not in text:
        return None
    try:
        value = json.loads(text.split(begin, 1)[1].split(end, 1)[0])
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


def text_from_tool_result(result: dict[str, Any]) -> str:
    blocks = result.get("content", [])
    return "\n".join(str(block.get("text", "")) for block in blocks
                     if isinstance(block, dict) and block.get("type") == "text")


def python_tool(tools: list[dict[str, Any]]) -> tuple[str, str] | None:
    preferred = {"execute_blender_code", "execute_code", "run_blender_python", "run_python"}
    for tool in tools:
        name = str(tool.get("name", ""))
        description = str(tool.get("description", "")).lower()
        schema = tool.get("inputSchema", {})
        properties = schema.get("properties", {}) if isinstance(schema, dict) else {}
        code_field = next((field for field in ("code", "python_code", "script") if field in properties), None)
        if code_field and (name in preferred or ("blender" in description and "python" in description)):
            return name, code_field
    return None


def _probe_stdio_mcp(config: dict[str, Any], spec: dict[str, Any], previous: dict[str, Any],
                     previous_runtime: dict[str, Any] | None) -> tuple[dict[str, Any], dict[str, Any] | None]:
    command_path = Path(spec["command"][0])
    resolved_command = command_path if command_path.is_file() else Path(shutil.which(spec["command"][0]) or "")
    command_file = file_evidence(resolved_command if resolved_command.is_file() else None,
                                 previous.get("commandFile") if isinstance(previous, dict) else None)
    client = None
    try:
        client = StdioMcpClient(spec, timeout=float(config.get("mcpTimeoutSeconds", 30)))
        initialized = client.initialize()
        tools = client.list_tools()
        server = initialized.get("serverInfo", {})
        name = server.get("name", "Blender MCP") if isinstance(server, dict) else "Blender MCP"
        version = server.get("version", "unknown") if isinstance(server, dict) else "unknown"
        result: dict[str, Any] = {
            "status": "ok",
            "summary": f"{name} {version}",
            "source": spec.get("source", "configured command"),
            "command": spec["command"],
            "commandFile": command_file,
            "protocolVersion": initialized.get("protocolVersion"),
            "serverInfo": server,
            "tools": tools,
        }
        runtime = None
        executable = python_tool(tools)
        if executable and PROBE_SCRIPT.is_file():
            tool_name, code_field = executable
            source = PROBE_SCRIPT.read_text(encoding="utf-8")
            try:
                called = client.call_tool(tool_name, {code_field: source})
                runtime = marker_json(text_from_tool_result(called))
                if runtime:
                    result["runtimeProbe"] = "complete"
                else:
                    result["runtimeProbe"] = "no marked JSON returned"
            except Exception as error:
                result["runtimeProbe"] = f"unavailable: {type(error).__name__}"
        return result, runtime
    except Exception as error:
        retained_tools = previous.get("tools", []) if isinstance(previous, dict) else []
        retained_server = previous.get("serverInfo", {}) if isinstance(previous, dict) else {}
        return {
            "status": "error",
            "summary": f"Configured Blender MCP probe failed: {type(error).__name__}",
            "source": spec.get("source", "configured command"),
            "command": spec["command"],
            "commandFile": command_file,
            "serverInfo": retained_server,
            "tools": retained_tools,
        }, previous_runtime
    finally:
        if client:
            client.close()


def _tcp_tool_inventory() -> list[dict[str, Any]]:
    return [{
        "name": "execute_blender_code",
        "description": "Execute Python inside Blender through the official Blender MCP TCP extension.",
        "inputSchema": {
            "type": "object",
            "properties": {"code": {"type": "string", "description": "Python source to execute in Blender"}},
            "required": ["code"],
        },
    }]


def _probe_tcp_extension(config: dict[str, Any], spec: dict[str, Any], previous: dict[str, Any],
                         previous_runtime: dict[str, Any] | None) -> tuple[dict[str, Any], dict[str, Any] | None]:
    host = spec["host"]
    port = spec["port"]
    try:
        if not PROBE_SCRIPT.is_file():
            raise FileNotFoundError(PROBE_SCRIPT)
        response = BlenderTcpExtensionClient(
            host, port, timeout=float(config.get("mcpTimeoutSeconds", 30))
        ).execute(PROBE_SCRIPT.read_text(encoding="utf-8"))
        runtime = response.get("result")
        if not isinstance(runtime, dict) or not runtime:
            runtime = marker_json(str(response.get("stdout", "")))
        if not isinstance(runtime, dict) or not runtime:
            raise ValueError("Blender runtime probe returned no capability object")
        extension = runtime.get("blenderMcpTcpExtension", {})
        version = extension.get("version", "unknown") if isinstance(extension, dict) else "unknown"
        tools = _tcp_tool_inventory()
        return {
            "status": "ok",
            "summary": f"Blender MCP TCP extension {version}",
            "source": spec["source"],
            "transport": "tcp-extension",
            "host": host,
            "port": port,
            "serverInfo": {"name": "Blender MCP TCP extension", "version": version},
            "tools": tools,
            "runtimeProbe": "complete",
        }, runtime
    except Exception as error:
        retained_tools = previous.get("tools", []) if isinstance(previous, dict) else []
        retained_server = previous.get("serverInfo", {}) if isinstance(previous, dict) else {}
        return {
            "status": "unavailable",
            "summary": f"Blender MCP TCP extension is not answering {host}:{port}: {type(error).__name__}",
            "source": spec["source"],
            "transport": "tcp-extension",
            "host": host,
            "port": port,
            "serverInfo": retained_server,
            "tools": retained_tools,
        }, previous_runtime


def probe_mcp(config: dict[str, Any], previous: dict[str, Any],
              previous_runtime: dict[str, Any] | None = None) -> tuple[dict[str, Any], dict[str, Any] | None]:
    mcp_config = config.get("blenderMcp", {}) if isinstance(config.get("blenderMcp"), dict) else {}
    transport = str(mcp_config.get("transport") or os.environ.get("BLENDER_MCP_TRANSPORT") or "auto").lower()
    stdio_spec = None if transport == "tcp" else discover_mcp_spec(config)
    stdio_result = None
    if stdio_spec:
        stdio_result, runtime = _probe_stdio_mcp(config, stdio_spec, previous, previous_runtime)
        if stdio_result.get("status") == "ok":
            return stdio_result, runtime
    tcp_spec = tcp_extension_spec(config)
    if tcp_spec:
        tcp_result, runtime = _probe_tcp_extension(config, tcp_spec, previous, previous_runtime)
        if tcp_result.get("status") == "ok" or stdio_result is None:
            return tcp_result, runtime
    if stdio_result is not None:
        return stdio_result, previous_runtime
    return {
        "status": "missing",
        "summary": "No Blender MCP stdio command or TCP extension transport is enabled",
        "tools": [],
    }, previous_runtime


def winget_blender_version(package_id: str) -> str | None:
    if os.name != "nt" or not shutil.which("winget"):
        return None
    command = ["winget", "list", "--id", package_id, "--exact", "--accept-source-agreements", "--disable-interactivity"]
    try:
        completed = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=45)
    except (OSError, subprocess.TimeoutExpired):
        return None
    for line in completed.stdout.splitlines():
        fields = line.split()
        if package_id in fields:
            index = fields.index(package_id)
            if index + 1 < len(fields):
                return fields[index + 1]
    return None


def discover_blender_executable(config: dict[str, Any]) -> Path | None:
    configured = config.get("blender", {}).get("executable") if isinstance(config.get("blender"), dict) else None
    candidates = [configured, os.environ.get("BLENDER_EXECUTABLE"), os.environ.get("TIXL_BRIDGE_BLENDER"), shutil.which("blender")]
    if os.name == "nt":
        program_files = Path(os.environ.get("ProgramFiles", "C:/Program Files"))
        candidates.extend(sorted((program_files / "Blender Foundation").glob("Blender */blender.exe"), reverse=True))
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return Path(candidate).resolve()
    return None


def probe_blender(config: dict[str, Any], previous: dict[str, Any], runtime: dict[str, Any] | None) -> dict[str, Any]:
    executable = discover_blender_executable(config)
    binary = file_evidence(executable, previous.get("binary") if isinstance(previous, dict) else None)
    blender_config = config.get("blender", {}) if isinstance(config.get("blender"), dict) else {}
    package_id = str(blender_config.get("packageId") or "9PP3C07GTVRH")
    package_version = winget_blender_version(package_id)
    runtime_version = runtime.get("blenderVersion") if isinstance(runtime, dict) else None
    version = runtime_version or package_version
    if binary.get("status") != "ok" and not version:
        return {"status": "missing", "summary": "Blender executable/package was not discovered", "binary": binary}
    source = "MCP runtime" if runtime_version else (f"Windows package {package_id}" if package_version else "executable")
    return {
        "status": "ok",
        "summary": f"Blender {version or 'version unknown'} via {source}",
        "version": version,
        "packageId": package_id if package_version else None,
        "binary": binary,
        "runtime": runtime,
    }


def discover_tixl_executable(config: dict[str, Any], source: Path | None) -> Path | None:
    tixl_config = config.get("tixl", {}) if isinstance(config.get("tixl"), dict) else {}
    candidates = [tixl_config.get("executable"), os.environ.get("TIXL_EXECUTABLE")]
    if source:
        candidates.extend([
            source / "Editor/bin/Debug/net10.0-windows/TiXL.exe",
            source / "Editor/bin/Release/net10.0-windows/TiXL.exe",
        ])
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return Path(candidate).resolve()
    return None


def probe_tixl(config: dict[str, Any], previous: dict[str, Any]) -> tuple[dict[str, Any], Path | None, int]:
    tixl_config = config.get("tixl", {}) if isinstance(config.get("tixl"), dict) else {}
    configured_source = Path(tixl_config["source"]).expanduser() if tixl_config.get("source") else None
    source = rebuild.infer_tixl_source(configured_source)
    executable = discover_tixl_executable(config, source)
    binary = file_evidence(executable, previous.get("binary") if isinstance(previous, dict) else None)
    server_file = source / rebuild.DEBUG_SERVER_RELATIVE if source else None
    server = file_evidence(server_file, previous.get("debugServer") if isinstance(previous, dict) else None)
    port = int(tixl_config.get("port") or os.environ.get("TIXL_BRIDGE_PORT") or 9042)
    live = rebuild.probe_tixl(port)
    last_live = previous.get("live") if isinstance(previous, dict) else None
    if live and live.get("error") and isinstance(last_live, dict) and last_live.get("version"):
        live = {**last_live, "currentlyUnavailable": True}
    version = (live or {}).get("version") if isinstance(live, dict) else None
    if binary.get("status") != "ok" and server.get("status") != "ok" and not version:
        status = "missing"
        summary = "TiXL executable/source/debug server was not discovered"
    else:
        status = "ok"
        editor_version = version.get("editorVersion") if isinstance(version, dict) else None
        summary = f"TiXL {editor_version or 'version inferred from binary/source'}"
    return {
        "status": status,
        "summary": summary,
        "binary": binary,
        "debugServer": server,
        "live": live,
    }, source, port


def stable_component(value: Any) -> Any:
    if isinstance(value, dict):
        ignored = {"path", "mtimeNs", "summary", "currentlyUnavailable", "runtimeProbe"}
        return {key: stable_component(child) for key, child in sorted(value.items()) if key not in ignored}
    if isinstance(value, list):
        return [stable_component(child) for child in value]
    return value


def fingerprint(value: Any) -> str:
    encoded = json.dumps(stable_component(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def public_file(value: dict[str, Any]) -> dict[str, Any]:
    return {key: child for key, child in value.items() if key not in {"path", "mtimeNs"}}


def public_evidence(components: dict[str, Any]) -> dict[str, Any]:
    result = json.loads(json.dumps(components))
    for component in result.values():
        if not isinstance(component, dict):
            continue
        for key in ("binary", "debugServer", "commandFile", "client", "server"):
            if isinstance(component.get(key), dict):
                component[key] = public_file(component[key])
        if isinstance(component.get("live"), dict):
            component["liveVersion"] = component["live"].get("version")
            component["liveCurrentlyUnavailable"] = bool(component["live"].get("currentlyUnavailable"))
        component.pop("command", None)
        component.pop("tools", None)
        component.pop("runtime", None)
        component.pop("live", None)
    return {"schemaVersion": SCHEMA_VERSION, "components": result}


def bridge_evidence(tixl: dict[str, Any]) -> dict[str, Any]:
    client = file_evidence(BRIDGE_PACKAGE / "source/tixl_bridge.py")
    server = tixl.get("debugServer", {})
    protocol = ((tixl.get("live") or {}).get("version") or {}).get("protocolVersion") if isinstance(tixl.get("live"), dict) else None
    status = "ok" if client.get("status") == "ok" and (server.get("status") == "ok" or protocol is not None) else "missing"
    return {
        "status": status,
        "summary": f"client `{str(client.get('sha256', 'missing'))[:16]}`; server `{str(server.get('sha256', protocol or 'missing'))[:16]}`",
        "client": client,
        "server": server,
        "protocolVersion": protocol,
    }


def collect(config: dict[str, Any], previous: dict[str, Any]) -> tuple[dict[str, Any], Path | None, int]:
    previous_components = previous.get("components", {}) if isinstance(previous, dict) else {}
    previous_blender = previous_components.get("blender", {})
    previous_runtime = previous_blender.get("runtime") if isinstance(previous_blender, dict) else None
    mcp, runtime = probe_mcp(config, previous_components.get("blenderMcp", {}), previous_runtime)
    blender = probe_blender(config, previous_components.get("blender", {}), runtime)
    tixl, tixl_source, port = probe_tixl(config, previous_components.get("tixl", {}))
    bridge_suffixes = {".py", ".json", ".cs", ".t3", ".t3ui"}
    bridge_files = [
        path for path in BRIDGE_PACKAGE.rglob("*")
        if path.is_file()
        and path.suffix.lower() in bridge_suffixes
        and ".agents" not in path.parts
        and "__pycache__" not in path.parts
    ]
    bridge_files.extend((REPOSITORY / name for name in ("install_blender_addon.py", "build_addon_zip.py")))
    bridge = tree_evidence(bridge_files)
    bridge.update({"summary": f"bridge source `{bridge.get('sha256', '')[:16]}`"})
    components = {
        "bridge": bridge,
        "blender": blender,
        "blenderMcp": mcp,
        "tixl": tixl,
        "tixlDebugBridge": bridge_evidence(tixl),
    }
    return components, tixl_source, port


def rebuild_snapshot(config: dict[str, Any], components: dict[str, Any], tixl_source: Path | None, port: int) -> Path:
    output = Path(config.get("output") or DEFAULT_OUTPUT)
    if not output.is_absolute():
        output = (REPOSITORY / output).resolve()
    with tempfile.TemporaryDirectory(prefix="blender-tixl-capabilities-") as temporary_text:
        temporary = Path(temporary_text)
        mcp_path = temporary / "mcp-tools.json"
        blender_path = temporary / "blender-probe.json"
        evidence_path = temporary / "automation-evidence.json"
        atomic_write_json(mcp_path, components.get("blenderMcp", {}).get("tools", []))
        runtime = components.get("blender", {}).get("runtime")
        blender_argument = None
        if isinstance(runtime, dict):
            atomic_write_json(blender_path, runtime)
            blender_argument = blender_path
        atomic_write_json(evidence_path, public_evidence(components))
        args = SimpleNamespace(
            tixl_source=tixl_source,
            tixl_port=port,
            blender_probe=blender_argument,
            blender_mcp_tools=mcp_path,
            automation_evidence=evidence_path,
            output=output,
            check=False,
        )
        atomic_write(output, rebuild.render(args))
    return output


def _acquire_lock() -> int | None:
    try:
        return os.open(DEFAULT_LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        try:
            if time.time() - DEFAULT_LOCK.stat().st_mtime > 3600:
                DEFAULT_LOCK.unlink()
                return os.open(DEFAULT_LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except OSError:
            pass
        return None


def run_once(config_path: Path, force: bool = False) -> dict[str, Any]:
    lock = _acquire_lock()
    if lock is None:
        return {"changed": False, "skipped": "another capability refresh is running"}
    os.close(lock)
    try:
        return _run_once_unlocked(config_path, force)
    finally:
        DEFAULT_LOCK.unlink(missing_ok=True)


def _run_once_unlocked(config_path: Path, force: bool = False) -> dict[str, Any]:
    config = read_json(config_path, {})
    state_path = Path(config.get("state") or DEFAULT_STATE)
    if not state_path.is_absolute():
        state_path = (REPOSITORY / state_path).resolve()
    previous = read_json(state_path, {})
    components, tixl_source, port = collect(config, previous)
    current_fingerprint = fingerprint(components)
    output = Path(config.get("output") or DEFAULT_OUTPUT)
    if not output.is_absolute():
        output = (REPOSITORY / output).resolve()
    changed = force or previous.get("fingerprint") != current_fingerprint or not output.is_file()
    if changed:
        rebuilt = rebuild_snapshot(config, components, tixl_source, port)
        log(f"rebuilt {rebuilt} because monitored capability evidence changed")
    else:
        log("capability evidence unchanged")
    state = {
        "schemaVersion": SCHEMA_VERSION,
        "fingerprint": current_fingerprint,
        "lastCheckedUtc": utc_now(),
        "lastRebuiltUtc": utc_now() if changed else previous.get("lastRebuiltUtc"),
        "components": components,
    }
    atomic_write_json(state_path, state)
    return {"changed": changed, "fingerprint": current_fingerprint, "output": str(output), "components": public_evidence(components)["components"]}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("once", "status"), nargs="?", default="once")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def main() -> int:
    options = parse_args()
    config_path = options.config.resolve()
    if options.action == "status":
        config = read_json(config_path, {})
        state_path = Path(config.get("state") or DEFAULT_STATE)
        if not state_path.is_absolute():
            state_path = (REPOSITORY / state_path).resolve()
        print(json.dumps(read_json(state_path, {"status": "not yet checked"}), indent=2, sort_keys=True))
        return 0
    if options.action == "once":
        sys.path.insert(0, str(REPOSITORY / "blender_tixl_bridge" / "source"))
        from sync_metrics import phase, worker_metrics
        with worker_metrics("discovery") as metrics:
            with phase("discovery"):
                result = run_once(config_path, options.force)
            if metrics is not None:
                metrics.report["resultStatus"] = "skipped" if result.get("skipped") else ("rebuilt" if result.get("changed") else "unchanged")
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

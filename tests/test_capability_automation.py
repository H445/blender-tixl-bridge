import importlib.util
import json
import socket
import tempfile
import threading
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class CapabilityAutomationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        agents = ROOT / ".agents"
        cls.rebuild = load("test_rebuild_capabilities", agents / "rebuild_capabilities.py")
        # capability_automation imports rebuild_capabilities by its normal name.
        import sys
        sys.modules["rebuild_capabilities"] = cls.rebuild
        cls.automation = load("test_capability_automation", agents / "capability_automation.py")

    def test_marker_json_extracts_runtime_probe(self):
        text = "before\nBLENDER_TIXL_CAPABILITIES_BEGIN\n{\"blenderVersion\":\"5.2\"}\nBLENDER_TIXL_CAPABILITIES_END\nafter"
        self.assertEqual(self.automation.marker_json(text), {"blenderVersion": "5.2"})

    def test_file_fingerprint_changes_with_content(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "component.bin"
            path.write_bytes(b"one")
            first = self.automation.file_evidence(path)
            path.write_bytes(b"two-two")
            second = self.automation.file_evidence(path, first)
            self.assertNotEqual(first["sha256"], second["sha256"])

    def test_stable_fingerprint_ignores_paths_and_summaries(self):
        left = {"status": "ok", "path": "C:/one", "mtimeNs": 1, "summary": "first", "version": "1"}
        right = {"status": "ok", "path": "D:/two", "mtimeNs": 2, "summary": "second", "version": "1"}
        self.assertEqual(self.automation.fingerprint(left), self.automation.fingerprint(right))
        right["version"] = "2"
        self.assertNotEqual(self.automation.fingerprint(left), self.automation.fingerprint(right))

    def test_mcp_tool_schema_is_preserved(self):
        raw = {"tools": [{
            "name": "execute_blender_code",
            "description": "Run Python in Blender",
            "inputSchema": {"type": "object", "properties": {"code": {"type": "string"}}, "required": ["code"]},
        }]}
        tools = self.rebuild.normalize_mcp_tools(raw)
        self.assertEqual(tools[0]["inputSchema"]["required"], ["code"])
        self.assertIn("`code` (required)", self.rebuild.mcp_inputs(tools[0]))

    def test_command_spec_accepts_json_array_and_config_object(self):
        self.assertEqual(self.automation.command_spec('["server", "--stdio"]')["command"], ["server", "--stdio"])
        configured = self.automation.command_spec({"command": ["server", "--stdio"], "env": {"MODE": "test"}})
        self.assertEqual(configured["command"], ["server", "--stdio"])
        self.assertEqual(configured["env"], {"MODE": "test"})

    def test_tcp_extension_client_executes_null_delimited_request(self):
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        port = listener.getsockname()[1]
        received = {}

        def serve():
            connection, _ = listener.accept()
            with connection:
                payload = bytearray()
                while b"\0" not in payload:
                    payload.extend(connection.recv(4096))
                received.update(json.loads(bytes(payload).split(b"\0", 1)[0]))
                response = {"status": "ok", "result": {"blenderVersion": "5.2.2"}}
                connection.sendall(json.dumps(response).encode("utf-8") + b"\0")
            listener.close()

        thread = threading.Thread(target=serve)
        thread.start()
        response = self.automation.BlenderTcpExtensionClient("127.0.0.1", port).execute("result = {}")
        thread.join(timeout=2)
        self.assertFalse(thread.is_alive())
        self.assertEqual(received["type"], "execute")
        self.assertTrue(received["strict_json"])
        self.assertEqual(response["result"]["blenderVersion"], "5.2.2")

    def test_tcp_extension_defaults_and_tool_contract(self):
        spec = self.automation.tcp_extension_spec({})
        self.assertEqual(spec["host"], "127.0.0.1")
        self.assertEqual(spec["port"], 9876)
        tool = self.automation._tcp_tool_inventory()[0]
        self.assertEqual(tool["name"], "execute_blender_code")
        self.assertEqual(tool["inputSchema"]["required"], ["code"])


if __name__ == "__main__":
    unittest.main()

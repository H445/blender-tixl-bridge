import importlib.util
import json
import socket
import tempfile
import threading
import unittest
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch


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

    def test_file_digest_reuse_requires_same_resolved_path_and_stat(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            original = root / "original.bin"
            different = root / "different.bin"
            original.write_bytes(b"first")
            prior = self.automation.file_evidence(original)
            stat = original.stat()
            different.write_bytes(b"other")
            os.utime(different, ns=(stat.st_atime_ns, stat.st_mtime_ns))

            changed_path = self.automation.file_evidence(different, prior)
            self.assertNotEqual(changed_path["sha256"], prior["sha256"])

            with patch.object(self.automation, "sha256_file", side_effect=AssertionError("unchanged file re-hashed")):
                unchanged = self.automation.file_evidence(original, prior)
            self.assertEqual(unchanged["sha256"], prior["sha256"])

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

    def test_complete_recent_evidence_skips_live_probes_and_writes(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            config_path = root / "config.json"
            config = {"state": str(root / "state.json"), "output": str(root / "CAPABILITIES.md")}
            config_path.write_text(json.dumps(config), encoding="utf-8")
            output = Path(config["output"])
            output.write_text("snapshot", encoding="utf-8")
            detail_output = self.automation.rebuild.detail_output_path(output)
            detail_output.write_text("detailed snapshot", encoding="utf-8")
            contract = root / "operator.t3ui"
            contract.write_text("contract", encoding="utf-8")
            components = {
                "bridge": {"status": "ok", "fileCount": 1,
                           "_files": [{"path": str(contract), "sha256": "a"}]},
                "blenderMcp": {"status": "ok", "runtimeProbe": "complete", "tools": [{"name": "execute"}]},
                "blender": {"status": "ok", "runtime": {"blenderVersion": "5.2"}},
                "tixl": {"status": "ok", "live": {"version": {"editorVersion": "4.3"}}},
                "tixlDebugBridge": {"status": "ok"},
            }
            verified = datetime.now(timezone.utc).replace(microsecond=0)
            with patch.object(self.automation, "bridge_file_paths", return_value=[contract]), \
                 patch.object(self.automation, "discover_mcp_spec", return_value=None), \
                 patch.object(self.automation, "discover_blender_executable", return_value=None), \
                 patch.object(self.rebuild, "infer_tixl_source", return_value=None), \
                 patch.object(self.automation, "discover_tixl_executable", return_value=None):
                screen = self.automation.quick_screen(config, config_path)
                state = {
                    "components": components,
                    "fingerprint": "cached-fingerprint",
                    "outputHashes": self.automation._output_hashes(output),
                    "quickScreen": screen,
                    "lastFullyVerifiedUtc": verified.isoformat(),
                    "evidenceFreshUntilUtc": (verified + timedelta(seconds=30)).isoformat(),
                    "freshnessSeconds": 30,
                }
                state_path = Path(config["state"])
                state_path.write_text(json.dumps(state), encoding="utf-8")
                with patch.object(self.automation, "atomic_write_json", side_effect=AssertionError("cache hit wrote state")), \
                     patch.object(self.automation, "collect", side_effect=AssertionError("cache hit probed components")), \
                     patch.object(self.automation, "log"):
                    result = self.automation._run_once_unlocked(config_path)

            self.assertTrue(result["cached"])
            self.assertEqual(result["fingerprint"], "cached-fingerprint")
            self.assertEqual(result["counters"]["freshCacheHits"], 1)
            self.assertEqual(result["counters"].get("liveMcpProbes", 0), 0)
            self.assertEqual(result["counters"].get("liveTiXLProbes", 0), 0)
            self.assertEqual(result["counters"].get("stateAndReportWrites", 0), 0)
            self.assertEqual(output.read_text(encoding="utf-8"), "snapshot")
            self.assertEqual(detail_output.read_text(encoding="utf-8"), "detailed snapshot")

    def test_cache_screen_invalidates_for_operator_membership_config_and_endpoint(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            contract = root / "operator.t3ui"
            contract.write_text("one", encoding="utf-8")
            config_path = root / "config.json"
            config = {"blenderMcp": {"transport": "tcp", "host": "127.0.0.1", "port": 9876}}
            config_path.write_text(json.dumps(config), encoding="utf-8")
            with patch.object(self.automation, "bridge_file_paths", return_value=[contract]), \
                 patch.object(self.automation, "discover_mcp_spec", return_value=None), \
                 patch.object(self.automation, "discover_blender_executable", return_value=None), \
                 patch.object(self.rebuild, "infer_tixl_source", return_value=None), \
                 patch.object(self.automation, "discover_tixl_executable", return_value=None):
                original = self.automation.quick_screen(config, config_path)
                contract.write_text("two", encoding="utf-8")
                contract_changed = self.automation.quick_screen(config, config_path)
                self.assertNotEqual(original, contract_changed)
                added = root / "extra_operator.t3ui"
                added.write_text("extra", encoding="utf-8")
                with patch.object(self.automation, "bridge_file_paths", return_value=[contract, added]):
                    membership_changed = self.automation.quick_screen(config, config_path)
                self.assertNotEqual(contract_changed, membership_changed)
                config["blenderMcp"]["port"] = 9991
                config_path.write_text(json.dumps(config), encoding="utf-8")
                endpoint_changed = self.automation.quick_screen(config, config_path)
                self.assertNotEqual(membership_changed, endpoint_changed)
                config["blenderMcp"]["port"] = 9992
                config_path.write_text(json.dumps(config), encoding="utf-8")
                config_changed = self.automation.quick_screen(config, config_path)
                self.assertNotEqual(endpoint_changed, config_changed)

    def test_unavailable_evidence_is_never_reused(self):
        incomplete = {
            "bridge": {"status": "ok", "_files": [{"path": "operator.t3ui"}]},
            "blenderMcp": {"status": "unavailable", "tools": []},
            "blender": {"status": "missing"},
            "tixl": {"status": "missing"},
            "tixlDebugBridge": {"status": "missing"},
        }
        self.assertFalse(self.automation._cache_is_complete(incomplete))
        incomplete["blenderMcp"] = {"status": "ok", "runtimeProbe": "complete", "tools": [{}]}
        incomplete["blender"] = {"status": "ok", "runtime": {}}
        incomplete["tixl"] = {"status": "ok", "live": {"error": "offline"}}
        incomplete["tixlDebugBridge"] = {"status": "ok"}
        self.assertFalse(self.automation._cache_is_complete(incomplete))
        incomplete["tixl"] = {
            "status": "ok",
            "live": {"currentlyUnavailable": True, "version": {"editorVersion": "previous"}},
        }
        self.assertFalse(self.automation._cache_is_complete(incomplete))

    def test_unavailable_refresh_preserves_last_complete_verification_time(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            config_path = root / "config.json"
            state_path = root / "state.json"
            output = root / "CAPABILITIES.md"
            config = {"state": str(state_path), "output": str(output)}
            config_path.write_text(json.dumps(config), encoding="utf-8")
            output.write_text("previous report", encoding="utf-8")
            operator = root / "operator.t3ui"
            operator.write_text("contract", encoding="utf-8")
            verified = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(seconds=5)
            deadline = verified + timedelta(seconds=30)
            complete = {
                "bridge": {"status": "ok", "fileCount": 1,
                           "_files": [{"path": str(operator), "sha256": "tree"}]},
                "blenderMcp": {"status": "ok", "runtimeProbe": "complete", "tools": [{}]},
                "blender": {"status": "ok", "runtime": {"blenderVersion": "5.2"}},
                "tixl": {"status": "ok", "live": {"version": {"editorVersion": "4.3"}}},
                "tixlDebugBridge": {"status": "ok"},
            }
            state_path.write_text(json.dumps({
                "components": complete,
                "fingerprint": "last-complete-fingerprint",
                "quickScreen": {"sha256": "old-screen"},
                "lastFullyVerifiedUtc": verified.isoformat(),
                "lastFullyVerifiedFingerprint": "last-complete-fingerprint",
                "evidenceFreshUntilUtc": deadline.isoformat(),
                "freshnessSeconds": 30,
            }), encoding="utf-8")
            unavailable = json.loads(json.dumps(complete))
            unavailable["tixl"]["live"]["currentlyUnavailable"] = True
            unavailable["tixl"]["live"]["version"] = {"editorVersion": "previous"}

            with patch.object(self.automation, "quick_screen", return_value={"sha256": "new-screen"}), \
                 patch.object(self.automation, "collect", return_value=(unavailable, None, 9042)) as collect, \
                 patch.object(self.automation, "rebuild_snapshot", return_value=output), \
                 patch.object(self.automation, "log"):
                result = self.automation._run_once_unlocked(config_path)
            self.assertTrue(collect.call_args.kwargs["force"])

            state = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(result["cache"]["status"],
                             "partial verification; unavailable evidence will be retried")
            self.assertEqual(state["verificationStatus"], "partial")
            self.assertEqual(state["lastFullyVerifiedUtc"], verified.isoformat())
            self.assertEqual(state["lastFullyVerifiedFingerprint"], "last-complete-fingerprint")
            self.assertEqual(state["evidenceFreshUntilUtc"], deadline.isoformat())

    def test_forced_file_evidence_bypasses_same_stat_hash_cache(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "component.py"
            path.write_bytes(b"first")
            before = self.automation.file_evidence(path)
            stat = path.stat()
            path.write_bytes(b"other")
            os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
            ordinary = self.automation.file_evidence(path, before)
            forced = self.automation.file_evidence(path, before, force_hash=True)
            self.assertEqual(ordinary["sha256"], before["sha256"])
            self.assertNotEqual(forced["sha256"], before["sha256"])

    def test_future_verification_timestamp_expires_cache(self):
        verified = datetime.now(timezone.utc) + timedelta(minutes=5)
        future = {
            "lastFullyVerifiedUtc": verified.isoformat(),
            "evidenceFreshUntilUtc": (verified + timedelta(seconds=30)).isoformat(),
            "freshnessSeconds": 30,
        }
        self.assertIsNone(self.automation._verification_age(future, datetime.now(timezone.utc)))

    def test_quick_screen_miss_forces_full_file_hash_pass(self):
        # The unavailable-refresh test also exercises this path, but keep the
        # core rule explicit: a config/source screen miss cannot reuse hashes.
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            config_path = root / "config.json"
            state_path = root / "state.json"
            output = root / "CAPABILITIES.md"
            config = {"state": str(state_path), "output": str(output)}
            config_path.write_text(json.dumps(config), encoding="utf-8")
            output.write_text("report", encoding="utf-8")
            operator = root / "operator.t3ui"
            operator.write_text("contract", encoding="utf-8")
            verified = datetime.now(timezone.utc).replace(microsecond=0)
            components = {
                "bridge": {"status": "ok", "_files": [{"path": str(operator), "sha256": "old"}]},
                "blenderMcp": {"status": "ok", "runtimeProbe": "complete", "tools": [{}]},
                "blender": {"status": "ok", "runtime": {"blenderVersion": "5.2"}},
                "tixl": {"status": "ok", "live": {"version": {"editorVersion": "4.3"}}},
                "tixlDebugBridge": {"status": "ok"},
            }
            state_path.write_text(json.dumps({
                "components": components, "fingerprint": "old",
                "quickScreen": {"sha256": "old-screen"},
                "lastFullyVerifiedUtc": verified.isoformat(),
                "evidenceFreshUntilUtc": (verified + timedelta(seconds=30)).isoformat(),
                "freshnessSeconds": 30,
            }), encoding="utf-8")
            with patch.object(self.automation, "quick_screen", return_value={"sha256": "changed-screen"}), \
                 patch.object(self.automation, "collect", return_value=(components, None, 9042)) as collect, \
                 patch.object(self.automation, "rebuild_snapshot", return_value=output), \
                 patch.object(self.automation, "log"):
                self.automation._run_once_unlocked(config_path)
            self.assertTrue(collect.call_args.kwargs["force"])

    def test_explicit_missing_tixl_source_or_executable_blocks_fresh_cache(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            missing_source = root / "missing-tixl-source"
            missing_executable = root / "missing" / "TiXL.exe"
            cases = (
                ({"tixl": {"source": str(missing_source)}}, {}, "source"),
                ({}, {"TIXL_SOURCE": str(missing_source)}, "source"),
                ({"tixl": {"executable": str(missing_executable)}}, {}, "executable"),
                ({}, {"TIXL_EXECUTABLE": str(missing_executable)}, "executable"),
            )
            for config, environment, expected in cases:
                with self.subTest(expected=expected, configured=bool(config)):
                    with patch.dict(os.environ, environment, clear=False), \
                         patch.object(self.rebuild, "infer_tixl_source", return_value=None), \
                         patch.object(self.automation, "discover_tixl_executable", return_value=None), \
                         patch.object(self.rebuild, "probe_tixl", return_value={
                             "version": {"editorVersion": "4.3"}}):
                        evidence, _, _ = self.automation.probe_tixl(config, {})
                    self.assertTrue(evidence["currentlyUnavailable"])
                    self.assertTrue(any(expected in issue for issue in evidence["configurationIssues"]))

                    complete = {
                        "bridge": {"status": "ok", "_files": [{"path": "operator.t3ui"}]},
                        "blenderMcp": {"status": "ok", "runtimeProbe": "complete", "tools": [{}]},
                        "blender": {"status": "ok", "runtime": {"blenderVersion": "5.2"}},
                        "tixl": evidence,
                        "tixlDebugBridge": {"status": "ok"},
                    }
                    self.assertFalse(self.automation._cache_is_complete(complete))

    def test_explicit_missing_blender_executable_blocks_runtime_only_cache(self):
        with tempfile.TemporaryDirectory() as folder:
            missing = str(Path(folder) / "missing-blender.exe")
            cases = (
                ({"blender": {"executable": missing}}, {}),
                ({}, {"BLENDER_EXECUTABLE": missing}),
                ({}, {"TIXL_BRIDGE_BLENDER": missing}),
            )
            for config, environment in cases:
                with self.subTest(configured=bool(config), environment=tuple(environment)):
                    with patch.dict(os.environ, environment, clear=True), \
                         patch.object(self.automation, "discover_blender_executable", return_value=None), \
                         patch.object(self.automation, "winget_blender_version", return_value=None):
                        evidence = self.automation.probe_blender(
                            config, {}, {"blenderVersion": "5.2.2"})
                    self.assertEqual(evidence["status"], "ok")
                    self.assertTrue(evidence["currentlyUnavailable"])
                    self.assertIn("executable", evidence["configurationIssues"][0])
                    complete = {
                        "bridge": {"status": "ok", "_files": [{"path": "operator.t3ui"}]},
                        "blenderMcp": {"status": "ok", "runtimeProbe": "complete", "tools": [{}]},
                        "blender": evidence,
                        "tixl": {"status": "ok", "live": {"version": {"editorVersion": "4.3"}}},
                        "tixlDebugBridge": {"status": "ok"},
                    }
                    self.assertFalse(self.automation._cache_is_complete(complete))


if __name__ == "__main__":
    unittest.main()

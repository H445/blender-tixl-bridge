import importlib.util
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class CapabilityRenderBundleTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        agents = ROOT / ".agents"
        cls.rebuild = load("test_render_bundle_rebuild_capabilities", agents / "rebuild_capabilities.py")
        sys.modules["rebuild_capabilities"] = cls.rebuild
        cls.automation = load("test_render_bundle_capability_automation", agents / "capability_automation.py")

    def _args(self, temporary, *, probe=None, tools=None, components=None, tixl_source=None):
        root = Path(temporary)
        probe_path = root / "blender.json"
        tools_path = root / "mcp.json"
        evidence_path = root / "automation.json"
        probe_path.write_text(json.dumps(probe) if probe is not None else "null", encoding="utf-8")
        tools_path.write_text(json.dumps(tools or []), encoding="utf-8")
        evidence_path.write_text(json.dumps({"components": components or {}}), encoding="utf-8")
        return SimpleNamespace(
            tixl_source=tixl_source,
            tixl_port=None,
            blender_probe=probe_path if probe is not None else None,
            blender_mcp_tools=tools_path,
            automation_evidence=evidence_path,
            output=root / "custom-report.md",
            check=False,
        )

    def test_bundle_collects_once_and_summary_retains_coverage_warnings_and_unclassified_names(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "tixl"
            server = source / self.rebuild.DEBUG_SERVER_RELATIVE
            server.parent.mkdir(parents=True)
            server.write_text('case "getContext":\ncase "futureMethod":\n', encoding="utf-8")
            args = self._args(
                temporary,
                probe={"blenderVersion": "5.2.2"},
                tools=[{"name": "execute_blender_code", "description": "Run code",
                        "inputSchema": {"type": "object", "properties": {"code": {}},
                                        "required": ["code"]}}],
                components={
                    "blender": {"status": "ok", "summary": "Blender found"},
                    "blenderMcp": {"status": "unavailable", "summary": "transport unavailable"},
                    "tixl": {"status": "missing", "summary": "configure TiXL"},
                    "tixlDebugBridge": {"status": "missing", "summary": "bridge unavailable"},
                },
                tixl_source=source,
            )
            large_schema_marker = "SENSITIVE_SCHEMA_DETAIL_" + ("x" * 4096)
            live = {"version": {"editorVersion": "4.3", "protocolVersion": 2}, "port": 9042,
                    "capabilities": {"methods": [{
                        "name": "futureLiveMethod",
                        "inputSchema": {"properties": {"payload": {"description": large_schema_marker}}},
                    }]}}
            with patch.object(self.rebuild, "probe_tixl", return_value=live) as probe:
                summary, detail = self.rebuild.render_bundle(args)
                probe.assert_called_once_with(None)

            self.assertEqual(self.rebuild.detail_output_path(args.output).name, "custom-report_DETAIL.md")
            self.assertIn("custom-report_DETAIL.md", summary)
            self.assertIn("| Blender MCP | unavailable |", summary)
            self.assertIn("| TiXL installation | missing |", summary)
            self.assertIn("Unavailable live probes are retried", summary)
            self.assertIn("futureMethod", summary)
            self.assertIn("futureLiveMethod", summary)
            self.assertIn("1 methods advertised", summary)
            self.assertNotIn(large_schema_marker, summary)
            self.assertIn("## Blender MCP tools discovered automatically", detail)
            self.assertIn("execute_blender_code", detail)
            self.assertIn("DebugServer.cs:", detail)
            self.assertIn("futureLiveMethod", detail)
            self.assertIn(large_schema_marker, detail)
            with patch.object(self.rebuild, "probe_tixl", return_value=live):
                self.assertEqual(self.rebuild.render(args), detail)

    def test_missing_inventories_remain_explicit_in_summary_and_detail(self):
        with tempfile.TemporaryDirectory() as temporary:
            args = self._args(temporary)
            with patch.object(self.rebuild, "infer_tixl_source", return_value=None), \
                    patch.object(self.rebuild, "probe_tixl", return_value=None):
                summary, detail = self.rebuild.render_bundle(args)
            self.assertIn("| Blender runtime via MCP | unavailable |", summary)
            self.assertIn("| Blender MCP | missing |", summary)
            self.assertIn("| TiXL source | missing |", summary)
            self.assertIn("Warning: no Blender MCP tool inventory", summary)
            self.assertIn("Warning: no TiXL method inventory", summary)
            self.assertIn("No Blender MCP command was discovered", detail)
            self.assertIn("No TiXL method inventory was available", detail)

    def test_automation_publishes_and_validates_both_custom_outputs(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "capabilities.md"
            config = {"output": str(output)}
            with patch.object(self.rebuild, "render_bundle", return_value=("summary\n", "detail\n")):
                returned = self.automation.rebuild_snapshot(config, {}, None, 0)
            detail = self.rebuild.detail_output_path(output)
            self.assertEqual(returned, output)
            self.assertEqual(output.read_text(encoding="utf-8"), "summary\n")
            self.assertEqual(detail.read_text(encoding="utf-8"), "detail\n")
            state = {"outputHashes": self.automation._output_hashes(output)}
            self.assertTrue(self.automation._outputs_match_previous(output, state))
            detail.write_text("corrupt\n", encoding="utf-8")
            self.assertFalse(self.automation._outputs_match_previous(output, state))
            detail.unlink()
            self.assertFalse(self.automation._outputs_match_previous(output, state))

    def test_cli_check_requires_both_summary_and_detail_to_match(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "custom.md"
            detail = self.rebuild.detail_output_path(output)
            argv = ["rebuild_capabilities.py", "--output", str(output)]
            with patch.object(sys, "argv", argv), \
                 patch.object(self.rebuild, "render_bundle", return_value=("summary\n", "detail\n")), \
                 redirect_stdout(io.StringIO()):
                self.assertEqual(self.rebuild.main(), 0)
            self.assertEqual(output.read_text(encoding="utf-8"), "summary\n")
            self.assertEqual(detail.read_text(encoding="utf-8"), "detail\n")

            check_argv = [*argv, "--check"]
            with patch.object(sys, "argv", check_argv), \
                 patch.object(self.rebuild, "render_bundle", return_value=("summary\n", "detail\n")), \
                 redirect_stdout(io.StringIO()):
                self.assertEqual(self.rebuild.main(), 0)
            detail.write_text("stale\n", encoding="utf-8")
            with patch.object(sys, "argv", check_argv), \
                 patch.object(self.rebuild, "render_bundle", return_value=("summary\n", "detail\n")), \
                 redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                self.assertEqual(self.rebuild.main(), 1)

    def test_run_once_rebuilds_legacy_missing_and_corrupt_detail_artifacts(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config_path = root / "config.json"
            output = root / "CAPABILITIES.md"
            state_path = root / "state.json"
            config_path.write_text(json.dumps({"state": str(state_path), "output": str(output)}),
                                   encoding="utf-8")
            contract = root / "BlenderOperator.t3ui"
            contract.write_text("operator contract", encoding="utf-8")
            components = {
                "bridge": {"status": "ok", "_files": [{"path": str(contract), "sha256": "contract"}]},
                "blenderMcp": {"status": "ok", "runtimeProbe": "complete", "tools": [{"name": "run"}]},
                "blender": {"status": "ok", "runtime": {"blenderVersion": "5.2"}},
                "tixl": {"status": "ok", "live": {"version": {"editorVersion": "4.3"}}},
                "tixlDebugBridge": {"status": "ok"},
            }
            refreshes = []

            def rebuild(config, _components, _source, _port):
                refreshes.append(len(refreshes) + 1)
                self.automation.atomic_write(
                    self.rebuild.detail_output_path(output), f"detail {len(refreshes)}\n")
                self.automation.atomic_write(output, f"summary {len(refreshes)}\n")
                return output

            with patch.object(self.automation, "quick_screen", return_value={"sha256": "stable"}), \
                 patch.object(self.automation, "collect", return_value=(components, None, 9042)) as collect, \
                 patch.object(self.automation, "rebuild_snapshot", side_effect=rebuild) as rebuild_mock, \
                 patch.object(self.automation, "log"):
                first = self.automation._run_once_unlocked(config_path)
                self.assertFalse(first["cached"])
                self.assertTrue(first["changed"])
                state = json.loads(state_path.read_text(encoding="utf-8"))
                self.assertTrue(self.automation._outputs_match_previous(output, state))

                cached = self.automation._run_once_unlocked(config_path)
                self.assertTrue(cached["cached"])

                detail = self.rebuild.detail_output_path(output)
                detail.unlink()
                missing = self.automation._run_once_unlocked(config_path)
                self.assertFalse(missing["cached"])
                self.assertTrue(missing["changed"])

                detail.write_text("corrupt\n", encoding="utf-8")
                corrupt = self.automation._run_once_unlocked(config_path)
                self.assertFalse(corrupt["cached"])
                self.assertTrue(corrupt["changed"])

            self.assertEqual(collect.call_count, 3)
            self.assertEqual(rebuild_mock.call_count, 3)
            self.assertEqual(len(refreshes), 3)


if __name__ == "__main__":
    unittest.main()

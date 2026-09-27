"""Behavioral tests for the read-only bridge diagnostics prototype."""
from __future__ import annotations

import json
import math
from pathlib import Path
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / ".agents"))
import bridge_diagnostics as diagnostics


COMPOSITION = "composition-id"
NODE_A = "node-a"
NODE_B = "node-b"
NODE_C = "node-c"


def context(composition=COMPOSITION, selected=NODE_A, output=NODE_A):
    return {
        "hasOpenProject": True,
        "compositionSymbolId": composition,
        "compositionName": "DiagnosticFixture",
        "compositionPath": ["Demo", "DiagnosticFixture"],
        "selectedChildren": [{"childId": selected, "name": "Selected"}],
        "outputView": {"isPinned": True, "childId": output, "symbolName": "RenderTarget"},
        "time": {"timeInSecs": 1.25, "playbackSpeed": 0, "isPlaying": False},
    }


def graph(unresolved=False):
    value = ["ARRAY_SENTINEL"] + list(range(64))
    result = {
        "symbolId": COMPOSITION,
        "symbolName": "DiagnosticFixture",
        "children": [
            {"childId": NODE_A, "symbolId": "symbol-a", "symbolName": "Source",
             "inputs": [{"id": "input-a", "name": "Value", "isDefault": False, "value": 1.0}]},
            {"childId": NODE_B, "symbolId": "symbol-b", "symbolName": "Mesh",
             "inputs": [{"id": "array", "name": "Samples", "isDefault": False, "value": value}]},
            {"childId": NODE_C, "symbolId": "symbol-c", "symbolName": "Unselected",
             "inputs": []},
        ],
        "connections": [{"sourceParentOrChildId": NODE_A, "sourceSlotId": "out-a",
                         "targetParentOrChildId": NODE_B, "targetSlotId": "in-b"}],
    }
    if unresolved:
        result["missingChildren"] = [{"childId": "missing-node", "symbolId": "missing-symbol"}]
        result["missingConnections"] = [{"targetParentOrChildId": "missing-node"}]
    return result


def wire(method, result=None, *, ok=True, error=None, ui_version=7, frame=22,
         playback_frame=91, response_line=None):
    request = {"id": method + "-id", "method": method}
    response = {"id": request["id"], "frame": frame, "playbackFrame": playback_frame,
                "structureVersion": ui_version, "ok": ok}
    if ok:
        response["result"] = result if result is not None else {}
    else:
        response["error"] = error or {"code": "FIXTURE_ERROR", "detail": "fixture failure"}
    request_line = json.dumps(request) + "\n"
    response_line = response_line or json.dumps(response, separators=(",", ":")) + "\n"
    return {"request": request, "response": response,
            "requestLine": request_line, "responseLine": response_line}


def log_result(entries=(), *, latest=None, oldest=0):
    entries = list(entries)
    return {"entries": entries,
            "latestSeq": latest if latest is not None else max((row["seq"] for row in entries), default=-1),
            "oldestAvailableSeq": oldest}


class Caller:
    def __init__(self, scripted):
        self.scripted = list(scripted)
        self.calls = []

    def __call__(self, method, port, **params):
        self.calls.append((method, port, params))
        if not self.scripted:
            raise AssertionError("unexpected RPC " + method)
        expected, response = self.scripted.pop(0)
        if expected != method:
            raise AssertionError(f"expected RPC {expected}, got {method}")
        return response


def inspect_script(*, ctx_before=None, ctx_after=None, graph_data=None,
                   structure_before=4, structure_after=4, ui_before=7, ui_after=7,
                   version=1, logs=None):
    return [
        ("getVersion", wire("getVersion", {"protocolVersion": version, "editorVersion": "fixture"})),
        ("getContext", wire("getContext", ctx_before or context(), ui_version=ui_before)),
        ("getStructureVersion", wire("getStructureVersion", {"symbolStructureVersion": structure_before})),
        ("getGraphState", wire("getGraphState", graph_data or graph(), ui_version=ui_before)),
        ("getLogTail", wire("getLogTail", logs or log_result([{"seq": 8, "time": "10:00:00.000",
                                                                   "level": "Debug", "message": "ok"}], latest=8))),
        ("getStructureVersion", wire("getStructureVersion", {"symbolStructureVersion": structure_after})),
        ("getContext", wire("getContext", ctx_after or ctx_before or context(), ui_version=ui_after)),
    ]


class BridgeDiagnosticsTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.output = Path(self.temp.name) / "evidence"

    def receipt(self, summary):
        return json.loads(Path(summary["evidence"]).read_text(encoding="utf-8"))

    def test_inspect_uses_exact_seven_read_calls_and_compacts_target_neighbors(self):
        caller = Caller(inspect_script())
        summary = diagnostics.collect_diagnostics(self.output, caller=caller, node_ids=[NODE_A])

        self.assertTrue(summary["ok"])
        self.assertEqual(summary["callCount"], 7)
        self.assertEqual([call[0] for call in caller.calls], [
            "getVersion", "getContext", "getStructureVersion", "getGraphState",
            "getLogTail", "getStructureVersion", "getContext"])
        graph_call = next(call for call in caller.calls if call[0] == "getGraphState")
        self.assertEqual(graph_call[2], {"compositionId": COMPOSITION, "includeDefaults": False})
        self.assertEqual([node["childId"] for node in summary["graph"]["nodes"]], [NODE_A, NODE_B])
        self.assertEqual(summary["graph"]["childCount"], 3)
        self.assertEqual(summary["graph"]["connectionCount"], 1)
        compact_array = summary["graph"]["nodes"][1]["inputs"][0]["value"]
        self.assertEqual(compact_array["type"], "list")
        self.assertEqual(compact_array["count"], 65)
        self.assertNotIn("getOutput", [call[0] for call in caller.calls])
        self.assertFalse(any(call[0] in {"setInput", "connect", "addOp", "reload", "openProject"}
                             for call in caller.calls))
        self.assertNotIn("ARRAY_SENTINEL", json.dumps(summary))
        receipt = self.receipt(summary)
        self.assertIn("ARRAY_SENTINEL", json.dumps(receipt["requests"]))
        self.assertNotIn("fullEvidence", summary)

    def test_full_option_is_required_to_return_raw_receipt(self):
        summary = diagnostics.collect_diagnostics(self.output, caller=Caller(inspect_script()), full=True)
        self.assertIn("fullEvidence", summary)
        self.assertIn("ARRAY_SENTINEL", json.dumps(summary["fullEvidence"]))

    def test_unresolved_counts_are_global_and_make_summary_fail(self):
        caller = Caller(inspect_script(graph_data=graph(unresolved=True)))
        summary = diagnostics.collect_diagnostics(self.output, caller=caller, node_ids=[NODE_A])
        self.assertEqual(summary["graph"]["unresolved"]["missingChildren"]["count"], 1)
        self.assertEqual(summary["graph"]["unresolved"]["missingConnections"]["count"], 1)
        self.assertFalse(summary["ok"])

    def test_unknown_protocol_fails_before_graph_or_cursor_publication(self):
        caller = Caller(inspect_script(version=2))
        summary = diagnostics.collect_diagnostics(self.output, caller=caller)
        self.assertFalse(summary["ok"])
        self.assertIn("Unsupported protocol", " ".join(summary["errors"]))
        self.assertEqual([call[0] for call in caller.calls], ["getVersion", "getContext"])
        self.assertFalse((self.output / "cursor.json").exists())

    def test_protocol_error_keeps_complete_wire_envelope_in_receipt(self):
        raw_line = '{"id":"getVersion-id","frame":8,"playbackFrame":3,"structureVersion":2,"ok":false,"error":{"code":"NO_COMPOSITION","detail":"No focused graph"}}\n'
        error_wire = wire("getVersion", ok=False,
                          error={"code": "NO_COMPOSITION", "detail": "No focused graph"},
                          response_line=raw_line)
        summary = diagnostics.collect_diagnostics(self.output, caller=Caller([("getVersion", error_wire)]))
        self.assertFalse(summary["ok"])
        receipt = self.receipt(summary)
        self.assertEqual(receipt["requests"][0]["wire"]["responseLine"], raw_line)
        self.assertEqual(receipt["requests"][0]["wire"]["response"]["error"]["code"], "NO_COMPOSITION")
        self.assertTrue(receipt["requests"][0]["error"])

    def test_context_change_during_inspection_does_not_advance_existing_cursor(self):
        self.output.mkdir(parents=True)
        state_path = self.output / "cursor.json"
        original = {"schema": 1, "identity": {"previous": True}, "cursor": 99,
                    "anchorSha256": "old", "version": {"protocolVersion": 1}}
        diagnostics.write_json(state_path, original)
        script = inspect_script(ctx_before=context(), ctx_after=context(composition="other-comp"))
        summary = diagnostics.collect_diagnostics(self.output, caller=Caller(script))
        self.assertFalse(summary["ok"])
        self.assertIn("changed during diagnostics", " ".join(summary["errors"]))
        self.assertEqual(json.loads(state_path.read_text(encoding="utf-8")), original)

    def test_symbol_or_ui_counter_change_does_not_advance_existing_cursor(self):
        for label, script in (
                ("symbol", inspect_script(structure_before=4, structure_after=5)),
                ("ui", inspect_script(ui_before=7, ui_after=8))):
            with self.subTest(label=label), tempfile.TemporaryDirectory() as directory:
                output = Path(directory) / "evidence"
                output.mkdir()
                state_path = output / "cursor.json"
                original = {"schema": 1, "identity": {"previous": True}, "cursor": 99,
                            "anchorSha256": "old", "version": {"protocolVersion": 1}}
                diagnostics.write_json(state_path, original)
                summary = diagnostics.collect_diagnostics(output, caller=Caller(script))
                self.assertFalse(summary["ok"])
                self.assertTrue(summary["errors"])
                self.assertEqual(json.loads(state_path.read_text(encoding="utf-8")), original)

    def test_malformed_structure_counters_fail_closed(self):
        malformed_scripts = (
            inspect_script(structure_before={}, structure_after={}),
            inspect_script(ui_before={}, ui_after={}),
            inspect_script(structure_before=True, structure_after=True),
            inspect_script(ui_before="7", ui_after="7"),
        )
        for index, script in enumerate(malformed_scripts):
            with self.subTest(index=index), tempfile.TemporaryDirectory() as directory:
                summary = diagnostics.collect_diagnostics(
                    Path(directory) / "evidence", caller=Caller(script))
                self.assertFalse(summary["ok"])
                self.assertTrue(summary.get("errors"))

    def test_summary_budget_preserves_global_counts_and_raw_receipt_details(self):
        oversized = graph(unresolved=True)
        oversized["children"] = []
        requested = []
        for index in range(20):
            child_id = f"node-{index:02d}"
            requested.append(child_id)
            oversized["children"].append({
                "childId": child_id,
                "symbolId": f"symbol-{index}",
                "symbolName": "節点" * 100,
                "name": f"ノード {index} " * 80,
                "inputs": [{"id": f"入力ID {slot} " * 80,
                            "name": f"入力名 {slot} " * 100,
                            "isDefault": False,
                            "value": [index, slot, "large payload" * 50]}
                           for slot in range(12)],
            })
        oversized["connections"] = []
        oversized["missingChildren"] = [
            {"childId": f"missing-{index}", "name": f"missing child detail {index} " * 100}
            for index in range(250)]
        oversized["missingConnections"] = [
            {"targetParentOrChildId": f"absent-{index}", "sourceSlotName": "missing edge " * 100}
            for index in range(175)]
        error_rows = [{"seq": index + 1, "time": "10:00:00.000", "level": "Error",
                       "message": f"important error {index} " * 100, "sourceId": "fixture"}
                      for index in range(30)]
        caller = Caller(inspect_script(graph_data=oversized,
                                       logs=log_result(error_rows, latest=30, oldest=1)))
        summary = diagnostics.collect_diagnostics(self.output, caller=caller, node_ids=requested,
                                                   node_limit=20, log_limit=30)

        encoded = json.dumps(summary, separators=(",", ":"), allow_nan=False).encode("utf-8")
        self.assertLessEqual(len(encoded), 16 * 1024)
        self.assertEqual(summary["summaryBudgetBytes"], 16 * 1024)
        self.assertEqual(summary["graph"]["childCount"], 20)
        self.assertEqual(summary["graph"]["unresolved"]["missingChildren"]["count"], 250)
        self.assertEqual(summary["graph"]["unresolved"]["missingConnections"]["count"], 175)
        self.assertEqual(summary["logs"]["retainedErrors"], 30)
        self.assertGreater(summary["graph"]["nodesOmitted"], 0)
        self.assertGreater(summary["graph"]["unresolved"]["missingChildren"]["omitted"], 0)
        self.assertGreater(summary["logs"]["recordsOmitted"], 0)
        self.assertEqual(summary["logs"]["records"][0]["level"], "Error")

        receipt = self.receipt(summary)
        raw_graph = receipt["requests"][3]["response"]
        self.assertEqual(len(raw_graph["children"]), 20)
        self.assertEqual(len(raw_graph["missingChildren"]), 250)
        self.assertIn("入力名", raw_graph["children"][0]["inputs"][0]["name"])
        self.assertEqual(len(receipt["requests"][4]["response"]["entries"]), 30)

    def test_nonfinite_numeric_response_fails_but_receipt_preserves_safe_marker(self):
        malformed = wire("getVersion", {"protocolVersion": 1, "measurement": float("nan")})
        summary = diagnostics.collect_diagnostics(
            self.output, caller=Caller([("getVersion", malformed)]))
        self.assertFalse(summary["ok"])
        self.assertTrue(summary.get("errors"))
        receipt = self.receipt(summary)
        row = receipt["requests"][0]
        self.assertIn("error", row)
        self.assertEqual(row["response"]["measurement"], {"nonFinite": "nan"})
        self.assertEqual(row["wire"]["response"]["result"]["measurement"],
                         {"nonFinite": "nan"})

    def test_cursor_rollover_after_restart_is_reported_as_a_gap(self):
        ctx = context()
        old_cursor = 10_000
        old_anchor = {"seq": old_cursor, "time": "10:00:00.000", "level": "Debug",
                      "message": "old process anchor", "sourceId": None}
        self._write_log_cursor(ctx, old_cursor, old_anchor)
        restarted = log_result([{"seq": 500, "time": "10:05:00.000", "level": "Debug",
                                 "message": "new process retained tail", "sourceId": None}],
                               latest=500, oldest=100)
        caller = Caller([
            ("getContext", wire("getContext", ctx)),
            ("getLogTail", wire("getLogTail", restarted)),
            ("getLogTail", wire("getLogTail", restarted)),
            ("getLogTail", wire("getLogTail", log_result([], latest=500, oldest=100))),
            ("getContext", wire("getContext", ctx)),
        ])
        summary = diagnostics.collect_diagnostics(self.output, mode="logs", caller=caller)
        self.assertTrue(summary["logs"]["cursorReset"])
        self.assertTrue(summary["logs"]["gap"])
        self.assertFalse(summary["ok"])

    def test_warning_guard_rollover_beyond_cursor_is_reported_as_a_gap(self):
        ctx = context()
        cursor = 10
        anchor = {"seq": cursor, "time": "10:00:00.000", "level": "Debug",
                  "message": "cursor", "sourceId": None}
        self._write_log_cursor(ctx, cursor, anchor)
        incremental = log_result([anchor, {"seq": 11, "time": "10:00:01.000", "level": "Debug",
                                           "message": "next", "sourceId": None}], latest=11, oldest=0)
        rolled_guard = log_result([{"seq": 100, "time": "10:01:40.000", "level": "Warning",
                                    "message": "after ring rollover", "sourceId": None}],
                                  latest=5000, oldest=100)
        caller = Caller([
            ("getContext", wire("getContext", ctx)),
            ("getLogTail", wire("getLogTail", incremental)),
            ("getLogTail", wire("getLogTail", rolled_guard)),
            ("getContext", wire("getContext", ctx)),
        ])
        summary = diagnostics.collect_diagnostics(self.output, mode="logs", caller=caller)
        self.assertTrue(summary["logs"]["gap"])
        self.assertFalse(summary["ok"])

    def _write_log_cursor(self, context_value, cursor, anchor):
        self.output.mkdir(parents=True, exist_ok=True)
        identity = {"context": diagnostics.context_key(context_value), "generation": None, "port": 9042}
        diagnostics.write_json(self.output / "cursor.json", {
            "schema": 1, "identity": identity, "cursor": cursor,
            "anchorSha256": diagnostics.digest(anchor),
            "version": {"protocolVersion": 1, "editorVersion": "fixture"},
        })

    def test_log_follow_uses_four_calls_and_cursor_is_last_returned_not_latest(self):
        ctx = context()
        cursor = 10
        anchor = {"seq": cursor, "time": "10:00:00.000", "level": "Debug",
                  "message": "cursor", "sourceId": None}
        self._write_log_cursor(ctx, cursor, anchor)
        batch = [anchor, {"seq": 11, "time": "10:00:01.000", "level": "Debug",
                          "message": "next", "sourceId": None}]
        warning_guard = []
        caller = Caller([
            ("getContext", wire("getContext", ctx)),
            ("getLogTail", wire("getLogTail", log_result(batch, latest=50, oldest=0))),
            ("getLogTail", wire("getLogTail", log_result(warning_guard, latest=50, oldest=0))),
            ("getContext", wire("getContext", ctx)),
        ])
        summary = diagnostics.collect_diagnostics(self.output, mode="logs", caller=caller)
        self.assertTrue(summary["ok"])
        self.assertEqual([call[0] for call in caller.calls],
                         ["getContext", "getLogTail", "getLogTail", "getContext"])
        self.assertEqual(caller.calls[1][2], {"sinceSeq": 9, "minLevel": "debug", "maxCount": 4096})
        state = json.loads((self.output / "cursor.json").read_text(encoding="utf-8"))
        self.assertEqual(state["cursor"], 11)
        self.assertEqual(summary["logs"]["latestSeq"], 50)
        self.assertEqual(summary["graph"]["status"], "not inspected; previous graph evidence is historical")

    def test_restart_anchor_miss_still_surfaces_error_behind_old_cursor(self):
        ctx = context()
        old_cursor = 100
        old_anchor = {"seq": old_cursor, "time": "10:00:00.000", "level": "Debug",
                      "message": "old server anchor", "sourceId": None}
        self._write_log_cursor(ctx, old_cursor, old_anchor)
        new_tail = [
            {"seq": 1, "time": "10:05:00.000", "level": "Debug", "message": "new server", "sourceId": None},
            {"seq": 2, "time": "10:05:01.000", "level": "Error", "message": "failure behind old cursor", "sourceId": None},
            *[{"seq": n, "time": f"10:05:{n:02d}.000", "level": "Warning", "message": f"warning {n}", "sourceId": None}
              for n in range(3, 24)],
        ]
        caller = Caller([
            ("getContext", wire("getContext", ctx)),
            ("getLogTail", wire("getLogTail", log_result(new_tail[:2], latest=23, oldest=0))),
            ("getLogTail", wire("getLogTail", log_result(new_tail, latest=23, oldest=0))),
            ("getLogTail", wire("getLogTail", log_result(new_tail[1:], latest=23, oldest=0))),
            ("getContext", wire("getContext", ctx)),
        ])
        summary = diagnostics.collect_diagnostics(self.output, mode="logs", log_limit=4, caller=caller)
        self.assertFalse(summary["ok"])
        self.assertTrue(summary["logs"]["cursorReset"])
        self.assertEqual(summary["logs"]["retainedErrors"], 1)
        self.assertTrue(any(row["message"] == "failure behind old cursor" for row in summary["logs"]["records"]))
        self.assertEqual(summary["logs"]["newEntries"], len(new_tail))

    def test_initial_truncated_tail_is_reported_as_gap(self):
        truncated = log_result([{"seq": 100, "time": "10:00:00.000", "level": "Debug",
                                 "message": "last retained", "sourceId": None}], latest=100, oldest=50)
        caller = Caller(inspect_script(logs=truncated))
        summary = diagnostics.collect_diagnostics(self.output, caller=caller)
        self.assertTrue(summary["logs"]["gap"])
        self.assertFalse(summary["ok"])

    def test_capture_is_opt_in_and_default_inspection_never_calls_render_or_mutation_apis(self):
        caller = Caller(inspect_script())
        summary = diagnostics.collect_diagnostics(self.output, caller=caller)
        self.assertTrue(summary["ok"])
        self.assertNotIn("render", summary)
        self.assertFalse(any(name in {"screenshot", "setTime", "setPlayback", "pumpFrames"}
                             for name, _, _ in caller.calls))

    def test_explicit_capture_writes_evidence_restores_context_and_requires_visual_review(self):
        before = context()
        before["time"] = {"timeInSecs": 1.25, "playbackSpeed": 2.0, "isPlaying": True}
        script = inspect_script(ctx_before=before, ctx_after=before)

        class CaptureCaller(Caller):
            def __init__(self, scripted):
                super().__init__(scripted)
                self.delegate = Caller(scripted)
                self.context_reads = 0

            def __call__(self, method, port, **params):
                self.calls.append((method, port, params))
                if method == "getContext":
                    self.context_reads += 1
                    if self.context_reads == 2:
                        return wire(method, before)
                if method in {"setTime", "setPlayback", "pumpFrames"}:
                    return wire(method, {"accepted": True})
                if method == "screenshot":
                    png = b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\x0dIHDR" + struct.pack(">II", 320, 200)
                    Path(params["path"]).write_bytes(png)
                    return wire(method, {"path": params["path"]})
                return self.delegate(method, port, **params)

        caller = CaptureCaller(script)
        summary = diagnostics.collect_diagnostics(self.output, caller=caller, capture_times=[0.0, 1.5])
        self.assertTrue(summary["ok"], summary.get("errors"))
        self.assertEqual(summary["render"]["status"],
                         "needs visual review; file/size checks are not render verification")
        self.assertEqual([row["timeInSecs"] for row in summary["render"]["captures"]], [0.0, 1.5])
        expected_time = {"timeInSecs": 1.25, "playbackSpeed": 2.0, "isPlaying": True,
                         "timeInBars": None, "bpm": None}
        self.assertEqual(summary["context"]["timeBefore"], expected_time)
        self.assertEqual(summary["context"]["timeAfter"], expected_time)
        names = [name for name, _, _ in caller.calls]
        self.assertIn("pumpFrames", names)
        self.assertEqual(names.count("screenshot"), 2)
        restore_index = max(index for index, name in enumerate(names) if name == "screenshot") + 1
        self.assertEqual(names[restore_index:restore_index + 3], ["setPlayback", "setPlayback", "setTime"])
        self.assertEqual(caller.calls[restore_index][2], {"playing": True})
        self.assertEqual(caller.calls[restore_index + 1][2], {"speed": 2.0})
        self.assertEqual(caller.calls[restore_index + 2][2], {"timeInSecs": 1.25})
        receipt = self.receipt(summary)
        self.assertEqual(len(receipt["renderCaptures"]), 2)

    def test_capture_failure_attempts_every_restore_and_records_capture_error(self):
        before = context()
        before["time"] = {"timeInSecs": 4.5, "playbackSpeed": -1.25, "isPlaying": True}

        class FailingCaptureCaller:
            def __init__(self):
                self.scripted = inspect_script(ctx_before=before, ctx_after=before)
                self.delegate = Caller(self.scripted)
                self.calls = []
                self.context_reads = 0

            def __call__(self, method, port, **params):
                self.calls.append((method, port, params))
                if method == "getContext":
                    self.context_reads += 1
                    if self.context_reads == 2:
                        return wire(method, before)
                if method in {"setTime", "setPlayback", "pumpFrames"}:
                    return wire(method, {"accepted": True})
                if method == "screenshot":
                    raise OSError("fixture screenshot failure")
                return self.delegate(method, port, **params)

        caller = FailingCaptureCaller()
        summary = diagnostics.collect_diagnostics(self.output, caller=caller, capture_times=[2.0])
        self.assertFalse(summary["ok"])
        self.assertIn("fixture screenshot failure", " ".join(summary["errors"]))
        self.assertEqual([row[0] for row in caller.calls[-4:]],
                         ["setPlayback", "setPlayback", "setTime", "getContext"])
        self.assertEqual(caller.calls[-4][2], {"playing": True})
        self.assertEqual(caller.calls[-3][2], {"speed": -1.25})
        self.assertEqual(caller.calls[-2][2], {"timeInSecs": 4.5})
        receipt = self.receipt(summary)
        self.assertTrue(any("fixture screenshot failure" in row.get("error", "")
                            for row in receipt["requests"]))

    def test_capture_fails_when_accepted_restore_calls_do_not_restore_state(self):
        before = context()
        before["time"] = {"timeInSecs": 1.25, "playbackSpeed": 0.0, "isPlaying": False}
        after = context()
        after["time"] = {"timeInSecs": 900.0, "playbackSpeed": 0.0, "isPlaying": False}

        class StaleReadbackCaller:
            def __init__(self):
                self.delegate = Caller(inspect_script(ctx_before=before, ctx_after=before))
                self.calls = []
                self.context_reads = 0

            def __call__(self, method, port, **params):
                self.calls.append((method, port, params))
                if method == "getContext":
                    self.context_reads += 1
                    if self.context_reads == 2:
                        return wire(method, after)
                if method in {"setTime", "setPlayback", "pumpFrames"}:
                    return wire(method, {"accepted": True})
                if method == "screenshot":
                    png = b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\x0dIHDR" + struct.pack(">II", 320, 200)
                    Path(params["path"]).write_bytes(png)
                    return wire(method, {"path": params["path"]})
                return self.delegate(method, port, **params)

        caller = StaleReadbackCaller()
        summary = diagnostics.collect_diagnostics(self.output, caller=caller, capture_times=[0.0])
        self.assertFalse(summary["ok"])
        self.assertTrue(any("restoration readback failed" in error for error in summary["errors"]))
        self.assertEqual(caller.calls[-1][0], "getContext")

    def test_capture_cleanup_continues_after_keyboard_interrupt_in_restore_call(self):
        before = context()
        before["time"] = {"timeInSecs": 1.25, "playbackSpeed": 1.5, "isPlaying": True}
        calls = []

        def request(method, **params):
            calls.append((method, params))
            if method == "setPlayback" and params == {"playing": True}:
                raise KeyboardInterrupt("restore interrupted")
            if method == "screenshot":
                path = Path(params["path"])
                path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\x0dIHDR" + struct.pack(">II", 320, 200))
                return {"path": str(path)}
            if method == "getContext":
                return before
            return {"accepted": True}

        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(RuntimeError, "restore interrupted"):
                diagnostics.capture_output(request, before, [0.0], Path(directory))
        restoration = calls[-4:]
        self.assertEqual([name for name, _ in restoration],
                         ["setPlayback", "setPlayback", "setTime", "getContext"])

    def test_capture_times_are_bounded_and_finite_before_any_bridge_call(self):
        for values in ([0.0] * 65, [math.nan], [math.inf], [-math.inf]):
            with self.subTest(values=values[:1], length=len(values)), tempfile.TemporaryDirectory() as directory:
                caller = Caller([])
                with self.assertRaises(ValueError):
                    diagnostics.collect_diagnostics(Path(directory) / "evidence", caller=caller,
                                                     capture_times=values)
                self.assertEqual(caller.calls, [])


if __name__ == "__main__":
    unittest.main()

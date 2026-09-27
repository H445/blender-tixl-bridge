"""Raw and backwards-compatible TiXL debug JSON-lines client tests."""
from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "blender_tixl_bridge" / "source"))
import tixl_bridge


class Reader:
    def __init__(self, line):
        self.line = line

    def readline(self):
        return self.line


class Connection:
    def __init__(self, response_line):
        self.response_line = response_line
        self.sent = []
        self.reader = Reader(response_line)
        self.timeout = None
        self.closed = False
        self.file_args = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.closed = True

    def settimeout(self, value):
        self.timeout = value

    def sendall(self, value):
        self.sent.append(value)

    def makefile(self, *args, **kwargs):
        self.file_args = (args, kwargs)
        return self.reader


class TiXLBridgeTransportTest(unittest.TestCase):
    def test_exchange_preserves_exact_request_response_lines_and_envelope(self):
        response = {"id": "request-1", "frame": 27, "playbackFrame": 106,
                    "structureVersion": 8, "ok": True, "result": {"compositionName": "Demo"}}
        response_line = json.dumps(response, separators=(",", ":")) + "\n"
        connection = Connection(response_line)

        with patch.object(tixl_bridge.socket, "create_connection", return_value=connection), \
                patch.object(tixl_bridge.time, "time_ns", return_value=1234):
            wire = tixl_bridge.exchange("getContext", 9042, timeout=9, detail=False)

        expected_request = {"id": "1234", "method": "getContext", "detail": False}
        expected_request_line = json.dumps(expected_request) + "\n"
        self.assertEqual(wire["request"], expected_request)
        self.assertEqual(wire["requestLine"], expected_request_line)
        self.assertEqual(connection.sent, [expected_request_line.encode("utf-8")])
        self.assertEqual(wire["response"], response)
        self.assertEqual(wire["responseLine"], response_line)
        self.assertEqual(connection.timeout, 9)
        self.assertTrue(connection.closed)

    def test_call_retains_legacy_result_return_and_raises_full_api_error(self):
        success = {"id": "1", "ok": True, "result": {"x": 3}}
        connection = Connection(json.dumps(success) + "\n")
        with patch.object(tixl_bridge.socket, "create_connection", return_value=connection):
            self.assertEqual(tixl_bridge.call("getVersion", 9042), {"x": 3})

        failure = {"id": "2", "ok": False,
                   "error": {"code": "NO_COMPOSITION", "detail": "Open a project"}}
        connection = Connection(json.dumps(failure) + "\n")
        with patch.object(tixl_bridge.socket, "create_connection", return_value=connection), \
                patch.object(tixl_bridge.time, "time_ns", return_value=2):
            with self.assertRaises(RuntimeError) as raised:
                tixl_bridge.call("getGraphState", 9042)
        self.assertEqual(str(raised.exception), json.dumps(failure))

    def test_empty_server_response_is_connection_error(self):
        connection = Connection("")
        with patch.object(tixl_bridge.socket, "create_connection", return_value=connection):
            with self.assertRaisesRegex(ConnectionError, "closed without a response"):
                tixl_bridge.exchange("getContext", 9042)


if __name__ == "__main__":
    unittest.main()

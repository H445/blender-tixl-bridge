#!/usr/bin/env python3
"""Recompute a portable token/call benchmark from actual diagnostics receipts.

This script never contacts Blender or TiXL. Capture fresh receipts separately
with the read-only bridge diagnostics helper, then pass both receipt paths here.
The bundled tokenizer directory is ignored local evidence, not a project install.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TOKENIZER = ROOT / "examples/.tixl_cache/issue11_validation/tokenizer_dependencies"
EXPECTED_TIKTOKEN_VERSION = "0.11.0"
ENCODING_NAME = "o200k_base"


def canonical_digest(value):
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def sha256_bytes(value):
    return hashlib.sha256(value).hexdigest()


def load_receipt(path, expected_mode):
    path = Path(path)
    data = path.read_bytes()
    receipt = json.loads(data.decode("utf-8"))
    if not isinstance(receipt, dict) or receipt.get("schema") != 1:
        raise ValueError(f"{expected_mode} receipt must use schema 1")
    if receipt.get("mode") != expected_mode:
        raise ValueError(f"Expected a {expected_mode} receipt")
    if receipt.get("errors"):
        raise ValueError(f"{expected_mode} receipt has helper errors")
    rows = receipt.get("requests")
    if not isinstance(rows, list) or not rows:
        raise ValueError(f"{expected_mode} receipt has no request evidence")
    for row in rows:
        wire = row.get("wire", {})
        if not isinstance(wire.get("requestLine"), str) or not isinstance(wire.get("responseLine"), str):
            raise ValueError(f"{expected_mode} receipt is missing raw protocol lines")
    if not receipt.get("summary", {}).get("logs"):
        raise ValueError(f"{expected_mode} receipt has no log summary")
    return receipt, data


def wire_error_inventory(receipt):
    """Collect distinct error records from raw getLogTail response envelopes."""
    errors = {}
    for row in receipt["requests"]:
        response = row.get("wire", {}).get("response", {})
        result = response.get("result", {}) if isinstance(response, dict) else {}
        entries = result.get("entries", []) if isinstance(result, dict) else []
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict) or str(entry.get("level", "")).lower() != "error":
                continue
            seq = entry.get("seq")
            if seq is None:
                raise ValueError("Raw error entry is missing its sequence number")
            errors[seq] = {"seq": seq, "messageSha256": canonical_digest(entry.get("message"))}
    return [errors[key] for key in sorted(errors)]


def summary_error_inventory(receipt):
    records = receipt["summary"]["logs"].get("records", [])
    result = []
    for item in records:
        if str(item.get("level", "")).lower() != "error":
            continue
        message = item.get("message")
        if isinstance(message, dict) and isinstance(message.get("sha256"), str):
            digest = message["sha256"]
        else:
            digest = canonical_digest(message)
        result.append({"seq": item.get("seq"), "messageSha256": digest})
    return sorted(result, key=lambda item: item["seq"])


def token_count(encoding, text):
    return len(encoding.encode(text))


def lane_metrics(receipt, raw_receipt_bytes, encoding):
    rows = receipt["requests"]
    request_lines = [row["wire"]["requestLine"] for row in rows]
    response_lines = [row["wire"]["responseLine"] for row in rows]
    summary = receipt["summary"]
    stdout = json.dumps(summary, allow_nan=False) + "\n"
    errors_wire = wire_error_inventory(receipt)
    errors_summary = summary_error_inventory(receipt)
    if errors_wire != errors_summary:
        raise ValueError("Compact summary does not preserve every raw error entry")
    retained_error_count = summary["logs"].get("retainedErrors")
    if retained_error_count != len(errors_wire):
        raise ValueError("Retained error count does not match raw error entries")

    request_tokens = sum(token_count(encoding, line) for line in request_lines)
    response_tokens = sum(token_count(encoding, line) for line in response_lines)
    full_receipt_tokens = token_count(encoding, raw_receipt_bytes.decode("utf-8"))
    summary_tokens = token_count(encoding, stdout)
    raw_response_bytes = sum(len(line.encode("utf-8")) for line in response_lines)
    raw_request_bytes = sum(len(line.encode("utf-8")) for line in request_lines)
    return {
        "captureUtc": receipt.get("createdUtc"),
        "mode": receipt["mode"],
        "calls": len(rows),
        "methods": [row["method"] for row in rows],
        "status": "passed" if summary.get("ok") else "diagnostic findings present",
        "protocol": {
            "requestTokens": request_tokens,
            "responseTokens": response_tokens,
            "combinedTokens": request_tokens + response_tokens,
            "requestBytes": raw_request_bytes,
            "responseBytes": raw_response_bytes,
        },
        "savedFullReceipt": {
            "tokens": full_receipt_tokens,
            "bytes": len(raw_receipt_bytes),
            "sha256": sha256_bytes(raw_receipt_bytes),
        },
        "compactCliStdout": {
            "tokens": summary_tokens,
            "bytes": len(stdout.encode("utf-8")),
            "reconstructedFromReturnedSummary": True,
            "includesEvidencePathInTokenCount": True,
        },
        "consumerOutputReductionVsFullReceiptPercent": round(
            100.0 * (1.0 - summary_tokens / full_receipt_tokens), 2
        ) if full_receipt_tokens else 0.0,
        "consumerOutputReductionVsWireResponsePercent": round(
            100.0 * (1.0 - summary_tokens / response_tokens), 2
        ) if response_tokens else 0.0,
        "fullReceiptComparisonBasis": "Stored forensic receipt includes raw wire and parsed response details; it is not normal CLI stdout.",
        "errors": {
            "retainedCount": retained_error_count,
            "rawErrorRecords": errors_wire,
            "summaryErrorRecords": errors_summary,
            "allRetainedErrorsPreserved": True,
        },
        "retainedWarningCount": summary["logs"].get("retainedWarnings"),
        "graph": ({
            "validation": "captured",
            "childCount": summary.get("graph", {}).get("childCount"),
            "connectionCount": summary.get("graph", {}).get("connectionCount"),
            "unresolved": summary.get("graph", {}).get("unresolved"),
        } if receipt["mode"] == "inspect" else {
            "validation": "not repeated in logs-only follow; earlier graph snapshot is not current graph evidence"
        }),
        "renderValidation": "not measured; diagnostic evidence does not prove rendered output",
        "cursorContinuity": summary["logs"].get("cursorContinuity"),
    }


def load_encoding(tokenizer_path):
    tokenizer_path = Path(tokenizer_path).resolve()
    if not tokenizer_path.is_dir():
        raise FileNotFoundError(f"Tokenizer dependency directory not found: {tokenizer_path}")
    sys.path.insert(0, str(tokenizer_path))
    import tiktoken

    if getattr(tiktoken, "__version__", None) != EXPECTED_TIKTOKEN_VERSION:
        raise RuntimeError(f"Expected tiktoken {EXPECTED_TIKTOKEN_VERSION}, found {getattr(tiktoken, '__version__', 'unknown')}")
    return tiktoken, tiktoken.get_encoding(ENCODING_NAME)


def build_report(inspect_path, logs_path, helper_path, tokenizer_path, encoding):
    inspect_receipt, inspect_bytes = load_receipt(inspect_path, "inspect")
    logs_receipt, logs_bytes = load_receipt(logs_path, "logs")
    inspect_time = datetime.fromisoformat(inspect_receipt["createdUtc"].replace("Z", "+00:00"))
    logs_time = datetime.fromisoformat(logs_receipt["createdUtc"].replace("Z", "+00:00"))
    if logs_time <= inspect_time:
        raise ValueError("Log-follow capture must be later than the inspect capture")
    if len(inspect_receipt["requests"]) != 7 or len(logs_receipt["requests"]) != 4:
        raise ValueError("Expected the scoped 7-call inspect and 4-call log-follow captures")
    if inspect_receipt["summary"].get("mode") != "inspect" or logs_receipt["summary"].get("mode") != "logs":
        raise ValueError("Capture summaries do not match their receipt modes")

    inspect_recipe = ".agents/bridge_diagnostics.py --mode inspect --output <private-output-directory>"
    logs_recipe = ".agents/bridge_diagnostics.py --mode logs --output <same-private-output-directory>"
    helper_bytes = Path(helper_path).read_bytes()
    inspect_metrics = lane_metrics(inspect_receipt, inspect_bytes, encoding)
    logs_metrics = lane_metrics(logs_receipt, logs_bytes, encoding)
    if inspect_metrics["errors"]["rawErrorRecords"] != logs_metrics["errors"]["rawErrorRecords"]:
        raise ValueError("The two snapshots do not retain the same error records")

    result = {
        "schema": 1,
        "benchmark": "TiXL bridge diagnostics consumer-output and protocol-token comparison",
        "computedUtc": datetime.now(timezone.utc).isoformat(),
        "method": {
            "liveCalls": "Receipts were captured by direct collect_diagnostics calls using the official TiXL debug bridge; this benchmark only analyzes saved receipts.",
            "tokenizer": {"package": "tiktoken", "version": EXPECTED_TIKTOKEN_VERSION, "encoding": ENCODING_NAME},
            "tokens": "Exact request/response wire lines, complete saved receipt JSON, and the default CLI JSON serialization of the returned summary plus trailing newline are tokenized independently.",
            "inputScope": "CLI recipe tokens are a reproducible command-line argument template, not a captured model prompt or process transcript; machine paths, interpreter location, task prompt, and system instructions are excluded.",
            "sourceHashes": {
                "diagnosticsHelperSha256": sha256_bytes(helper_bytes),
                "inspectReceiptSha256": sha256_bytes(inspect_bytes),
                "logsReceiptSha256": sha256_bytes(logs_bytes),
            },
        },
        "options": {
            "port": 9042,
            "inspect": {"nodeLimit": 12, "logLimit": 12, "full": False, "cache": None, "captureTimes": []},
            "logs": {"nodeLimit": 12, "logLimit": 12, "full": False, "cache": None, "captureTimes": []},
            "logCapacity": 4096,
            "tokenizerDependencyDirectory": "ignored local dependency bundle; path omitted",
        },
        "cliInput": {
            "recipeWasExecuted": False,
            "inspectRecipe": inspect_recipe,
            "inspectRecipeTokens": token_count(encoding, inspect_recipe),
            "logsFollowRecipe": logs_recipe,
            "logsFollowRecipeTokens": token_count(encoding, logs_recipe),
        },
        "captures": {
            "inspect": inspect_metrics,
            "logsFollow": logs_metrics,
        },
        "comparisonScope": {
            "inspect": "A fresh graph/log inspection at the inspect capture time.",
            "logsFollow": "A later log-only follow on the same persisted cursor. It does not revalidate the graph and is not a repeated graph-inspection baseline.",
            "timeDeltaSeconds": (logs_time - inspect_time).total_seconds(),
            "warningsMayDiffer": "The snapshots are separated in time; newly retained warning counts may change.",
            "sharedErrorCoverage": "Both captures include the same retained error records, checked by sequence and canonical message hash. The helper reports historical retained errors and does not claim they belong to the current task.",
            "transportScope": "Wire token/byte totals include actual protocol requests and responses; they are separate from CLI input and caller-facing output tokens.",
        },
    }
    serialized = json.dumps(result, indent=2, allow_nan=False) + "\n"
    if re.search(r"[A-Za-z]:[\\/]", serialized):
        raise ValueError("Portable report unexpectedly contains an absolute Windows path")
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inspect-receipt", type=Path, required=True)
    parser.add_argument("--logs-receipt", type=Path, required=True)
    parser.add_argument("--helper", type=Path, default=ROOT / ".agents/bridge_diagnostics.py")
    parser.add_argument("--tokenizer-deps", type=Path, default=DEFAULT_TOKENIZER)
    parser.add_argument("--output", type=Path, default=ROOT / "docs/benchmarks/diagnostics-2026-09-27.json")
    args = parser.parse_args(argv)
    _, encoding = load_encoding(args.tokenizer_deps)
    report = build_report(args.inspect_receipt, args.logs_receipt, args.helper, args.tokenizer_deps, encoding)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(f"Wrote portable benchmark report: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Measure fixed documentation readsets with the pinned o200k tokenizer.

This is an evidence-generation CLI, not a hosted-CI test. It needs tiktoken
0.11.0; dependency and merge-table cache folders can be supplied locally.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys


BASELINE_REF = "f46904892e8aba2d85e1920d251bbe859f0ba30c"
CORE = ["AGENTS.md", ".agents/skills/blender-tixl-bridge/SKILL.md",
        ".agents/CAPABILITIES.md"]
TASKS = {
    "first_run_onboarding": {
        "description": "Set up a first-time user, preserve namespace choices, then follow focused sync verification.",
        "before": CORE + [".agents/README.md"],
        "after": CORE + [".agents/README.md", ".agents/skills/blender-tixl-bridge/references/sync.md"],
    },
    "sync_and_verify": {
        "description": "Sync a saved Blender source and verify installed graph structure, paths and rendered output.",
        "before": CORE,
        "after": CORE + [".agents/skills/blender-tixl-bridge/references/sync.md"],
    },
    "edit_tixl_graph": {
        "description": "Safely edit an existing TiXL graph, verify the change and restore diagnostic state.",
        "before": CORE,
        "after": CORE + [".agents/skills/blender-tixl-bridge/references/edit.md",
                          ".agents/skills/blender-tixl-bridge/references/operators.md"],
    },
    "troubleshoot_blank_or_stale_output": {
        "description": "Diagnose stale or blank output using manifests, graph state, logs and safe recovery.",
        "before": CORE,
        "after": CORE + [".agents/skills/blender-tixl-bridge/references/troubleshoot.md"],
    },
    "release_refresh": {
        "description": "Refresh capabilities, release evidence and package after an application or add-on upgrade.",
        "before": CORE + [".agents/skills/blender-tixl-release-refresh/SKILL.md",
                           ".agents/README.md", "README.md"],
        "after": CORE + [".agents/skills/blender-tixl-release-refresh/SKILL.md",
                         ".agents/skills/blender-tixl-release-refresh/references/refresh.md",
                         "README.md"],
    },
}


def _load_encoding(dependency_dir: Path | None, cache_dir: Path | None):
    if dependency_dir is not None and dependency_dir.is_dir():
        sys.path.insert(0, str(dependency_dir))
    elif dependency_dir is not None:
        raise FileNotFoundError(f"Tokenizer dependency directory is missing: {dependency_dir}")
    if cache_dir is not None:
        os.environ["TIKTOKEN_CACHE_DIR"] = str(cache_dir)
    try:
        import tiktoken
    except ImportError as error:
        raise RuntimeError(
            "Install the pinned tokenizer from the evidence instructions; "
            "tiktoken is intentionally not a CI dependency.") from error
    if getattr(tiktoken, "__file__", None) is None:
        raise RuntimeError("Imported an empty tiktoken namespace, not the installed package")
    try:
        from importlib.metadata import version
        actual_version = version("tiktoken")
    except Exception as error:
        raise RuntimeError("Could not identify the installed tiktoken version") from error
    if actual_version != "0.11.0":
        raise RuntimeError(f"Expected tiktoken 0.11.0, found {actual_version}")
    return tiktoken.get_encoding("o200k_base")


def _record(path: str, data: bytes, encoding) -> dict:
    text = data.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")
    canonical = text.encode("utf-8")
    return {"path": path, "sha256": hashlib.sha256(canonical).hexdigest(),
            "bytes": len(canonical), "tokens": len(encoding.encode_ordinary(text))}


def _count_files(paths: list[str], base: Path, encoding) -> dict:
    files = []
    for relative in paths:
        path = base / relative
        if not path.is_file():
            raise FileNotFoundError(f"Required task reference is missing: {path}")
        files.append(_record(relative, path.read_bytes(), encoding))
    return {"paths": list(paths), "files": files,
            "total_tokens": sum(row["tokens"] for row in files),
            "total_bytes": sum(row["bytes"] for row in files)}


def build_report(current_root: Path, baseline_ref: str = BASELINE_REF,
                 dependency_dir: Path | None = None, cache_dir: Path | None = None) -> dict:
    current_root = current_root.resolve()
    encoding = _load_encoding(dependency_dir, cache_dir)
    before_files: dict[str, dict] = {}
    before_paths = sorted({path for task in TASKS.values() for path in task["before"]})
    for relative in before_paths:
        data = subprocess.check_output(["git", "show", f"{baseline_ref}:{relative}"], cwd=current_root)
        before_files[relative] = _record(relative, data, encoding)

    report = {
        "schema": 1,
        "measured_at_utc": datetime.now(timezone.utc).isoformat(),
        "tokenizer": {"package": "tiktoken", "version": "0.11.0",
                      "encoding": "o200k_base", "method": "encode_ordinary"},
        "baseline_commit": baseline_ref,
        "readsets": TASKS,
        "reproduction": {
            "install": "python -m pip install --target examples/.tixl_cache/issue11_validation/tokenizer_dependencies tiktoken==0.11.0",
            "run": "python tests/benchmark_documentation_reading.py --baseline-ref " + baseline_ref +
                  " --current-root . --tokenizer-dependencies examples/.tixl_cache/issue11_validation/tokenizer_dependencies"+
                  " --tokenizer-cache examples/.tixl_cache/issue11_validation/tokenizer_cache",
        },
        "measurement_scope": (
            "Full UTF-8 Markdown bodies normalized from CRLF/CR to LF in each fixed task readset. "
            "Per-file SHA-256 and byte lengths use that canonical LF content. Counts do not include "
            "system instructions, tool/API overhead, path labels, conditional references "
            "not listed for that task, or runtime/model prompting. These are comparable "
            "documentation-body counts, not API usage or cost claims."),
        "tasks": {},
    }
    for task, definition in TASKS.items():
        before_paths = definition["before"]
        if len(before_paths) != len(set(before_paths)):
            raise ValueError(f"Duplicate baseline file in task {task}")
        before_rows = [before_files[path] for path in before_paths]
        before_total = sum(row["tokens"] for row in before_rows)
        after_result = _count_files(definition["after"], current_root, encoding)
        reduction = (before_total - after_result["total_tokens"]) / before_total * 100 if before_total else 0.0
        report["tasks"][task] = {
            "description": definition["description"],
            "before": {"paths": before_paths, "files": before_rows,
                       "total_tokens": before_total},
            "after": after_result,
            "token_reduction": before_total - after_result["total_tokens"],
            "reduction_percent": round(reduction, 2),
        }
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-ref", default=BASELINE_REF,
                        help="Full Git commit containing the original mandatory reading set")
    parser.add_argument("--current-root", type=Path, default=Path(__file__).resolve().parents[1],
                        help="Repository root with the routed documentation to count")
    parser.add_argument("--output", type=Path,
                        help="Optional JSON report destination; defaults to stdout")
    parser.add_argument("--tokenizer-dependencies", type=Path,
                        help="Optional folder containing the pinned tiktoken installation")
    parser.add_argument("--tokenizer-cache", type=Path,
                        help="Optional folder containing cached o200k_base ranks")
    args = parser.parse_args(argv)
    report = build_report(args.current_root, args.baseline_ref,
                          args.tokenizer_dependencies, args.tokenizer_cache)
    text = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
        print(args.output)
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

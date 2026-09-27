"""Drain child output to a bounded head/tail log without buffering whole runs."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

DEFAULT_LOG_BYTES = 4 * 1024 * 1024


def configured_log_bytes(cache: Path) -> int:
    """Invalid retention configuration defers cleanup, never blocks a sync."""
    try:
        path = cache / "retention_policy.json"
        value = json.loads(path.read_text(encoding="utf-8")).get("max_log_bytes", DEFAULT_LOG_BYTES)
        if isinstance(value, int) and not isinstance(value, bool) and value >= 1024:
            return value
    except (OSError, ValueError, AttributeError):
        pass
    return DEFAULT_LOG_BYTES


class BoundedLog:
    def __init__(self, path: Path, max_bytes: int = DEFAULT_LOG_BYTES):
        if max_bytes < 1024:
            raise ValueError("Log budget must be at least 1024 bytes")
        self.path = Path(path)
        self.limit = max_bytes
        self.head_limit = max_bytes // 4
        self.tail_limit = max_bytes - self.head_limit - 192
        self.total = 0
        self.head = bytearray()
        self.tail = bytearray()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.stream = self.path.open("w+b")

    def write(self, block: bytes):
        self.total += len(block)
        take = min(len(block), self.head_limit - len(self.head))
        self.head.extend(block[:take])
        self.tail.extend(block[take:])
        if len(self.tail) > self.tail_limit:
            del self.tail[:-self.tail_limit]
        self.stream.seek(0)
        self.stream.write(self.head)
        omitted = self.total - len(self.head) - len(self.tail)
        if omitted:
            self.stream.write(f"\n[bounded log: {omitted} middle bytes omitted; head and latest tail retained]\n".encode())
        self.stream.write(self.tail)
        self.stream.truncate()
        self.stream.flush()

    def close(self):
        self.stream.close()


def run_to_log(command, path: Path, *, env=None, cwd=None, max_bytes=DEFAULT_LOG_BYTES,
               latest_log: Path | None = None, completion_marker: bytes | None = None):
    log = BoundedLog(path, max_bytes)
    try:
        child = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                 env=env, cwd=cwd,
                                 creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        write_error = None
        read_error = None
        marker_seen = False
        marker_tail = b""
        try:
            while block := child.stdout.read1(64 * 1024):
                if completion_marker:
                    window = marker_tail + block
                    marker_seen |= completion_marker in window
                    marker_tail = window[-(len(completion_marker) - 1):] if len(completion_marker) > 1 else b""
                if write_error is None:
                    try:
                        log.write(block)
                    except OSError as error:
                        # Continue draining and retain process ownership even
                        # if the evidence disk fills while the child is active.
                        write_error = error
        except BaseException as error:
            read_error = error
            # The child may own its own export worker. Let it finish and reap
            # it before returning; killing only an orchestration child would
            # orphan that worker and prematurely release its cache lease.
        finally:
            try:
                try:
                    child.stdout.close()
                except BaseException as error:
                    if read_error is None:
                        read_error = error
            finally:
                while True:
                    try:
                        code = child.wait()
                        break
                    except KeyboardInterrupt as error:
                        if read_error is None:
                            read_error = error
        if read_error is not None:
            raise read_error
    finally:
        log.close()
    if write_error is not None:
        raise write_error
    temporary = None
    try:
        metadata = {"schema": 1, "exitCode": code, "outputBytes": log.total,
                    "retainedBytes": path.stat().st_size, "maxBytes": max_bytes,
                    "omittedBytes": max(0, log.total - len(log.head) - len(log.tail))}
        if completion_marker is not None:
            metadata["completionMarkerSeen"] = marker_seen
        temporary = path.with_name(path.name + ".meta.tmp")
        temporary.write_text(json.dumps(metadata), encoding="utf-8")
        os.replace(temporary, path.with_name(path.name + ".meta.json"))
        if latest_log is not None:
            temporary = latest_log.with_name(latest_log.name + "." + uuid.uuid4().hex + ".tmp")
            temporary.write_bytes(path.read_bytes())
            os.replace(temporary, latest_log)
    except OSError:
        pass  # Auxiliary metadata cannot change a completed child result.
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
    result = subprocess.CompletedProcess(command, code)
    result.completion_marker_seen = marker_seen
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--log", required=True, type=Path)
    parser.add_argument("--max-bytes", type=int, default=DEFAULT_LOG_BYTES)
    parser.add_argument("--latest-log", type=Path)
    parser.add_argument("--prune-logs", action="store_true")
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if args.max_bytes == DEFAULT_LOG_BYTES:
        args.max_bytes = configured_log_bytes(args.log.parent.parent)
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        parser.error("A child command is required")
    if args.prune_logs:
        from process_lock import process_lock
        # One-shot discovery callers can overlap. A group lease protects both
        # active log writers and the latest failed log during archive cleanup.
        with process_lock(args.log.parent / ".logging.process.lock"):
            env = dict(os.environ)
            env["TIXL_LOG_GROUP_LOCK"] = str(args.log.parent.resolve())
            result = run_to_log(command, args.log, env=env, max_bytes=args.max_bytes,
                                latest_log=args.latest_log)
            try:
                prune_log_archives(args.log, result.returncode)
            except Exception as error:
                try:
                    (args.log.parent / "retention.json").write_text(json.dumps({"status": "deferred",
                        "reason": f"{type(error).__name__}: {error}"[:1024]}), encoding="utf-8")
                except OSError:
                    pass
    else:
        result = run_to_log(command, args.log, max_bytes=args.max_bytes,
                            latest_log=args.latest_log)
    raise SystemExit(result.returncode)


def prune_log_archives(log: Path, exit_code: int):
    from cache_retention import RetentionPolicy, prune_files
    folder = log.parent
    failed = folder / "latest_failed.json"
    if exit_code:
        failed.write_text(json.dumps({"log": log.name}), encoding="utf-8")
    pins = {log.name, log.name + ".meta.json"}
    for summary in ("latest_run.json", "last_successful_run.json", "failed_run.json"):
        path = folder / summary
        if path.exists():
            run_id = json.loads(path.read_text(encoding="utf-8"))["runId"]
            pins.update(p.name for p in folder.iterdir() if p.name.startswith(run_id + "."))
    if failed.exists():
        name = json.loads(failed.read_text(encoding="utf-8"))["log"]
        pins.update({name, name + ".meta.json"})
    policy = RetentionPolicy(20 if folder.name == "sync_logs" else 40, 64 * 1024 * 1024, 30)
    config = folder.parent / "retention_policy.json"
    if config.exists():
        defaults = {"max_count": policy.max_count, "max_bytes": policy.max_bytes, "max_age_days": policy.max_age_days}
        policy = RetentionPolicy(**(defaults | json.loads(config.read_text(encoding="utf-8")).get("logs", {})))
    report = prune_files(folder, folder.parent, policy,
                         name_pattern=r"[0-9a-f]{32}\.log(?:\.meta\.json)?",
                         pinned_names=pins, dry_run=False)
    (folder / "retention.json").write_text(json.dumps(report), encoding="utf-8")


if __name__ == "__main__":
    main()

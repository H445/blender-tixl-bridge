"""Non-blocking, per-source queue for save-triggered TiXL sync processes.

The queue is deliberately independent of Blender so its lifecycle and
coalescing behavior can be tested with small fake process handles.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Callable


def source_key(source: os.PathLike[str] | str) -> str:
    """Return a stable key for a saved .blend path, including on Windows."""
    return os.path.normcase(str(Path(source).expanduser().resolve(strict=False)))


def write_status_file(path: os.PathLike[str] | str, status: dict[str, Any]) -> None:
    """Atomically publish a JSON status snapshot beside the sync logs."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".tmp")
    temporary.write_text(json.dumps(status, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, target)


def get_or_create_queue(registry: dict[str, Any], key: str,
                        factory: Callable[[], "LatestRequestQueue"]) -> "LatestRequestQueue":
    """Keep one coordinator in a host-owned registry across add-on reloads."""
    queue = registry.get(key)
    if queue is None:
        queue = factory()
        registry[key] = queue
    return queue


class LatestRequestQueue:
    """Run one child per source and retain only its newest waiting request.

    A request is a mapping containing at least ``source``. The injected launch
    callback receives a shallow copy and returns a Popen-like object with
    ``poll()`` and optional ``pid`` attributes. Failed launches remain pending
    and are retried with bounded backoff; a new submission replaces that
    pending request and gets an immediate launch attempt.
    """

    def __init__(
        self,
        launch: Callable[[dict[str, Any]], Any],
        *,
        clock: Callable[[], float] = time.monotonic,
        status_writer: Callable[[os.PathLike[str] | str, dict[str, Any]], None] | None = write_status_file,
        retry_base: float = 1.0,
        retry_max: float = 30.0,
        max_launch_attempts: int = 3,
    ) -> None:
        if retry_base <= 0 or retry_max < retry_base or max_launch_attempts < 1:
            raise ValueError("retry_max must be at least a positive retry_base")
        self._launch = launch
        self._clock = clock
        self._status_writer = status_writer
        self._retry_base = retry_base
        self._retry_max = retry_max
        self._max_launch_attempts = max_launch_attempts
        self._sources: dict[str, dict[str, Any]] = {}
        self.total_launches = 0
        self.total_finished = 0
        # Blender's driver_namespace survives add-on unregister/re-register.
        self.timer_registered = False

    @property
    def has_work(self) -> bool:
        return any(state["active"] is not None or
                   (state["pending"] is not None and state["retry_at"] is not None)
                   for state in self._sources.values())

    @property
    def active_count(self) -> int:
        return sum(state["active"] is not None for state in self._sources.values())

    def submit(self, request: dict[str, Any]) -> dict[str, Any]:
        request = dict(request)
        if "source" not in request:
            raise ValueError("request requires a source path")
        key = source_key(request["source"])
        request["source"] = key
        state = self._sources.get(key)
        if state is None:
            state = {
                "source": key,
                "status_path": request.get("statusPath"),
                "status": "queued",
                "active": None,
                "active_request": None,
                "pending": None,
                "last_outcome": None,
                "outcomes": [],
                "launch_error": None,
                "launch_failures": 0,
                "retry_at": None,
                "retry_delay": self._retry_base,
            }
            self._sources[key] = state
        if request.get("statusPath"):
            state["status_path"] = request["statusPath"]

        # Keep the latest request even when launching immediately fails.
        state["pending"] = request
        state["retry_at"] = self._clock()
        state["retry_delay"] = self._retry_base
        state["launch_failures"] = 0
        if state["active"] is not None:
            state["status"] = "running"
            self._publish(state)
        else:
            self._publish(state)
            self._start_pending(state)
        return self.snapshot(key) or {}

    def poll(self) -> bool:
        """Poll live children and launch ready pending work; return work state."""
        now = self._clock()
        for state in tuple(self._sources.values()):
            process = state["active"]
            if process is not None:
                try:
                    return_code = process.poll()
                except Exception as exc:  # Keep ownership until polling recovers.
                    state["status"] = "error"
                    state["launch_error"] = f"Could not poll sync child: {type(exc).__name__}: {exc}"
                    self._publish(state)
                    continue
                if return_code is None:
                    continue
                outcome = {
                    "status": "completed" if return_code == 0 else "error",
                    "exitCode": int(return_code),
                    "completedAt": self._clock(),
                    "queuedAt": state["active_request"].get("queuedAt"),
                    "logPath": state["active_request"].get("logPath"),
                }
                if return_code != 0:
                    outcome["error"] = f"Sync child exited with code {return_code}"
                self._remember_outcome(state, outcome)
                self.total_finished += 1
                state["active"] = None
                state["active_request"] = None
                state["status"] = outcome["status"]
                state["launch_error"] = None
                if state["pending"] is not None:
                    state["status"] = "queued"
                    state["retry_at"] = now
                    self._publish(state)
                    self._start_pending(state)
                else:
                    self._publish(state)
                continue

            if state["pending"] is not None and state["retry_at"] is not None and now >= state["retry_at"]:
                self._start_pending(state)
        return self.has_work

    def snapshot(self, source: os.PathLike[str] | str) -> dict[str, Any] | None:
        state = self._sources.get(source_key(source))
        if state is None:
            return None
        active_request = state["active_request"]
        pending = state["pending"]
        active = None
        if state["active"] is not None:
            active = {
                "status": "running",
                "pid": getattr(state["active"], "pid", None),
                "queuedAt": active_request.get("queuedAt") if active_request else None,
                "logPath": active_request.get("logPath") if active_request else None,
            }
        pending_status = None
        if pending is not None:
            pending_status = {
                "status": "queued",
                "queuedAt": pending.get("queuedAt"),
                "logPath": pending.get("logPath"),
            }
        return {
            "schema": 1,
            "source": state["source"],
            "status": state["status"],
            "active": active,
            "pending": pending_status,
            "lastOutcome": state["last_outcome"],
            "recentOutcomes": list(state["outcomes"]),
            "launchError": state["launch_error"],
            "launchFailures": state["launch_failures"],
            "retryAt": state["retry_at"],
        }

    def _start_pending(self, state: dict[str, Any]) -> None:
        request = state["pending"]
        if request is None or state["active"] is not None:
            return
        state["status"] = "queued"
        self._publish(state)
        try:
            process = self._launch(dict(request))
        except Exception as exc:
            state["status"] = "error"
            state["launch_error"] = f"Could not start sync child: {type(exc).__name__}: {exc}"
            state["launch_failures"] += 1
            if state["launch_failures"] >= self._max_launch_attempts:
                # Retain the request for the next explicit save, but stop the
                # timer so a persistent launch failure cannot become a watcher.
                state["retry_at"] = None
            else:
                delay = min(state["retry_delay"], self._retry_max)
                state["retry_at"] = self._clock() + delay
                state["retry_delay"] = min(delay * 2, self._retry_max)
            self._publish(state)
            return
        state["active"] = process
        self.total_launches += 1
        state["active_request"] = request
        state["pending"] = None
        state["status"] = "running"
        state["launch_error"] = None
        state["launch_failures"] = 0
        state["retry_at"] = None
        state["retry_delay"] = self._retry_base
        self._publish(state)

    @staticmethod
    def _remember_outcome(state: dict[str, Any], outcome: dict[str, Any]) -> None:
        state["last_outcome"] = outcome
        state["outcomes"].append(outcome)
        del state["outcomes"][:-8]

    def _publish(self, state: dict[str, Any]) -> None:
        path = state["status_path"]
        if not path or self._status_writer is None:
            return
        try:
            self._status_writer(path, self.snapshot(state["source"]) or {})
        except Exception:
            # Status-file trouble must never prevent a sync from being queued.
            pass

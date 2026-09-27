import json
import tempfile
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "blender_tixl_bridge" / "source"))
from sync_queue import LatestRequestQueue, get_or_create_queue


class FakeClock:
    def __init__(self):
        self.value = 100.0

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value += seconds


class FakeProcess:
    def __init__(self, pid):
        self.pid = pid
        self.return_code = None

    def poll(self):
        return self.return_code


class LatestRequestQueueTests(unittest.TestCase):
    def make_request(self, source, revision, status_path=None):
        return {
            "source": str(source),
            "revision": revision,
            "queuedAt": float(revision),
            "logPath": f"{revision}.log",
            "statusPath": str(status_path) if status_path else None,
            "env": {"PRIVATE_TEST_VALUE": "must not be serialized"},
            "command": ["worker", str(revision)],
        }

    def test_same_source_requests_coalesce_to_latest_and_run_after_success(self):
        launched = []

        def launch(request):
            process = FakeProcess(len(launched) + 1)
            launched.append((request, process))
            return process

        queue = LatestRequestQueue(launch)
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "scene.blend"
            queue.submit(self.make_request(source, 1))
            queue.submit(self.make_request(source.parent / "unused" / ".." / "scene.blend", 2))
            queue.submit(self.make_request(source, 3))

            self.assertEqual([item[0]["revision"] for item in launched], [1])
            self.assertEqual(queue.active_count, 1)
            snapshot = queue.snapshot(source)
            self.assertEqual(snapshot["status"], "running")
            self.assertEqual(snapshot["pending"]["queuedAt"], 3.0)

            launched[0][1].return_code = 0
            self.assertTrue(queue.poll())
            self.assertEqual([item[0]["revision"] for item in launched], [1, 3])
            snapshot = queue.snapshot(source)
            self.assertEqual(snapshot["lastOutcome"]["status"], "completed")
            self.assertEqual(snapshot["status"], "running")
            self.assertIsNone(snapshot["pending"])

            launched[1][1].return_code = 0
            self.assertFalse(queue.poll())
            self.assertEqual(queue.snapshot(source)["status"], "completed")
            self.assertEqual(queue.total_launches, 2)
            self.assertEqual(queue.total_finished, 2)

    def test_failed_child_does_not_drop_latest_pending_request(self):
        launched = []

        def launch(request):
            process = FakeProcess(len(launched) + 1)
            launched.append((request, process))
            return process

        queue = LatestRequestQueue(launch)
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "scene.blend"
            queue.submit(self.make_request(source, 1))
            queue.submit(self.make_request(source, 2))
            queue.submit(self.make_request(source, 4))
            launched[0][1].return_code = 7

            queue.poll()

            self.assertEqual([item[0]["revision"] for item in launched], [1, 4])
            snapshot = queue.snapshot(source)
            self.assertEqual(snapshot["lastOutcome"]["status"], "error")
            self.assertEqual(snapshot["lastOutcome"]["exitCode"], 7)
            self.assertEqual(snapshot["status"], "running")
            self.assertIsNone(snapshot["pending"])

    def test_different_sources_run_independently(self):
        launched = []

        def launch(request):
            process = FakeProcess(len(launched) + 1)
            launched.append((request, process))
            return process

        queue = LatestRequestQueue(launch)
        with tempfile.TemporaryDirectory() as temp:
            first = Path(temp) / "one.blend"
            second = Path(temp) / "two.blend"
            queue.submit(self.make_request(first, 1))
            queue.submit(self.make_request(second, 2))
            queue.submit(self.make_request(first, 3))

            self.assertEqual(queue.active_count, 2)
            self.assertEqual([item[0]["revision"] for item in launched], [1, 2])
            launched[0][1].return_code = 0
            queue.poll()
            self.assertEqual([item[0]["revision"] for item in launched], [1, 2, 3])
            self.assertEqual(queue.active_count, 2)

    def test_launch_failures_retry_then_retain_request_without_live_timer(self):
        clock = FakeClock()
        attempts = []
        process = FakeProcess(91)

        def launch(request):
            attempts.append(request["revision"])
            if len(attempts) <= 4:
                raise OSError("simulated process creation failure")
            return process

        queue = LatestRequestQueue(launch, clock=clock, retry_base=1, retry_max=2,
                                   max_launch_attempts=3)
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "scene.blend"
            queue.submit(self.make_request(source, 1))
            self.assertEqual(attempts, [1])
            self.assertTrue(queue.has_work)
            queue.submit(self.make_request(source, 2))
            self.assertEqual(attempts, [1, 2])
            clock.advance(1)
            queue.poll()
            self.assertEqual(attempts, [1, 2, 2])
            clock.advance(2)
            queue.poll()
            self.assertEqual(attempts, [1, 2, 2, 2])
            self.assertFalse(queue.has_work)
            snapshot = queue.snapshot(source)
            self.assertEqual(snapshot["status"], "error")
            self.assertEqual(snapshot["pending"]["queuedAt"], 2.0)
            self.assertEqual(snapshot["launchFailures"], 3)

            # A new explicit save replaces the retained request and can recover.
            queue.submit(self.make_request(source, 5))
            self.assertEqual(attempts, [1, 2, 2, 2, 5])
            self.assertEqual(queue.snapshot(source)["status"], "running")

    def test_shared_registry_preserves_queue_when_host_namespace_is_replaced(self):
        registry = {}
        launched = []

        def launch(request):
            process = FakeProcess(len(launched) + 1)
            launched.append((request, process))
            return process

        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "scene.blend"
            queue = get_or_create_queue(registry, "bridge.queue", lambda: LatestRequestQueue(launch))
            queue.submit(self.make_request(source, 1))

            # Blender can replace driver_namespace while loading a .blend;
            # the add-on's stable runtime registry still owns the coordinator.
            simulated_driver_namespace = {"queue": queue}
            simulated_driver_namespace = {}
            restored = get_or_create_queue(registry, "bridge.queue", lambda: LatestRequestQueue(launch))
            restored.submit(self.make_request(source, 2))

            self.assertIs(restored, queue)
            self.assertEqual(restored.active_count, 1)
            self.assertEqual(restored.snapshot(source)["pending"]["queuedAt"], 2.0)
            self.assertEqual(len(launched), 1)
            self.assertEqual(simulated_driver_namespace, {})

    def test_status_file_reports_transitions_without_command_or_environment(self):
        launched = []

        def launch(request):
            process = FakeProcess(123)
            launched.append(process)
            return process

        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "scene.blend"
            status_path = Path(temp) / "status.json"
            queue = LatestRequestQueue(launch)
            queue.submit(self.make_request(source, 1, status_path))

            status = json.loads(status_path.read_text(encoding="utf-8"))
            self.assertEqual(status["status"], "running")
            self.assertEqual(status["active"]["pid"], 123)
            self.assertNotIn("env", status)
            self.assertNotIn("command", status)

            launched[0].return_code = 0
            queue.poll()
            status = json.loads(status_path.read_text(encoding="utf-8"))
            self.assertEqual(status["status"], "completed")
            self.assertEqual(status["lastOutcome"]["exitCode"], 0)


if __name__ == "__main__":
    unittest.main()

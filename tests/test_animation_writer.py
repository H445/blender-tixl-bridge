"""Byte-compatibility and bounded-write tests for animation cache batching."""
from __future__ import annotations

import io
import ast
import json
import struct
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "blender_tixl_bridge" / "source"))
from animation_writer import MATRIX_BYTES, MAX_BATCH_SAMPLES, PAYLOAD_BUDGET, MatrixRecordWriter, batch_samples


class CountingStream(io.BytesIO):
    def __init__(self):
        super().__init__()
        self.seek_calls = 0
        self.write_calls = 0

    def seek(self, offset, whence=io.SEEK_SET):
        self.seek_calls += 1
        return super().seek(offset, whence)

    def write(self, value):
        self.write_calls += 1
        return super().write(value)


def payload(world_index: int, record_index: int, frame: int) -> bytes:
    base = world_index * 10000 + record_index * 100 + frame
    return struct.pack("<16f", *(base + lane / 8 for lane in range(16)))


def fixture_jobs():
    """Two worlds with disjoint clips, sparse starts, animated and static rows."""
    return [
        {"world": "opening", "clip": (10, 16), "world_index": 1,
         "records": [
             {"index": 0, "start": 10, "count": 3, "animated": True},
             {"index": 1, "start": 10, "count": 1, "animated": False},
             {"index": 2, "start": 14, "count": 3, "animated": True},
         ]},
        {"world": "ending", "clip": (20, 24), "world_index": 2,
         "records": [
             {"index": 0, "start": 21, "count": 2, "animated": True},
             {"index": 1, "start": 20, "count": 1, "animated": False},
             {"index": 2, "start": 22, "count": 3, "animated": True},
         ]},
    ]


def reserve_legacy_layout(stream, job):
    stream.write(b"TIXLANIM\x01" + struct.pack("<I", len(job["records"])))
    for record in job["records"]:
        stream.write(struct.pack("<III", record["index"], record["start"], record["count"]))
        record["offset"] = stream.tell()
        stream.seek(record["count"] * MATRIX_BYTES, io.SEEK_CUR)
    stream.truncate(stream.tell())


def legacy_seek_write(job, stream):
    """Independent model of the original per-matrix seek/write loop."""
    for frame in range(job["clip"][0], job["clip"][1] + 1):
        entries = ([row for row in job["records"] if row["animated"]]
                   + ([row for row in job["records"] if not row["animated"]]
                      if frame == job["clip"][0] else []))
        for record in entries:
            start = record["start"]
            end = start + record["count"] - 1
            if start <= frame <= end:
                stream.seek(record["offset"] + (frame - start) * MATRIX_BYTES)
                stream.write(payload(job["world_index"], record["index"], frame))


def batched_writer(job, stream, samples_per_batch):
    writers = {record["index"]: MatrixRecordWriter(stream, record["offset"],
                                                   record["start"], samples_per_batch)
               for record in job["records"]}
    for frame in range(job["clip"][0], job["clip"][1] + 1):
        entries = ([row for row in job["records"] if row["animated"]]
                   + ([row for row in job["records"] if not row["animated"]]
                      if frame == job["clip"][0] else []))
        for record in entries:
            start = record["start"]
            end = start + record["count"] - 1
            if start <= frame <= end:
                writers[record["index"]].append(
                    frame, payload(job["world_index"], record["index"], frame))
    for record in job["records"]:
        writers[record["index"]].flush()


def load_bake_all(*, end, failure=None):
    """Compile only the production bake_all function with controlled globals."""
    source_path = Path(__file__).resolve().parents[1] / "blender_tixl_bridge" / "source" / "tixl_animation_export.py"
    module = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
    function = next(node for node in module.body
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and node.name == "bake_all")
    isolated = ast.Module(body=[function], type_ignores=[])
    ast.fix_missing_locations(isolated)
    namespace = {
        "sys": sys,
        "time": time,
        "batch_samples": lambda count: 1,
        "END": end,
        "set_output_frame": lambda scene, frame: None,
        "struct": struct,
        "runtime_matrix": lambda source: [1.0] * 16,
        "material_values": lambda material: ([1, 1, 1, 1], [0, 0, 0, 1]),
        "transparent": lambda material: False,
        "json": json,
        "print": lambda *args, **kwargs: None,
    }

    writer_creations = [0]

    class FakeWriter:
        def __init__(self, stream, offset, start, samples_per_batch):
            self.stream = stream
            writer_creations[0] += 1
            if failure == "constructor" and writer_creations[0] == 2:
                raise MemoryError("injected writer constructor failure")

        def append(self, frame, payload):
            if failure == "sample":
                raise RuntimeError("injected sample failure")

        def flush(self):
            if failure == "flush":
                raise OSError("injected flush failure")

    namespace["MatrixRecordWriter"] = FakeWriter
    exec(compile(isolated, str(source_path), "exec"), namespace)
    return namespace["bake_all"]


class FakeStream:
    def __init__(self, *, close_error=False):
        self.close_error = close_error
        self.close_attempts = 0
        self.closed = False

    def close(self):
        self.close_attempts += 1
        self.closed = True
        if self.close_error:
            message = self.close_error if isinstance(self.close_error, str) else "injected close failure"
            raise OSError(message)


def fake_jobs(streams):
    jobs = []
    for index, stream in enumerate(streams):
        record = {"offset": 0, "start": 1, "end": 1, "source": object()}
        jobs.append({"stream": stream, "clip": (1, 1), "world": f"world_{index}",
                     "animated": [record], "static": [], "morphs": [], "visibility": [],
                     "materials": [], "lights": [], "channels": {}})
    return jobs


class AnimationWriterTests(unittest.TestCase):
    def test_batch_budget_is_bounded_and_scales_with_record_count(self):
        self.assertEqual(batch_samples(0), MAX_BATCH_SAMPLES)
        self.assertEqual(batch_samples(1), MAX_BATCH_SAMPLES)
        self.assertEqual(batch_samples(128), MAX_BATCH_SAMPLES)
        self.assertEqual(batch_samples(129), PAYLOAD_BUDGET // 129 // MATRIX_BYTES)
        self.assertEqual(batch_samples(PAYLOAD_BUDGET // MATRIX_BYTES), 1)
        self.assertEqual(batch_samples(PAYLOAD_BUDGET // MATRIX_BYTES + 1), 1)
        self.assertLessEqual(batch_samples(129) * 129 * MATRIX_BYTES, PAYLOAD_BUDGET)

    def test_multijob_sparse_static_and_non_one_start_bytes_match_legacy(self):
        legacy_jobs = fixture_jobs()
        batched_jobs = fixture_jobs()
        legacy = {}
        batched = {}
        record_count = sum(len(job["records"]) for job in batched_jobs)
        window = batch_samples(record_count)
        for job in legacy_jobs:
            stream = CountingStream()
            reserve_legacy_layout(stream, job)
            before = (stream.seek_calls, stream.write_calls)
            legacy_seek_write(job, stream)
            legacy[job["world"]] = (stream.getvalue(), stream.seek_calls - before[0],
                                    stream.write_calls - before[1])
        for job in batched_jobs:
            stream = CountingStream()
            reserve_legacy_layout(stream, job)
            before = (stream.seek_calls, stream.write_calls)
            batched_writer(job, stream, window)
            batched[job["world"]] = (stream.getvalue(), stream.seek_calls - before[0],
                                     stream.write_calls - before[1])
        for world in ("opening", "ending"):
            self.assertEqual(batched[world][0], legacy[world][0], world)
            self.assertLess(batched[world][1], legacy[world][1], world + " seek reduction")
            self.assertLess(batched[world][2], legacy[world][2], world + " write reduction")
            job = next(row for row in batched_jobs if row["world"] == world)
            expected_size = 13 + sum(12 + record["count"] * MATRIX_BYTES for record in job["records"])
            self.assertEqual(len(batched[world][0]), expected_size)
            self.assertEqual(batched[world][0][:9], b"TIXLANIM\x01")
            for record in job["records"]:
                header = struct.unpack_from("<III", batched[world][0], record["offset"] - 12)
                self.assertEqual(header, (record["index"], record["start"], record["count"]))

    def test_partial_final_batch_flushes_exact_tail(self):
        stream = CountingStream()
        offset = 4
        stream.write(b"HEAD" + b"\0" * (6 * MATRIX_BYTES))
        writer = MatrixRecordWriter(stream, offset, start=30, samples_per_batch=4)
        for frame in range(30, 36):
            writer.append(frame, payload(0, 0, frame))
        self.assertEqual(len(writer.buffer), 2 * MATRIX_BYTES)
        writer.flush()
        expected = b"HEAD" + b"".join(payload(0, 0, frame) for frame in range(30, 36))
        self.assertEqual(stream.getvalue(), expected)
        self.assertEqual(stream.seek_calls, 2)
        self.assertEqual(stream.write_calls, 3)  # header, full batch, trailing partial
        self.assertEqual(writer.offset, offset + 6 * MATRIX_BYTES)
        self.assertEqual(writer.buffer, b"")

    def test_single_sample_capacity_uses_direct_writes(self):
        stream = CountingStream()
        stream.write(b"\0" * (3 * MATRIX_BYTES))
        writer = MatrixRecordWriter(stream, 0, start=7, samples_per_batch=batch_samples(200_000))
        self.assertEqual(writer.capacity, MATRIX_BYTES)
        for frame in range(7, 10):
            writer.append(frame, payload(0, 0, frame))
        writer.flush()
        self.assertEqual(stream.getvalue(), b"".join(payload(0, 0, frame) for frame in range(7, 10)))
        self.assertEqual(stream.seek_calls, 3)
        self.assertEqual(stream.write_calls, 4)

    def test_invalid_frame_or_payload_is_rejected_without_advancing(self):
        stream = CountingStream()
        writer = MatrixRecordWriter(stream, 0, start=11, samples_per_batch=3)
        with self.assertRaisesRegex(ValueError, "consecutive"):
            writer.append(12, payload(0, 0, 12))
        with self.assertRaisesRegex(ValueError, "consecutive"):
            writer.append(11, b"short")
        self.assertEqual(writer.next_frame, 11)
        self.assertEqual(writer.buffer, b"")
        self.assertEqual(stream.getvalue(), b"")

    def test_write_failure_propagates_without_advancing_offset_or_clearing_batch(self):
        class FailingStream(io.BytesIO):
            def write(self, value):
                raise OSError("injected disk failure")

        stream = FailingStream()
        writer = MatrixRecordWriter(stream, 64, start=4, samples_per_batch=2)
        writer.append(4, payload(0, 0, 4))
        with self.assertRaisesRegex(OSError, "injected disk failure"):
            writer.append(5, payload(0, 0, 5))
        self.assertEqual(writer.offset, 64)
        self.assertEqual(writer.next_frame, 5)
        self.assertEqual(writer.buffer, payload(0, 0, 4) + payload(0, 0, 5))

        direct = MatrixRecordWriter(stream, 64, start=4, samples_per_batch=0)
        with self.assertRaisesRegex(OSError, "injected disk failure"):
            direct.append(4, payload(0, 0, 4))
        self.assertEqual(direct.offset, 64)
        self.assertEqual(direct.next_frame, 4)

    def test_bake_failure_closes_every_job_stream_and_preserves_sample_error(self):
        streams = [FakeStream(), FakeStream(close_error="close must not mask sample failure")]
        bake = load_bake_all(end=1, failure="sample")
        with tempfile.TemporaryDirectory() as folder:
            namespace_out = Path(folder)
            # The isolated function gets this module global via its function globals.
            bake.__globals__["OUT"] = namespace_out
            with self.assertRaisesRegex(RuntimeError, "injected sample failure"):
                bake(None, fake_jobs(streams))
        self.assertTrue(all(stream.closed for stream in streams))
        self.assertTrue(all(stream.close_attempts >= 1 for stream in streams))

    def test_flush_failure_closes_later_job_streams(self):
        streams = [FakeStream(), FakeStream()]
        bake = load_bake_all(end=1, failure="flush")
        with tempfile.TemporaryDirectory() as folder:
            bake.__globals__["OUT"] = Path(folder)
            with self.assertRaisesRegex(OSError, "injected flush failure"):
                bake(None, fake_jobs(streams))
        self.assertTrue(all(stream.closed for stream in streams))
        self.assertTrue(all(stream.close_attempts >= 1 for stream in streams))

    def test_writer_construction_failure_closes_every_job_stream_and_preserves_error(self):
        streams = [FakeStream(close_error="close must not mask allocation failure"), FakeStream()]
        bake = load_bake_all(end=1, failure="constructor")
        with self.assertRaisesRegex(MemoryError, "injected writer constructor failure"):
            bake(None, fake_jobs(streams))
        self.assertTrue(all(stream.closed for stream in streams))
        self.assertTrue(all(stream.close_attempts >= 1 for stream in streams))

    def test_close_failure_without_prior_error_closes_all_and_raises_first(self):
        streams = [FakeStream(close_error="first close failure"),
                   FakeStream(close_error="second close failure")]
        bake = load_bake_all(end=1)
        with tempfile.TemporaryDirectory() as folder:
            bake.__globals__["OUT"] = Path(folder)
            with self.assertRaisesRegex(OSError, "first close failure"):
                bake(None, fake_jobs(streams))
        self.assertTrue(all(stream.closed for stream in streams))
        self.assertTrue(all(stream.close_attempts >= 1 for stream in streams))


if __name__ == "__main__":
    unittest.main()

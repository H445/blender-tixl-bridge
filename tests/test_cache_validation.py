"""Checks staged binary payload validation against exporter formats."""
import json
import math
import struct
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "blender_tixl_bridge" / "source"))
from cache_validation import validate_export_payload


class CacheValidationTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.stage = Path(self.temp.name)
        self.world_dir = self.stage / "worlds"
        self.world_dir.mkdir()
        self.worlds = [
            {"world": "opening", "fps": 60, "active_clip": [1, 61],
             "object_count": 1, "glbs": {"opaque": "opening_opaque.glb"}},
            {"world": "spin", "fps": 60, "active_clip": [62, 121],
             "object_count": 1, "glbs": {"opaque": "spin_opaque.glb"}},
        ]
        self.manifest = {"fps": 60, "worlds": self.worlds}
        for world in self.worlds:
            self._write_world(world)
        self._write_camera()
        self._write_timeline()

    def _write_world(self, world, *, record_start=None, record_count=2, index=0,
                     extra_binary=b"", sample_value=0.0):
        name = world["world"]
        start = world["active_clip"][0] if record_start is None else record_start
        metadata = {
            "magic": r"TIXLANIM\x01",
            "fps": 60,
            "matrix_layout": "float32 row-major System.Numerics",
            "records": [{"export_name": f"{name}_mesh", "source_name": "SourceMesh",
                         "start": start, "count": record_count,
                         "animated": record_count > 1, "parent": None}],
        }
        (self.world_dir / f"{name}_animation.json").write_text(
            json.dumps(metadata), encoding="utf-8")
        channels = {"world": name, "fps": 60, "morphs": [], "materials": [],
                    "visibility": [], "lights": []}
        (self.world_dir / f"{name}_channels.json").write_text(
            json.dumps(channels), encoding="utf-8")
        world_manifest = {**world, "runtime_contract": "test"}
        (self.world_dir / f"{name}_manifest.json").write_text(
            json.dumps(world_manifest), encoding="utf-8")
        matrices = []
        for _ in range(record_count):
            matrix = [sample_value, 0, 0, 0,
                      0, 1, 0, 0,
                      0, 0, 1, 0,
                      0, 0, 0, 1]
            matrices.extend(matrix)
        payload = (b"TIXLANIM\x01" + struct.pack("<I", 1)
                   + struct.pack("<III", index, start, record_count)
                   + struct.pack("<" + "f" * len(matrices), *matrices) + extra_binary)
        (self.world_dir / f"{name}_animation.bin").write_bytes(payload)
        self._write_glb(self.world_dir / f"{name}_opaque.glb", f"{name}_mesh")

    @staticmethod
    def _write_glb(path, node_name, *, declared_length=None, chunk_length=None):
        document = json.dumps({"asset": {"version": "2.0"},
                               "nodes": [{"name": node_name, "mesh": 0}],
                               "meshes": [{"primitives": []}]}).encode("utf-8")
        document += b" " * (-len(document) % 4)
        if chunk_length is None:
            chunk_length = len(document)
        chunk = struct.pack("<I4s", chunk_length, b"JSON") + document
        total = 12 + len(chunk)
        if declared_length is not None:
            total = declared_length
        path.write_bytes(struct.pack("<4sII", b"glTF", 2, total) + chunk)

    def _write_camera(self, *, count=120, sample=None, trailing=b""):
        sample = sample or [0, 0, 0, 0, -1, 0, 0, 0, -1, 60, 0.1, 100]
        values = sample * count
        path = self.stage / "camera_60hz.bin"
        path.write_bytes(struct.pack("<i", count)
                         + struct.pack("<" + "f" * len(values), *values) + trailing)

    def _write_timeline(self, shots=None):
        if shots is None:
            shots = [
                {"id": 1, "start": 0.0, "label": "Opening", "camera": "CameraA"},
                {"id": 2, "start": 1.0, "label": "Spin", "camera": "CameraB"},
            ]
        (self.stage / "camera_timeline.json").write_text(
            json.dumps({"shots": shots, "passages": []}), encoding="utf-8")

    def assert_invalid(self):
        with self.assertRaises(ValueError):
            validate_export_payload(self.stage, self.manifest)

    def test_exporter_shaped_payload_passes(self):
        self.assertTrue(validate_export_payload(self.stage, self.manifest))

    def test_animation_file_requires_exact_record_lengths(self):
        path = self.world_dir / "opening_animation.bin"
        path.write_bytes(path.read_bytes()[:-1])
        self.assert_invalid()
        path.write_bytes(path.read_bytes() + b"\0")
        self.assert_invalid()  # A truncated record plus compensating trailing byte is rejected.

    def test_animation_record_index_and_metadata_ranges_are_checked(self):
        self._write_world(self.worlds[0], index=1)
        self.assert_invalid()
        self._write_world(self.worlds[0], record_start=60, record_count=3)
        self.assert_invalid()

    def test_animation_matrix_samples_must_be_finite_and_affine(self):
        self._write_world(self.worlds[0], sample_value=math.nan)
        self.assert_invalid()
        self._write_world(self.worlds[0], sample_value=0.0)
        path = self.world_dir / "opening_animation.bin"
        payload = bytearray(path.read_bytes())
        # The first matrix's final float is M44; runtime requires it to equal 1.
        struct.pack_into("<f", payload, 16 + 12 + 60, 0.0)
        path.write_bytes(payload)
        self.assert_invalid()

    def test_glb_declared_length_and_chunk_boundaries_are_checked(self):
        path = self.world_dir / "opening_opaque.glb"
        self._write_glb(path, "opening_mesh", declared_length=100)
        self.assert_invalid()
        self._write_glb(path, "opening_mesh", chunk_length=4)
        self.assert_invalid()

    def test_camera_rail_requires_exact_length_and_finite_samples(self):
        self._write_camera(trailing=b"\0")
        self.assert_invalid()
        sample = [0, 0, 0, 0, -1, 0, 0, 0, -1, float("inf"), 0.1, 100]
        self._write_camera(sample=sample)
        self.assert_invalid()

    def test_camera_timeline_requires_ordered_bounded_shots(self):
        self._write_timeline([
            {"id": 1, "start": 0.0, "label": "Opening", "camera": "CameraA"},
            {"id": 2, "start": 0.5, "label": "Second", "camera": "CameraB"},
            {"id": 3, "start": 0.4, "label": "Third", "camera": "CameraC"},
        ])
        self.assert_invalid()
        self._write_timeline([
            {"id": 1, "start": 0.0, "label": "Opening", "camera": "CameraA"},
            {"id": 2, "start": 2.0, "label": "Too late", "camera": "CameraB"},
        ])
        self.assert_invalid()

    def test_camera_and_world_fps_and_sample_bounds_must_match(self):
        self.manifest["fps"] = 30
        self.assert_invalid()
        self.manifest["fps"] = 60
        self._write_camera(count=60)
        self.assert_invalid()  # The second world ends at frame 121.

    def test_world_manifest_order_and_gaps_are_checked(self):
        self.manifest["worlds"] = list(reversed(self.worlds))
        self.assert_invalid()
        self.manifest["worlds"] = [self.worlds[0],
                                   {**self.worlds[1], "active_clip": [63, 121]}]
        self.assert_invalid()

    def test_world_file_metadata_must_match_global_manifest(self):
        self._write_world({**self.worlds[0], "fps": 30})
        self.assert_invalid()


if __name__ == "__main__":
    unittest.main()

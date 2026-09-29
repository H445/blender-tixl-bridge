"""Check that declared SDF proxies become connected native TiXL fields."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "blender_tixl_bridge" / "source"))
from blend_sync_graph import generate  # noqa: E402


class NativeSdfGraphTest(unittest.TestCase):
    def test_static_fields_join_the_world_command(self):
        fields = [
            {"name": "Beacon", "kind": "sphere", "center": {"X": 1, "Y": 2, "Z": 3},
             "radius": 1.5, "color": {"X": .2, "Y": .8, "Z": 1, "W": 1}},
            {"name": "Portal", "kind": "torus", "center": {"X": 4, "Y": 5, "Z": 6},
             "radius": 2, "thickness": .1, "axis": 2,
             "color": {"X": 1, "Y": .5, "Z": .2, "W": 1}},
        ]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            blend = root / "Source.blend"
            blend.write_bytes(b"source")
            cache = root / "cache"
            cache.mkdir()
            (cache / "camera_timeline.json").write_text(json.dumps({"shots": [], "passages": []}))
            manifest = {"fps": 60, "worlds": [{"world": "main", "active_clip": [1, 121],
                "opaque_count": 0, "glass_count": 0, "sdf_fields": fields}]}
            graph_path = generate(blend, cache, manifest)[0]
            graph = json.loads(graph_path.read_text())
            children = {c["Id"]: c for c in graph["Children"]}
            native = [c for c in children.values() if c.get("Name", "").endswith(" SDF")]
            rays = [c for c in children.values() if c.get("Name", "").endswith(" raymarch")]
            self.assertEqual(len(native), 2)
            self.assertEqual(len(rays), 2)
            for ray in rays:
                inbound = [e for e in graph["Connections"] if e["TargetParentOrChildId"] == ray["Id"]]
                outbound = [e for e in graph["Connections"] if e["SourceParentOrChildId"] == ray["Id"]]
                self.assertEqual(len(inbound), 1)
                self.assertEqual(len(outbound), 1)
                self.assertEqual(children[outbound[0]["TargetParentOrChildId"]]["SymbolName"],
                                 "Lib.render.transform.Group")
            self.assertEqual(len({c["Id"] for c in graph["Children"]}), len(graph["Children"]))
            self.assertTrue(all(e["SourceParentOrChildId"] in children or
                                e["SourceParentOrChildId"] == "00000000-0000-0000-0000-000000000000"
                                for e in graph["Connections"]))


if __name__ == "__main__":
    unittest.main()

"""Protect the seeded 108-second audio/video event loop and Home graph edit."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "examples"))
from advanced_spaceship.audio.techno_pattern import events, signal_events  # noqa: E402
from install_asterion_audio import BUS_INPUT, CLIP_OUTPUT, GRAPH_ID, link  # noqa: E402
from install_asterion_techno_refresh import install, morph_curves, NEW_NAME  # noqa: E402


class TechnoLoopTest(unittest.TestCase):
    def test_seeded_events_are_varied_and_repeatable(self):
        self.assertEqual(events(), events())
        hits = events()
        self.assertTrue(all(0 <= event.time < 108 for event in hits))
        self.assertGreater(len(signal_events()), 30)
        kicks = [tuple(round(e.time - bar*2, 3) for e in hits
                       if e.kind == "kick" and bar*2 <= e.time < (bar+1)*2)
                 for bar in range(54)]
        self.assertGreater(len(set(kicks)), 12)
        self.assertTrue(all(round(e.time/.125)*.125 == e.time for e in hits))

    def test_sdf_channels_close_at_loop_seam(self):
        channels = morph_curves()
        self.assertEqual(set(channels), {"radius", "thickness", "noise", "tilt",
                                         "offset_x", "offset_y"})
        for name, data in channels.items():
            keys = data["Curve"]["Keys"]
            self.assertEqual((keys[0]["Time"], keys[-1]["Time"]), (0, 108))
            self.assertGreater(len({k["Value"] for k in keys}), 10, name)
            if name == "tilt":
                self.assertEqual(keys[-1]["Value"] % 360, keys[0]["Value"])
            else:
                self.assertEqual(keys[-1]["Value"], keys[0]["Value"])

    def test_home_edit_preserves_unrelated_nodes_and_bus(self):
        names = ("Audio | score clip", "Audio | mission audio bus",
                 "Signal | torus signed distance", "Signal | SDF turbulent rim",
                 "Signal | ASCII accents at 120 BPM", "Signal | SDF scan accents",
                 "Signal | ASCII on sparse chops", "Post FX | 03 scanline signal",
                 "Main / clip to scene time", "Unrelated node")
        nodes = []
        for index, name in enumerate(names):
            nodes.append({"Id": f"id-{index}", "SymbolName":
                          "Lib.io.audio.AudioClip" if index == 0 else "other",
                          "Name": name, "InputValues": [], "Outputs": []})
        ids = {n["Name"]: n["Id"] for n in nodes}
        score_edge = link(ids[names[0]], CLIP_OUTPUT, ids[names[1]], BUS_INPUT)
        sdf_edge = link(ids[names[2]],
                        "14cd4d1f-0b9b-43c4-93cc-d730c137cee8",
                        ids[names[3]], "1799f18f-92c5-4885-b6c1-6a196eee805f")
        unrelated_edge = link(ids[names[-1]], "out", ids[names[-1]], "in")
        graph = {"Id": GRAPH_ID, "Children": nodes,
                 "Connections": [score_edge, sdf_edge, unrelated_edge]}
        ui = {"Id": GRAPH_ID, "SymbolChildUis": [
            {"ChildId": n["Id"], "Position": {"X": index*420, "Y": 0}}
            for index, n in enumerate(nodes)]}
        edited, layout = install(graph, ui)
        self.assertIn(unrelated_edge, edited["Connections"])
        self.assertFalse(any(n["Name"] == names[0] for n in edited["Children"]))
        self.assertEqual(sum(n["Name"] == NEW_NAME for n in edited["Children"]), 1)
        self.assertEqual(len(layout["SymbolChildUis"]), len(edited["Children"]))
        self.assertTrue(all(e["SourceParentOrChildId"] in
                            {n["Id"] for n in edited["Children"]} and
                            e["TargetParentOrChildId"] in
                            {n["Id"] for n in edited["Children"]}
                            for e in edited["Connections"]))


if __name__ == "__main__":
    unittest.main()

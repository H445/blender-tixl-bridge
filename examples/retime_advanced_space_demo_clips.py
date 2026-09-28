"""Extend an existing Asterion TiXL project's seven editable source clips.

Run only after closing TiXL through its debug bridge. This edits the user-owned
home graph deliberately; normal bridge sync preserves its TimeClips.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


EXPECTED = {
    "01 / COMBAT | compact strike ship": (0.0, 9.0, 0.0, 24.0),
    "02 / Projectile breakup to EXPLORER": (9.0, 21.0, 24.0, 36.0),
    "03 / EXPLORER | survey array": (21.0, 30.0, 36.0, 60.0),
    "04 / Projectile breakup to HAULER": (30.0, 42.0, 60.0, 72.0),
    "05 / HAULER | cargo cradle": (42.0, 51.0, 72.0, 96.0),
    "06 / Return to COMBAT": (51.0, 58.0, 96.0, 105.3333333333),
    "07 / COMBAT | final assembly": (58.0, 60.0, 105.3333333333, 108.0),
}


def retime(path: Path) -> None:
    graph = json.loads(path.read_text(encoding="utf-8"))
    found = set()
    changed = 0
    for child in graph["Children"]:
        name = child.get("Name")
        if name not in EXPECTED:
            continue
        if not child.get("SymbolName", "").endswith(".BlenderSourceClip"):
            raise ValueError(f"Unexpected operator for {name}")
        old_start, old_end, new_start, new_end = EXPECTED[name]
        outputs = child.get("Outputs", [])
        if len(outputs) != 1:
            raise ValueError(f"Expected one editable clip output for {name}")
        clip = outputs[0]["OutputData"]["TimeClip"]
        source = clip["SourceRange"]
        timeline = clip["TimeRange"]
        current = (source["Start"], source["End"],
                   timeline["Start"]*2, timeline["End"]*2)
        expected_old = (old_start, old_end, old_start, old_end)
        expected_new = (new_start, new_end, new_start, new_end)
        if all(abs(a-b) < 1e-6 for a, b in zip(current, expected_new)):
            found.add(name)
            continue
        if not all(abs(a-b) < 1e-6 for a, b in zip(current, expected_old)):
            raise ValueError(f"Refusing to overwrite user-edited timing for {name}: {current}")
        source.update(Start=new_start, End=new_end)
        timeline.update(Start=new_start/2, End=new_end/2)
        found.add(name)
        changed += 1
    if found != EXPECTED.keys():
        raise ValueError(f"Missing expected clips: {sorted(EXPECTED.keys()-found)}")
    if changed:
        path.write_text(json.dumps(graph, indent=2, ensure_ascii=False)+"\n",
                        encoding="utf-8")
    print(f"ASTERION_TIXL_CLIPS_RETIMER {changed} changed; duration 108 seconds")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: retime_advanced_space_demo_clips.py <AsterionBreakaway.t3>")
    retime(Path(sys.argv[1]))

"""Compare freshly baked example caches through TiXL, restoring editor state."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path

from transparent_render_equivalence import _restore
from tixl_runtime_benchmark import call


TIMES = (0, 3.5, 3.999, 4, 4.001, 7.999, 8, 8.001,
         11.999, 12, 12.001, 15.999)
LOAD_COUNTERS = ("Blender cumulative scene loads", "Blender cumulative GLB reads",
                 "Blender cumulative GLB JSON parses")


def load_counters(stats):
    values = {key: stats.get(key) for key in LOAD_COUNTERS}
    if any(isinstance(value, bool) or not isinstance(value, int)
           or not 0 <= value < 2**31 - 1 for value in values.values()):
        raise ValueError("Loading counters must be present, nonnegative, and unsaturated")
    return values


def bindings(graph, baseline, optimized):
    changes = []
    for child in graph.get("children", []):
        if child.get("symbolName", "").split(".")[-1] != "BlenderAnimationScene":
            continue
        items = [item for item in child.get("inputs", []) if item.get("name") == "DataPath"]
        if len(items) != 1 or not isinstance(items[0].get("value"), str):
            raise ValueError("Animation scene has no unique existing DataPath")
        name = Path(items[0]["value"]).name
        if not name.endswith("_animation.bin"):
            raise ValueError("Unexpected animation cache filename")
        stem = name.removesuffix("_animation.bin")
        for filename in (name, stem + "_animation.json", stem + "_channels.json"):
            first, second = baseline / filename, optimized / filename
            if not first.is_file() or not second.is_file() or first.read_bytes() != second.read_bytes():
                raise ValueError("Freshly baked caches must match exactly: " + filename)
        changes.append((child["childId"], items[0]["id"], name))
    if len(changes) != 4:
        raise ValueError("The bundled example must have four animation bindings")
    return changes


def reload_original_scenes(graph, payload, protocol_call, port):
    """Refresh native scenes after undo has restored all related path fields."""
    refreshed = []
    for child in graph["children"]:
        if child.get("symbolName", "").split(".")[-1] != "LoadGltfScene":
            continue
        item = next(item for item in child["inputs"] if item["name"] == "Path")
        changed = False
        error = None
        try:
            protocol_call("setInput", port, childId=child["childId"], inputId=item["id"],
                          value=str((payload / Path(item["value"]).name).resolve()))
            changed = True
            protocol_call("pumpFrames", port, count=3)
        except BaseException as failure:
            error = failure
        finally:
            if changed:
                try:
                    protocol_call("undo", port)
                    protocol_call("pumpFrames", port, count=3)
                except BaseException as failure:
                    if error is None:
                        error = failure
        if error is not None:
            raise error
        refreshed.append(child["childId"])
    return refreshed


def validate(baseline, optimized, folder, port=9042):
    from PIL import Image, ImageChops

    context = call("getContext", port)
    if context.get("compositionName") != "BlendShapeExample" or context["time"]["isPlaying"]:
        raise ValueError("The bundled example must already be open and paused")
    original = call("getGraphState", port, includeDefaults=True)
    if original.get("missingChildren") or original.get("missingConnections"):
        raise ValueError("The example graph contains unresolved structure")
    view = call("getGraphView", port)
    changes = bindings(original, baseline, optimized)
    folder.mkdir(parents=True, exist_ok=True)
    payloads = {}
    phase_changes = {}
    for phase, worlds in (("baseline", baseline), ("optimized", optimized)):
        payload = folder / (phase + "_payload")
        payload.mkdir()
        payloads[phase] = payload
        planned = []
        for child, slot, name in changes:
            stem = name.removesuffix("_animation.bin")
            for suffix in ("animation.bin", "animation.json", "channels.json"):
                shutil.copy2(worlds / (stem + "_" + suffix), payload)
            planned.append((child, slot, name))
        native_loads = 0
        for child in original["children"]:
            kind = child.get("symbolName", "").split(".")[-1]
            field = "GlbPath" if kind == "BlenderAnimationScene" else "Path" if kind == "LoadGltfScene" else None
            if field is None:
                continue
            item = next(item for item in child["inputs"] if item["name"] == field)
            source = Path(item["value"])
            target = payload / source.name
            if target.exists() and target.read_bytes() != source.read_bytes():
                raise ValueError("Private GLB filenames collide")
            shutil.copy2(source, target)
            planned.append((child["childId"], item["id"], source.name))
            native_loads += kind == "LoadGltfScene"
        if native_loads != 4:
            raise ValueError("The bundled example must have four native GLB loaders")
        kinds = {child["childId"]: child.get("symbolName", "").split(".")[-1]
                 for child in original["children"]}
        # The editor renders between requests. Reload native scenes last so a
        # partial path update cannot rebind from dispatches hidden by animation.
        planned.sort(key=lambda row: 2 if kinds[row[0]] == "LoadGltfScene"
                     else 1 if row[2].endswith(".glb") else 0)
        phase_changes[phase] = planned
    report = {"schema": 1, "project": "BlendShapeExample", "times": list(TIMES),
              "scope": "complete private payload per phase: identical GLB copies, existing camera cuts and graph, freshly baked baseline/current animation and channels",
              "phases": {}, "comparisons": []}
    applied = 0
    failure = None
    traceback = None
    try:
        for phase, worlds in payloads.items():
            for child, slot, name in phase_changes[phase]:
                call("setInput", port, childId=child, inputId=slot, value=str((worlds / name).resolve()))
                applied += 1
            staged = call("getGraphState", port, includeDefaults=True)
            expected = json.loads(json.dumps(original))
            normalized = json.loads(json.dumps(staged))
            for child, slot, name in phase_changes[phase]:
                node = next(row for row in expected["children"] if row["childId"] == child)
                item = next(row for row in node["inputs"] if row["id"] == slot)
                item["value"] = str((worlds / name).resolve())
                item["isDefault"] = False
                actual_node = next(row for row in normalized["children"] if row["childId"] == child)
                actual_item = next(row for row in actual_node["inputs"] if row["id"] == slot)
                if Path(actual_item["value"]).resolve() != (worlds / name).resolve():
                    raise AssertionError("The temporary path did not read back")
                # Native FilePath inputs normalize separators; string inputs do not.
                actual_item["value"] = item["value"]
            if normalized != expected:
                raise AssertionError("The temporary animation bindings changed unrelated graph state")
            call("setTime", port, timeInSecs=0)
            call("pumpFrames", port, count=3)
            initial_stats = call("getMetrics", port)["renderStats"]
            initial_loads = load_counters(initial_stats)
            rows = []
            for index, seconds in enumerate(TIMES):
                call("setTime", port, timeInSecs=seconds)
                call("pumpFrames", port, count=3)
                stats = call("getMetrics", port)["renderStats"]
                if load_counters(stats) != initial_loads:
                    raise AssertionError("Playback source-time steps caused additional disk loading")
                path = folder / f"{phase}_{index:02d}.png"
                call("screenshot", port, path=str(path.resolve()), target="output")
                with Image.open(path) as image:
                    rgb = image.convert("RGB")
                    red, green, blue = rgb.split()
                    brighter_than_red = ImageChops.subtract(blue, red.point(lambda value: min(255, int(value * 1.4))))
                    brighter_than_green = ImageChops.subtract(blue, green.point(lambda value: min(255, int(value * 1.05))))
                    positive = lambda value: 255 if value > 0 else 0
                    mask = ImageChops.multiply(brighter_than_red.point(positive), brighter_than_green.point(positive))
                    mask = ImageChops.multiply(mask, blue.point(lambda value: 255 if value > 40 else 0))
                    visible = mask.histogram()[255]
                    if visible < 20000:
                        raise AssertionError("Rendered geometry is missing at " + str(seconds))
                    dimensions = list(rgb.size)
                rows.append({"seconds": seconds, "path": path.name,
                             "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                             "dimensions": dimensions, "visibleBluePixels": visible})
            call("pumpFrames", port, count=10)
            held = call("getMetrics", port)["renderStats"]
            for key in ("Blender morph uploads", "Blender material uploads", "Blender upload bytes"):
                if held[key] != 0:
                    raise AssertionError("Held source frame performed additional uploads")
            report["phases"][phase] = {"graphVerified": True, "captures": rows,
                                       "loadCountersStable": True, "heldUploadsZero": True,
                                       "initialLoadCounters": initial_loads,
                                       "finalLoadCounters": load_counters(held)}
        for first, second in zip(report["phases"]["baseline"]["captures"],
                                 report["phases"]["optimized"]["captures"]):
            if first["sha256"] != second["sha256"] or first["dimensions"] != second["dimensions"]:
                raise AssertionError("Rendered cut or morph differs at " + str(first["seconds"]))
            report["comparisons"].append({"seconds": first["seconds"], "exactPngMatch": True,
                                           "sha256": first["sha256"]})
    except BaseException as error:
        failure, traceback = error, error.__traceback__
        report["failure"] = {"type": type(error).__name__, "message": str(error)}
    finally:
        _restore(call, port, context, view, original, applied, report)
        report["commandRestoration"] = report["restoration"]
        if report["stateRestored"]:
            try:
                report["originalNativeScenesRefreshed"] = reload_original_scenes(
                    original, payloads["baseline"], call, port)
            except BaseException as error:
                report["nativeRestorationFailure"] = {"type": type(error).__name__, "message": str(error)}
                if failure is None:
                    failure, traceback = error, error.__traceback__
            _restore(call, port, context, view, original, 0, report)
        report["status"] = "passed" if failure is None and report["restoration"]["verified"] else "failed"
        (folder / "render_comparison.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    if failure is not None:
        raise failure.with_traceback(traceback)
    if report["status"] != "passed":
        raise AssertionError("Original graph and editor state were not restored")
    return folder / "render_comparison.json"


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--optimized", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--port", type=int, default=9042)
    args = parser.parse_args()
    print(validate(args.baseline.resolve(), args.optimized.resolve(), args.output.resolve(), args.port))

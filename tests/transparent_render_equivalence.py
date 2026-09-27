"""Capture comparable transparent TiXL output through the local debug bridge.

Each invocation tests one loaded code phase. It temporarily redirects the
BlendShapeExample Cube animation paths, adds a transparent DrawScene fed from
TransparentResult and appends its command to the existing Cube scene group,
captures selected source times, then undoes every graph command and verifies
exact graph restoration. Run once for each code build, restoring the graph
before reloading the other build.

This harness never opens projects or writes graph files. It requires a supplied
GLB and matching TIXLANIM file that contain the same preserved Cube animation
track plus transparent material geometry.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import struct
import sys
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "blender_tixl_bridge" / "source"))
from tixl_bridge import call

TRANSPARENT_RESULT_ID = "20bcdd8a-2615-4e45-b9db-15548809a25e"
DRAW_SCENE_SYMBOL_ID = "2fcdea21-18f1-4006-a2fe-aab40893fed8"
DRAW_COMMAND_ID = "3b00e1d6-f966-4b03-81fc-2291e0fa7dbf"
ALPHA_BLEND_MODE = 0  # SharedEnums.BlendModes.Normal (source alpha compositing).


def _child_by_name(graph: dict, name: str) -> dict:
    found = [child for child in graph.get("children", []) if child.get("name") == name]
    if len(found) != 1:
        raise ValueError(f"Expected one graph child named {name!r}, found {len(found)}")
    return found[0]


def _input_by_name(child: dict, name: str) -> dict:
    found = [item for item in child.get("inputs", []) if item.get("name") == name]
    if len(found) != 1:
        raise ValueError(f"Expected one {name!r} input on {child.get('name')!r}")
    return found[0]


def _assert_fixture(glb: Path, animation: Path) -> None:
    for label, path in (("GLB", glb), ("animation cache", animation)):
        if not path.is_file() or path.is_symlink():
            raise ValueError(f"The supplied {label} must be an existing regular file: {path}")
        if path.stat().st_size <= 0:
            raise ValueError(f"The supplied {label} is empty: {path}")
    raw = glb.read_bytes()
    if len(raw) < 20 or raw[:4] != b"glTF" or struct.unpack_from("<I", raw, 4)[0] != 2:
        raise ValueError("The supplied transparent fixture is not a GLB 2.0 file")
    declared_length = struct.unpack_from("<I", raw, 8)[0]
    chunk_length, chunk_type = struct.unpack_from("<II", raw, 12)
    if declared_length != len(raw) or chunk_type != 0x4E4F534A or 20 + chunk_length > len(raw):
        raise ValueError("The supplied GLB has an invalid JSON chunk")
    document = json.loads(raw[20:20 + chunk_length].decode("utf-8").rstrip(" \0"))
    materials = document.get("materials", [])
    transparent_materials = {index for index, material in enumerate(materials)
                             if material.get("alphaMode") == "BLEND"
                             and material.get("pbrMetallicRoughness", {}).get("baseColorFactor", [1, 1, 1, 1])[3] < 1}
    transparent_primitives = sum(1 for mesh in document.get("meshes", [])
                                 for primitive in mesh.get("primitives", [])
                                 if primitive.get("material") in transparent_materials)
    if not transparent_primitives:
        raise ValueError("The fixture must contain at least one BLEND primitive with alpha below one")
    if animation.read_bytes()[:9] != b"TIXLANIM\x01":
        raise ValueError("The animation cache does not have the TIXLANIM binary signature")
    metadata_path = animation.with_suffix(".json")
    if metadata_path.is_file():
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        records = metadata.get("records", [])
        if not records or not any(row.get("count", 0) > 1 for row in records if isinstance(row, dict)):
            raise ValueError("The matching animation metadata must preserve a sampled Cube track")


def _verify_temporary_graph(graph: dict, motion: dict, draw_id: str, old_draw: dict,
                            native_load: dict, group: dict, glb: Path, animation: Path,
                            blend_mode: int, original_graph: dict) -> None:
    motion_now = _child_by_name(graph, motion["name"])
    draw_now = next((child for child in graph.get("children", []) if child.get("childId") == draw_id), None)
    if draw_now is None or draw_now.get("symbolId") != DRAW_SCENE_SYMBOL_ID:
        raise AssertionError("Temporary transparent DrawScene did not read back")
    values = {item["name"]: item.get("value") for item in motion_now.get("inputs", [])}
    if Path(values.get("GlbPath", "")).resolve() != glb.resolve():
        raise AssertionError("Temporary GLB path did not read back")
    if Path(values.get("DataPath", "")).resolve() != animation.resolve():
        raise AssertionError("Temporary animation path did not read back")
    load_now = _child_by_name(graph, native_load["name"])
    load_values = {item["name"]: item.get("value") for item in load_now.get("inputs", [])}
    if Path(load_values.get("Path", "")).resolve() != glb.resolve():
        raise AssertionError("Native Cube glTF loader did not read back the alpha fixture path")
    draw_values = {item["name"]: item.get("value") for item in draw_now.get("inputs", [])}
    if draw_values.get("BlendMode") != blend_mode or draw_values.get("EnableZWrite") is not False:
        raise AssertionError("Transparent draw settings did not read back")
    if draw_values.get("Color", {}).get("W") != 1.0:
        raise AssertionError("Transparent DrawScene color alpha was changed")
    old_now = _child_by_name(graph, old_draw["name"])
    old_values = {item["name"]: item.get("value") for item in old_now.get("inputs", [])}
    if (old_values.get("BlendMode") != blend_mode
            or old_values.get("EnableZWrite") is not False
            or old_values.get("Color", {}).get("W") != 0.0):
        raise AssertionError("Original Cube draw was not made transparent and non depth-writing")
    edges = graph.get("connections", [])
    for original_edge in original_graph.get("connections", []):
        if original_edge not in edges:
            raise AssertionError("A pre-existing graph connection changed during the temporary render")
    scene_input = _input_by_name(draw_now, "Scene")["id"]
    matched = [edge for edge in edges
               if edge.get("sourceParentOrChildId") == motion_now["childId"]
               and edge.get("sourceSlotId") == TRANSPARENT_RESULT_ID
               and edge.get("targetParentOrChildId") == draw_now["childId"]
               and edge.get("targetSlotId") == scene_input]
    if len(matched) != 1:
        raise AssertionError("TransparentResult is not uniquely connected to temporary DrawScene.Scene")
    command_input = _input_by_name(group, "Commands")["id"]
    command_edges = [edge for edge in edges
                     if edge.get("sourceParentOrChildId") == draw_now["childId"]
                     and edge.get("sourceSlotId") == DRAW_COMMAND_ID
                     and edge.get("targetParentOrChildId") == group["childId"]
                     and edge.get("targetSlotId") == command_input]
    if len(command_edges) != 1:
        raise AssertionError("Temporary DrawScene command is not connected to the Cube scene group")


def _restore(protocol_call: Callable, port: int, original_context: dict,
             original_view: dict, original_graph: dict, applied: int, report: dict) -> None:
    evidence: dict[str, Any] = {"attempts": [], "graphMatchesOriginal": None,
                                "contextMatchesOriginal": None, "graphViewMatchesOriginal": None,
                                "verified": False}

    def attempt(step: str, method: str, **params):
        record = {"step": step, "method": method}
        evidence["attempts"].append(record)
        try:
            value = protocol_call(method, port, **params)
        except BaseException as exc:
            record.update(status="failed", errorType=type(exc).__name__, error=str(exc))
            return False, None
        record["status"] = "passed"
        return True, value

    for index in range(applied):
        attempt(f"undo_{index + 1}", "undo")
    selected = original_context.get("selectedChildren", [])
    selected_ids = [row.get("childId") if isinstance(row, dict) else row for row in selected]
    attempt("restore_selection", "select", childIds=selected_ids)
    scale = original_view.get("scale")
    if isinstance(scale, (int, float)) and scale > 0:
        width, height = original_view.get("windowWidth", 0), original_view.get("windowHeight", 0)
        center_x = original_view.get("scrollX", 0) + width / (2 * scale)
        center_y = original_view.get("scrollY", 0) + height / (2 * scale)
        attempt("restore_graph_view", "setGraphView", centerX=center_x, centerY=center_y,
                scale=scale, smooth=False)
        view_ok, restored_view = attempt("readback_graph_view", "getGraphView")
        if view_ok:
            fields = ("scale", "scrollX", "scrollY")
            evidence["graphViewMatchesOriginal"] = all(
                isinstance(restored_view.get(key), (int, float))
                and abs(restored_view[key] - original_view[key]) <= 0.01
                for key in fields)
            if not evidence["graphViewMatchesOriginal"]:
                evidence["attempts"].append({"step": "verify_graph_view", "status": "failed",
                                             "errorType": "AssertionError",
                                             "error": "Temporary render did not restore graph view"})
    attempt("restore_time", "setTime", timeInSecs=original_context["time"]["timeInSecs"])
    attempt("pump_after_time_restore", "pumpFrames", count=3)
    graph_ok, restored_graph = attempt("readback_graph", "getGraphState", includeDefaults=True)
    # Preserve non-default rates: setting playing alone can reset speed.
    attempt("restore_playing", "setPlayback", playing=original_context["time"]["isPlaying"])
    attempt("restore_playback_speed", "setPlayback", speed=original_context["time"]["playbackSpeed"])
    context_ok, restored_context = attempt("readback_context", "getContext")

    if graph_ok:
        evidence["graphMatchesOriginal"] = restored_graph == original_graph
        if not evidence["graphMatchesOriginal"]:
            evidence["attempts"].append({"step": "verify_graph", "status": "failed",
                                         "errorType": "AssertionError",
                                         "error": "Temporary render did not restore the original graph"})
    if context_ok:
        actual_time = restored_context.get("time", {}) if isinstance(restored_context, dict) else {}
        expected_time = original_context["time"]
        static = lambda value: {key: val for key, val in value.items() if key != "time"}
        context_matches = (isinstance(restored_context, dict)
                           and static(restored_context) == static(original_context)
                           and actual_time.get("isPlaying") == expected_time["isPlaying"]
                           and actual_time.get("playbackSpeed") == expected_time["playbackSpeed"])
        if not expected_time["isPlaying"]:
            context_matches = context_matches and actual_time == expected_time
        original_selection = original_context.get("selectedChildren", [])
        actual_selection = restored_context.get("selectedChildren", []) if isinstance(restored_context, dict) else []
        context_matches = context_matches and actual_selection == original_selection
        evidence["contextMatchesOriginal"] = context_matches
        if not context_matches:
            evidence["attempts"].append({"step": "verify_context", "status": "failed",
                                         "errorType": "AssertionError",
                                         "error": "Temporary render did not restore original editor context"})
    evidence["verified"] = (all(row["status"] == "passed" for row in evidence["attempts"])
                            and evidence["graphMatchesOriginal"] is True
                            and evidence["graphViewMatchesOriginal"] is True
                            and evidence["contextMatchesOriginal"] is True)
    report["restoration"] = evidence
    report["stateRestored"] = evidence["verified"]


def _image_measurements(path: Path, *, require_visible: bool = True) -> dict:
    try:
        from PIL import Image, ImageChops, ImageStat
    except ImportError as exc:
        raise RuntimeError("Pillow is required to validate rendered PNGs") from exc
    with Image.open(path) as opened:
        image = opened.convert("RGBA")
        red, green, blue, _ = image.split()
        max_rgb = ImageChops.lighter(ImageChops.lighter(red, green), blue)
        visible_mask = max_rgb.point(lambda value: 255 if value > 3 else 0)
        rgb_nonzero = visible_mask.histogram()[255]
        if require_visible and rgb_nonzero == 0:
            raise AssertionError(f"Rendered output is black: {path}")
        return {"size": list(image.size), "visiblePixels": rgb_nonzero,
                "rgbMean": list(ImageStat.Stat(image.convert("RGB")).mean),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def _visible_difference(transparent: Path, control: Path) -> dict:
    try:
        from PIL import Image, ImageChops, ImageStat
    except ImportError as exc:
        raise RuntimeError("Pillow is required to validate transparent geometry visibility") from exc
    with Image.open(transparent) as a_open, Image.open(control) as b_open:
        a, b = a_open.convert("RGB"), b_open.convert("RGB")
        if a.size != b.size:
            raise AssertionError("Transparent and control output sizes differ")
        difference = ImageChops.difference(a, b)
        mean = sum(ImageStat.Stat(difference).mean) / 3
        red, green, blue = ImageChops.difference(a, b).split()
        max_difference = ImageChops.lighter(ImageChops.lighter(red, green), blue)
        changed_mask = max_difference.point(lambda value: 255 if value > 2 else 0)
        changed = changed_mask.histogram()[255]
        if changed < 8 or mean < 0.002:
            raise AssertionError("Transparent DrawScene did not visibly change the rendered output")
        return {"meanRgbDifference": mean, "changedPixels": changed}


def run_phase(*, phase: str, project: str, glb: Path, animation: Path,
              output_dir: Path, port: int = 9042, blend_mode: int = ALPHA_BLEND_MODE,
              times: tuple[float, ...], protocol_call: Callable = call) -> dict:
    """Run one transparent-render phase and undo all graph changes on exit."""
    _assert_fixture(glb, animation)
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", phase):
        raise ValueError("Phase labels may contain only letters, digits, underscore, and hyphen")
    if not times or any(not math.isfinite(value) or value < 0 for value in times):
        raise ValueError("Render times must be a non-empty list of finite non-negative seconds")
    if isinstance(blend_mode, bool) or not isinstance(blend_mode, int):
        raise ValueError("BlendMode must be the verified integer enum value for AlphaBlend")
    if blend_mode != ALPHA_BLEND_MODE:
        raise ValueError(f"Expected the verified BlendModes.Normal alpha blend value {ALPHA_BLEND_MODE}")
    output_dir.mkdir(parents=True, exist_ok=True)
    context = protocol_call("getContext", port)
    if context.get("compositionName") != project:
        raise ValueError(f"Expected the open project {project!r}; left current project untouched")
    graph_before = protocol_call("getGraphState", port, includeDefaults=True)
    if graph_before.get("missingChildren") or graph_before.get("missingConnections"):
        raise ValueError("Resolve missing graph items before running transparent render validation")
    motion = _child_by_name(graph_before, "Cube / opaque motion")
    old_draw = _child_by_name(graph_before, "Cube / opaque draw")
    native_load = _child_by_name(graph_before, "Cube / opaque load")
    group = _child_by_name(graph_before, "Cube / scene")
    if motion.get("symbolId") != "8cc13ea4-9e0d-4b61-9b1f-b72f6c470a7a":
        raise ValueError("Cube animation node is not the expected BlenderAnimationScene operator")
    motion_inputs = {name: _input_by_name(motion, name)["id"] for name in ("GlbPath", "DataPath")}
    load_path_input = _input_by_name(native_load, "Path")["id"]
    old_draw_inputs = {name: _input_by_name(old_draw, name)["id"]
                       for name in ("Color", "BlendMode", "EnableZWrite")}
    if group.get("symbolName") != "Group":
        raise ValueError("Cube / scene is not the expected Command group")
    report: dict[str, Any] = {"schema": 1, "phase": phase, "project": project,
                              "fixture": {"glb": str(glb.resolve()), "animation": str(animation.resolve())},
                              "blendModeAlphaBlend": blend_mode, "times": list(times),
                              "captures": [], "scope": "debug-protocol output screenshots; current graph is always undone and read back"}
    applied = 0
    graph_view = protocol_call("getGraphView", port)
    failure: BaseException | None = None
    traceback = None
    try:
        protocol_call("setPlayback", port, playing=False)
        protocol_call("setInput", port, childId=motion["childId"], inputId=motion_inputs["GlbPath"], value=str(glb.resolve()))
        applied += 1
        protocol_call("setInput", port, childId=motion["childId"], inputId=motion_inputs["DataPath"], value=str(animation.resolve()))
        applied += 1
        # DrawScene cannot be bypassed because its input/output types differ.
        # Point the native loader at the same BLEND fixture and make its current
        # draw invisible without writing depth, retaining its original edge.
        protocol_call("setInput", port, childId=native_load["childId"],
                      inputId=load_path_input, value=str(glb.resolve()))
        applied += 1
        protocol_call("setInput", port, childId=old_draw["childId"],
                      inputId=old_draw_inputs["Color"],
                      value={"X": 1.0, "Y": 1.0, "Z": 1.0, "W": 0.0})
        applied += 1
        protocol_call("setInput", port, childId=old_draw["childId"],
                      inputId=old_draw_inputs["BlendMode"], value=blend_mode)
        applied += 1
        protocol_call("setInput", port, childId=old_draw["childId"],
                      inputId=old_draw_inputs["EnableZWrite"], value=False)
        applied += 1
        added = protocol_call("addOp", port, symbolId=DRAW_SCENE_SYMBOL_ID,
                              posX=old_draw.get("posX", 0) + 250,
                              posY=old_draw.get("posY", 0) + 200)
        applied += 1
        draw_id = added.get("childId") if isinstance(added, dict) else None
        if not draw_id:
            raise RuntimeError("Debug bridge did not return the added DrawScene child ID")
        draw = next((child for child in protocol_call("getGraphState", port, includeDefaults=True).get("children", [])
                     if child.get("childId") == draw_id), None)
        if draw is None:
            raise RuntimeError("Added DrawScene was not present in the graph readback")
        draw_inputs = {name: _input_by_name(draw, name)["id"]
                       for name in ("Scene", "Color", "BlendMode", "EnableZWrite", "EnableZTest", "UseSceneMaterials")}
        protocol_call("setInput", port, childId=draw_id,
                      inputId=draw_inputs["UseSceneMaterials"], value=True)
        applied += 1
        protocol_call("setInput", port, childId=draw_id,
                      inputId=draw_inputs["BlendMode"], value=blend_mode)
        applied += 1
        protocol_call("setInput", port, childId=draw_id,
                      inputId=draw_inputs["EnableZWrite"], value=False)
        applied += 1
        protocol_call("setInput", port, childId=draw_id,
                      inputId=draw_inputs["EnableZTest"], value=True)
        applied += 1
        protocol_call("connect", port, sourceChildId=motion["childId"],
                      sourceOutput=TRANSPARENT_RESULT_ID, targetChildId=draw_id,
                      targetInput=draw_inputs["Scene"])
        applied += 1
        command_edges = [edge for edge in graph_before.get("connections", [])
                         if edge.get("targetParentOrChildId") == group["childId"]
                         and edge.get("targetSlotId") == _input_by_name(group, "Commands")["id"]]
        protocol_call("connect", port, sourceChildId=draw_id,
                      sourceOutput=DRAW_COMMAND_ID, targetChildId=group["childId"],
                      targetInput=_input_by_name(group, "Commands")["id"],
                      multiInputIndex=len(command_edges))
        applied += 1
        protocol_call("pumpFrames", port, count=3)
        staged = protocol_call("getGraphState", port, includeDefaults=True)
        _verify_temporary_graph(staged, motion, draw_id, old_draw, native_load, group,
                                glb, animation, blend_mode, graph_before)
        report["temporaryGraphVerified"] = True
        for index, seconds in enumerate(times):
            protocol_call("setTime", port, timeInSecs=seconds)
            protocol_call("pumpFrames", port, count=3)
            # SceneSetup serializes as a null value in this protocol. Read it
            # without forcing evaluation, and use normal rendered output plus
            # metrics for frame evidence.
            transparent_output = protocol_call("getOutput", port, childId=motion["childId"],
                                               outputId=TRANSPARENT_RESULT_ID)
            if (transparent_output.get("outputId", "").lower() != TRANSPARENT_RESULT_ID.lower()
                    or transparent_output.get("valueType") != "SceneSetup"):
                raise AssertionError("TransparentResult output could not be read back as SceneSetup")
            metrics = protocol_call("getMetrics", port)
            report.setdefault("transparentOutputReadbacks", []).append({
                "seconds": seconds, "valueType": transparent_output.get("valueType"),
                "outputId": transparent_output.get("outputId"),
                "renderStats": metrics.get("renderStats", {}),
                "note": "SceneSetup dispatches are checked through normal output rendering; debug getOutput cannot serialize SceneSetup"})
            image_path = output_dir / f"{phase}_{index:02d}_{seconds:.6f}.png"
            protocol_call("screenshot", port, path=str(image_path), target="output")
            metrics = _image_measurements(image_path)
            original_draw_color = _input_by_name(draw, "Color").get("value")
            if not isinstance(original_draw_color, dict):
                raise ValueError("Temporary DrawScene Color input did not contain a vector value")
            no_alpha = dict(original_draw_color)
            no_alpha["W"] = 0.0
            protocol_call("setInput", port, childId=draw_id,
                          inputId=draw_inputs["Color"], value=no_alpha)
            applied += 1
            protocol_call("pumpFrames", port, count=3)
            control_path = output_dir / f"{phase}_{index:02d}_{seconds:.6f}_without_transparent.png"
            protocol_call("screenshot", port, path=str(control_path), target="output")
            control_metrics = _image_measurements(control_path, require_visible=False)
            protocol_call("setInput", port, childId=draw_id,
                          inputId=draw_inputs["Color"], value=original_draw_color)
            applied += 1
            protocol_call("pumpFrames", port, count=3)
            delta = _visible_difference(image_path, control_path)
            report["captures"].append({"seconds": seconds, "path": str(image_path.resolve()), **metrics,
                                       "withoutTransparentPath": str(control_path.resolve()),
                                       "withoutTransparentMetrics": control_metrics,
                                       "transparentPathContribution": delta})
        report["status"] = "passed"
    except BaseException as exc:
        failure = exc
        traceback = exc.__traceback__
        report["status"] = "failed"
        report["failure"] = {"errorType": type(exc).__name__, "error": str(exc)}
    _restore(protocol_call, port, context, graph_view, graph_before, applied, report)
    report_path = output_dir / f"{phase}_report.json"
    report_path.write_text(json.dumps(report, indent=2, allow_nan=False), encoding="utf-8")
    if not report["stateRestored"]:
        report["status"] = "failed"
        report_path.write_text(json.dumps(report, indent=2, allow_nan=False), encoding="utf-8")
        raise AssertionError(f"Transparent render phase could not verify restoration; see {report_path}")
    if failure is not None:
        raise failure.with_traceback(traceback)
    return report


def compare_phases(reference_report: Path, candidate_report: Path, *, max_mean_error: float = 0.5) -> dict:
    """Compare phase screenshots per pixel; both inputs must be successful reports."""
    try:
        from PIL import Image, ImageChops, ImageStat
    except ImportError as exc:
        raise RuntimeError("Pillow is required to compare rendered PNGs") from exc
    left = json.loads(reference_report.read_text(encoding="utf-8"))
    right = json.loads(candidate_report.read_text(encoding="utf-8"))
    for report in (left, right):
        if report.get("status") != "passed" or report.get("stateRestored") is not True:
            raise ValueError("Both phase reports must pass and prove graph/context restoration")
    a, b = left["captures"], right["captures"]
    if [(row["seconds"], row["size"]) for row in a] != [(row["seconds"], row["size"]) for row in b]:
        raise ValueError("Phase sample times or output sizes differ")
    rows = []
    for first, second in zip(a, b):
        with Image.open(first["path"]) as first_open, Image.open(second["path"]) as second_open:
            image_a, image_b = first_open.convert("RGBA"), second_open.convert("RGBA")
            difference = ImageChops.difference(image_a, image_b)
            mean = sum(ImageStat.Stat(difference).mean[:3]) / 3
            maximum = max(difference.getextrema()[channel][1] for channel in range(3))
            if mean > max_mean_error:
                raise AssertionError(f"Render changed at {first['seconds']}s: mean RGB error {mean:.4f}")
            rows.append({"seconds": first["seconds"], "meanRgbError": mean, "maxRgbError": maximum})
    return {"schema": 1, "reference": str(reference_report.resolve()),
            "candidate": str(candidate_report.resolve()), "maxMeanRgbError": max_mean_error,
            "samples": rows, "status": "passed"}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=9042)
    parser.add_argument("--project", default="BlendShapeExample")
    parser.add_argument("--phase", required=True, help="short label such as baseline or optimized")
    parser.add_argument("--glb", type=Path, required=True, help="private transparent GLB fixture")
    parser.add_argument("--animation", type=Path, required=True, help="matching animation cache")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--blend-mode-alpha", type=int, default=ALPHA_BLEND_MODE,
                        help="Verified TiXL SharedEnums.BlendModes.Normal is 0")
    parser.add_argument("--times", default="0,1.5", help="comma-separated source seconds")
    parser.add_argument("--compare-to", type=Path, help="compare captures to a successful phase report")
    parser.add_argument("--max-mean-error", type=float, default=0.5)
    args = parser.parse_args()
    times = tuple(float(value.strip()) for value in args.times.split(",") if value.strip())
    report = run_phase(phase=args.phase, project=args.project, glb=args.glb.resolve(),
                       animation=args.animation.resolve(), output_dir=args.output_dir.resolve(),
                       port=args.port, blend_mode=args.blend_mode_alpha, times=times)
    report_path = args.output_dir.resolve() / f"{args.phase}_report.json"
    if args.compare_to:
        comparison = compare_phases(args.compare_to.resolve(), report_path,
                                    max_mean_error=args.max_mean_error)
        comparison_path = args.output_dir.resolve() / f"{args.phase}_comparison.json"
        comparison_path.write_text(json.dumps(comparison, indent=2), encoding="utf-8")
        print(comparison_path)
    else:
        print(report_path)


if __name__ == "__main__":
    main()

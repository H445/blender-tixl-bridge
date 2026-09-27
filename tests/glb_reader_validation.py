"""Numeric regression harness for the production private GLB reader.

Creates a small deterministic GLB fixture, extracts the production reader and
its output records from BlenderAnimationScene.cs, compiles that exact source
with a tiny System.Numerics PbrVertex stub, then checks returned values. Requires
only Python's standard library and the .NET 8 SDK (also works with .NET 10).

Examples:
  python tests/glb_reader_validation.py
  python tests/glb_reader_validation.py --require-single-parse --baseline baseline.json
"""
from __future__ import annotations

import argparse
import json
import os
import struct
import subprocess
import tempfile
from pathlib import Path

from csharp_source import extract_class, write_net8_project


ROOT = Path(__file__).resolve().parents[1]
OPERATOR = ROOT / "blender_tixl_bridge" / "operators" / "BlenderAnimationScene.cs"
MARKER = "GLB_READER_VALIDATION "


class GlbFixture:
    """Write tightly controlled, interleaved GLB accessors without dependencies."""

    def __init__(self, *, reload_variant: bool = False, missing_material_name: bool = False,
                 invalid_center_accessor: bool = False):
        self.binary = bytearray()
        self.views: list[dict] = []
        self.accessors: list[dict] = []
        self.meshes: list[dict] = []
        self.reload_variant = reload_variant
        self.missing_material_name = missing_material_name
        self.invalid_center_accessor = invalid_center_accessor

    def _align(self, alignment: int = 4) -> None:
        self.binary.extend(b"\0" * ((-len(self.binary)) % alignment))

    def accessor(self, rows, *, component: int, shape: str, stride: int | None = None,
                 prefix: bytes = b"", bounds: bool = False) -> int:
        components = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4}[shape]
        fmt, scalar_size = {5126: ("f", 4), 5123: ("H", 2)}[component]
        row_size = components * scalar_size
        stride = stride or row_size
        if stride < row_size or stride % scalar_size:
            raise ValueError("invalid fixture accessor stride")
        self._align(4)
        view_start = len(self.binary)
        self.binary.extend(prefix)
        accessor_offset = len(prefix)
        for row in rows:
            if not isinstance(row, (tuple, list)):
                row = (row,)
            if len(row) != components:
                raise ValueError(f"{shape} row has the wrong component count")
            self.binary.extend(struct.pack("<" + fmt * components, *row))
            self.binary.extend(b"\0" * (stride - row_size))
        view_length = len(self.binary) - view_start
        view = {"buffer": 0, "byteOffset": view_start, "byteLength": view_length}
        if stride != row_size:
            view["byteStride"] = stride
        view_index = len(self.views)
        self.views.append(view)
        accessor = {"bufferView": view_index, "byteOffset": accessor_offset,
                    "componentType": component, "count": len(rows), "type": shape}
        if bounds and shape == "VEC3":
            accessor["min"] = [min(row[i] for row in rows) for i in range(3)]
            accessor["max"] = [max(row[i] for row in rows) for i in range(3)]
        accessor_index = len(self.accessors)
        self.accessors.append(accessor)
        return accessor_index

    def sparse_accessor(self, count: int, entries: list[tuple[int, tuple[float, float, float]]]) -> int:
        sparse_indices = self.accessor([(index,) for index, _ in entries],
                                       component=5123, shape="SCALAR")
        sparse_values = self.accessor([value for _, value in entries],
                                      component=5126, shape="VEC3", stride=16)
        indices_accessor = self.accessors[sparse_indices]
        values_accessor = self.accessors[sparse_values]
        accessor_index = len(self.accessors)
        self.accessors.append({
            "componentType": 5126, "count": count, "type": "VEC3",
            "sparse": {"count": len(entries),
                       "indices": {"bufferView": indices_accessor["bufferView"],
                                   "componentType": indices_accessor["componentType"]},
                       "values": {"bufferView": values_accessor["bufferView"]}},
        })
        return accessor_index

    def write(self, path: Path) -> None:
        if len(self.binary) % 4:
            self._align()
        glass = {"name": "GlassPaint", "alphaMode": "BLEND",
                 "pbrMetallicRoughness": {"baseColorFactor": [0.25, 0.5, 0.75,
                                            0.6 if self.reload_variant else 0.35]},
                 "emissiveFactor": [0.1, 0.2, 0.3],
                 "extensions": {"KHR_materials_emissive_strength": {"emissiveStrength": 2.0}}}
        if self.missing_material_name:
            glass.pop("name")
        document = {
            "asset": {"version": "2.0", "generator": "tests/glb_reader_validation.py"},
            "scene": 0,
            "scenes": [{"nodes": [0, 1]}],
            "nodes": [
                {"name": "OpaqueCluster", "mesh": 0, "translation": [4, 5, 6],
                 "rotation": [0, 0, 0.70710677, 0.70710677], "scale": [2, 2, 2],
                 "weights": [0.25, 0.5, 0.75]},
                {"name": "BlendCluster", "mesh": 1, "translation": [-3, 2, 1],
                 "rotation": [0, 0, 0, 1], "scale": [0.5, 1.5, 2]},
            ],
            "meshes": self.meshes,
            "materials": [
                {"name": "OpaquePaint", "alphaMode": "OPAQUE",
                 "pbrMetallicRoughness": {"baseColorFactor": [0.8, 0.7, 0.6, 1.0],
                                          "metallicFactor": 0.3, "roughnessFactor": 0.4}},
                {"name": "SecondaryPaint", "alphaMode": "OPAQUE",
                 "pbrMetallicRoughness": {"baseColorFactor": [0.2, 0.3, 0.4, 1.0]}},
                glass,
            ],
            "buffers": [{"byteLength": len(self.binary)}],
            "bufferViews": self.views,
            "accessors": self.accessors,
        }
        json_bytes = json.dumps(document, separators=(",", ":"), allow_nan=False).encode("utf-8")
        json_bytes += b" " * ((-len(json_bytes)) % 4)
        total = 12 + 8 + len(json_bytes) + 8 + len(self.binary)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("wb") as stream:
            stream.write(struct.pack("<III", 0x46546C67, 2, total))
            stream.write(struct.pack("<II", len(json_bytes), 0x4E4F534A))
            stream.write(json_bytes)
            stream.write(struct.pack("<II", len(self.binary), 0x004E4942))
            stream.write(self.binary)


def make_fixture(path: Path, *, reload_variant: bool = False, missing_material_name: bool = False,
                 invalid_center_accessor: bool = False) -> dict:
    glb = GlbFixture(reload_variant=reload_variant, missing_material_name=missing_material_name,
                     invalid_center_accessor=invalid_center_accessor)
    # Accessor 0 has a byteOffset inside an interleaved bufferView and a
    # byteStride of 16; the other vector records exercise strided decoding.
    opaque_positions = [(0, 0, 0), (2, 0, 0), (0, 2, 0)]
    opaque_normals = [(0, 0, 1)] * 3
    uv = [(0, 0), (1, 0), (0, 1)]
    indices = [(0,), (1,), (2,)]
    pos0 = glb.accessor(opaque_positions, component=5126, shape="VEC3", stride=16,
                        prefix=b"PAD!", bounds=True)
    normal0 = glb.accessor(opaque_normals, component=5126, shape="VEC3", stride=16)
    uv0 = glb.accessor(uv, component=5126, shape="VEC2", stride=12)
    indices0 = glb.accessor(indices, component=5123, shape="SCALAR")
    target_delta_z = 4.5 if reload_variant else 1.5
    target0_pos = [(0, 0, 0.5), (0, 0, 1.0), (0, 0, target_delta_z)]
    target0_norm = [(0.1, 0, 0), (0.2, 0, 0), (0.3, 0, 0)]
    target1_pos = [(1, 0, 0), (1, 0, 0), (1, 0, 0)]
    target0_pos_accessor = glb.accessor(target0_pos, component=5126, shape="VEC3", stride=16)
    target0_normal_accessor = glb.accessor(target0_norm, component=5126, shape="VEC3", stride=16)
    target1_pos_accessor = glb.accessor(target1_pos, component=5126, shape="VEC3", stride=16)
    sparse_pos_accessor = glb.sparse_accessor(3, [(2, (0.5, -0.5, 2.0))])
    secondary_positions = [(10, 0, 0), (12, 0, 0), (10, 2, 0)]
    pos1 = glb.accessor(secondary_positions, component=5126, shape="VEC3", stride=16,
                        bounds=True)
    indices1 = glb.accessor(indices, component=5123, shape="SCALAR")
    glass_positions = [(-2, 0, 0), (0, 0, 0), (-2, 1, 0)]
    pos2 = glb.accessor(glass_positions, component=5126, shape="VEC3", stride=16,
                        bounds=True)
    indices2 = glb.accessor(indices, component=5123, shape="SCALAR")
    glb.meshes = [
        {"name": "OpaqueMesh", "primitives": [
            {"attributes": {"POSITION": pos0, "NORMAL": normal0, "TEXCOORD_0": uv0},
             "indices": indices0, "material": 0, "targets": [
                 {"POSITION": target0_pos_accessor, "NORMAL": target0_normal_accessor},
                 {"POSITION": target1_pos_accessor}, {"POSITION": sparse_pos_accessor}]},
            {"attributes": {"POSITION": pos1}, "indices": indices1, "material": 1},
        ]},
        {"name": "BlendMesh", "primitives": [
            {"attributes": {"POSITION": pos2}, "indices": indices2, "material": 2},
        ]},
    ]
    if invalid_center_accessor:
        glb.meshes[1]["primitives"][0]["attributes"]["POSITION"] = 10000
    glb.write(path)
    return {"opaqueCenterLocal": [1.0, 1.0, 0.0],
            "secondaryCenterLocal": [11.0, 1.0, 0.0],
            "blendCenterLocal": [-1.0, 0.5, 0.0],
            "opaqueNodeTransform": {"translation": [4, 5, 6],
                                    "rotationZDegrees": 90, "scale": [2, 2, 2]},
            "morphDefaultWeights": [0.25, 0.5, 0.75], "indices": [0, 1, 2],
            "alphaMode": "BLEND", "blendBaseFactor": [0.25, 0.5, 0.75,
                                                          0.6 if reload_variant else 0.35],
            "emissionWithStrength": [0.2, 0.4, 0.6, 1.0]}


CSHARP_PROGRAM = r'''using System;
using System.Collections;
using System.Diagnostics;
using System.Linq;
using System.Numerics;
using System.Reflection;
using System.Text.Json;

namespace ProductionReader;

internal static class ReaderCounters
{
    public static int FileReads;
    public static int JsonParses;
    public static void Reset() { FileReads = 0; JsonParses = 0; }
    public static FileStream OpenRead(string path) { FileReads++; return File.OpenRead(path); }
    public static byte[] ReadAllBytes(string path) { FileReads++; return File.ReadAllBytes(path); }
    public static JsonDocument ParseJson(byte[] bytes) { JsonParses++; return JsonDocument.Parse(bytes); }
    public static JsonDocument ParseJson(Stream stream) { JsonParses++; return JsonDocument.Parse(stream); }
}

internal static class Program
{
    private const int WarmupIterations = 5;
    private const int DefaultMeasuredIterations = 40;
    private static void Need(bool condition, string message)
    {
        if (!condition) throw new InvalidOperationException(message);
    }
    private static bool Near(float actual, float expected) => MathF.Abs(actual - expected) < 1e-5f;
    private static void Vec(Vector3 actual, float x, float y, float z, string label) =>
        Need(Near(actual.X, x) && Near(actual.Y, y) && Near(actual.Z, z), label + " mismatch: " + actual);
    private static void Vec(Vector4 actual, float x, float y, float z, float w, string label) =>
        Need(Near(actual.X, x) && Near(actual.Y, y) && Near(actual.Z, z) && Near(actual.W, w), label + " mismatch: " + actual);
    private static object Member(object value, string name)
    {
        var type = value.GetType();
        var flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
        var property = type.GetProperty(name, flags);
        if (property != null) return property.GetValue(value)!;
        var field = type.GetField(name, flags);
        if (field != null) return field.GetValue(value)!;
        throw new InvalidOperationException("Missing output member " + type.Name + "." + name);
    }
    private static object Invoke(MethodInfo method, string path) => method.Invoke(null, new object[] { path })!;
    private static MethodInfo FindMethod(MethodInfo[] methods, string name) => methods.First(m =>
        m.Name == name && m.IsStatic && m.GetParameters().Length == 1 && m.GetParameters()[0].ParameterType == typeof(string));
    private static (object Morphs, object MaterialDefaults, object PrimitiveCenters) Load(
        MethodInfo[] methods, MethodInfo? aggregateMethod, string path)
    {
        if (aggregateMethod != null)
        {
            var result = Invoke(aggregateMethod, path);
            return (Member(result, "Morphs"), Member(result, "MaterialDefaults"), Member(result, "PrimitiveCenters"));
        }
        return (Invoke(FindMethod(methods, "LoadMorphs"), path),
                Invoke(FindMethod(methods, "LoadMaterialDefaults"), path),
                Invoke(FindMethod(methods, "LoadPrimitiveCenters"), path));
    }
    private static double Percentile(long[] values, double percentile)
    {
        var sorted = values.OrderBy(value => value).ToArray();
        var index = Math.Clamp((int)Math.Ceiling(percentile * sorted.Length) - 1, 0, sorted.Length - 1);
        return sorted[index];
    }
    private static double Percentile(double[] values, double percentile)
    {
        var sorted = values.OrderBy(value => value).ToArray();
        var index = Math.Clamp((int)Math.Ceiling(percentile * sorted.Length) - 1, 0, sorted.Length - 1);
        return sorted[index];
    }

    public static int Main(string[] args)
    {
        try
        {
            var path = args[0];
            var reloadPath = args[1];
            var malformedMaterialPath = args[2];
            var malformedCenterPath = args[3];
            var requireSingleParse = args.Skip(4).Contains("--require-single-parse");
            var iterationsArg = args.Skip(4).FirstOrDefault(arg => arg.StartsWith("--iterations="));
            var iterations = iterationsArg == null ? DefaultMeasuredIterations
                : int.Parse(iterationsArg.Substring("--iterations=".Length));
            Need(iterations >= 30, "Use at least 30 measured iterations");
            var methods = typeof(GlbReader).GetMethods(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Static);
            var aggregateMethod = methods.FirstOrDefault(m => m.IsStatic && m.GetParameters().Length == 1
                && m.GetParameters()[0].ParameterType == typeof(string)
                && HasMember(m.ReturnType, "Morphs") && HasMember(m.ReturnType, "MaterialDefaults")
                && HasMember(m.ReturnType, "PrimitiveCenters"));
            var api = aggregateMethod?.Name ?? "legacy-three-methods";

            // Warm the actual extracted production code before recording any
            // timing or allocation sample, including JIT compilation.
            for (var warmup = 0; warmup < WarmupIterations; warmup++)
                _ = Load(methods, aggregateMethod, path);

            ReaderCounters.Reset();
            var allocationSamples = new long[iterations];
            var timeSamples = new double[iterations];
            (object Morphs, object MaterialDefaults, object PrimitiveCenters) first = default!;
            for (var iteration = 0; iteration < iterations; iteration++)
            {
                var allocatedBefore = GC.GetAllocatedBytesForCurrentThread();
                var started = Stopwatch.GetTimestamp();
                var sample = Load(methods, aggregateMethod, path);
                timeSamples[iteration] = Stopwatch.GetElapsedTime(started).TotalMilliseconds;
                allocationSamples[iteration] = GC.GetAllocatedBytesForCurrentThread() - allocatedBefore;
                if (iteration == 0) first = sample;
            }
            var morphMap = (IDictionary)first.Morphs;
            var materialMap = (IDictionary)first.MaterialDefaults;
            var centerMap = (IDictionary)first.PrimitiveCenters;

            Need(morphMap.Contains("OpaqueCluster"), "Morph-bearing node missing");
            var primitives = (IList)morphMap["OpaqueCluster"]!;
            Need(primitives.Count == 2, "Multi-primitive mesh order/count changed");
            var firstPrimitive = primitives[0]!;
            var baseVertices = (Array)Member(firstPrimitive, "Base");
            Need(baseVertices.Length == 3, "Base POSITION accessor count mismatch");
            Vec((Vector3)Member(baseVertices.GetValue(1)!, "Position"), 2, 0, 0, "strided/offset base POSITION");
            var indices = (int[])Member(firstPrimitive, "Indices");
            Need(indices.SequenceEqual(new[] { 0, 1, 2 }), "Unsigned-short indices mismatch");
            var targets = (Array)Member(firstPrimitive, "Targets");
            Need(targets.Length == 3, "Morph target count mismatch");
            var target0 = targets.GetValue(0)!;
            var targetPositions = (Vector3[])Member(target0, "Positions");
            var targetNormals = (Vector3[])Member(target0, "Normals");
            Vec(targetPositions[2], 0, 0, 1.5f, "strided morph POSITION");
            Vec(targetNormals[1], 0.2f, 0, 0, "strided morph NORMAL");
            Need((bool)Member(firstPrimitive, "RecomputeNormals"), "Missing NORMAL target did not request recomputation");
            var sparsePositions = (Vector3[])Member(targets.GetValue(2)!, "Positions");
            Vec(sparsePositions[2], 0.5f, -0.5f, 2, "sparse morph POSITION");
            var weights = (float[])Member(firstPrimitive, "DefaultWeights");
            Need(weights.Length == 3 && Near(weights[0], 0.25f) && Near(weights[1], 0.5f)
                 && Near(weights[2], 0.75f), "Node default morph weights mismatch");
            Need(((Array)Member(primitives[1]!, "Targets")).Length == 0, "Non-morph primitive should remain in mesh order");
            Need(!morphMap.Contains("BlendCluster"), "Non-morph node should not be returned as morph-bearing");

            var glass = materialMap["GlassPaint"]!;
            Vec((Vector4)Member(glass, "BaseFactor"), 0.25f, 0.5f, 0.75f, 0.35f, "alpha-blend material factor");
            Vec((Vector4)Member(glass, "EmissionFactor"), 0.2f, 0.4f, 0.6f, 1, "emissive strength");
            Need(!((bool)Member(glass, "HasBaseTexture")), "Unexpected base texture flag");
            var opaque = materialMap["OpaquePaint"]!;
            Vec((Vector4)Member(opaque, "BaseFactor"), 0.8f, 0.7f, 0.6f, 1, "opaque material factor");

            var opaqueCenters = (IList)centerMap["OpaqueCluster"]!;
            var blendCenters = (IList)centerMap["BlendCluster"]!;
            Need(opaqueCenters.Count == 2 && blendCenters.Count == 1, "Primitive center grouping/count mismatch");
            Vec((Vector3)opaqueCenters[0]!, 1, 1, 0, "opaque primitive center");
            Vec((Vector3)opaqueCenters[1]!, 11, 1, 0, "secondary primitive center");
            Vec((Vector3)blendCenters[0]!, -1, 0.5f, 0, "alpha primitive center");

            var localCenter = (Vector3)opaqueCenters[0]!;
            var transform = Matrix4x4.CreateScale(2) * Matrix4x4.CreateRotationZ(MathF.PI / 2)
                            * Matrix4x4.CreateTranslation(4, 5, 6);
            var transformedCenter = Vector3.Transform(localCenter, transform);
            Vec(transformedCenter, 2, 7, 6, "fixture node transform applied to local primitive center");

            var readCallsBeforeReload = ReaderCounters.FileReads;
            var parseCallsBeforeReload = ReaderCounters.JsonParses;
            Need(readCallsBeforeReload == iterations * (aggregateMethod == null ? 3 : 1)
                 && parseCallsBeforeReload == readCallsBeforeReload,
                 "Unexpected read/parse instrumentation counts during measured iterations");

            // Replace bytes at the exact same path, then invoke the production
            // reader again. This detects accidental path-keyed stale sharing.
            File.Copy(reloadPath, path, overwrite: true);
            var reloaded = Load(methods, aggregateMethod, path);
            var reloadMorphs = (IDictionary)reloaded.Morphs;
            var reloadPrimitives = (IList)reloadMorphs["OpaqueCluster"]!;
            var reloadTargets = (Array)Member(reloadPrimitives[0]!, "Targets");
            var reloadedDelta = (Vector3[])Member(reloadTargets.GetValue(0)!, "Positions");
            Vec(reloadedDelta[2], 0, 0, 4.5f, "same-path updated morph delta");
            var reloadMaterials = (IDictionary)reloaded.MaterialDefaults;
            Vec((Vector4)Member(reloadMaterials["GlassPaint"]!, "BaseFactor"),
                0.25f, 0.5f, 0.75f, 0.6f, "same-path updated material factor");
            var movedPath = path + ".disposed-check";
            File.Move(path, movedPath);
            File.Move(movedPath, path);
            var samePathReload = new { morphTargetPosition = new[] { 0f, 0f, 4.5f }, glassAlpha = 0.6f,
                                       fileHandleReleasedForMove = true };

            var malformedResults = new List<object>();
            var measuredMethod = methods.FirstOrDefault(m => m.Name == "LoadAllMeasured" && m.IsStatic);
            if (measuredMethod != null)
            {
                foreach (var malformedPath in new[] { malformedMaterialPath, malformedCenterPath })
                {
                    ReaderCounters.Reset();
                    var readCallback = 0;
                    var parseCallback = 0;
                    var parameters = measuredMethod.GetParameters();
                    var invokeArgs = new object?[parameters.Length];
                    invokeArgs[0] = malformedPath;
                    for (var index = 1; index < parameters.Length; index++)
                    {
                        var callbackName = parameters[index].Name;
                        if (parameters[index].ParameterType == typeof(Action))
                            invokeArgs[index] = (Action)(() =>
                            {
                                if (callbackName?.Contains("read", StringComparison.OrdinalIgnoreCase) == true)
                                    readCallback++;
                                else
                                    parseCallback++;
                            });
                    }
                    object? partial = null;
                    Exception? projectionFailure = null;
                    try { partial = measuredMethod.Invoke(null, invokeArgs); }
                    catch (TargetInvocationException error) { projectionFailure = error.InnerException ?? error; }
                    Need(projectionFailure != null && partial == null,
                         "Malformed later projection returned partially assigned scene data");
                    Need(readCallback == 1 && parseCallback == 1
                         && ReaderCounters.FileReads == 1 && ReaderCounters.JsonParses == 1,
                         $"Failed projection counts were callbacks={readCallback}/{parseCallback}, " +
                         $"instrumented={ReaderCounters.FileReads}/{ReaderCounters.JsonParses}");
                    malformedResults.Add(new { path = Path.GetFileName(malformedPath),
                        failure = projectionFailure.GetType().Name, readCallback, parseCallback,
                        fileReadCalls = ReaderCounters.FileReads, jsonParseCalls = ReaderCounters.JsonParses,
                        returnedPartialData = partial != null });
                }
            }

            Need(readCallsBeforeReload > 0 && parseCallsBeforeReload > 0, "Reader instrumentation did not run");
            Need(!requireSingleParse || (readCallsBeforeReload == iterations && parseCallsBeforeReload == iterations),
                 "Single-parse API performed more than one file read or JSON parse per iteration");
            Need(!requireSingleParse || (measuredMethod != null && malformedResults.Count == 2),
                 "Production atomic projection failure cases were not exercised");
            var numeric = new {
                opaqueBasePosition1 = new[] { 2f, 0f, 0f },
                morphPositionTarget0Vertex2 = new[] { 0f, 0f, 1.5f },
                morphNormalTarget0Vertex1 = new[] { 0.2f, 0f, 0f },
                sparseMorphPositionTarget2Vertex2 = new[] { 0.5f, -0.5f, 2f },
                morphWeights = weights,
                primitiveCenters = new[] { new[] { 1f, 1f, 0f }, new[] { 11f, 1f, 0f }, new[] { -1f, 0.5f, 0f } },
                transformedOpaqueCenter = new[] { 2f, 7f, 6f },
                glassBaseFactor = new[] { 0.25f, 0.5f, 0.75f, 0.35f },
                glassEmissionFactor = new[] { 0.2f, 0.4f, 0.6f, 1f },
                opaqueBaseFactor = new[] { 0.8f, 0.7f, 0.6f, 1f },
                indices = indices,
            };
            var report = new {
                schema = 1, status = "passed", readerApi = api,
                measuredIterations = iterations, warmupIterations = WarmupIterations,
                fileReadCalls = readCallsBeforeReload, jsonParseCalls = parseCallsBeforeReload,
                readsPerIteration = (double)readCallsBeforeReload / iterations,
                parsesPerIteration = (double)parseCallsBeforeReload / iterations,
                allocatedBytesMedian = Percentile(allocationSamples, 0.5),
                allocatedBytesP95 = Percentile(allocationSamples, 0.95),
                elapsedMillisecondsMedian = Percentile(timeSamples, 0.5),
                elapsedMillisecondsP95 = Percentile(timeSamples, 0.95),
                samePathReload, malformedAtomicFailures = malformedResults,
                atomicFailureTestSupported = measuredMethod != null,
                numericResults = numeric,
            };
            Console.WriteLine("GLB_READER_VALIDATION " + JsonSerializer.Serialize(report));
            return 0;
        }
        catch (Exception error)
        {
            Console.Error.WriteLine(error);
            return 1;
        }
    }

    private static bool HasMember(Type type, string name) =>
        type.GetProperty(name, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic) != null
        || type.GetField(name, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic) != null;
}
'''


def create_project(project: Path, source_path: Path) -> None:
    write_net8_project(project, "GlbReaderValidation", CSHARP_PROGRAM)
    operator = source_path.read_text(encoding="utf-8")
    extracted = [extract_class(operator, name) for name in
                 ("MaterialDefaults", "MorphTarget", "MorphMesh", "GlbReader")]
    extracted_reader = "\n\n".join(extracted)
    extracted_reader = extracted_reader.replace("File.OpenRead(", "ReaderCounters.OpenRead(")
    extracted_reader = extracted_reader.replace("File.ReadAllBytes(", "ReaderCounters.ReadAllBytes(")
    extracted_reader = extracted_reader.replace("JsonDocument.Parse(", "ReaderCounters.ParseJson(")
    stub = """using System;
using System.IO;
using System.Numerics;
using System.Text.Json;
using System.Collections.Generic;
namespace ProductionReader;
internal struct PbrVertex
{
 public Vector3 Position; public Vector3 Normal; public Vector3 Tangent;
 public Vector3 Bitangent; public Vector2 Texcoord; public Vector2 Texcoord2;
 public Vector3 ColorRgb; public float Selection;
}
"""
    (project / "GlbReaderUnderTest.cs").write_text(
        stub + "\n" + extracted_reader, encoding="utf-8")


def run(args) -> dict:
    fixture_meta = {}
    keep_dir = Path(args.artifact_dir).resolve() if args.artifact_dir else None
    if keep_dir:
        keep_dir.mkdir(parents=True, exist_ok=True)
    temp_context = tempfile.TemporaryDirectory(prefix="glb-reader-validation-")
    try:
        temporary = Path(temp_context.name)
        project = temporary / "project"
        project.mkdir()
        dotnet_home = project / "dotnet-home"
        app_data = project / "app-data"
        nuget_dir = app_data / "NuGet"
        nuget_dir.mkdir(parents=True)
        (nuget_dir / "NuGet.Config").write_text(
            "<configuration><packageSources><clear /></packageSources></configuration>",
            encoding="utf-8")
        environment = dict(os.environ)
        environment.update({"DOTNET_CLI_HOME": str(dotnet_home),
                            "NUGET_CLI_HOME": str(project / "nuget-home"),
                            "APPDATA": str(app_data),
                            "LOCALAPPDATA": str(project / "local-app-data")})
        fixture = (keep_dir / "numeric_reader_fixture.glb") if keep_dir else temporary / "numeric_reader_fixture.glb"
        fixture_meta = make_fixture(fixture)
        reload_fixture = temporary / "same_path_reload.glb"
        reload_meta = make_fixture(reload_fixture, reload_variant=True)
        malformed_material = temporary / "missing_material_name.glb"
        make_fixture(malformed_material, missing_material_name=True)
        malformed_center = temporary / "invalid_center_accessor.glb"
        make_fixture(malformed_center, invalid_center_accessor=True)
        create_project(project, Path(args.operator_source).resolve())
        restore = subprocess.run(["dotnet", "restore", str(project / "GlbReaderValidation.csproj"),
                                  "--configfile", str(nuget_dir / "NuGet.Config")],
                                 cwd=str(project), env=environment, check=False,
                                 capture_output=True, text=True)
        if restore.returncode:
            raise RuntimeError(".NET GLB reader restore failed:\n" + restore.stdout + restore.stderr)
        command = ["dotnet", "run", "--no-restore", "--project", str(project / "GlbReaderValidation.csproj"),
                   "--configuration", "Release", "--", str(fixture), str(reload_fixture),
                   str(malformed_material), str(malformed_center), f"--iterations={args.iterations}"]
        if args.require_single_parse:
            command.append("--require-single-parse")
        completed = subprocess.run(command, cwd=str(project), check=False,
                                   env=environment, capture_output=True, text=True)
        if completed.returncode:
            raise RuntimeError(".NET GLB reader harness failed:\n" + completed.stdout + completed.stderr)
        result_line = next((line[len(MARKER):] for line in completed.stdout.splitlines()
                            if line.startswith(MARKER)), None)
        if result_line is None:
            raise RuntimeError(".NET harness did not emit its result record:\n" + completed.stdout)
        report = json.loads(result_line)
        report["fixture"] = fixture_meta
        report["reloadFixture"] = reload_meta
        report["fixturePath"] = str(fixture.resolve())
        if args.baseline:
            baseline = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
            for key in ("numericResults", "samePathReload"):
                expected = baseline.get(key)
                if expected is None or expected != report.get(key):
                    raise AssertionError(f"{key} differs from the supplied baseline")
            report["baselineCompared"] = str(Path(args.baseline).resolve())
        if args.report:
            output = Path(args.report).resolve()
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(report, indent=2), encoding="utf-8")
            report["reportPath"] = str(output)
        return report
    finally:
        temp_context.cleanup()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-dir", help="Keep the generated .glb fixture in this directory")
    parser.add_argument("--report", help="Write the numeric/performance report to this JSON file")
    parser.add_argument("--baseline", help="Compare numericResults with an earlier JSON report")
    parser.add_argument("--operator-source", default=str(OPERATOR),
                        help="Operator C# source to extract; defaults to the current production file")
    parser.add_argument("--iterations", type=int, default=40,
                        help="Measured parses per source build; minimum 30 (default: 40)")
    parser.add_argument("--require-single-parse", action="store_true",
                        help="Require exactly one reader file read and JSON parse")
    args = parser.parse_args()
    report = run(args)
    print(MARKER + json.dumps(report, separators=(",", ":")), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

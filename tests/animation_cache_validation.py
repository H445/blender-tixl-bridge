"""Exercise the production shared animation cache without TiXL dependencies.

The wrapper makes real Blender-format animation fixtures with Python's standard
library, extracts the cache loader and accounting types from the operator's C#
source, then compiles those exact declarations in a temporary .NET 8 project.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import struct
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from csharp_source import extract_class, extract_method, write_net8_project

ROOT = Path(__file__).resolve().parents[1]
OPERATOR = ROOT / "blender_tixl_bridge" / "operators" / "BlenderAnimationScene.cs"
MARKER = "ANIMATION_CACHE_VALIDATION "
MATRIX = struct.pack("<16f", 1, 0, 0, 0, 0, 1, 0, 0,
                     0, 0, 1, 0, 0, 0, 0, 1)


def write_fixture(path: Path, samples: int = 1, morph_rows: int = 2) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    metadata = path.with_suffix(".json")
    channels = Path(str(path).replace("_animation.bin", "_channels.json"))
    metadata.write_text(json.dumps({"records": [{"export_name": "mesh"}]}), encoding="utf-8")
    with path.open("wb") as stream:
        stream.write(b"TIXLANIM\x01")
        stream.write(struct.pack("<iii", 1, 0, 1))
        stream.write(struct.pack("<i", samples))
        stream.write(MATRIX * samples)
    if morph_rows == 2:
        channel_data = {
            "visibility": [{"export_name": "mesh", "start": 1, "values": [1, 0, 1]}],
            "morphs": [{"export_name": "mesh", "start": 1, "weights": [[0.0, 1.0], [0.5, 0.0]]}],
            "materials": [{"export_name": "mesh", "start": 1,
                           "emission": [[0, 0, 0, 1], [0.1, 0.2, 0.3, 1]],
                           "base_color": [[1, 1, 1, 1], [0.2, 0.4, 0.6, 1]]}],
        }
        channels.write_text(json.dumps(channel_data, separators=(",", ":")), encoding="utf-8")
    else:
        # Stream the large real channel fixture without retaining a second copy
        # of its rows in the Python wrapper's memory.
        with channels.open("w", encoding="utf-8") as stream:
            stream.write('{"morphs":[{"export_name":"mesh","start":1,"weights":[')
            row = "[0.0,1.0]"
            for index in range(morph_rows):
                if index:
                    stream.write(",")
                stream.write(row)
            stream.write("]}]}" )
    return path


def create_fixtures(root: Path) -> dict:
    simple_a = write_fixture(root / "generation-a" / "mesh_animation.bin")
    simple_b = write_fixture(root / "generation-b" / "mesh_animation.bin")
    changed = write_fixture(root / "changed" / "mesh_animation.bin", samples=1)
    entry_paths = [write_fixture(root / "entry-limit" / f"generation-{i:02d}" / "mesh_animation.bin")
                   for i in range(22)]
    budget_paths = [write_fixture(root / "byte-budget" / f"generation-{i:02d}" / "mesh_animation.bin",
                                  samples=300_000)
                    for i in range(4)]
    oversized = write_fixture(root / "oversized" / "mesh_animation.bin",
                              samples=1_000_000, morph_rows=60_000)
    plateau_paths = [write_fixture(root / "plateau" / f"generation-{i:02d}" / "mesh_animation.bin")
                     for i in range(48)]
    return {"simpleA": str(simple_a), "simpleB": str(simple_b), "changed": str(changed),
            "entryPaths": [str(path) for path in entry_paths],
            "budgetPaths": [str(path) for path in budget_paths], "oversized": str(oversized),
            "plateauPaths": [str(path) for path in plateau_paths]}


def extracted_harness(operator_path: Path) -> str:
    source = operator_path.read_text(encoding="utf-8")
    nested = [extract_class(source, name) for name in (
        "TransformTrack", "VisibilityTrack", "MorphTrack", "MaterialTrack",
        "ChannelSet", "CachedAnimation", "MorphTarget", "MorphMesh",
        "MorphBinding", "RuntimeStats")]
    transforms = extract_method(source,
        r"\bprivate\s+static\s+Dictionary<string,\s*TransformTrack>\s+LoadTransforms\s*\(",
        "LoadTransforms method")
    shared = extract_method(source,
        r"\bprivate\s+static\s+CachedAnimation\s+LoadAnimationShared\s*\(",
        "LoadAnimationShared method")
    dispose = extract_method(source,
        r"\bprotected\s+override\s+void\s+Dispose\s*\(bool\s+disposing\)",
        "BlenderAnimationScene.Dispose method")
    wrappers = r'''
    public static int EntryLimit => SharedCacheEntryLimit;
    public static long ByteBudget => SharedCacheByteBudget;
    public static int CacheCount { get { lock (SharedCacheLock) return SharedCache.Count; } }
    public static long CacheBytes { get { lock (SharedCacheLock) return SharedCacheRetainedBytes; } }
    public static long SumEntryBytes { get { lock (SharedCacheLock) return SharedCache.Values.Sum(value => value.RetainedBytes); } }
    public static CachedAnimation Load(string path) => LoadAnimationShared(path);
    public static long ObjectBytes(CachedAnimation value) => value.RetainedBytes;
    public static int TransformSampleCount(CachedAnimation value) => value.Transforms["mesh"].Samples.Length;
    public static RuntimeStats NewRegisteredStats()
    {
        var stats = new RuntimeStats(); RenderStatsCollector.RegisterProvider(stats); return stats;
    }
    public static void DisposeStats(RuntimeStats stats)
    {
        RenderStatsCollector.UnregisterProvider(stats); stats.Detach();
    }
    public static int StatValue(RuntimeStats stats, string name) => stats.GetStats().First(item => item.Item1 == name).Item2;
    public static (SceneSetup, SceneSetup.SceneDrawDispatch, MeshBuffers, BufferWithViews, BufferWithViews, BufferWithViews)
        NewNativeScene()
    {
        var owner = new SceneSetup();
        var dispatch = new SceneSetup.SceneDrawDispatch();
        var original = new MeshBuffers { VertexBuffer = new BufferWithViews(),
                                         IndicesBuffer = new BufferWithViews(), ChunkDefsBuffer = new BufferWithViews() };
        dispatch.MeshBuffers = original; owner.Dispatches.Add(dispatch);
        return (owner, dispatch, original, original.VertexBuffer!, original.IndicesBuffer, original.ChunkDefsBuffer);
    }
    public static MorphBinding NewMorphBinding(SceneSetup owner, SceneSetup.SceneDrawDispatch dispatch, RuntimeStats stats)
    {
        var mesh = new MorphMesh
        {
            Base = new[] { new PbrVertex { Position = Vector3.Zero, Normal = Vector3.UnitZ,
                                          Tangent = Vector3.UnitX, Bitangent = Vector3.UnitY } },
            Targets = new[] { new MorphTarget { Positions = new[] { Vector3.Zero } } },
            DefaultWeights = new[] { 0.0f }, Indices = Array.Empty<int>()
        };
        return new MorphBinding(dispatch, mesh, null, 0, stats, owner);
    }
    public static void ApplyMorph(MorphBinding binding) => binding.Apply(1, new float[1]);
    public static void DisposeMorph(MorphBinding binding) => binding.Dispose();
    public static void NativeDispose(SceneSetup owner)
    {
        foreach (var dispatch in owner.Dispatches)
        {
            var buffers = dispatch.MeshBuffers;
            buffers.VertexBuffer?.Dispose();
            buffers.IndicesBuffer.Dispose();
            buffers.ChunkDefsBuffer.Dispose();
        }
        owner.Dispatches.Clear();
    }
    private static Vector3 SafeNormalize(Vector3 value, Vector3 fallback) =>
        value.LengthSquared() > 1e-12f ? Vector3.Normalize(value) : fallback;
    public static void ClearCache()
    {
        lock (SharedCacheLock)
        {
            SharedCache.Clear(); SharedCacheOrder.Clear(); SharedCacheRetainedBytes = 0;
        }
    }
    public static long ExpectedBytes(string path, int transformSamples = 1,
                                     int visibilitySamples = 3, int morphRows = 2,
                                     int morphWidth = 2, int materialSamples = 2)
    {
        static long array(long count, int stride) => 64 + count * stride;
        static long entry(string name) => 256 + 2L * name.Length;
        static string stamp(string file) => File.Exists(file)
            ? $"{new FileInfo(file).Length}:{File.GetLastWriteTimeUtc(file).Ticks}" : "missing";
        var fullPath = Path.GetFullPath(path);
        var metadata = Path.ChangeExtension(fullPath, ".json");
        var channels = fullPath.Replace("_animation.bin", "_channels.json", StringComparison.Ordinal);
        var key = $"{fullPath}|{stamp(fullPath)}|{stamp(metadata)}|{stamp(channels)}";
        long bytes = 512 + 192 + 2L * key.Length;
        bytes += entry("mesh") + array(transformSamples, 64);
        bytes += entry("mesh") + array(visibilitySamples, 1);
        bytes += entry("mesh") + array(morphRows, 8) + morphRows * array(morphWidth, 4);
        bytes += entry("mesh") + array(materialSamples, 16) * 2;
        return bytes;
    }
    public static long ExpectedLargeBytes(string path, int transformSamples, int morphRows, int morphWidth)
    {
        static long array(long count, int stride) => 64 + count * stride;
        static long entry(string name) => 256 + 2L * name.Length;
        static string stamp(string file) => File.Exists(file)
            ? $"{new FileInfo(file).Length}:{File.GetLastWriteTimeUtc(file).Ticks}" : "missing";
        var fullPath = Path.GetFullPath(path);
        var metadata = Path.ChangeExtension(fullPath, ".json");
        var channels = fullPath.Replace("_animation.bin", "_channels.json", StringComparison.Ordinal);
        var key = $"{fullPath}|{stamp(fullPath)}|{stamp(metadata)}|{stamp(channels)}";
        return 512 + 192 + 2L * key.Length + entry("mesh") + array(transformSamples, 64)
             + entry("mesh") + array(morphRows, 8) + morphRows * array(morphWidth, 4);
    }
'''
    program = r'''
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Numerics;
using System.Text;
using System.Text.Json;

namespace AnimationCacheValidation;

internal interface IRenderStatsProvider
{
    IEnumerable<(string, int)> GetStats();
    void StartNewFrame();
}

internal static class RenderStatsCollector
{
    private static readonly List<IRenderStatsProvider> Providers = new();
    public static void RegisterProvider(IRenderStatsProvider provider) { if (!Providers.Contains(provider)) Providers.Add(provider); }
    public static void UnregisterProvider(IRenderStatsProvider provider) => Providers.Remove(provider);
    public static int ProviderCount => Providers.Count;
    public static Dictionary<string, int> Snapshot() => Providers.SelectMany(provider => provider.GetStats())
        .GroupBy(item => item.Item1).ToDictionary(group => group.Key, group => group.Sum(item => item.Item2));
}

internal struct PbrVertex
{
    public const int Stride = 128;
    public Vector3 Position, Normal, Tangent, Bitangent;
}
internal struct PbrMaterial { public struct PbrParameters { public const int Stride = 64; } }
internal sealed class BufferWithViews : IDisposable
{
    public int Uploads { get; private set; }
    public int DisposeCalls { get; private set; }
    public bool IsDisposed { get; private set; }
    public object? Buffer { get; private set; } = new();
    public object? Srv { get; private set; } = new();
    public object? Uav { get; private set; } = new();
    public void Upload() { if (IsDisposed) throw new ObjectDisposedException(nameof(BufferWithViews)); Uploads++; }
    public void Dispose()
    {
        if (!IsDisposed) { IsDisposed = true; DisposeCalls++; Buffer = null; Srv = null; Uav = null; }
    }
}
internal sealed class MeshBuffers
{
    public BufferWithViews? VertexBuffer;
    public BufferWithViews IndicesBuffer = new();
    public BufferWithViews ChunkDefsBuffer = new();
}
internal sealed class SceneSetup
{
    public readonly List<SceneDrawDispatch> Dispatches = new();
    public sealed class SceneDrawDispatch { public MeshBuffers MeshBuffers = new(); }
}
internal static class ResourceManager
{
    public static int UploadCount { get; private set; }
    public static void Reset() => UploadCount = 0;
    public static void SetupBufferWithViews<T>(T[] values, ref BufferWithViews? buffer)
    {
        if (buffer == null) buffer = new BufferWithViews();
        buffer.Upload(); UploadCount++;
    }
}

internal static class CacheHarness
{
__FIELDS__
__NESTED__
__TRANSFORMS__
__SHARED__
__WRAPPERS__
}

internal class DisposableBase { protected virtual void Dispose(bool disposing) { } }
internal sealed class StatsOwner : DisposableBase
{
    private readonly CacheHarness.RuntimeStats _stats;
    public StatsOwner() { _stats = new CacheHarness.RuntimeStats(); RenderStatsCollector.RegisterProvider(_stats); }
    private void ReleaseMorphs() { }
    public void Close() => Dispose(true);
__DISPOSE__
}

internal static class Program
{
    private static void Require(bool condition, string message)
    {
        if (!condition) throw new InvalidOperationException(message);
    }
    private static string Fixture(JsonElement root, string name) => root.GetProperty(name).GetString()!;
    private static string[] Fixtures(JsonElement root, string name) => root.GetProperty(name).EnumerateArray().Select(item => item.GetString()!).ToArray();
    private static long Gauge(Dictionary<string, int> stats, string name) => stats.TryGetValue(name, out var value) ? value : -1;
    private static string stamp(string file) => File.Exists(file) ? $"{new FileInfo(file).Length}:{File.GetLastWriteTimeUtc(file).Ticks}" : "missing";
    private static string cacheKey(string path)
    {
        var full = Path.GetFullPath(path);
        var metadata = Path.ChangeExtension(full, ".json");
        var channels = full.Replace("_animation.bin", "_channels.json", StringComparison.Ordinal);
        return $"{full}|{stamp(full)}|{stamp(metadata)}|{stamp(channels)}";
    }
    private static void ExactAccounting(string path, CacheHarness.CachedAnimation value, int samples = 1)
    {
        Require(CacheHarness.ObjectBytes(value) == CacheHarness.ExpectedBytes(path, transformSamples: samples),
                "CachedAnimation.RetainedBytes differs from exact fixture payload accounting");
        Require(CacheHarness.CacheBytes == CacheHarness.SumEntryBytes,
                "SharedCacheRetainedBytes differs from the retained entry sum");
    }
    private static int Main(string[] args)
    {
        try
        {
            var fixtures = JsonDocument.Parse(File.ReadAllText(args[0])).RootElement;
            CacheHarness.ClearCache();
            var a = Fixture(fixtures, "simpleA");
            var first = CacheHarness.Load(a);
            var repeated = CacheHarness.Load(a);
            Require(ReferenceEquals(first, repeated), "A repeated path+stamp did not share the cached object");
            ExactAccounting(a, first);

            var otherGeneration = CacheHarness.Load(Fixture(fixtures, "simpleB"));
            Require(!ReferenceEquals(first, otherGeneration), "Different generation paths shared one cached object");
            Require(CacheHarness.CacheCount == 2, "Different generations were not both retained");

            var changedPath = Fixture(fixtures, "changed");
            var priorStamp = cacheKey(changedPath);
            var prior = CacheHarness.Load(changedPath);
            var changedBytes = File.ReadAllBytes(changedPath);
            BitConverter.GetBytes(2).CopyTo(changedBytes, 21);
            File.WriteAllBytes(changedPath, changedBytes.Concat(changedBytes.Skip(25).Take(64)).ToArray());
            // Change the real sample count and append a valid second identity matrix.
            var changed = CacheHarness.Load(changedPath);
            Require(cacheKey(changedPath) != priorStamp, "Fixture did not change its file stamp");
            Require(!ReferenceEquals(prior, changed), "Changed file stamp reused stale animation data");
            Require(CacheHarness.TransformSampleCount(changed) == 2, "Changed stamp reload did not parse the updated transforms");
            Require(CacheHarness.ObjectBytes(changed) == CacheHarness.ExpectedBytes(changedPath, transformSamples: 2),
                    "Changed-stamp entry accounting omitted its updated transform samples");

            CacheHarness.ClearCache();
            var entryPaths = Fixtures(fixtures, "entryPaths");
            var entryBytes = new Dictionary<string, long>(StringComparer.OrdinalIgnoreCase);
            CacheHarness.CachedAnimation? oldest = null;
            for (var i = 0; i < entryPaths.Length; i++)
            {
                var value = CacheHarness.Load(entryPaths[i]);
                if (i == 0) oldest = value;
                entryBytes[cacheKey(entryPaths[i])] = CacheHarness.ObjectBytes(value);
            }
            Require(CacheHarness.CacheCount == CacheHarness.EntryLimit, "Entry-count bound did not stop at 16");
            var keptEntryKeys = entryPaths.TakeLast(CacheHarness.EntryLimit).Select(cacheKey).ToHashSet(StringComparer.OrdinalIgnoreCase);
            Require(CacheHarness.CacheBytes == entryBytes.Where(pair => keptEntryKeys.Contains(pair.Key)).Sum(pair => pair.Value),
                    "Entry eviction did not subtract the evicted entry's exact accounted bytes");
            var evictedReload = CacheHarness.Load(entryPaths[0]);
            Require(!ReferenceEquals(oldest, evictedReload), "Evicted entry was incorrectly reused");

            CacheHarness.ClearCache();
            var largePath = Fixture(fixtures, "oversized");
            var oversized = CacheHarness.Load(largePath);
            var expectedOversized = CacheHarness.ExpectedLargeBytes(largePath, 1_000_000, 60_000, 2);
            Require(CacheHarness.ObjectBytes(oversized) == expectedOversized, "Oversized entry accounting differs from fixture size");
            Require(expectedOversized > CacheHarness.ByteBudget, "Oversized fixture did not cross the 64 MiB cache budget");
            Require(CacheHarness.CacheCount == 0 && CacheHarness.CacheBytes == 0,
                    "Oversized entry was retained in the process-wide cache");
            Require(!ReferenceEquals(oversized, CacheHarness.Load(largePath)), "Oversized bypass unexpectedly shared a retained entry");

            CacheHarness.ClearCache();
            var budgetPaths = Fixtures(fixtures, "budgetPaths");
            var budgetBytes = new Dictionary<string, long>(StringComparer.OrdinalIgnoreCase);
            for (var i = 0; i < budgetPaths.Length; i++)
            {
                var value = CacheHarness.Load(budgetPaths[i]);
                budgetBytes[cacheKey(budgetPaths[i])] = CacheHarness.ObjectBytes(value);
            }
            var retainedBudgetKeys = budgetPaths.TakeLast(3).Select(cacheKey).ToHashSet(StringComparer.OrdinalIgnoreCase);
            Require(CacheHarness.CacheCount == 3, "Byte-budget eviction did not remove the oldest 20 MiB entry");
            Require(CacheHarness.CacheBytes <= CacheHarness.ByteBudget, "Retained cache exceeded its byte budget");
            Require(CacheHarness.CacheBytes == budgetBytes.Where(pair => retainedBudgetKeys.Contains(pair.Key)).Sum(pair => pair.Value),
                    "Byte-budget eviction retained-byte gauge differs from its surviving entries");
            var budgetReload = CacheHarness.Load(budgetPaths[0]);
            Require(CacheHarness.CacheCount <= CacheHarness.EntryLimit && CacheHarness.CacheBytes <= CacheHarness.ByteBudget,
                    "Reload after byte eviction exceeded a cache bound");

            CacheHarness.ClearCache();
            var plateauPaths = Fixtures(fixtures, "plateauPaths");
            var plateauFirst = new List<long>();
            foreach (var path in plateauPaths.Take(32))
                plateauFirst.Add(CacheHarness.ObjectBytes(CacheHarness.Load(path)));
            var after32 = CacheHarness.CacheBytes;
            foreach (var path in plateauPaths.Skip(32))
                CacheHarness.Load(path);
            var plateauLast = plateauPaths.TakeLast(CacheHarness.EntryLimit).Select(path => CacheHarness.ExpectedBytes(path)).Sum();
            Require(CacheHarness.CacheCount == CacheHarness.EntryLimit, "Repeated generations did not plateau at entry limit");
            Require(CacheHarness.CacheBytes == plateauLast && CacheHarness.CacheBytes <= CacheHarness.ByteBudget,
                    "Repeated generations did not plateau at exact bounded retained bytes");
            Require(after32 == plateauLast, "Cache accounting grew after the entry-count plateau");

            // RuntimeStats is extracted verbatim. The test collector sums all
            // providers like the application collector, so a process gauge must
            // be emitted by only one instance and transfer when that owner closes.
            var gaugeExpectedBytes = CacheHarness.CacheBytes;
            var ownerA = new StatsOwner();
            var ownerB = new StatsOwner();
            var snapshot = RenderStatsCollector.Snapshot();
            Require(Gauge(snapshot, "Blender shared animation cache entries") == CacheHarness.CacheCount,
                    "Shared entry gauge was missing or double-counted across providers");
            Require(Gauge(snapshot, "Blender shared animation cache accounted bytes") == gaugeExpectedBytes,
                    "Shared accounted-byte gauge was missing or double-counted across providers");
            var unrelatedEditorData = new byte[8 * 1024 * 1024];
            unrelatedEditorData[0] = 1;
            GC.KeepAlive(unrelatedEditorData);
            var afterAllocation = RenderStatsCollector.Snapshot();
            Require(Gauge(afterAllocation, "Blender shared animation cache accounted bytes") == gaugeExpectedBytes,
                    "Cache gauge included unrelated whole-editor managed allocations");
            ownerA.Close();
            var transferred = RenderStatsCollector.Snapshot();
            Require(Gauge(transferred, "Blender shared animation cache entries") == CacheHarness.CacheCount
                    && Gauge(transferred, "Blender shared animation cache accounted bytes") == gaugeExpectedBytes,
                    "Shared gauges did not transfer to the next provider exactly once on disposal");
            ownerB.Close();
            Require(!RenderStatsCollector.Snapshot().ContainsKey("Blender shared animation cache accounted bytes"),
                    "Disposed providers remained registered or reported the shared gauge");

            // Native scene disposal runs first and sees only the installed morph
            // wrapper. The bridge must then free the hidden original vertex too.
            ResourceManager.Reset();
            var nativeFirst = CacheHarness.NewNativeScene();
            var nativeStats = CacheHarness.NewRegisteredStats();
            var nativeBinding = CacheHarness.NewMorphBinding(nativeFirst.Item1, nativeFirst.Item2, nativeStats);
            CacheHarness.ApplyMorph(nativeBinding);
            var nativeWrapper = nativeFirst.Item2.MeshBuffers;
            Require(!ReferenceEquals(nativeWrapper, nativeFirst.Item3), "Morph upload did not install its owned wrapper");
            Require(ReferenceEquals(nativeWrapper.IndicesBuffer, nativeFirst.Item5)
                    && ReferenceEquals(nativeWrapper.ChunkDefsBuffer, nativeFirst.Item6),
                    "Morph wrapper did not preserve native index/chunk buffer ownership");
            CacheHarness.ApplyMorph(nativeBinding);
            Require(ResourceManager.UploadCount == 1, "Held frame zero caused a redundant morph upload");
            Require(CacheHarness.StatValue(nativeStats, "Blender cumulative morph uploads") == 1,
                    "Held frame zero changed cumulative upload accounting");
            CacheHarness.NativeDispose(nativeFirst.Item1);
            Require(nativeWrapper.VertexBuffer!.IsDisposed && nativeWrapper.VertexBuffer.Buffer == null
                    && nativeWrapper.VertexBuffer.Srv == null && nativeWrapper.VertexBuffer.Uav == null
                    && !nativeFirst.Item4.IsDisposed,
                    "Native-first disposal did not free the installed wrapper and preserve hidden original vertex");
            Require(nativeFirst.Item5.Buffer == null && nativeFirst.Item5.Srv == null && nativeFirst.Item5.Uav == null
                    && nativeFirst.Item6.Buffer == null && nativeFirst.Item6.Srv == null && nativeFirst.Item6.Uav == null,
                    "Native-first fixture did not model disposed index/chunk views");
            CacheHarness.DisposeMorph(nativeBinding);
            Require(nativeFirst.Item4.DisposeCalls == 1 && nativeWrapper.VertexBuffer.DisposeCalls == 1,
                    "Native-first bridge cleanup leaked or double-freed a vertex buffer");
            Require(nativeFirst.Item5.DisposeCalls == 1 && nativeFirst.Item6.DisposeCalls == 1,
                    "Native-first cleanup changed shared index/chunk disposal ownership");
            CacheHarness.DisposeStats(nativeStats);

            // Bridge-first cleanup restores native buffers; native scene disposal
            // remains their only owner and later frees them once.
            var bridgeFirst = CacheHarness.NewNativeScene();
            var bridgeStats = CacheHarness.NewRegisteredStats();
            var bridgeBinding = CacheHarness.NewMorphBinding(bridgeFirst.Item1, bridgeFirst.Item2, bridgeStats);
            CacheHarness.ApplyMorph(bridgeBinding);
            var bridgeWrapper = bridgeFirst.Item2.MeshBuffers;
            CacheHarness.DisposeMorph(bridgeBinding);
            Require(ReferenceEquals(bridgeFirst.Item2.MeshBuffers, bridgeFirst.Item3),
                    "Bridge-first disposal did not restore the original native buffers");
            Require(bridgeWrapper.VertexBuffer!.DisposeCalls == 1 && !bridgeFirst.Item4.IsDisposed,
                    "Bridge-first cleanup leaked/disposed the wrong vertex buffer");
            Require(bridgeFirst.Item5.DisposeCalls == 0 && bridgeFirst.Item6.DisposeCalls == 0,
                    "Morph binding disposed buffers shared with the native scene");
            CacheHarness.NativeDispose(bridgeFirst.Item1);
            Require(bridgeFirst.Item4.DisposeCalls == 1 && bridgeFirst.Item5.DisposeCalls == 1
                    && bridgeFirst.Item6.DisposeCalls == 1,
                    "Native disposal after bridge-first cleanup did not release each original resource once");
            CacheHarness.DisposeStats(bridgeStats);

            // A cleared dispatch list alone can represent filtering. If the
            // native resources still expose any Buffer/SRV/UAV, bridge cleanup
            // must leave the original vertex and shared index/chunk alive.
            var filteredOwner = CacheHarness.NewNativeScene();
            var filteredStats = CacheHarness.NewRegisteredStats();
            var filteredBinding = CacheHarness.NewMorphBinding(filteredOwner.Item1, filteredOwner.Item2, filteredStats);
            CacheHarness.ApplyMorph(filteredBinding);
            var filteredWrapper = filteredOwner.Item2.MeshBuffers;
            filteredOwner.Item1.Dispatches.Clear();
            CacheHarness.DisposeMorph(filteredBinding);
            Require(filteredWrapper.VertexBuffer!.IsDisposed && !filteredOwner.Item4.IsDisposed,
                    "Dispatch-list filtering was mistaken for native resource disposal");
            Require(filteredOwner.Item5.Buffer != null && filteredOwner.Item5.Srv != null && filteredOwner.Item5.Uav != null
                    && filteredOwner.Item6.Buffer != null && filteredOwner.Item6.Srv != null && filteredOwner.Item6.Uav != null,
                    "Bridge cleanup disposed shared index/chunk resources after list-only clearing");
            filteredOwner.Item4.Dispose(); filteredOwner.Item5.Dispose(); filteredOwner.Item6.Dispose();
            CacheHarness.DisposeStats(filteredStats);

            // Reinitialization repeats the ownership handoff on the same native
            // dispatch. Each new binding's initial zero weights must upload once.
            ResourceManager.Reset();
            var repeatedNative = CacheHarness.NewNativeScene();
            var repeatedStats = CacheHarness.NewRegisteredStats();
            for (var cycle = 0; cycle < 3; cycle++)
            {
                var binding = CacheHarness.NewMorphBinding(repeatedNative.Item1, repeatedNative.Item2, repeatedStats);
                CacheHarness.ApplyMorph(binding);
                var wrapper = repeatedNative.Item2.MeshBuffers;
                CacheHarness.ApplyMorph(binding);
                Require(ResourceManager.UploadCount == cycle + 1,
                        "A paused frame with unchanged zero weights repeated a morph upload");
                CacheHarness.DisposeMorph(binding);
                Require(ReferenceEquals(repeatedNative.Item2.MeshBuffers, repeatedNative.Item3)
                        && wrapper.VertexBuffer!.DisposeCalls == 1 && !repeatedNative.Item4.IsDisposed,
                        "Repeated reinitialization leaked a replacement or lost native vertex ownership");
                Require(repeatedNative.Item5.DisposeCalls == 0 && repeatedNative.Item6.DisposeCalls == 0,
                        "Repeated reinitialization freed shared index/chunk buffers early");
            }
            Require(CacheHarness.StatValue(repeatedStats, "Blender cumulative morph uploads") == 3,
                    "Repeated binding cumulative upload counter is inaccurate");
            CacheHarness.NativeDispose(repeatedNative.Item1);
            Require(repeatedNative.Item4.DisposeCalls == 1 && repeatedNative.Item5.DisposeCalls == 1
                    && repeatedNative.Item6.DisposeCalls == 1,
                    "Repeated reinitialization native cleanup did not release original resources once");
            CacheHarness.DisposeStats(repeatedStats);

            var report = new {
                status = "passed", cacheEntries = CacheHarness.CacheCount,
                retainedBytes = CacheHarness.CacheBytes, sharedByteBudget = CacheHarness.ByteBudget,
                entryLimit = CacheHarness.EntryLimit, repeatPathSharesObject = true,
                differentGenerationsSeparate = true, changedStampReloads = true,
                entryLimitEvictsOldest = true, oversizedBypassesProcessCache = true,
                byteBudgetEvictsAndReconciles = true, repeatedGenerationsPlateau = true,
                exactRetainedAccounting = true, statsGaugeTransfersExactlyOnce = true,
                cacheGaugeExcludesWholeEditorHeap = true,
                morphNativeFirstDisposal = true, morphBridgeFirstDisposal = true,
                morphClearedListWithLiveResourcesIsSafe = true,
                morphRepeatedReinitialization = true, morphHeldFrameZeroUploads = true,
                morphSharedIndexChunkOwnership = true,
                memoryScope = "cache-accounted managed payload estimate; excludes unrelated editor/process heap and GPU/native resources",
                oversizedBytes = expectedOversized, finalPlateauBytes = plateauLast
            };
            Console.WriteLine("ANIMATION_CACHE_VALIDATION " + JsonSerializer.Serialize(report));
            return 0;
        }
        catch (Exception error)
        {
            Console.Error.WriteLine(error);
            return 1;
        }
    }
}
'''
    # Use the exact production declarations rather than a test-side cache copy.
    lines = []
    for name in ("SharedCacheEntryLimit", "SharedCacheByteBudget", "SharedCacheRetainedBytes",
                 "SharedCacheLock", "SharedCache", "SharedCacheOrder"):
        match = re.search(rf"^\s*private\s+(?:(?:static|const|readonly)\s+)*[^;\n]*\b{name}\b[^;]*;",
                          source, flags=re.MULTILINE)
        if not match:
            raise RuntimeError(f"Could not find production cache field {name}")
        lines.append(match.group(0).strip())
    fields = "\n".join(lines)
    return (program.replace("__FIELDS__", fields)
            .replace("__NESTED__", "\n\n".join(nested))
            .replace("__TRANSFORMS__", transforms)
            .replace("__SHARED__", shared)
            .replace("__WRAPPERS__", wrappers)
            .replace("__DISPOSE__", dispose))


def run(args) -> dict:
    started = time.perf_counter()
    temporary = tempfile.TemporaryDirectory(prefix="animation-cache-validation-")
    try:
        root = Path(temporary.name)
        fixture_root = root / "fixtures"
        fixture_root.mkdir()
        fixtures = create_fixtures(fixture_root)
        fixture_manifest = root / "fixtures.json"
        fixture_manifest.write_text(json.dumps(fixtures), encoding="utf-8")
        project = root / "project"
        program = extracted_harness(Path(args.operator_source).resolve())
        write_net8_project(project, "AnimationCacheValidation", program)
        dotnet_home = root / "dotnet-home"
        app_data = root / "app-data"
        nuget_dir = app_data / "NuGet"
        nuget_dir.mkdir(parents=True)
        (nuget_dir / "NuGet.Config").write_text(
            "<configuration><packageSources><clear /></packageSources></configuration>", encoding="utf-8")
        environment = dict(os.environ)
        environment.update({"DOTNET_CLI_HOME": str(dotnet_home), "NUGET_CLI_HOME": str(root / "nuget-home"),
                            "APPDATA": str(app_data), "LOCALAPPDATA": str(root / "local-app-data")})
        project_file = project / "AnimationCacheValidation.csproj"
        restore = subprocess.run(["dotnet", "restore", str(project_file), "--configfile", str(nuget_dir / "NuGet.Config")],
                                 cwd=project, env=environment, check=False, capture_output=True, text=True)
        if restore.returncode:
            raise RuntimeError(".NET source-extraction restore failed:\n" + restore.stdout + restore.stderr)
        completed = subprocess.run(["dotnet", "run", "--no-restore", "--project", str(project_file),
                                    "--configuration", "Release", "--", str(fixture_manifest)],
                                   cwd=project, env=environment, check=False, capture_output=True, text=True)
        if completed.returncode:
            raise RuntimeError(".NET animation cache harness failed:\n" + completed.stdout + completed.stderr)
        result_line = next((line[len(MARKER):] for line in completed.stdout.splitlines()
                            if line.startswith(MARKER)), None)
        if result_line is None:
            raise RuntimeError(".NET cache harness did not emit its result record:\n" + completed.stdout)
        report = json.loads(result_line)
        report["runtime"] = {"targetFramework": "net8.0", "harness": "production source extraction"}
        report["fixtureCounts"] = {"entryLimit": 22, "byteBudgetEntries": 4,
                                   "oversizedTransformSamples": 1_000_000,
                                   "oversizedMorphFrames": 60_000, "plateauGenerations": 48}
        report["durationSeconds"] = time.perf_counter() - started
        return report
    finally:
        temporary.cleanup()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--operator-source", default=str(OPERATOR),
                        help="Operator C# source to extract; defaults to current production source")
    args = parser.parse_args()
    report = run(args)
    print(MARKER + json.dumps(report, separators=(",", ":")), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

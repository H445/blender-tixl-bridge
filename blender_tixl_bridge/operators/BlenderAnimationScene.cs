#nullable enable
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Numerics;
using System.Text;
using System.Text.Json;
using T3.Core.DataTypes;
using T3.Core.Logging;
using T3.Core.Operator;
using T3.Core.Operator.Attributes;
using T3.Core.Operator.Interfaces;
using T3.Core.Operator.Slots;
using T3.Core.Rendering;
using T3.Core.Rendering.Material;
using T3.Core.Resource;

namespace PrismalLabs.BlenderExport;

/// <summary>Applies a Blender export cache to a glTF scene. Supports sampled world transforms, visibility, animated material channels, morph targets, and separate opaque/transparent draw outputs.</summary>
[Guid("8cc13ea4-9e0d-4b61-9b1f-b72f6c470a7a")]
public sealed class BlenderAnimationScene : Instance<BlenderAnimationScene>, IStatusProvider
{
    [Output(Guid = "cbb6f6a0-27c9-4555-8e5e-fd23e8d3f991", DirtyFlagTrigger = DirtyFlagTrigger.Animated)]
    public readonly Slot<SceneSetup> Result = new();
    [Output(Guid = "47cf6d63-582b-46e6-b94a-b69b1c77f347", DirtyFlagTrigger = DirtyFlagTrigger.Animated)]
    public readonly Slot<SceneSetup> OpaqueResult = new();
    [Output(Guid = "20bcdd8a-2615-4e45-b9db-15548809a25e", DirtyFlagTrigger = DirtyFlagTrigger.Animated)]
    public readonly Slot<SceneSetup> TransparentResult = new();
    [Output(Guid = "bb11e48d-7a08-4ca9-a0df-b4a4bdeee502", DirtyFlagTrigger = DirtyFlagTrigger.Animated)]
    public readonly Slot<Matrix4x4[]> EvaluatedWorldTransforms = new();
    [Output(Guid = "5fd00595-fdaa-4f74-a8f2-ecf45f521e3f", DirtyFlagTrigger = DirtyFlagTrigger.Animated)]
    public readonly Slot<int[]> Visibility = new();
    [Output(Guid = "2cfcfa02-e123-4f58-a1ef-0b2e22ac2df3", DirtyFlagTrigger = DirtyFlagTrigger.Animated)]
    public readonly Slot<Vector4[]> ShaderEmission = new();
    [Output(Guid = "2de5fbd8-3aa6-47b3-82ac-17bc4fef3129", DirtyFlagTrigger = DirtyFlagTrigger.Animated)]
    public readonly Slot<Vector4[]> MaterialValues = new();
    [Output(Guid = "f9bebd39-bc9d-4303-a5ab-0c1baaca4495", DirtyFlagTrigger = DirtyFlagTrigger.Animated)]
    public readonly Slot<float[]> MeshShapeKeyValues = new();

    [Input(Guid = "f5cd6fc8-54bd-4cf0-885f-2b244d9c1902")] public readonly InputSlot<SceneSetup> Scene = new();
    [Input(Guid = "ca02f7a3-a03a-4db0-a05d-3a66b0c9ab11")] public readonly InputSlot<string> DataPath = new();
    [Input(Guid = "ee2eaef9-6e5a-48b3-9df0-91b2f9ab7dc7")] public readonly InputSlot<float> TimeSeconds = new();
    [Input(Guid = "3a4c36f9-e8c1-4ab7-b370-0f548b054933")] public readonly InputSlot<string> GlbPath = new();

    public BlenderAnimationScene()
    {
        RenderStatsCollector.RegisterProvider(_stats);
        Result.UpdateAction = Update;
        OpaqueResult.UpdateAction = Update;
        TransparentResult.UpdateAction = Update;
        EvaluatedWorldTransforms.UpdateAction = Update;
        Visibility.UpdateAction = Update;
        ShaderEmission.UpdateAction = Update;
        MaterialValues.UpdateAction = Update;
        MeshShapeKeyValues.UpdateAction = Update;
    }

    private readonly RuntimeStats _stats = new();

    private void Update(EvaluationContext context)
    {
        var requestedPath = DataPath.GetValue(context) ?? string.Empty;
        var requestedGlbPath = GlbPath.GetValue(context) ?? string.Empty;
        // Scene.GetValue can trigger the native glTF loader. If this operator
        // has not been initialized (or its source changed), leave the old
        // scene on screen until a paused frame can safely rebuild bindings.
        if (Math.Abs(context.Playback.PlaybackSpeed) > 0.001
            && (_scene == null || requestedPath != _requestedPath || requestedGlbPath != _requestedGlbPath))
        {
            _status = "Pause playback to load changed Blender scene data.";
            Result.Value = _scene!;
            OpaqueResult.Value = _opaqueScene;
            TransparentResult.Value = _transparentScene;
            return;
        }
        var scene = Scene.GetValue(context);
        if (scene == null)
        {
            Result.Value = scene!;
            _opaqueScene.Dispatches.Clear();
            _transparentScene.Dispatches.Clear();
            OpaqueResult.Value = _opaqueScene;
            TransparentResult.Value = _transparentScene;
            return;
        }

        if (!ReferenceEquals(scene, _scene) || requestedPath != _requestedPath || requestedGlbPath != _requestedGlbPath
            || scene.Dispatches.Count != _bindings.Length)
        {
            Initialize(scene, requestedPath, requestedGlbPath);
        }

        var seconds = TimeSeconds.HasInputConnections
                          ? TimeSeconds.GetValue(context)
                          : (float)(context.LocalTime * 240 / Math.Max(1, context.Playback.Bpm));
        // World selection uses half-open source-time ranges. Rounding forward
        // can sample a hidden end frame before the camera selects the next
        // world, blanking the outgoing mesh for half a frame at each cut.
        var frame = Math.Clamp((int)MathF.Floor(seconds * 60 + 0.0001f) + 1, 1, _maxFrame);
        if (frame != _lastFrame)
        {
            Evaluate(frame);
            _lastFrame = frame;
        }
        PartitionDraws(context);
        Result.Value = scene;
        OpaqueResult.Value = _opaqueScene;
        TransparentResult.Value = _transparentScene;
        EvaluatedWorldTransforms.Value = _transforms;
        Visibility.Value = _visibility;
        ShaderEmission.Value = _emission;
        MaterialValues.Value = _colors;
        MeshShapeKeyValues.Value = _weights;
    }

    private string Resolve(string path)
    {
        if (File.Exists(path))
            return Path.GetFullPath(path);
        return TryGetFilePath(path, out var absolutePath) ? absolutePath : path;
    }

    private void Initialize(SceneSetup scene, string requestedPath, string requestedGlbPath)
    {
        var started = Stopwatch.GetTimestamp();
        try { InitializeCore(scene, requestedPath, requestedGlbPath); }
        finally { _stats.SceneLoad(Stopwatch.GetTimestamp() - started); }
    }

    private void InitializeCore(SceneSetup scene, string requestedPath, string requestedGlbPath)
    {
        ReleaseMorphs();
        _scene = scene;
        _requestedPath = requestedPath;
        _requestedGlbPath = requestedGlbPath;
        _lastFrame = -1;
        _status = string.Empty;
        var count = scene.Dispatches.Count;
        _bindings = new Binding[count];
        _transforms = new Matrix4x4[count];
        _visibility = new int[count];
        _emission = new Vector4[count];
        _colors = new Vector4[count];
        var nodes = new List<SceneSetup.SceneNode>(count);
        foreach (var root in scene.RootNodes)
            CollectMeshNodes(root, nodes);

        var path = Resolve(requestedPath);
        Dictionary<string, TransformTrack> transforms;
        var channels = new ChannelSet();
        var morphMeshes = new Dictionary<string, List<MorphMesh>>(StringComparer.Ordinal);
        var materialDefaults = new Dictionary<string, MaterialDefaults>(StringComparer.Ordinal);
        var primitiveCenters = new Dictionary<string, List<Vector3>>(StringComparer.Ordinal);
        try
        {
            var cached = LoadAnimationShared(path);
            transforms = cached.Transforms;
            channels = cached.Channels;
            _maxFrame = cached.MaxFrame;
            if (!string.IsNullOrWhiteSpace(requestedGlbPath))
            {
                morphMeshes = GlbReader.LoadMorphs(Resolve(requestedGlbPath));
                materialDefaults = GlbReader.LoadMaterialDefaults(Resolve(requestedGlbPath));
                primitiveCenters = GlbReader.LoadPrimitiveCenters(Resolve(requestedGlbPath));
            }
        }
        catch (Exception e)
        {
            transforms = new Dictionary<string, TransformTrack>(StringComparer.Ordinal);
            _status = "Blender export cache: " + e.Message;
        }

        var primitives = new Dictionary<string, int>(StringComparer.Ordinal);
        var uniqueMaterials = new HashSet<PbrMaterial>();
        var materials = new List<MaterialBinding>();
        var weightCount = 0;
        var missing = 0;
        for (var i = 0; i < count; i++)
        {
            var dispatch = scene.Dispatches[i];
            var node = i < nodes.Count ? nodes[i] : null;
            var name = node?.Name ?? string.Empty;
            primitives.TryGetValue(name, out var primitive);
            primitives[name] = primitive + 1;
            transforms.TryGetValue(name, out var track);
            channels.Visibility.TryGetValue(name, out var visible);
            channels.Morphs.TryGetValue(name, out var morphTrack);
            var binding = new Binding(dispatch, node, track, visible);
            binding.Order = i;
            if (primitiveCenters.TryGetValue(name, out var centers) && primitive < centers.Count)
                binding.LocalCenter = centers[primitive];
            if (track == null)
                missing++;
            if (morphMeshes.TryGetValue(name, out var meshes) && primitive < meshes.Count && meshes[primitive].Targets.Length > 0)
            {
                binding.Morph = new MorphBinding(dispatch, meshes[primitive], morphTrack, weightCount, _stats);
                weightCount += meshes[primitive].Targets.Length;
            }
            _bindings[i] = binding;
            if (dispatch.Material != null && uniqueMaterials.Add(dispatch.Material))
            {
                channels.Materials.TryGetValue(dispatch.Material.Name, out var materialTrack);
                materialDefaults.TryGetValue(dispatch.Material.Name, out var defaults);
                if (materialTrack != null)
                    materials.Add(new MaterialBinding(dispatch.Material, materialTrack, defaults, _stats));
            }
        }
        _materials = materials.ToArray();
        _weights = new float[weightCount];
        if (missing > 0 && _status.Length == 0)
            _status = $"{missing} of {count} primitives have no exported transform binding.";
    }

    private void PartitionDraws(EvaluationContext context)
    {
        _opaqueScene.Dispatches.Clear();
        _transparentScene.Dispatches.Clear();
        _transparentBindings.Clear();
        var objectToCamera = context.ObjectToWorld * context.WorldToCamera;
        for (var i = 0; i < _bindings.Length; i++)
        {
            var binding = _bindings[i];
            if ((binding.Dispatch.Material?.Parameters.BaseColor.W ?? 1) >= 0.999f)
            {
                _opaqueScene.Dispatches.Add(binding.Dispatch);
            }
            else
            {
                var center = Vector3.Transform(binding.LocalCenter, binding.Dispatch.CombinedTransform * objectToCamera);
                binding.Depth = MathF.Abs(center.Z);
                _transparentBindings.Add(binding);
            }
        }
        _transparentBindings.Sort(DepthComparer.Instance);
        for (var i = 0; i < _transparentBindings.Count; i++)
            _transparentScene.Dispatches.Add(_transparentBindings[i].Dispatch);
    }

    private void Evaluate(int frame)
    {
        for (var i = 0; i < _materials.Length; i++)
            _materials[i].Apply(frame);

        for (var i = 0; i < _bindings.Length; i++)
        {
            var binding = _bindings[i];
            var matrix = binding.Track?.Sample(frame) ?? binding.BaseMatrix;
            var visible = binding.Visible?.Sample(frame) ?? true;
            var scale = new Vector3(new Vector3(matrix.M11, matrix.M12, matrix.M13).Length(),
                                    new Vector3(matrix.M21, matrix.M22, matrix.M23).Length(),
                                    new Vector3(matrix.M31, matrix.M32, matrix.M33).Length());
            // Blender uses zero scale to remove a bubble immediately at its pop frame.
            visible &= scale.X > 1e-8f && scale.Y > 1e-8f && scale.Z > 1e-8f;
            binding.Dispatch.CombinedTransform = matrix;
            binding.Dispatch.Scale = scale;
            binding.Dispatch.VertexCount = visible ? binding.BaseVertexCount : 0;
            if (binding.Node != null)
                binding.Node.CombinedTransform = matrix;
            binding.Morph?.Apply(frame, _weights);
            _transforms[i] = matrix;
            _visibility[i] = visible ? 1 : 0;
            _emission[i] = binding.Dispatch.Material?.Parameters.EmissiveColor ?? Vector4.Zero;
            _colors[i] = binding.Dispatch.Material?.Parameters.BaseColor ?? Vector4.One;
        }
    }

    private static void CollectMeshNodes(SceneSetup.SceneNode node, List<SceneSetup.SceneNode> result)
    {
        if (node.MeshBuffers != null)
            result.Add(node);
        foreach (var child in node.ChildNodes)
            CollectMeshNodes(child, result);
    }

    private static Dictionary<string, TransformTrack> LoadTransforms(string path)
    {
        using var metadata = JsonDocument.Parse(File.ReadAllText(Path.ChangeExtension(path, ".json")));
        var names = new List<string>();
        foreach (var record in metadata.RootElement.GetProperty("records").EnumerateArray())
            names.Add(record.GetProperty("export_name").GetString() ?? string.Empty);
        using var stream = File.OpenRead(path);
        using var reader = new BinaryReader(stream);
        if (Encoding.ASCII.GetString(reader.ReadBytes(9)) != "TIXLANIM\x01")
            throw new InvalidDataException("Unsupported matrix cache header.");
        var count = reader.ReadInt32();
        if (count != names.Count)
            throw new InvalidDataException("Matrix cache and metadata record counts differ.");
        var result = new Dictionary<string, TransformTrack>(count, StringComparer.Ordinal);
        for (var r = 0; r < count; r++)
        {
            var index = reader.ReadInt32();
            var start = reader.ReadInt32();
            var sampleCount = reader.ReadInt32();
            if (index < 0 || index >= count || sampleCount < 1 || sampleCount > 1000000)
                throw new InvalidDataException("Invalid transform record.");
            var matrices = new Matrix4x4[sampleCount];
            for (var k = 0; k < matrices.Length; k++)
            {
                matrices[k] = new Matrix4x4(reader.ReadSingle(), reader.ReadSingle(), reader.ReadSingle(), reader.ReadSingle(),
                                           reader.ReadSingle(), reader.ReadSingle(), reader.ReadSingle(), reader.ReadSingle(),
                                           reader.ReadSingle(), reader.ReadSingle(), reader.ReadSingle(), reader.ReadSingle(),
                                           reader.ReadSingle(), reader.ReadSingle(), reader.ReadSingle(), reader.ReadSingle());
                if (matrices[k].M44 != 1 || !float.IsFinite(matrices[k].M11))
                    throw new InvalidDataException("The animation cache is incomplete or contains an invalid transform.");
            }
            result.Add(names[index], new TransformTrack(start, matrices));
        }
        return result;
    }

    private sealed class CachedAnimation
    {
        public readonly Dictionary<string, TransformTrack> Transforms;
        public readonly ChannelSet Channels;
        public readonly int MaxFrame;
        public CachedAnimation(Dictionary<string, TransformTrack> transforms, ChannelSet channels)
        {
            Transforms = transforms;
            Channels = channels;
            // Geometry can stop moving before material, visibility, or morph
            // animation ends, so include every channel in the duration.
            var last = 1;
            foreach (var track in transforms.Values)
                last = Math.Max(last, track.Start + track.Samples.Length - 1);
            foreach (var track in channels.Visibility.Values)
                last = Math.Max(last, track.Start + track.Values.Length - 1);
            foreach (var track in channels.Morphs.Values)
                last = Math.Max(last, track.Start + track.Weights.Length - 1);
            foreach (var track in channels.Materials.Values)
                last = Math.Max(last, track.Start + Math.Max(track.Emission.Length, track.BaseColor.Length) - 1);
            MaxFrame = last;
        }
    }

    private static readonly object SharedCacheLock = new();
    private static readonly Dictionary<string, CachedAnimation> SharedCache = new(StringComparer.OrdinalIgnoreCase);
    private static readonly Queue<string> SharedCacheOrder = new();

    private static CachedAnimation LoadAnimationShared(string path)
    {
        var fullPath = Path.GetFullPath(path);
        var metadata = Path.ChangeExtension(fullPath, ".json");
        var channels = fullPath.Replace("_animation.bin", "_channels.json", StringComparison.Ordinal);
        static string stamp(string file) => File.Exists(file)
                                          ? $"{new FileInfo(file).Length}:{File.GetLastWriteTimeUtc(file).Ticks}"
                                          : "missing";
        var key = $"{fullPath}|{stamp(fullPath)}|{stamp(metadata)}|{stamp(channels)}";
        lock (SharedCacheLock)
        {
            if (SharedCache.TryGetValue(key, out var cached))
                return cached;
            cached = new CachedAnimation(LoadTransforms(fullPath), ChannelSet.Load(fullPath));
            SharedCache[key] = cached;
            SharedCacheOrder.Enqueue(key);
            // Bound the process-wide cache when other Blender exports are used
            // in the same TiXL session. Scene bindings keep their own tracks.
            while (SharedCacheOrder.Count > 16)
                SharedCache.Remove(SharedCacheOrder.Dequeue());
            return cached;
        }
    }

    private void ReleaseMorphs()
    {
        foreach (var binding in _bindings)
            binding?.Morph?.Dispose();
    }

    protected override void Dispose(bool disposing)
    {
        if (disposing)
        {
            ReleaseMorphs();
            RenderStatsCollector.UnregisterProvider(_stats);
        }
        base.Dispose(disposing);
    }

    private sealed class RuntimeStats : IRenderStatsProvider
    {
        private int _morphUploads, _materialUploads, _sceneLoads;
        private long _morphBytes, _materialBytes, _loadUs;
        private long _totalMorphUploads, _totalMaterialUploads, _totalMorphBytes, _totalMaterialBytes;
        private long _totalSceneLoads, _totalLoadUs;
        public void MorphUpload(int vertices)
        {
            _morphUploads++; _totalMorphUploads++;
            var bytes = (long)vertices * PbrVertex.Stride;
            _morphBytes += bytes; _totalMorphBytes += bytes;
        }
        public void MaterialUpload()
        {
            _materialUploads++; _totalMaterialUploads++;
            _materialBytes += PbrMaterial.PbrParameters.Stride;
            _totalMaterialBytes += PbrMaterial.PbrParameters.Stride;
        }
        public void SceneLoad(long elapsedTicks)
        {
            _sceneLoads++; _totalSceneLoads++;
            var microseconds = elapsedTicks * 1_000_000 / Stopwatch.Frequency;
            _loadUs += microseconds; _totalLoadUs += microseconds;
        }
        private static int Bound(long value) => (int)Math.Min(int.MaxValue, value);
        public IEnumerable<(string, int)> GetStats()
        {
            yield return ("Blender scene loads", _sceneLoads);
            yield return ("Blender scene load us", Bound(_loadUs));
            yield return ("Blender cumulative scene loads", Bound(_totalSceneLoads));
            yield return ("Blender cumulative scene load us", Bound(_totalLoadUs));
            yield return ("Blender morph uploads", _morphUploads);
            yield return ("Blender material uploads", _materialUploads);
            yield return ("Blender upload bytes", Bound(_morphBytes + _materialBytes));
            yield return ("Blender cumulative morph uploads", Bound(_totalMorphUploads));
            yield return ("Blender cumulative material uploads", Bound(_totalMaterialUploads));
            yield return ("Blender cumulative upload bytes", Bound(_totalMorphBytes + _totalMaterialBytes));
        }
        public void StartNewFrame()
        {
            _morphUploads = _materialUploads = _sceneLoads = 0;
            _morphBytes = _materialBytes = _loadUs = 0;
        }
    }

    private sealed class Binding
    {
        public readonly SceneSetup.SceneDrawDispatch Dispatch;
        public readonly SceneSetup.SceneNode? Node;
        public readonly TransformTrack? Track;
        public readonly VisibilityTrack? Visible;
        public readonly Matrix4x4 BaseMatrix;
        public readonly int BaseVertexCount;
        public MorphBinding? Morph;
        public Vector3 LocalCenter;
        public float Depth;
        public int Order;
        public Binding(SceneSetup.SceneDrawDispatch dispatch, SceneSetup.SceneNode? node, TransformTrack? track, VisibilityTrack? visible)
        {
            Dispatch = dispatch; Node = node; Track = track; Visible = visible;
            BaseMatrix = dispatch.CombinedTransform; BaseVertexCount = dispatch.VertexCount;
        }
    }

    private sealed class DepthComparer : IComparer<Binding>
    {
        public static readonly DepthComparer Instance = new();
        public int Compare(Binding? a, Binding? b)
        {
            if (a == null || b == null)
                return 0;
            var depthOrder = b.Depth.CompareTo(a.Depth);
            return depthOrder != 0 ? depthOrder : a.Order.CompareTo(b.Order);
        }
    }

    private sealed class TransformTrack
    {
        public readonly int Start;
        public readonly Matrix4x4[] Samples;
        public TransformTrack(int start, Matrix4x4[] samples) { Start = start; Samples = samples; }
        public Matrix4x4 Sample(int frame) => Samples[Math.Clamp(frame - Start, 0, Samples.Length - 1)];
    }

    private sealed class VisibilityTrack
    {
        public int Start;
        public bool[] Values = Array.Empty<bool>();
        public bool Sample(int frame) => Values.Length == 0 || Values[Math.Clamp(frame - Start, 0, Values.Length - 1)];
    }

    private sealed class MorphTrack
    {
        public int Start;
        public float[][] Weights = Array.Empty<float[]>();
        public float[] Sample(int frame) => Weights[Math.Clamp(frame - Start, 0, Weights.Length - 1)];
    }

    private sealed class MaterialTrack
    {
        public int Start;
        public Vector4[] Emission = Array.Empty<Vector4>();
        public Vector4[] BaseColor = Array.Empty<Vector4>();
    }

    private sealed class MaterialBinding
    {
        private readonly PbrMaterial _material;
        private readonly MaterialTrack _track;
        private readonly MaterialDefaults? _defaults;
        private readonly RuntimeStats _stats;
        public MaterialBinding(PbrMaterial material, MaterialTrack track, MaterialDefaults? defaults, RuntimeStats stats) { _material = material; _track = track; _defaults = defaults; _stats = stats; }
        public void Apply(int frame)
        {
            var p = _material.Parameters;
            var emission = _track.Emission.Length > 0 ? _track.Emission[Math.Clamp(frame - _track.Start, 0, _track.Emission.Length - 1)] : p.EmissiveColor;
            var color = _track.BaseColor.Length > 0 ? _track.BaseColor[Math.Clamp(frame - _track.Start, 0, _track.BaseColor.Length - 1)] : p.BaseColor;
            // Linked Blender inputs ignore their default RGB; glTF retains the actual texture factors.
            if (_defaults?.HasBaseTexture == true)
                color = new Vector4(_defaults.BaseFactor.X, _defaults.BaseFactor.Y, _defaults.BaseFactor.Z, color.W);
            if (_defaults?.HasEmissionTexture == true && _track.Emission.Length <= 1)
                emission = _defaults.EmissionFactor;
            if (p.EmissiveColor == emission && p.BaseColor == color)
                return;
            p.EmissiveColor = emission;
            p.BaseColor = color;
            _material.Parameters = p;
            _material.UpdateParameterBuffer();
            _stats.MaterialUpload();
        }
    }

    private sealed class MaterialDefaults
    {
        public bool HasBaseTexture, HasEmissionTexture;
        public Vector4 BaseFactor = Vector4.One;
        public Vector4 EmissionFactor = new(0, 0, 0, 1);
    }

    private sealed class ChannelSet
    {
        public readonly Dictionary<string, VisibilityTrack> Visibility = new(StringComparer.Ordinal);
        public readonly Dictionary<string, MorphTrack> Morphs = new(StringComparer.Ordinal);
        public readonly Dictionary<string, MaterialTrack> Materials = new(StringComparer.Ordinal);
        public static ChannelSet Load(string animationPath)
        {
            var result = new ChannelSet();
            var path = animationPath.Replace("_animation.bin", "_channels.json", StringComparison.Ordinal);
            if (!File.Exists(path))
                return result;
            using var document = JsonDocument.Parse(File.ReadAllText(path));
            var root = document.RootElement;
            if (root.TryGetProperty("visibility", out var visibility))
            {
                foreach (var record in visibility.EnumerateArray())
                {
                    var values = new List<bool>();
                    foreach (var value in record.GetProperty("values").EnumerateArray())
                        values.Add(value.ValueKind == JsonValueKind.True || value.ValueKind == JsonValueKind.Number && value.GetInt32() != 0);
                    result.Visibility[record.GetProperty("export_name").GetString()!] = new VisibilityTrack { Start = record.GetProperty("start").GetInt32(), Values = values.ToArray() };
                }
            }
            if (root.TryGetProperty("morphs", out var morphs))
            {
                foreach (var record in morphs.EnumerateArray())
                {
                    var weights = new List<float[]>();
                    foreach (var sample in record.GetProperty("weights").EnumerateArray())
                    {
                        var row = new float[sample.GetArrayLength()];
                        var index = 0;
                        foreach (var value in sample.EnumerateArray())
                            row[index++] = value.GetSingle();
                        weights.Add(row);
                    }
                    result.Morphs[record.GetProperty("export_name").GetString()!] = new MorphTrack { Start = record.GetProperty("start").GetInt32(), Weights = weights.ToArray() };
                }
            }
            if (root.TryGetProperty("materials", out var materials))
            {
                foreach (var record in materials.EnumerateArray())
                {
                    var track = new MaterialTrack { Start = record.GetProperty("start").GetInt32() };
                    if (record.TryGetProperty("emission", out var emission))
                        track.Emission = ReadVector4Array(emission);
                    if (record.TryGetProperty("base_color", out var color))
                        track.BaseColor = ReadVector4Array(color);
                    result.Materials[record.GetProperty("export_name").GetString()!] = track;
                }
            }
            return result;
        }

        private static Vector4[] ReadVector4Array(JsonElement array)
        {
            var result = new Vector4[array.GetArrayLength()];
            var index = 0;
            foreach (var row in array.EnumerateArray())
                result[index++] = new Vector4(row[0].GetSingle(), row[1].GetSingle(), row[2].GetSingle(), row.GetArrayLength() > 3 ? row[3].GetSingle() : 1);
            return result;
        }
    }

    private sealed class MorphTarget
    {
        public Vector3[] Positions = Array.Empty<Vector3>();
        public Vector3[] Normals = Array.Empty<Vector3>();
        public Vector3[] Tangents = Array.Empty<Vector3>();
    }

    private sealed class MorphMesh
    {
        public PbrVertex[] Base = Array.Empty<PbrVertex>();
        public MorphTarget[] Targets = Array.Empty<MorphTarget>();
        public float[] DefaultWeights = Array.Empty<float>();
        public int[] Indices = Array.Empty<int>();
        public bool RecomputeNormals;
    }

    private sealed class MorphBinding : IDisposable
    {
        private readonly SceneSetup.SceneDrawDispatch _dispatch;
        private readonly MeshBuffers _originalBuffers;
        private readonly MeshBuffers _ownedWrapper;
        private readonly MorphMesh _mesh;
        private readonly MorphTrack? _track;
        private readonly PbrVertex[] _vertices;
        private readonly float[] _lastWeights;
        private readonly int _weightOffset;
        private BufferWithViews? _vertexBuffer = new();
        private bool _uploaded;

        private readonly RuntimeStats _stats;
        public MorphBinding(SceneSetup.SceneDrawDispatch dispatch, MorphMesh mesh, MorphTrack? track, int weightOffset, RuntimeStats stats)
        {
            _dispatch = dispatch; _mesh = mesh; _track = track; _weightOffset = weightOffset;
            _stats = stats;
            _vertices = new PbrVertex[mesh.Base.Length];
            _lastWeights = new float[mesh.Targets.Length];
            _originalBuffers = dispatch.MeshBuffers;
            _ownedWrapper = new MeshBuffers { VertexBuffer = _vertexBuffer, IndicesBuffer = _originalBuffers.IndicesBuffer, ChunkDefsBuffer = _originalBuffers.ChunkDefsBuffer };
        }

        public void Apply(int frame, float[] weightOutput)
        {
            var weights = _track != null && _track.Weights.Length > 0 ? _track.Sample(frame) : _mesh.DefaultWeights;
            var changed = !_uploaded;
            for (var target = 0; target < _mesh.Targets.Length; target++)
            {
                var weight = target < weights.Length ? weights[target] : 0;
                changed |= _lastWeights[target] != weight;
                _lastWeights[target] = weight;
                weightOutput[_weightOffset + target] = weight;
            }
            if (!changed)
                return;

            Array.Copy(_mesh.Base, _vertices, _vertices.Length);
            for (var target = 0; target < _mesh.Targets.Length; target++)
            {
                var weight = _lastWeights[target];
                if (MathF.Abs(weight) < 1e-8f)
                    continue;
                var delta = _mesh.Targets[target];
                for (var v = 0; v < _vertices.Length; v++)
                {
                    _vertices[v].Position += delta.Positions[v] * weight;
                    if (delta.Normals.Length > 0)
                        _vertices[v].Normal += delta.Normals[v] * weight;
                    if (delta.Tangents.Length > 0)
                        _vertices[v].Tangent += delta.Tangents[v] * weight;
                }
            }
            if (_mesh.RecomputeNormals)
            {
                for (var v = 0; v < _vertices.Length; v++)
                    _vertices[v].Normal = Vector3.Zero;
                for (var f = 0; f + 2 < _mesh.Indices.Length; f += 3)
                {
                    var a = _mesh.Indices[f]; var b = _mesh.Indices[f + 1]; var c = _mesh.Indices[f + 2];
                    var normal = Vector3.Cross(_vertices[b].Position - _vertices[a].Position, _vertices[c].Position - _vertices[a].Position);
                    _vertices[a].Normal += normal; _vertices[b].Normal += normal; _vertices[c].Normal += normal;
                }
            }
            for (var v = 0; v < _vertices.Length; v++)
            {
                ref var vertex = ref _vertices[v];
                vertex.Normal = SafeNormalize(vertex.Normal, Vector3.UnitY);
                var tangent = vertex.Tangent - vertex.Normal * Vector3.Dot(vertex.Normal, vertex.Tangent);
                // Untextured GLBs have no tangent accessor. UnitX is parallel
                // to the normals of a cube's side faces, so it cannot serve as
                // the fallback after projection into the tangent plane.
                var axis = MathF.Abs(vertex.Normal.X) < 0.9f ? Vector3.UnitX : Vector3.UnitY;
                vertex.Tangent = SafeNormalize(tangent, Vector3.Normalize(Vector3.Cross(axis, vertex.Normal)));
                var sign = Vector3.Dot(Vector3.Cross(_mesh.Base[v].Normal, _mesh.Base[v].Tangent), _mesh.Base[v].Bitangent) < 0 ? -1 : 1;
                vertex.Bitangent = Vector3.Cross(vertex.Normal, vertex.Tangent) * sign;
            }
            ResourceManager.SetupBufferWithViews(_vertices, ref _vertexBuffer);
            _stats.MorphUpload(_vertices.Length);
            _ownedWrapper.VertexBuffer = _vertexBuffer!;
            _dispatch.MeshBuffers = _ownedWrapper;
            _uploaded = true;
        }

        public void Dispose()
        {
            if (ReferenceEquals(_dispatch.MeshBuffers, _ownedWrapper))
                _dispatch.MeshBuffers = _originalBuffers;
            // Index and chunk buffers belong to LoadGltfScene; only the replacement vertex buffer is owned here.
            _vertexBuffer?.Dispose();
        }
    }

    private static Vector3 SafeNormalize(Vector3 value, Vector3 fallback) => value.LengthSquared() > 1e-12f ? Vector3.Normalize(value) : fallback;

    private sealed class GlbReader
    {
        private readonly JsonElement _root;
        private readonly byte[] _binary;
        private GlbReader(JsonElement root, byte[] binary) { _root = root; _binary = binary; }

        public static Dictionary<string, List<Vector3>> LoadPrimitiveCenters(string path)
        {
            using var stream = File.OpenRead(path);
            using var reader = new BinaryReader(stream);
            stream.Position = 12;
            var length = reader.ReadInt32();
            reader.ReadUInt32();
            using var document = JsonDocument.Parse(reader.ReadBytes(length));
            var root = document.RootElement;
            var result = new Dictionary<string, List<Vector3>>(StringComparer.Ordinal);
            foreach (var node in root.GetProperty("nodes").EnumerateArray())
            {
                if (!node.TryGetProperty("mesh", out var meshIndex))
                    continue;
                var centers = new List<Vector3>();
                foreach (var primitive in root.GetProperty("meshes")[meshIndex.GetInt32()].GetProperty("primitives").EnumerateArray())
                {
                    var accessor = root.GetProperty("accessors")[primitive.GetProperty("attributes").GetProperty("POSITION").GetInt32()];
                    var center = Vector3.Zero;
                    if (accessor.TryGetProperty("min", out var min) && accessor.TryGetProperty("max", out var max))
                        center = new Vector3(min[0].GetSingle() + max[0].GetSingle(), min[1].GetSingle() + max[1].GetSingle(), min[2].GetSingle() + max[2].GetSingle()) * 0.5f;
                    centers.Add(center);
                }
                result[node.GetProperty("name").GetString()!] = centers;
            }
            return result;
        }

        public static Dictionary<string, MaterialDefaults> LoadMaterialDefaults(string path)
        {
            using var stream = File.OpenRead(path);
            using var reader = new BinaryReader(stream);
            stream.Position = 12;
            var length = reader.ReadInt32();
            reader.ReadUInt32();
            using var document = JsonDocument.Parse(reader.ReadBytes(length));
            var result = new Dictionary<string, MaterialDefaults>(StringComparer.Ordinal);
            if (!document.RootElement.TryGetProperty("materials", out var materials))
                return result;
            foreach (var material in materials.EnumerateArray())
            {
                var defaults = new MaterialDefaults();
                if (material.TryGetProperty("pbrMetallicRoughness", out var pbr))
                {
                    defaults.HasBaseTexture = pbr.TryGetProperty("baseColorTexture", out _);
                    if (pbr.TryGetProperty("baseColorFactor", out var factor))
                        defaults.BaseFactor = new Vector4(factor[0].GetSingle(), factor[1].GetSingle(), factor[2].GetSingle(), factor[3].GetSingle());
                }
                defaults.HasEmissionTexture = material.TryGetProperty("emissiveTexture", out _);
                if (material.TryGetProperty("emissiveFactor", out var emission))
                    defaults.EmissionFactor = new Vector4(emission[0].GetSingle(), emission[1].GetSingle(), emission[2].GetSingle(), 1);
                if (material.TryGetProperty("extensions", out var extensions)
                    && extensions.TryGetProperty("KHR_materials_emissive_strength", out var strength))
                {
                    var value = strength.GetProperty("emissiveStrength").GetSingle();
                    defaults.EmissionFactor *= new Vector4(value, value, value, 1);
                }
                result[material.GetProperty("name").GetString()!] = defaults;
            }
            return result;
        }

        public static Dictionary<string, List<MorphMesh>> LoadMorphs(string path)
        {
            using var stream = File.OpenRead(path);
            using var reader = new BinaryReader(stream);
            if (reader.ReadUInt32() != 0x46546c67 || reader.ReadUInt32() != 2)
                throw new InvalidDataException("Expected a glTF 2 binary.");
            reader.ReadUInt32();
            var jsonLength = reader.ReadInt32();
            if (reader.ReadUInt32() != 0x4e4f534a)
                throw new InvalidDataException("Missing glTF JSON chunk.");
            using var document = JsonDocument.Parse(reader.ReadBytes(jsonLength));
            var binaryLength = reader.ReadInt32();
            if (reader.ReadUInt32() != 0x004e4942)
                throw new InvalidDataException("Missing glTF binary chunk.");
            var glb = new GlbReader(document.RootElement, reader.ReadBytes(binaryLength));
            var result = new Dictionary<string, List<MorphMesh>>(StringComparer.Ordinal);
            foreach (var node in glb._root.GetProperty("nodes").EnumerateArray())
            {
                if (!node.TryGetProperty("mesh", out var meshIndex))
                    continue;
                var mesh = glb._root.GetProperty("meshes")[meshIndex.GetInt32()];
                var hasMorph = false;
                foreach (var primitive in mesh.GetProperty("primitives").EnumerateArray())
                    hasMorph |= primitive.TryGetProperty("targets", out _);
                if (!hasMorph)
                    continue;
                var defaults = Array.Empty<float>();
                if (node.TryGetProperty("weights", out var weights) || mesh.TryGetProperty("weights", out weights))
                {
                    defaults = new float[weights.GetArrayLength()];
                    var index = 0;
                    foreach (var value in weights.EnumerateArray())
                        defaults[index++] = value.GetSingle();
                }
                var meshes = new List<MorphMesh>();
                foreach (var primitive in mesh.GetProperty("primitives").EnumerateArray())
                    meshes.Add(glb.ReadMesh(primitive, defaults));
                result[node.GetProperty("name").GetString()!] = meshes;
            }
            return result;
        }

        private MorphMesh ReadMesh(JsonElement primitive, float[] weights)
        {
            var mesh = new MorphMesh { DefaultWeights = weights };
            if (!primitive.TryGetProperty("targets", out var targets))
                return mesh;
            var attributes = primitive.GetProperty("attributes");
            var positions = ReadVec3(attributes.GetProperty("POSITION").GetInt32());
            var normals = attributes.TryGetProperty("NORMAL", out var normal) ? ReadVec3(normal.GetInt32()) : Array.Empty<Vector3>();
            var tangents = attributes.TryGetProperty("TANGENT", out var tangent) ? ReadAccessor(tangent.GetInt32()) : Array.Empty<float>();
            var uv = attributes.TryGetProperty("TEXCOORD_0", out var texcoord) ? ReadAccessor(texcoord.GetInt32()) : Array.Empty<float>();
            var uv2 = attributes.TryGetProperty("TEXCOORD_1", out var texcoord2) ? ReadAccessor(texcoord2.GetInt32()) : Array.Empty<float>();
            mesh.Base = new PbrVertex[positions.Length];
            for (var i = 0; i < positions.Length; i++)
            {
                var n = normals.Length > 0 ? normals[i] : Vector3.UnitY;
                var t = tangents.Length > 0 ? new Vector3(tangents[i * 4], tangents[i * 4 + 1], tangents[i * 4 + 2]) : Vector3.UnitX;
                mesh.Base[i] = new PbrVertex { Position = positions[i], Normal = n, Tangent = t,
                    Bitangent = Vector3.Cross(n, t) * (tangents.Length > 0 ? tangents[i * 4 + 3] : 1),
                    Texcoord = uv.Length > 0 ? new Vector2(uv[i * 2], 1 - uv[i * 2 + 1]) : Vector2.Zero,
                    Texcoord2 = uv2.Length > 0 ? new Vector2(uv2[i * 2], 1 - uv2[i * 2 + 1]) : Vector2.Zero,
                    ColorRgb = Vector3.One, Selection = 1 };
            }
            if (primitive.TryGetProperty("indices", out var indices))
            {
                var source = ReadAccessor(indices.GetInt32());
                mesh.Indices = new int[source.Length];
                for (var i = 0; i < source.Length; i++)
                    mesh.Indices[i] = (int)source[i];
            }
            mesh.Targets = new MorphTarget[targets.GetArrayLength()];
            var targetIndex = 0;
            foreach (var target in targets.EnumerateArray())
            {
                var delta = new MorphTarget
                {
                    Positions = target.TryGetProperty("POSITION", out var p) ? ReadVec3(p.GetInt32()) : new Vector3[positions.Length],
                    Normals = target.TryGetProperty("NORMAL", out var n) ? ReadVec3(n.GetInt32()) : Array.Empty<Vector3>(),
                    Tangents = target.TryGetProperty("TANGENT", out var t) ? ReadVec3(t.GetInt32()) : Array.Empty<Vector3>(),
                };
                mesh.RecomputeNormals |= delta.Normals.Length == 0;
                mesh.Targets[targetIndex++] = delta;
            }
            return mesh;
        }

        private Vector3[] ReadVec3(int index)
        {
            var values = ReadAccessor(index);
            var result = new Vector3[values.Length / 3];
            for (var i = 0; i < result.Length; i++)
                result[i] = new Vector3(values[i * 3], values[i * 3 + 1], values[i * 3 + 2]);
            return result;
        }

        private float[] ReadAccessor(int index)
        {
            var accessor = _root.GetProperty("accessors")[index];
            var componentType = accessor.GetProperty("componentType").GetInt32();
            var components = accessor.GetProperty("type").GetString() switch { "SCALAR" => 1, "VEC2" => 2, "VEC3" => 3, "VEC4" => 4, _ => throw new InvalidDataException("Unsupported morph accessor shape.") };
            var size = ComponentSize(componentType);
            var normalized = accessor.TryGetProperty("normalized", out var norm) && norm.GetBoolean();
            var count = accessor.GetProperty("count").GetInt32();
            var result = new float[count * components];
            if (accessor.TryGetProperty("bufferView", out var viewIndex))
            {
                var view = _root.GetProperty("bufferViews")[viewIndex.GetInt32()];
                var offset = Int(view, "byteOffset") + Int(accessor, "byteOffset");
                var stride = view.TryGetProperty("byteStride", out var step) ? step.GetInt32() : components * size;
                for (var i = 0; i < count; i++)
                    for (var c = 0; c < components; c++)
                        result[i * components + c] = ReadComponent(offset + i * stride + c * size, componentType, normalized);
            }
            if (accessor.TryGetProperty("sparse", out var sparse))
            {
                var indices = sparse.GetProperty("indices");
                var values = sparse.GetProperty("values");
                var indicesType = indices.GetProperty("componentType").GetInt32();
                var indicesOffset = Int(_root.GetProperty("bufferViews")[indices.GetProperty("bufferView").GetInt32()], "byteOffset") + Int(indices, "byteOffset");
                var valuesOffset = Int(_root.GetProperty("bufferViews")[values.GetProperty("bufferView").GetInt32()], "byteOffset") + Int(values, "byteOffset");
                for (var i = 0; i < sparse.GetProperty("count").GetInt32(); i++)
                {
                    var destination = (int)ReadComponent(indicesOffset + i * ComponentSize(indicesType), indicesType, false);
                    for (var c = 0; c < components; c++)
                        result[destination * components + c] = ReadComponent(valuesOffset + (i * components + c) * size, componentType, normalized);
                }
            }
            return result;
        }

        private float ReadComponent(int offset, int type, bool normalized) => type switch
        {
            5126 => BitConverter.ToSingle(_binary, offset),
            5125 => BitConverter.ToUInt32(_binary, offset),
            5123 => normalized ? BitConverter.ToUInt16(_binary, offset) / 65535f : BitConverter.ToUInt16(_binary, offset),
            5122 => normalized ? Math.Max(-1, BitConverter.ToInt16(_binary, offset) / 32767f) : BitConverter.ToInt16(_binary, offset),
            5121 => normalized ? _binary[offset] / 255f : _binary[offset],
            5120 => normalized ? Math.Max(-1, (sbyte)_binary[offset] / 127f) : (sbyte)_binary[offset],
            _ => throw new InvalidDataException("Unsupported morph component type.")
        };
        private static int ComponentSize(int type) => type is 5120 or 5121 ? 1 : type is 5122 or 5123 ? 2 : 4;
        private static int Int(JsonElement element, string property) => element.TryGetProperty(property, out var value) ? value.GetInt32() : 0;
    }

    IStatusProvider.StatusLevel IStatusProvider.GetStatusLevel() => _status.Length == 0 ? IStatusProvider.StatusLevel.Success : IStatusProvider.StatusLevel.Warning;
    string IStatusProvider.GetStatusMessage() => _status;
    private SceneSetup? _scene;
    private string _requestedPath = string.Empty, _requestedGlbPath = string.Empty, _status = string.Empty;
    private int _lastFrame = -1;
    private Binding[] _bindings = Array.Empty<Binding>();
    private int _maxFrame = 1;
    private MaterialBinding[] _materials = Array.Empty<MaterialBinding>();
    private Matrix4x4[] _transforms = Array.Empty<Matrix4x4>();
    private int[] _visibility = Array.Empty<int>();
    private Vector4[] _emission = Array.Empty<Vector4>(), _colors = Array.Empty<Vector4>();
    private float[] _weights = Array.Empty<float>();
    private readonly SceneSetup _opaqueScene = new(), _transparentScene = new();
    private readonly List<Binding> _transparentBindings = new();
}

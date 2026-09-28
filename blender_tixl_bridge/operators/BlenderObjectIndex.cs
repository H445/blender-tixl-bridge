#nullable enable
using System;
using System.Collections.Generic;
using T3.Core.DataTypes;
using T3.Core.Operator;
using T3.Core.Operator.Attributes;
using T3.Core.Operator.Interfaces;
using T3.Core.Operator.Slots;

namespace PrismalLabs.BlenderExport;

/// <summary>Resolve an imported Blender object name to its current TiXL primitive index.</summary>
[Guid("b62fce64-2efe-54ac-9d6f-3db2f83deed4")]
public sealed class BlenderObjectIndex : Instance<BlenderObjectIndex>, IStatusProvider
{
    [Input(Guid = "dc7ae73f-9b1d-54a1-9fc2-d5d7581c4f84")]
    public readonly InputSlot<SceneSetup> Scene = new();

    [Input(Guid = "9e4a2fb0-334e-5567-8f63-e9d1ac3260aa")]
    public readonly InputSlot<string> ObjectName = new();

    [Output(Guid = "74cf55e0-7b98-5e5a-ae5d-f77a2f72079c", DirtyFlagTrigger = DirtyFlagTrigger.Animated)]
    public readonly Slot<int> PrimitiveIndex = new();

    [Output(Guid = "428e7504-8fc6-4689-99d5-d9562d7020fb", DirtyFlagTrigger = DirtyFlagTrigger.Animated)]
    public readonly Slot<string> SelectedObject = new();

    private string _status = "Enter a Blender object name";

    public BlenderObjectIndex()
    {
        PrimitiveIndex.UpdateAction = Update;
        SelectedObject.UpdateAction = Update;
    }

    private void Update(EvaluationContext context)
    {
        var scene = Scene.GetValue(context);
        var requested = ObjectName.GetValue(context)?.Trim() ?? string.Empty;
        var names = new List<string>();
        if (scene != null)
            foreach (var root in scene.RootNodes)
                CollectNames(root, names);

        var matches = new List<int>();
        if (requested.Length > 0)
        {
            for (var i = 0; i < names.Count; i++)
                if (string.Equals(names[i], requested, StringComparison.OrdinalIgnoreCase))
                    matches.Add(i);
            if (matches.Count == 0)
            {
                // glTF sometimes appends .001 to an otherwise unique Blender name.
                for (var i = 0; i < names.Count; i++)
                    if (names[i].StartsWith(requested + ".", StringComparison.OrdinalIgnoreCase)
                        && int.TryParse(names[i].Substring(requested.Length + 1), out _))
                        matches.Add(i);
            }
            if (matches.Count == 0)
                for (var i = 0; i < names.Count; i++)
                    if (names[i].Contains(requested, StringComparison.OrdinalIgnoreCase))
                        matches.Add(i);
        }
        var index = matches.Count == 1 ? matches[0] : -1;
        if (scene == null || index >= scene.Dispatches.Count)
            index = -1;
        PrimitiveIndex.Value = index;
        SelectedObject.Value = index >= 0 ? names[index] : string.Empty;
        _status = requested.Length == 0 ? $"Search {names.Count} imported Blender meshes by name"
                : matches.Count > 1 ? $"{matches.Count} matches for '{requested}': {string.Join(", ", matches.GetRange(0, Math.Min(4, matches.Count)).ConvertAll(i => names[i]))}"
                : index < 0 ? $"No imported Blender mesh matches '{requested}'"
                : $"Selected Blender object: {names[index]}";
    }

    private static void CollectNames(SceneSetup.SceneNode node, List<string> names)
    {
        if (node.MeshBuffers != null)
            names.Add(node.Name ?? string.Empty);
        foreach (var child in node.ChildNodes)
            CollectNames(child, names);
    }

    IStatusProvider.StatusLevel IStatusProvider.GetStatusLevel() =>
        PrimitiveIndex.Value >= 0 ? IStatusProvider.StatusLevel.Success : IStatusProvider.StatusLevel.Warning;
    string IStatusProvider.GetStatusMessage() => _status;
}

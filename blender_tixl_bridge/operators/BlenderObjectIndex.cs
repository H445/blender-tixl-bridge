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

    private string _status = "Enter a Blender object name";

    public BlenderObjectIndex() => PrimitiveIndex.UpdateAction = Update;

    private void Update(EvaluationContext context)
    {
        var scene = Scene.GetValue(context);
        var requested = ObjectName.GetValue(context)?.Trim() ?? string.Empty;
        var names = new List<string>();
        if (scene != null)
            foreach (var root in scene.RootNodes)
                CollectNames(root, names);

        var index = -1;
        if (requested.Length > 0)
        {
            index = names.FindIndex(name => string.Equals(name, requested, StringComparison.OrdinalIgnoreCase));
            if (index < 0)
            {
                // glTF sometimes appends .001 to an otherwise unique Blender name.
                var matches = new List<int>();
                for (var i = 0; i < names.Count; i++)
                    if (names[i].StartsWith(requested + ".", StringComparison.OrdinalIgnoreCase)
                        && int.TryParse(names[i].Substring(requested.Length + 1), out _))
                        matches.Add(i);
                if (matches.Count == 1)
                    index = matches[0];
            }
        }
        if (scene == null || index >= scene.Dispatches.Count)
            index = -1;
        PrimitiveIndex.Value = index;
        _status = requested.Length == 0 ? "Enter a Blender object name"
                : index < 0 ? $"No unique primitive named '{requested}'"
                : $"Selected {names[index]} ({index + 1}/{names.Count})";
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

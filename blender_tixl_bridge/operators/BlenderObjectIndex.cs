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
public sealed class BlenderObjectIndex : Instance<BlenderObjectIndex>, IStatusProvider, ICustomDropdownHolder
{
    private static readonly Guid ObjectNameInputId = Guid.Parse("9e4a2fb0-334e-5567-8f63-e9d1ac3260aa");
    [Input(Guid = "dc7ae73f-9b1d-54a1-9fc2-d5d7581c4f84")]
    public readonly InputSlot<SceneSetup> Scene = new();

    [Input(Guid = "9e4a2fb0-334e-5567-8f63-e9d1ac3260aa")]
    public readonly InputSlot<string> ObjectName = new();

    [Output(Guid = "74cf55e0-7b98-5e5a-ae5d-f77a2f72079c", DirtyFlagTrigger = DirtyFlagTrigger.Animated)]
    public readonly Slot<int> PrimitiveIndex = new();

    [Output(Guid = "428e7504-8fc6-4689-99d5-d9562d7020fb", DirtyFlagTrigger = DirtyFlagTrigger.Animated)]
    public readonly Slot<string> SelectedObject = new();

    private string _status = "Render the connected Blender scene to list its mesh objects";
    private readonly List<string> _availableObjects = new();

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
        _availableObjects.Clear();
        var totals = new Dictionary<string, int>(StringComparer.Ordinal);
        foreach (var name in names)
            totals[name] = totals.TryGetValue(name, out var existingCount) ? existingCount + 1 : 1;
        var occurrences = new Dictionary<string, int>(StringComparer.Ordinal);
        foreach (var name in names)
        {
            occurrences[name] = occurrences.TryGetValue(name, out var previousOccurrence) ? previousOccurrence + 1 : 1;
            _availableObjects.Add(totals[name] == 1 ? name
                                  : $"{name} [primitive {occurrences[name]}/{totals[name]}]");
        }

        var matches = new List<int>();
        if (requested.Length > 0)
        {
            for (var i = 0; i < _availableObjects.Count; i++)
                if (string.Equals(_availableObjects[i], requested, StringComparison.OrdinalIgnoreCase))
                    matches.Add(i);
        }
        if (requested.Length > 0 && matches.Count == 0)
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
        SelectedObject.Value = index >= 0 ? _availableObjects[index] : string.Empty;
        _status = requested.Length == 0 ? $"Choose from {names.Count} imported Blender mesh objects"
                : matches.Count > 1 ? $"{matches.Count} matches for '{requested}': {string.Join(", ", matches.GetRange(0, Math.Min(4, matches.Count)).ConvertAll(i => names[i]))}"
                : index < 0 ? $"No imported Blender mesh matches '{requested}'"
                : $"Selected Blender mesh: {_availableObjects[index]}";
    }

    private static void CollectNames(SceneSetup.SceneNode node, List<string> names)
    {
        if (node.MeshBuffers != null)
            names.Add(node.Name ?? string.Empty);
        foreach (var child in node.ChildNodes)
            CollectNames(child, names);
    }

    string? ICustomDropdownHolder.GetValueForInput(Guid inputId)
    {
        if (inputId != ObjectNameInputId)
            return null;
        var requested = ObjectName.TypedInputValue.Value;
        return _availableObjects.Contains(requested) ? requested
               : !string.IsNullOrEmpty(SelectedObject.Value) ? SelectedObject.Value : requested;
    }

    IEnumerable<string> ICustomDropdownHolder.GetOptionsForInput(Guid inputId) =>
        inputId == ObjectNameInputId ? _availableObjects.ToArray() : Array.Empty<string>();

    void ICustomDropdownHolder.HandleResultForInput(Guid inputId, string? selected, bool isAListItem)
    {
        if (inputId == ObjectNameInputId && isAListItem && selected != null
            && _availableObjects.Contains(selected))
            ObjectName.SetTypedInputValue(selected);
    }

    IStatusProvider.StatusLevel IStatusProvider.GetStatusLevel() =>
        PrimitiveIndex.Value >= 0 ? IStatusProvider.StatusLevel.Success : IStatusProvider.StatusLevel.Warning;
    string IStatusProvider.GetStatusMessage() => _status;
}

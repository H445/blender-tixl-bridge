using System;
using System.Runtime.InteropServices;
using T3.Core.Operator;
using T3.Core.Operator.Attributes;
using T3.Core.Operator.Slots;

namespace PrismalLabs.BlenderExport;

/// <summary>Selects the active source clip and exposes its mapped Blender time.</summary>
[Guid("6defae81-c198-5bee-91e6-3160d17651dd")]
public sealed class BlenderClipSequence : Instance<BlenderClipSequence>
{
    [Input(Guid = "36bf79ae-84ac-5691-b8cb-a65d2e055d1a")]
    public readonly MultiInputSlot<float> Clips = new();

    [Input(Guid = "887bf3b5-45fa-4db1-a056-199d0a088931")]
    public readonly InputSlot<float> LoopDurationSeconds = new();

    [Output(Guid = "0b2900ec-dd39-55a7-8738-2e07d265f78c", DirtyFlagTrigger = DirtyFlagTrigger.Animated)]
    public readonly Slot<float> TimeSeconds = new();

    [Output(Guid = "8ac94bb7-59c9-486b-9f8a-47e0ec25110e", DirtyFlagTrigger = DirtyFlagTrigger.Animated)]
    public readonly Slot<bool> HasActiveClip = new();

    public BlenderClipSequence()
    {
        TimeSeconds.UpdateAction = Update;
        HasActiveClip.UpdateAction = Update;
    }

    private void Update(EvaluationContext context)
    {
        // A positive loop duration wraps the entire clip lane, including the
        // TimeClip's own source-range mapping. Zero preserves normal TiXL timing.
        var loopSeconds = LoopDurationSeconds.GetValue(context);
        var loopBars = loopSeconds * Math.Max(1, context.Playback.Bpm) / 240.0;
        var originalTime = context.LocalTime;
        if (loopBars > 0)
            context.LocalTime = originalTime - loopBars * Math.Floor(originalTime / loopBars);
        try
        {
            UpdateAtLocalTime(context);
        }
        finally
        {
            context.LocalTime = originalTime;
        }
    }

    private void UpdateAtLocalTime(EvaluationContext context)
    {
        var inputs = Clips.GetCollectedTypedInputs();
        Slot<float>? selected = null;
        var layer = int.MaxValue;
        var start = float.MinValue;
        var previousEnd = double.MinValue;
        var heldSource = 0f;
        var firstStart = double.MaxValue;
        var firstSource = 0f;
        var hasClips = false;
        foreach (var input in inputs)
        {
            if (input is not ITimeClipProvider provider)
                continue;
            var clip = provider.TimeClip;
            hasClips = true;
            if (clip.TimeRange.Start < firstStart)
            {
                firstStart = clip.TimeRange.Start;
                firstSource = clip.SourceRange.Start;
            }
            if (clip.TimeRange.End <= context.LocalTime && clip.TimeRange.End > previousEnd)
            {
                previousEnd = clip.TimeRange.End;
                heldSource = clip.SourceRange.End;
            }
            if (context.LocalTime < clip.TimeRange.Start || context.LocalTime >= clip.TimeRange.End)
                continue;
            if (selected != null && (clip.LayerIndex > layer ||
                                     clip.LayerIndex == layer && clip.TimeRange.Start <= start))
                continue;
            selected = input;
            layer = clip.LayerIndex;
            start = clip.TimeRange.Start;
        }

        // Hold the last source frame in a gap, so only TimeClips drive source time.
        TimeSeconds.Value = selected != null
                                ? selected.GetValue(context)
                                : hasClips ? previousEnd > double.MinValue ? heldSource : firstSource
                                           : (float)(context.LocalTime * 240 / Math.Max(1, context.Playback.Bpm));
        HasActiveClip.Value = selected != null;
        Clips.DirtyFlag.Clear();
    }
}

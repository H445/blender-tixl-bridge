#nullable enable
using System;
using T3.Core.DataTypes;
using T3.Core.Operator;
using T3.Core.Operator.Attributes;
using T3.Core.Operator.Slots;

namespace PrismalLabs.BlenderExport;

/// <summary>Evaluates separate audio clips and their shared master fader.</summary>
[Guid("c54e249e-0a7f-41a5-aa62-31117f33d5df")]
public sealed class BlenderAudioBus : Instance<BlenderAudioBus>
{
    [Output(Guid = "6c6b994d-5fba-4c04-94a4-95a20314caf5", DirtyFlagTrigger = DirtyFlagTrigger.Animated)]
    public readonly Slot<Command> Result = new();

    [Input(Guid = "2786a789-4527-45a4-aeb8-581ee93a621e")]
    public readonly MultiInputSlot<Command> ClipsAndVisuals = new();

    [Input(Guid = "3974a495-1229-46c8-a1c7-7969a10b670d")]
    public readonly InputSlot<float> MasterVolume = new();

    [Input(Guid = "3252ab1d-73d6-4aae-8e27-6df4ff1b85ba")]
    public readonly InputSlot<bool> Mute = new();

    [ThreadStatic] private static float _gain;
    [ThreadStatic] private static int _depth;

    internal static float CurrentGain => _depth == 0 ? 1 : _gain;

    public BlenderAudioBus() => Result.UpdateAction = Update;

    private void Update(EvaluationContext context)
    {
        var priorGain = CurrentGain;
        _depth++;
        _gain = priorGain * (Mute.GetValue(context)
                                 ? 0
                                 : Math.Clamp(MasterVolume.GetValue(context), 0, 1));
        try
        {
            var commands = ClipsAndVisuals.CollectedInputs;
            for (var i = 0; i < commands.Count; i++)
            {
                commands[i].Value?.PrepareAction?.Invoke(context);
                commands[i].GetValue(context);
                commands[i].Value?.RestoreAction?.Invoke(context);
            }
        }
        finally
        {
            _depth--;
            _gain = priorGain;
            ClipsAndVisuals.DirtyFlag.Clear();
        }
    }
}

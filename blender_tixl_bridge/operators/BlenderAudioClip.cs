#nullable enable
using System;
using T3.Core.Animation;
using T3.Core.Audio;
using T3.Core.DataTypes;
using T3.Core.Operator;
using T3.Core.Operator.Attributes;
using T3.Core.Operator.Slots;

namespace PrismalLabs.BlenderExport;

/// <summary>
/// Plays one independent audio clip against the composition's time in seconds.
/// A seek, timeline loop, file change, or drift restarts at the matching sample.
/// Route Result into BlenderAudioBus to mix clips with individual levels.
/// </summary>
[Guid("4812d48b-f74e-49dd-98f3-bd6b5b1df82e")]
public sealed class BlenderAudioClip : Instance<BlenderAudioClip>
{
    [Output(Guid = "80923455-7af0-49f5-acb0-ed2a1e9fb715", DirtyFlagTrigger = DirtyFlagTrigger.Animated)]
    public readonly Slot<Command> Result = new();

    [Output(Guid = "3df7fdd0-00e0-4f5a-9e54-4d5a8fc00813", DirtyFlagTrigger = DirtyFlagTrigger.Animated)]
    public readonly Slot<bool> IsPlaying = new();

    [Output(Guid = "fa621ca0-8208-4616-bdc4-e763833cc85a", DirtyFlagTrigger = DirtyFlagTrigger.Animated)]
    public readonly Slot<float> Level = new();

    [Input(Guid = "20f00480-4039-4cb7-8120-5994db9ee296")]
    public readonly InputSlot<string> Path = new();

    [Input(Guid = "8ed11bc3-e8c1-4b0e-8c6c-26e79fe5d11b")]
    public readonly InputSlot<float> TimeSeconds = new();

    [Input(Guid = "8725b560-1ef8-4d87-9145-34e0547c80a9")]
    public readonly InputSlot<float> LengthSeconds = new();

    [Input(Guid = "20249dd6-273f-49d9-976a-bf78b3970817")]
    public readonly InputSlot<float> Volume = new();

    [Input(Guid = "f8b57e42-740c-450a-99c6-7aa62bc946f3")]
    public readonly InputSlot<bool> Loop = new();

    [Input(Guid = "bfb31e0c-9e50-487b-ae5b-c11640961173")]
    public readonly InputSlot<bool> Enabled = new();

    private readonly Guid _audioId = Guid.NewGuid();
    private string _lastPath = string.Empty;
    private double _lastTime = double.NaN;
    private double _lastRunTime = double.NaN;
    private bool _paused;
    private bool _playing;

    public BlenderAudioClip()
    {
        Result.UpdateAction = Update;
        IsPlaying.UpdateAction = UpdateStatus;
        Level.UpdateAction = UpdateStatus;
    }

    private void UpdateStatus(EvaluationContext context)
    {
        IsPlaying.Value = AudioEngine.IsOperatorStreamPlaying(_audioId);
        Level.Value = AudioEngine.GetOperatorLevel(_audioId);
    }

    private static double Wrap(double time, double length)
    {
        var wrapped = time % length;
        return wrapped < 0 ? wrapped + length : wrapped;
    }

    private void Update(EvaluationContext context)
    {
        var path = Path.GetValue(context) ?? string.Empty;
        var duration = Math.Max(0.01, LengthSeconds.GetValue(context));
        var time = TimeSeconds.GetValue(context);
        var volume = Math.Clamp(Volume.GetValue(context), 0, 1) * BlenderAudioBus.CurrentGain;
        var loop = Loop.GetValue(context);
        var speed = context.Playback.PlaybackSpeed;
        var now = Playback.RunTimeInSecs;
        var valid = Enabled.GetValue(context) && !string.IsNullOrWhiteSpace(path)
                    && double.IsFinite(time) && (loop || (time >= 0 && time < duration));
        if (!valid)
        {
            if (_playing)
                AudioEngine.UpdateStereoOperatorPlayback(_audioId, path, false, true, volume, false, 0);
            _playing = false;
            _lastTime = double.NaN;
            _lastPath = path;
            return;
        }

        var local = loop ? Wrap(time, duration) : time;
        var wrappedAcrossEnd = loop && double.IsFinite(_lastTime)
                               && local < _lastTime - duration / 2;
        var expected = double.IsFinite(_lastTime) && double.IsFinite(_lastRunTime)
                           ? _lastTime + (now - _lastRunTime) * speed
                           : double.NaN;
        var drift = double.IsFinite(expected) ? Math.Abs(local - expected) : double.PositiveInfinity;
        if (loop && double.IsFinite(expected))
            drift = Math.Min(drift, Math.Abs(local + duration - expected));

        var restart = !_playing || path != _lastPath || wrappedAcrossEnd || drift > .12;
        var seek = (float)Math.Clamp(local / duration, 0, .999999);
        var playbackSpeed = (float)Math.Clamp(Math.Abs(speed), .01, 8);
        if (restart)
        {
            AudioEngine.UpdateStereoOperatorPlayback(_audioId, path, false, true,
                                                      volume, false, 0, playbackSpeed, seek);
            AudioEngine.UpdateStereoOperatorPlayback(_audioId, path, true, false,
                                                      volume, false, 0, playbackSpeed, seek);
            _playing = true;
            _paused = false;
        }
        else
        {
            AudioEngine.UpdateStereoOperatorPlayback(_audioId, path, true, false,
                                                      volume, false, 0, playbackSpeed, seek);
        }

        if (Math.Abs(speed) < .001 && !_paused)
        {
            AudioEngine.PauseOperator(_audioId);
            _paused = true;
        }
        else if (Math.Abs(speed) >= .001 && _paused)
        {
            AudioEngine.ResumeOperator(_audioId);
            _paused = false;
        }

        _lastTime = local;
        _lastRunTime = now;
        _lastPath = path;
    }

    ~BlenderAudioClip() => AudioEngine.UnregisterOperator(_audioId);
}

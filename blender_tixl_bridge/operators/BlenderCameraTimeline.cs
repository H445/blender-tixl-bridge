#nullable enable
using System;
using System.IO;
using System.Numerics;
using System.Runtime.InteropServices;
using System.Collections.Generic;
using System.Globalization;
using System.Text.Json;
using T3.Core.Operator;
using T3.Core.Operator.Attributes;
using T3.Core.Operator.Slots;
namespace PrismalLabs.BlenderExport;
[Guid("18e0cf0e-af1a-531c-a999-1c10e053b797")]
/// <summary>Reads a Blender camera rail and exposes interpolated camera pose, lens, clip planes, scene time, and optional cut metadata.</summary>
public sealed class BlenderCameraTimeline : Instance<BlenderCameraTimeline>
{
    [Output(Guid="dcc2da87-6bd5-5e0b-87ac-2cb31a95ee76", DirtyFlagTrigger=DirtyFlagTrigger.Animated)] public readonly Slot<float> TimeSeconds=new();
    [Output(Guid="763db5bd-827a-5bed-9924-dbec43b3d7a7", DirtyFlagTrigger=DirtyFlagTrigger.Animated)] public readonly Slot<int> WorldIndex=new();
    [Output(Guid="da144668-cb98-5e29-9ff8-a58513bef117", DirtyFlagTrigger=DirtyFlagTrigger.Animated)] public readonly Slot<int> ShotIndex=new();
    [Output(Guid="4fced1de-b64c-579f-8761-a2d32885a4aa", DirtyFlagTrigger=DirtyFlagTrigger.Animated)] public readonly Slot<string> ShotLabel=new();
    [Output(Guid="f9f621a6-5972-5ff5-bf55-8c0aa4ba3f90", DirtyFlagTrigger=DirtyFlagTrigger.Animated)] public readonly Slot<Vector3> Position=new();
    [Output(Guid="edd4ec3f-286b-50ee-98c5-bdf3f0560ef5", DirtyFlagTrigger=DirtyFlagTrigger.Animated)] public readonly Slot<Vector3> Target=new();
    [Output(Guid="bd82686d-4bb7-5c8c-8b0c-154784c130b4", DirtyFlagTrigger=DirtyFlagTrigger.Animated)] public readonly Slot<Vector3> Up=new();
    [Output(Guid="993634db-47a2-5f92-8987-172157c46bab", DirtyFlagTrigger=DirtyFlagTrigger.Animated)] public readonly Slot<float> FieldOfView=new();
    [Output(Guid="5f1a1df0-fe35-5c8e-bff4-019aa3454c4c", DirtyFlagTrigger=DirtyFlagTrigger.Animated)] public readonly Slot<Vector2> ClipPlanes=new();
    [Output(Guid="e645bbb3-9202-552e-a127-1d079a18375f", DirtyFlagTrigger=DirtyFlagTrigger.Animated)] public readonly Slot<float> BlurRadius=new();
    [Output(Guid="125574ac-61db-5536-a5bf-0f2222bcbe8e", DirtyFlagTrigger=DirtyFlagTrigger.Animated)] public readonly Slot<float> Cover=new();
    [Output(Guid="aba0ed96-12fe-58c3-94ab-b2023bc3af0f", DirtyFlagTrigger=DirtyFlagTrigger.Animated)] public readonly Slot<Vector4> CoverColor=new();
    [Output(Guid="47e3ef0f-581e-559e-b102-da70e103db31", DirtyFlagTrigger=DirtyFlagTrigger.Animated)] public readonly Slot<Vector3> KeyPosition=new();
    [Output(Guid="75e3772c-c360-5cec-bab8-598db34a6f1b", DirtyFlagTrigger=DirtyFlagTrigger.Animated)] public readonly Slot<Vector3> FillPosition=new();
    [Output(Guid="ed8fc4b4-c711-52fd-9c86-760de44fe8dd", DirtyFlagTrigger=DirtyFlagTrigger.Animated)] public readonly Slot<float> KeyIntensity=new();
    [Output(Guid="2a941714-b8dc-57a5-b521-d2d637dc1fba", DirtyFlagTrigger=DirtyFlagTrigger.Animated)] public readonly Slot<float> FillIntensity=new();
    [Input(Guid="0713a026-3b7b-5ddf-ac49-e585d8248fa6")] public readonly InputSlot<string> CameraDataPath=new();
    [Input(Guid="df42be73-5639-53e6-82f4-f72a9b15aba6")] public readonly InputSlot<float> OverrideTime=new();
    [Input(Guid="8e21625b-2c15-5b6c-8b42-78aa3500bf8b")] public readonly InputSlot<bool> UseOverride=new();
    [Input(Guid="9aaf2997-d503-5100-97db-9e3f19bd0e50")] public readonly InputSlot<int> ActiveWorld=new();
    [Input(Guid="70bceb8e-15a0-592f-a01b-ff73dfac2a59")] public readonly InputSlot<string> TimelineDataPath=new();
    [Input(Guid="2748faa0-a40e-5a5e-8810-1170aff75f74")] public readonly InputSlot<string> WorldStartSeconds=new();
    public BlenderCameraTimeline()
    {
        TimeSeconds.UpdateAction=Update;
        WorldIndex.UpdateAction=Update;
        ShotIndex.UpdateAction=Update;
        ShotLabel.UpdateAction=Update;
        Position.UpdateAction=Update;
        Target.UpdateAction=Update;
        Up.UpdateAction=Update;
        FieldOfView.UpdateAction=Update;
        ClipPlanes.UpdateAction=Update;
        BlurRadius.UpdateAction=Update;
        Cover.UpdateAction=Update;
        CoverColor.UpdateAction=Update;
        KeyPosition.UpdateAction=Update;
        FillPosition.UpdateAction=Update;
        KeyIntensity.UpdateAction=Update;
        FillIntensity.UpdateAction=Update;
    }
    private readonly List<Shot> _shots=new(); private readonly List<Passage> _passages=new(); private readonly List<TimeMapPoint> _timeMap=new(); private string _timelinePath=string.Empty;
    private readonly List<float> _worldStarts=new(); private string _worldStartsText=string.Empty;
    private float[] _samples=Array.Empty<float>();
    private string _path=string.Empty;
    private static float Smooth(float x) { x=Math.Clamp(x,0,1); return x*x*x*(x*(x*6-15)+10); }
    private Vector3 Vec(int index,int offset) => new(_samples[index*12+offset],_samples[index*12+offset+1],_samples[index*12+offset+2]);
    private void Update(EvaluationContext context)
    {
        var path=CameraDataPath.GetValue(context) ?? string.Empty;
        if(path!=_path)
        {
            using var stream=File.OpenRead(path); using var reader=new BinaryReader(stream);
            int count=reader.ReadInt32(); if(count<2 || count>1000000)throw new InvalidDataException("Invalid Blender camera sample count");
            _samples=new float[count*12]; for(int i=0;i<_samples.Length;i++)_samples[i]=reader.ReadSingle(); _path=path;
        }
        var timelinePath=TimelineDataPath.GetValue(context)??string.Empty;
        if(timelinePath!=_timelinePath){LoadTimeline(timelinePath);_timelinePath=timelinePath;}
        var worldStartsText=WorldStartSeconds.GetValue(context)??string.Empty;
        if(worldStartsText!=_worldStartsText)
        {
            _worldStarts.Clear();
            foreach(var token in worldStartsText.Split(',',StringSplitOptions.RemoveEmptyEntries))
                if(float.TryParse(token,NumberStyles.Float,CultureInfo.InvariantCulture,out var start))_worldStarts.Add(start);
            _worldStartsText=worldStartsText;
        }
        float outputTime=Math.Max(0,UseOverride.GetValue(context)?OverrideTime.GetValue(context):(float)(context.LocalTime*240/context.Playback.Bpm));
        float t=MapSourceTime(outputTime);
        int shot=0; while(shot+1<_shots.Count && t>=_shots[shot+1].Start)shot++;
        TimeSeconds.Value=t; ShotIndex.Value=_shots.Count==0?0:_shots[shot].Id; ShotLabel.Value=_shots.Count==0?string.Empty:_shots[shot].Label;
        var worldIndex=ActiveWorld.GetValue(context);
        if(_worldStarts.Count>0)
        {
            worldIndex=0;
            while(worldIndex+1<_worldStarts.Count && t>=_worldStarts[worldIndex+1])worldIndex++;
        }
        WorldIndex.Value=worldIndex;
        // AnimationScene holds transforms at the current 60 Hz source sample.
        // Use that same sample for the camera pose so camera-parented meshes
        // (including HUD geometry) cannot slide during live playback.
        int countSamples=_samples.Length/12;
        int a=Math.Clamp((int)MathF.Floor(t*60+0.0001f),0,countSamples-1);
        Position.Value=Vec(a,0);
        Target.Value=Position.Value+Vector3.Normalize(Vec(a,3));
        Up.Value=Vector3.Normalize(Vec(a,6));
        FieldOfView.Value=_samples[a*12+9];
        ClipPlanes.Value=new(_samples[a*12+10],_samples[a*12+11]);
        BlurRadius.Value=0; Cover.Value=0; CoverColor.Value=Vector4.One;
        foreach(var passage in _passages)
        {
            float distance=MathF.Abs(t-passage.Time); if(distance>1.6f)continue;
            // TiXL Blur Size is percent of image width: 160 px at 960 px.
            BlurRadius.Value=(160f/9.6f)*Smooth(1-distance/1.6f); Cover.Value=Smooth((1-distance)/.92f); CoverColor.Value=passage.Color; break;
        }
        float origin=WorldIndex.Value*30;
        KeyPosition.Value=new(origin-1.5f,5.2f,3); FillPosition.Value=new(origin+4,3.8f,-1);
        KeyIntensity.Value=35; FillIntensity.Value=22;
    }
    private void LoadTimeline(string path)
    {
        _shots.Clear();_passages.Clear();_timeMap.Clear(); if(string.IsNullOrWhiteSpace(path)||!File.Exists(path))return;
        using var doc=JsonDocument.Parse(File.ReadAllText(path)); var root=doc.RootElement;
        if(root.TryGetProperty("shots",out var shots))foreach(var row in shots.EnumerateArray())_shots.Add(new Shot(row.GetProperty("id").GetInt32(),row.GetProperty("start").GetSingle(),row.GetProperty("label").GetString()??string.Empty));
        if(root.TryGetProperty("passages",out var passages))foreach(var row in passages.EnumerateArray()){var c=row.GetProperty("color");_passages.Add(new Passage(row.GetProperty("time").GetSingle(),new(c[0].GetSingle(),c[1].GetSingle(),c[2].GetSingle(),1)));}
        if(root.TryGetProperty("time_map",out var timeMap))foreach(var row in timeMap.EnumerateArray())_timeMap.Add(new TimeMapPoint(row.GetProperty("output").GetSingle(),row.GetProperty("source").GetSingle()));
    }
    private float MapSourceTime(float outputTime)
    {
        if(_timeMap.Count<2)return outputTime;
        for(int i=1;i<_timeMap.Count;i++)
        {
            var right=_timeMap[i]; if(outputTime>right.Output)continue;
            var left=_timeMap[i-1]; var fraction=(outputTime-left.Output)/(right.Output-left.Output);
            return left.Source+fraction*(right.Source-left.Source);
        }
        var last=_timeMap[^1]; return last.Source+outputTime-last.Output;
    }
    private sealed record Shot(int Id,float Start,string Label);
    private sealed record Passage(float Time,Vector4 Color);
    private sealed record TimeMapPoint(float Output,float Source);
}

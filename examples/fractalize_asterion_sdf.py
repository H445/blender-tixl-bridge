"""Stage recursive copper filaments and a wild moon fractal corona in TiXL.

Uses native CustomSDF, field material, world transform and depth-tested raymarch
operators. Static anchors were verified through Blender MCP; update them if
the source objects move. Audio, camera, source clips and surface FX are retained.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import random
import shutil
import sys
import uuid
from pathlib import Path

from anchor_asterion_sdf import CURVE, CURVE_OUT, set_value, vector
from animate_asterion_sdf_rings import CURVE_SYMBOL, CURVE_TIME, sample_curve
from install_asterion_audio import BACKUPS, DEFAULT_GRAPH, GRAPH_ID, read_graph, value
from rebalance_asterion_audio import editor_running

HELPERS = Path(__file__).with_name("advanced_spaceship") / "fractal_orbits.hlsl"
CUSTOM_OUT = "1aaaf637-a2f1-4706-909e-fa4fb102619d"
FIELD_IN = "7248c680-7279-4c1d-b968-3864cb849c77"
TRANSFORM_OUT = "9b12e766-9dcd-4c8f-83ee-2a0b78beae43"
CODE = "bde89b93-224c-4a3f-85ab-d85b0401c02a"
DEFINES = "48a0699d-1207-4e18-ab9b-4da7f77cc7aa"
PARAMS = ("3c366d34-c398-410e-972b-d8cc2baffddb",
          "874ae9c8-5835-4d0c-9bef-253ac75d19b2",
          "56e5d5ec-ec59-4ea0-85c1-1eca3dcb5790")

COPPER_CODE = """p -= Offset;
float bounds = length(p) - 1.20;
if (bounds > 0.02) return bounds;
float angle = atan2(p.z, p.x);
float d0 = asterionFractalOrbit(p, .81, .040 + C, A, 3, .040 + .035*B, 3*sin(A));
float d1 = asterionFractalOrbit(p, .925, .030 + .025*B, -A, 5, .055, 2*cos(2*A));
d1 = max(d1, .055*(sin(3*angle+6*A)-(.4+.4*B)));
float d2 = asterionFractalOrbit(p, 1.055, .022 + .022*(1-B), 2*A, 2, .050, 3*sin(3*A));
d2 = max(d2, .050*(sin(6*angle-5*A)-(.4+.3*cos(A))));
return .50 * min(d0, min(d1, d2));
"""

MOON_CODE = """p -= Offset;
float bounds = length(p) - 1.50;
if (bounds > .02) return bounds;
A += 1.7;
float breathing = .035*sin(4*A) + 2*C;
float d0 = asterionFractalOrbit(p, .84+breathing, .055+2*C, A, 5, .06+.05*B, 4*sin(3*A));
float3 q1 = asterionRotateX(p, 1.0+.20*sin(2*A));
float d1 = asterionFractalOrbit(q1, 1.03+breathing, .045+.035*B, -2*A, 7, .065, 4*cos(5*A));
float3 q2 = asterionRotateZ(p, -1.0+.24*cos(3*A));
float d2 = asterionFractalOrbit(q2, 1.15-breathing, .040+.030*(1-B), 3*A, 3, .085, 3*sin(7*A));
float3 q3 = asterionRotateZ(asterionRotateX(p, .65), .8);
float d3 = asterionFractalOrbit(q3, 1.32, .022+C, -A, 9, .035, 5*cos(4*A));
// Fourteen moving Menger knots orbit between the interlocking filaments.
float angle = atan2(p.z,p.x) + 2*A;
float sector = 6.283185307/14;
float folded = angle - sector*floor((angle+sector/2)/sector);
float radial = length(p.xz);
float3 bud = float3(radial*cos(folded)-(1.09+breathing),
                    p.y-.09*sin(3*A), radial*sin(folded));
float budScale = .085 + .040*B + C;
float knots = asterionMenger(bud/budScale)*budScale;
return .45 * min(min(d0,d1),min(min(d2,d3),knots));
"""


def fit_branch(graph, ui, added, consumer):
    """Place new nodes from their connections; keep the user's old positions."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
    from connected_graph_layout import count_wire_crossings
    by = {v['ChildId']: v for v in ui['SymbolChildUis']}
    ids = set(added)
    incoming = {i: [] for i in added}
    for e in graph['Connections']:
        if e['TargetParentOrChildId'] in ids and e['SourceParentOrChildId'] in ids:
            incoming[e['TargetParentOrChildId']].append(e['SourceParentOrChildId'])
    levels = {}
    def level(i):
        if i not in levels:
            levels[i] = max((level(p)+1 for p in incoming[i]), default=0)
        return levels[i]
    for i in added:
        level(i)
    last = max(levels.values())
    anchor = by[consumer]['Position']
    old = [v['Position'] for i,v in by.items() if i not in ids]
    best = None
    for dx in (420, 840, 1260):
        for step in range(-30,31):
            center = anchor['Y'] + 210*step
            positions = {}
            for layer in range(last+1):
                lane = [i for i in added if levels[i] == layer]
                for row,i in enumerate(lane):
                    positions[i] = vector(anchor['X']-dx-(last-layer)*420,
                                          center+(row-(len(lane)-1)/2)*300)
            if any(abs(p['X']-o['X'])<260 and abs(p['Y']-o['Y'])<180
                   for p in positions.values() for o in old):
                continue
            for i,p in positions.items():
                by[i]['Position'] = p
            score = count_wire_crossings(graph,ui), abs(step), dx
            if best is None or score < best[0]:
                best = score, positions
    if best is None:
        raise ValueError('No clear space for the fractal branch')
    for i,p in best[1].items():
        by[i]['Position'] = p


def prepare(graph, ui):
    if graph['Id'] != GRAPH_ID or ui['Id'] != GRAPH_ID:
        raise ValueError('Expected Asterion Home')
    names = {v['Name']: v for v in graph['Children']}
    if 'Moon SDF | fractal corona' in names:
        raise ValueError('Fractal pass already installed; preserve editor changes')
    added = []
    edges = graph['Connections']
    def link(a, output, b, slot):
        edges.append(dict(SourceParentOrChildId=a['Id'],SourceSlotId=output.lower(),
                          TargetParentOrChildId=b['Id'],TargetSlotId=slot.lower()))
    def add(name, symbol, symbol_name, inputs=()):
        v = dict(Id=str(uuid.uuid5(uuid.NAMESPACE_URL, GRAPH_ID+'/moon-fractal/'+name)),
                 SymbolId=symbol,SymbolName=symbol_name,Name='Moon SDF | '+name,
                 InputValues=list(inputs),Outputs=[])
        graph['Children'].append(v);added.append(v['Id'])
        ui['SymbolChildUis'].append(dict(ChildId=v['Id'],Position=vector(9000,-300*len(ui['SymbolChildUis']))))
        return v
    helpers = HELPERS.read_text(encoding='utf-8')
    copper = names['Copper SDF | braided orbital ribbons']
    set_value(copper,CODE,'System.String',COPPER_CODE)
    set_value(copper,DEFINES,'System.String',helpers)
    set_value(names['Copper SDF | depth-tested atmospheric contour'],
              'f14e7a2f-cd4e-4399-b137-ea0b87c7dfbd','System.Single',.035)
    set_value(names['Copper SDF | depth-tested atmospheric contour'],
              '9715075b-b02b-4290-9332-9bbfe67933f2','System.Numerics.Vector4',vector(.18,1.15,.82,1))
    field = add('fractal corona',copper['SymbolId'],copper['SymbolName'],
                [value(CODE,'System.String',MOON_CODE),value(DEFINES,'System.String',helpers)])
    rng = random.Random(445+1701)
    keys = [(0,.70)]+[(t,rng.uniform(.18,.96)) for t in range(3,108,3)]+[(108,.70)]
    morph = add('wild morphology',CURVE_SYMBOL,'Lib.numbers.curve.SampleCurve',
                [value(CURVE,'T3.Core.DataTypes.Curve',sample_curve(keys))])
    link(names['Main / clip to scene time'],'c1dbdb9e-a7ad-424b-b2ba-94bd9ce71daf',morph,CURVE_TIME)
    for control,slot in ((names['Copper SDF | orbital phase'],PARAMS[0]),
                         (morph,PARAMS[1]),(names['Copper SDF | 120 BPM filament surges'],PARAMS[2])):
        link(control,CURVE_OUT,field,slot)
    color = add('moving magenta cyan cells','edfc71fc-2d54-4226-b819-0340bb1fdd65',
                'Lib.field.generate.texture.Raster3dField',
                [value('d3d51c3c-9dd7-4f9b-849d-59e94abff605','System.Numerics.Vector4',vector(.95,.05,.72,1)),
                 value('21092a7f-01b8-47b4-ba37-c0b1dc6affc4','System.Numerics.Vector4',vector(.035,.90,1.25,1)),
                 value('9b324ca4-2116-489d-a829-8348a9984235','System.Numerics.Vector3',vector(.17,.17,.17)),
                 value('1108ec25-8d77-4c0b-8f17-5308ea017df4','System.Single',.045)])
    link(morph,CURVE_OUT,color,'606584e3-2c4a-432f-a7a4-c3093a34685e')
    link(names['Techno | SDF fluid noise travel'],'aedaead8-ccf0-43f0-9188-a79af8d45250',color,
         '3938188b-41ba-4efe-b7e1-9720d2e58cd4')
    material = add('fractal material','88926602-4694-4632-9fd7-04c8d6ddd728','Lib.field.adjust.SetSDFMaterial',
                   [value('d2a64234-c7ef-424b-822c-addce0b84e69','System.Numerics.Vector4',vector(1,1,1,1))])
    link(field,CUSTOM_OUT,material,'7c656067-ef12-4990-b094-7f8160a242d1')
    link(color,'096ef8a1-c5bb-4cc1-a4a9-fdc8ab1214ae',material,'93d0ee54-b2f6-41ea-bbaa-ef06bca1f1a0')
    anchor = add('moon world anchor','c44d23c7-bfac-403d-b49e-49d00001a316','Lib.field.space.TransformField',
                 [value('3b817e6c-f532-4a8c-a2ff-a00dc926eeb2','System.Numerics.Vector3',vector(65,-40,-185)),
                  value('5339862d-5a18-4d0c-b908-9277f5997563','System.Numerics.Vector3',vector(-27,22,8)),
                  value('58b9dfb6-0596-4f0d-baf6-7fb3ae426c94','System.Numerics.Vector3',vector(1,1,1)),
                  value('566f1619-1de0-4b41-b167-7fc261730d62','System.Single',30)])
    link(material,'51c8b9dd-9798-44e6-a9d0-0baecfc9c9a5',anchor,FIELD_IN)
    original_ray=names['Copper SDF | depth-tested atmospheric contour']
    ray=add('depth-tested fractal glow',original_ray['SymbolId'],original_ray['SymbolName'],
            copy.deepcopy(original_ray['InputValues']))
    set_value(ray,'9715075b-b02b-4290-9332-9bbfe67933f2','System.Numerics.Vector4',vector(1.1,1.1,1.1,1))
    set_value(ray,'e3a85c27-b94c-4e77-b0c2-4644cd3a22d4','System.Numerics.Vector4',vector(.15,.04,.22,.3))
    set_value(ray,'3148d927-8779-47ab-9e0a-fa63206f3002','System.Single',280)
    set_value(ray,'f14e7a2f-cd4e-4399-b137-ea0b87c7dfbd','System.Single',.025)
    set_value(ray,'0b4d60de-261f-4dbf-ad44-6395cda3a496','System.Single',.012)
    link(anchor,TRANSFORM_OUT,ray,'340ca675-9356-4548-ba64-732181bebeef')
    link(ray,'e178ef02-c9ac-48cd-a8cb-df3aec5941bb',names['Main / scene'],
         '9e961f73-1ee7-4369-9ac7-5c653e570b6f')
    ids={c['Id'] for c in graph['Children']}
    assert len(ids)==len(graph['Children'])
    assert all(e[k] in ids for e in edges for k in ('SourceParentOrChildId','TargetParentOrChildId'))
    fit_branch(graph,ui,added,names['Main / scene']['Id'])
    return graph,ui


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--graph',type=Path,default=DEFAULT_GRAPH)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--ui-output',type=Path,required=True)
    parser.add_argument('--apply',action='store_true')
    args=parser.parse_args()
    graph,ui=prepare(read_graph(args.graph),read_graph(args.graph.with_suffix('.t3ui')))
    if not args.apply:
        for p,data in ((args.output,graph),(args.ui_output,ui)):
            if any(x.lower()=='symbols' for x in p.resolve().parts):
                raise ValueError('Stage outside Symbols')
            p.parent.mkdir(parents=True,exist_ok=True)
            p.write_text(json.dumps(data,indent=2)+'\n',encoding='utf-8')
    else:
        if editor_running():raise RuntimeError('Close a saved editor through its bridge first')
        if read_graph(args.output)!=graph or read_graph(args.ui_output)!=ui:
            raise ValueError('Staged data differ from the planned update')
        BACKUPS.mkdir(parents=True,exist_ok=True)
        for dest,staged in ((args.graph,args.output),(args.graph.with_suffix('.t3ui'),args.ui_output)):
            backup=BACKUPS/(dest.stem+'-before-fractal-sdf-'+hashlib.sha256(dest.read_bytes()).hexdigest()[:12]+dest.suffix)
            if not backup.exists():shutil.copy2(dest,backup)
            incoming=dest.with_name(dest.name+'.incoming');shutil.copy2(staged,incoming);os.replace(incoming,dest)
    print(json.dumps(dict(children=len(graph['Children']),connections=len(graph['Connections']),installed=args.apply)))


if __name__=='__main__':main()

"""Adapter to the shared sampled-geometry contract; never imports editable designs."""
import math
from core import validate,geometry,digest,VERSION
import meridional
from turbomachinery_common import build,canonical_point


def export_geometry(raw,stage_index=0,row_index=1):
    d=validate(raw)
    if type(stage_index) is not int or type(row_index) is not int or not 0<=stage_index<len(d['stages']) or row_index not in (0,1):
        raise ValueError('翼列の指定が不正です。')
    row=d['stages'][stage_index]['rows'][row_index];mesh=geometry(d,stage_index,row_index);curves=[]
    for layer in mesh['layers']:
        for side_index,side in enumerate(layer['sides']):
            points=[]
            for i,(x,y) in enumerate(side):
                if 'world_sides' in layer:
                    wx,wy,wz=layer['world_sides'][side_index][i];r=math.hypot(wy,wz);x=wx
                else:r=layer['radius']
                points.append(canonical_point('turbine_x_m_phi',x,r,y/r))
            curves.append({'id':f'main:{layer["span"]:.17g}:{side_index}','group':'main','span':layer['span'],
                           'role':'A' if side_index==0 else 'B','points':points})
    if d['meridional']['enabled']:
        samples=meridional.report(d)['samples']
        wall_points={name:[[p['x'],p[key],0.] for p in samples] for name,key in [('hub','hub_radius'),('casing','casing_radius')]}
    else:
        xs=[p[0] for layer in mesh['layers'] for side in layer['sides'] for p in side];a,b=min(xs),max(xs)
        wall_points={name:[[a,d['geometry'][key],0.],[b,d['geometry'][key],0.]] for name,key in [('hub','hub_radius'),('casing','tip_radius')]}
    for name,points in wall_points.items():
        curves.append({'id':name,'group':name,'span':None,'role':'wall',
                       'points':[canonical_point('turbine_x_m_phi',*p) for p in points]})
    source={'app':'axial_turbine_designer','app_version':VERSION,'snapshot_hash':digest(d),
            'coordinate_frame':'turbine_x_m_phi','angle_reference':'local axial +x toward tangential +y; degrees',
            'angle_frame':'stator absolute / rotor relative metal angles; not converted',
            'span_definition':'geometric radial fraction at each axial position; hub=0 casing=1',
            'rotation_sign':-1,'surface_labels':'A/B fixed geometry IDs; pressure-side intent is not CFD pressure'}
    return build(source,[{'id':row['id'],'name':f'第{stage_index+1}段 {row["kind"]}','kind':'rotating' if row['kind']=='rotor' else 'stationary',
                          'source_kind':row['kind'],'blade_count':row['blade_count'],'curves':curves}])

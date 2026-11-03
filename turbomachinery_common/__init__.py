"""Versioned, dependency-free sampled geometry exchange for turbomachinery apps."""
import copy
import hashlib
import json
import math

VERSION = '0.1.0'
FORMAT = 'turbomachinery-geometry'
COORDINATES = {'length_unit':'m','angle_unit':'rad','rotation_axis':'Z',
               'theta_zero':'+X','theta_positive':'right_hand_about_positive_Z'}
FRAMES = ('compressor_z_mm_ccw','turbine_x_m_phi')
MAX_BYTES = 32*1024*1024


def digest(value):
    # JSON/JavaScript may re-emit 1.0 as 1 or -0.0 as 0. Hash numeric values,
    # not their source spelling. All accepted integers fit exactly in binary64.
    def normalized(item):
        if type(item) in (int,float):
            if not math.isfinite(item):raise ValueError('Nonfinite hash value.')
            return {'$binary64':float(item if item else 0.).hex()}
        if isinstance(item,dict):return {key:normalized(v) for key,v in item.items()}
        if isinstance(item,list):return [normalized(v) for v in item]
        return item
    return hashlib.sha256(json.dumps(normalized(value),ensure_ascii=False,sort_keys=True,allow_nan=False,separators=(',',':')).encode('utf-8')).hexdigest()


def _number(x,lo,hi):
    if type(x) not in (int,float) or not math.isfinite(x) or not lo<=x<=hi:
        raise ValueError('Expected a finite number in the exchange range.')
    return x


def canonical_point(frame,axial,radius,theta):
    """Do not wrap continuous theta. Turbine XYZ -> canonical (-Z,Y,X)."""
    _number(axial,-1e6,1e6);_number(radius,0,1e6);_number(theta,-1e9,1e9)
    if frame=='compressor_z_mm_ccw':return [axial*.001,radius*.001,theta]
    if frame=='turbine_x_m_phi':return [axial,radius,math.pi-theta]
    raise ValueError('Unknown source coordinate frame.')


def source_point(frame,point):
    axial,radius,theta=point
    _number(axial,-1000,1000);_number(radius,0,1000);_number(theta,-1e9,1e9)
    if frame=='compressor_z_mm_ccw':return [axial*1000,radius*1000,theta]
    if frame=='turbine_x_m_phi':return [axial,radius,math.pi-theta]
    raise ValueError('Unknown source coordinate frame.')


def cartesian(point):
    axial,radius,theta=point
    return [radius*math.cos(theta),radius*math.sin(theta),axial]


def _keys(value,keys,label):
    if not isinstance(value,dict) or set(value)!=set(keys):raise ValueError('Invalid '+label+' fields.')


def _text(value):
    if not isinstance(value,str) or not value.strip() or len(value)>500:raise ValueError('Expected a nonempty bounded identifier or description.')


def _hash(value):
    if not isinstance(value,str) or len(value)!=64 or any(c not in '0123456789abcdef' for c in value):raise ValueError('Invalid SHA-256.')


def validate(doc):
    _keys(doc,('format','schema_version','library_version','hash_encoding','coordinates','source','rows','content_hash'),'document')
    if doc['format']!=FORMAT or type(doc['schema_version']) is not int or doc['schema_version']!=1 or doc['library_version']!=VERSION:
        raise ValueError('Unsupported common geometry format/version.')
    if doc['coordinates']!=COORDINATES:raise ValueError('Unexpected canonical coordinate conventions.')
    if doc['hash_encoding']!='binary64-hex-json-v1':raise ValueError('Unknown hash encoding.')
    source=doc['source']
    _keys(source,('app','app_version','snapshot_hash','coordinate_frame','angle_reference','angle_frame','span_definition','rotation_sign','surface_labels'),'source')
    for key in ('app','app_version','angle_reference','angle_frame','span_definition','surface_labels'):_text(source[key])
    _hash(source['snapshot_hash'])
    if source['coordinate_frame'] not in FRAMES or type(source['rotation_sign']) is not int or source['rotation_sign'] not in (-1,1):raise ValueError('Invalid coordinate frame/rotation sign.')
    if not isinstance(doc['rows'],list) or not 1<=len(doc['rows'])<=128:raise ValueError('Expected 1..128 rows.')
    row_ids=set();total=0
    for row in doc['rows']:
        _keys(row,('id','name','kind','source_kind','blade_count','curves'),'row')
        for key in ('id','name','source_kind'):_text(row[key])
        if row['id'] in row_ids:raise ValueError('Duplicate row ID.')
        row_ids.add(row['id'])
        if row['kind'] not in ('rotating','stationary'):raise ValueError('Unknown row kind.')
        if type(row['blade_count']) is not int or not 1<=row['blade_count']<=10000:raise ValueError('Invalid blade count.')
        if not isinstance(row['curves'],list) or not 1<=len(row['curves'])<=1024:raise ValueError('Invalid curve count.')
        curve_ids=set()
        for curve in row['curves']:
            _keys(curve,('id','group','span','role','points'),'curve');_text(curve['id'])
            if curve['id'] in curve_ids:raise ValueError('Duplicate curve ID.')
            curve_ids.add(curve['id'])
            if curve['group'] not in ('main','splitter','hub','casing','analysis_casing'):raise ValueError('Unknown curve group.')
            if curve['role'] not in ('A','B','LE','PS','TE','SS','wall'):raise ValueError('Unknown curve role.')
            wall=curve['group'] in ('hub','casing','analysis_casing')
            if wall:
                if curve['span'] is not None or curve['role']!='wall':raise ValueError('Walls have no blade span and use role=wall.')
            else:
                _number(curve['span'],0,1)
                if curve['role']=='wall':raise ValueError('Blade curves cannot use role=wall.')
            points=curve['points']
            if not isinstance(points,list) or not 2<=len(points)<=20000:raise ValueError('Invalid point count.')
            total+=len(points)
            if total>2000000:raise ValueError('Geometry point budget exceeded.')
            for point in points:
                if not isinstance(point,list) or len(point)!=3:raise ValueError('Expected [axial_m,radius_m,theta_rad].')
                _number(point[0],-1000,1000);_number(point[1],0,1000);_number(point[2],-1e9,1e9)
    _hash(doc['content_hash'])
    if doc['content_hash']!=digest({k:v for k,v in doc.items() if k!='content_hash'}):raise ValueError('Common geometry content hash mismatch.')
    return doc


def build(source,rows):
    doc={'format':FORMAT,'schema_version':1,'library_version':VERSION,'hash_encoding':'binary64-hex-json-v1','coordinates':copy.deepcopy(COORDINATES),
         'source':copy.deepcopy(source),'rows':copy.deepcopy(rows)}
    doc['content_hash']=digest(doc)
    return validate(doc)


def dumps(doc):
    validate(doc);text=json.dumps(doc,ensure_ascii=False,allow_nan=False,indent=2)+'\n'
    if len(text.encode('utf-8'))>MAX_BYTES:raise ValueError('Exchange JSON exceeds 32 MiB.')
    return text


def loads(text):
    if not isinstance(text,(str,bytes)) or len(text if isinstance(text,bytes) else text.encode('utf-8'))>MAX_BYTES:raise ValueError('Invalid or oversized exchange JSON.')
    def pairs(items):
        out={}
        for key,value in items:
            if key in out:raise ValueError('Duplicate JSON key: '+key)
            out[key]=value
        return out
    def constant(value):raise ValueError('Nonfinite JSON constant: '+value)
    try:doc=json.loads(text,object_pairs_hook=pairs,parse_constant=constant)
    except (RecursionError,UnicodeError) as exc:raise ValueError('Invalid exchange JSON encoding/nesting.') from exc
    return validate(doc)


def summary(doc):
    validate(doc)
    return {'format':FORMAT,'source_app':doc['source']['app'],'source_snapshot_hash':doc['source']['snapshot_hash'],
            'content_hash':doc['content_hash'],'rows':len(doc['rows']),
            'curves':sum(len(row['curves']) for row in doc['rows']),
            'points':sum(len(c['points']) for row in doc['rows'] for c in row['curves']),
            'status':'sampled_geometry_integrity_checked','editable_design_import':False,'cfd_validation':'not_performed'}

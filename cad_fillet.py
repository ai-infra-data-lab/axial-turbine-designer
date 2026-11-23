"""Build the short endwall rings and blend their junctions with the blade."""
from OCP.BRepAlgoAPI import BRepAlgoAPI_Fuse
from OCP.BRepBuilderAPI import (
    BRepBuilderAPI_GTransform, BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakeFace, BRepBuilderAPI_MakeWire,
)
from OCP.BRepFilletAPI import BRepFilletAPI_MakeFillet
from OCP.BRepPrimAPI import BRepPrimAPI_MakeRevol
from OCP.collections import Array1_gp_Pnt, List_TopoDS_Shape
from OCP.Geom import Geom_BezierCurve
from OCP.gp import gp_Ax1, gp_Ax2, gp_Dir, gp_GTrsf, gp_Pnt
from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE, TopAbs_SOLID
from OCP.TopExp import TopExp_Explorer
from OCP.TopoDS import TopoDS


def subshapes(shape, kind):
    explorer = TopExp_Explorer(shape, kind)
    while explorer.More():
        yield explorer.Current()
        explorer.Next()


def profile_edge(points, offset=0):
    # Start the revolution opposite the blade so the ring seam stays clear of the junction.
    poles = [gp_Pnt(x, 0, -(r + offset)) for x, r in points]
    if len(poles) == 2:
        return BRepBuilderAPI_MakeEdge(*poles).Edge()
    array = Array1_gp_Pnt(1, len(poles))
    for i, point in enumerate(poles, 1):
        array.SetValue(i, point)
    return BRepBuilderAPI_MakeEdge(Geom_BezierCurve(array)).Edge()


def endwall(profile, offset):
    inner_flow = [profile_edge(segment) for segment in profile]
    backing = [profile_edge(segment[::-1], offset) for segment in reversed(profile)]
    x0, r0 = profile[0][0]
    x1, r1 = profile[-1][-1]
    wire = BRepBuilderAPI_MakeWire()
    for edge in (*inner_flow, profile_edge([(x1, r1), (x1, r1 + offset)]),
                 *backing, profile_edge([(x0, r0 + offset), (x0, r0)])):
        wire.Add(edge)
    if not wire.IsDone():
        raise ValueError('接合部の断面を閉じることができませんでした。')
    face = BRepBuilderAPI_MakeFace(wire.Wire(), True)
    if not face.IsDone():
        raise ValueError('接合部の断面を作成できませんでした。')
    ring = BRepPrimAPI_MakeRevol(face.Face(), gp_Ax1(gp_Pnt(), gp_Dir(1, 0, 0)), True)
    if not ring.IsDone():
        raise ValueError('接合部の回転ソリッドを作成できませんでした。')
    flow = [sub for edge in inner_flow for sub in ring.Generated(edge)]
    other = [face for face in subshapes(ring.Shape(), TopAbs_FACE)
             if not any(face.IsSame(item) for item in flow)]
    return ring.Shape(), flow, other


def junction_edges(fuse, ring_faces, blade):
    def descendants(faces):
        output = []
        for face in faces:
            output.extend(fuse.Modified(face))
            if not fuse.IsDeleted(face):
                output.append(face)
        return output

    result_faces = list(subshapes(fuse.Shape(), TopAbs_FACE))
    wall = descendants(ring_faces)
    wing = descendants(subshapes(blade, TopAbs_FACE))
    wall_edges = [edge for f in result_faces if any(f.IsSame(w) for w in wall)
                  for edge in subshapes(f, TopAbs_EDGE)]
    roots = []
    for f in result_faces:
        if any(f.IsSame(w) for w in wing):
            for edge in subshapes(f, TopAbs_EDGE):
                if any(edge.IsSame(w) for w in wall_edges) and not any(edge.IsSame(old) for old in roots):
                    roots.append(TopoDS.Edge(edge))
    return roots


def build_blends(shape, groups):
    builder = BRepFilletAPI_MakeFillet(shape)
    for label, radius, _, roots in groups:
        for edge in roots:
            builder.Add(radius, edge)
        if not all(builder.Contour(edge) for edge in roots):
            raise ValueError(f'{label}のフィレットを作る境界を特定できませんでした。')
    builder.Build()
    if not builder.IsDone() or not builder.NbSurfaces():
        raise ValueError('指定寸法でフィレットが成立しませんでした。')
    faces = list(subshapes(builder.Shape(), TopAbs_FACE))
    for label, _, _, roots in groups:
        if not any(generated.IsSame(face) for edge in roots for generated in builder.Generated(edge) for face in faces):
            raise ValueError(f'{label}に生成されたフィレット面を確認できませんでした。')
    return builder


def radial_affinity(radial_yz, scale):
    affinity = gp_GTrsf()
    affinity.SetAffinity(gp_Ax2(gp_Pnt(), gp_Dir(0, *radial_yz)), scale)
    return affinity


def map_roots(groups, transform):
    return [(label, radius, ratio, [TopoDS.Edge(transform.ModifiedShape(edge)) for edge in roots])
            for label, radius, ratio, roots in groups]


def blend_in_frames(shape, groups, radial_yz):
    # Each group is round in its own normalized frame. Move directly between
    # those frames and restore the original supports at the end.
    active_ratio = 1.
    for ratio in sorted({group[2] for group in groups}, key=lambda ratio: (ratio != 1, ratio)):
        if ratio != active_ratio:
            frame = BRepBuilderAPI_GTransform(shape, radial_affinity(radial_yz, active_ratio / ratio), True)
            shape, groups = frame.Shape(), map_roots(groups, frame)
            active_ratio = ratio
        current = [group for group in groups if group[2] == ratio]
        builder = build_blends(shape, current)
        shape = builder.Shape()
        pending = []
        result_edges = list(subshapes(shape, TopAbs_EDGE))
        for label, radius, next_ratio, roots in groups:
            if next_ratio == ratio:
                continue
            updated = []
            for edge in roots:
                candidates = [edge, *builder.Modified(edge)]
                matches = [item for item in result_edges if any(item.IsSame(e) for e in candidates)]
                if not matches:
                    raise ValueError(f'{label}の接合線をフィレット処理後に取得できませんでした。')
                for match in matches:
                    if not any(match.IsSame(e) for e in updated):
                        updated.append(TopoDS.Edge(match))
            pending.append((label, radius, next_ratio, updated))
        groups = pending
    if active_ratio != 1:
        shape = BRepBuilderAPI_GTransform(shape, radial_affinity(radial_yz, active_ratio), True).Shape()
    return shape


def blend_junctions(blade, fillets, radial_yz=None):
    walls = []
    tools = List_TopoDS_Shape()
    arguments = List_TopoDS_Shape()
    arguments.Append(blade)
    labels = []
    try:
        for side, settings in fillets.items():
            label = 'ハブ側' if side == 'hub' else 'チップ側'
            radius = settings['radius_mm']
            ratio = settings.get('radial_ratio', 1.)
            suffix = f' 楕円 比{ratio:g}' if ratio != 1 else ''
            labels.append(f'{label} R{radius:g} mm{suffix}')
            offset = settings['wall_mm'] * (-1 if side == 'hub' else 1)
            ring, flow_faces, other_faces = endwall(settings['wall_profile'], offset)
            tools.Append(ring)
            walls.append((label, radius, ratio, flow_faces, other_faces))
        fuse = BRepAlgoAPI_Fuse()
        fuse.SetArguments(arguments)
        fuse.SetTools(tools)
        fuse.Build()
        if not fuse.IsDone() or len(list(subshapes(fuse.Shape(), TopAbs_SOLID))) != 1:
            raise ValueError('翼と接合部を一つのソリッドに結合できませんでした。')
        groups = []
        for label, radius, ratio, flow_faces, other_faces in walls:
            if junction_edges(fuse, other_faces, blade):
                raise ValueError(f'{label}の翼が接合部の裏面または端面まで貫通しています。')
            roots = junction_edges(fuse, flow_faces, blade)
            if not roots:
                raise ValueError(f'{label}の翼と流路壁の境界を特定できませんでした。')
            groups.append((label, radius, ratio, roots))
        return blend_in_frames(fuse.Shape(), groups, radial_yz)
    except Exception as exc:
        raise ValueError(f'{"・".join(labels)}の接合部を作成できませんでした。{exc}') from None

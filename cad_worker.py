"""Build and verify a single blade STEP solid with the optional OCCT runtime."""
import json
import math
from pathlib import Path
import sys

import numpy as np
from scipy.interpolate import make_interp_spline
from OCP.Bnd import Bnd_Box
from OCP.BRep import BRep_Tool
from OCP.BRepAlgoAPI import BRepAlgoAPI_Check
from OCP.BRepBndLib import BRepBndLib
from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace, BRepBuilderAPI_MakeSolid, BRepBuilderAPI_Sewing
from OCP.BRepCheck import BRepCheck_Analyzer
from OCP.BRepGProp import BRepGProp
from OCP.BRepLib import BRepLib
from OCP.collections import Array1_double, Array1_int, Array2_gp_Pnt, Sequence_TCollection_AsciiString
from OCP.Geom import Geom_BSplineSurface
from OCP.GProp import GProp_GProps
from OCP.gp import gp_Pnt
from OCP.IFSelect import IFSelect_RetDone
from OCP.Interface import Interface_Static
from OCP.STEPControl import STEPControl_ManifoldSolidBrep, STEPControl_Reader, STEPControl_Writer
from OCP.TopAbs import TopAbs_EDGE, TopAbs_SHELL, TopAbs_SOLID
from OCP.TopExp import TopExp_Explorer
from OCP.TopoDS import TopoDS


TOLERANCE_MM = 0.0001


def surface(poles, u_sequence, v_sequence, u_degree, v_degree):
    def knots(sequence):
        values, counts = np.unique(sequence, return_counts=True)
        numbers = Array1_double(1, len(values))
        multiplicities = Array1_int(1, len(values))
        for i, (value, count) in enumerate(zip(values, counts, strict=True), 1):
            numbers.SetValue(i, float(value))
            multiplicities.SetValue(i, int(count))
        return numbers, multiplicities

    points = Array2_gp_Pnt(1, poles.shape[0], 1, poles.shape[1])
    for i, column in enumerate(poles, 1):
        for j, p in enumerate(column, 1):
            points.SetValue(i, j, gp_Pnt(*map(float, p)))
    u_knots, u_multiplicities = knots(u_sequence)
    v_knots, v_multiplicities = knots(v_sequence)
    return Geom_BSplineSurface(points, u_knots, v_knots, u_multiplicities, v_multiplicities,
                               u_degree, v_degree)


def subshapes(shape, kind):
    explorer = TopExp_Explorer(shape, kind)
    while explorer.More():
        yield explorer.Current()
        explorer.Next()


def solid_from_sections(spans, points_mm):
    a, b = points_mm[:, 0], points_mm[:, 1]
    if np.max(np.linalg.norm(a[:, 0] - b[:, 0], axis=1)) > 1e-6:
        raise ValueError('両面の前縁が一致しません。断面の前縁設定を確認してください。')
    a[:, 0] = b[:, 0] = (a[:, 0] + b[:, 0]) / 2
    sharp = np.linalg.norm(a[:, -1] - b[:, -1], axis=1) <= 1e-6
    if np.any(sharp) and not np.all(sharp):
        raise ValueError('後縁の厚みがゼロの断面と有限厚の断面が混在しています。後縁設定を確認してください。')
    if np.all(sharp):
        a[:, -1] = b[:, -1] = (a[:, -1] + b[:, -1]) / 2

    chord = np.linspace(0, 1, a.shape[1])
    chord_fit = [make_interp_spline(chord, samples.transpose(1, 0, 2), k=3) for samples in (a, b)]
    span_fit = [make_interp_spline(spans, fit.c.transpose(1, 0, 2), k=3) for fit in chord_fit]
    first, second = (fit.c.transpose(1, 0, 2) for fit in span_fit)
    u_sequence, v_sequence = chord_fit[0].t, span_fit[0].t
    linear = [0, 0, 1, 1]
    faces = [surface(poles, u_sequence, v_sequence, 3, 3) for poles in (first, second)]
    # Caps use the corresponding A/B curve with the exact boundary poles.
    # A collapsed leading or sharp trailing boundary becomes a degenerate edge.
    for end in (0, -1):
        faces.append(surface(np.stack((first[:, end], second[:, end]), axis=1), u_sequence, linear, 3, 1))
    if not np.all(sharp):
        faces.append(surface(np.stack((first[-1], second[-1]), axis=1), v_sequence, linear, 3, 1))

    sewing = BRepBuilderAPI_Sewing(TOLERANCE_MM)
    for patch in faces:
        builder = BRepBuilderAPI_MakeFace(patch, 1e-6)
        if not builder.IsDone():
            raise ValueError('翼面または端面の作成に失敗しました。')
        sewing.Add(builder.Face())
    sewing.Perform()
    shells = list(subshapes(sewing.SewedShape(), TopAbs_SHELL))
    if len(shells) != 1 or sewing.NbFreeEdges() or sewing.NbMultipleEdges():
        raise ValueError('翼面を一つの閉じたシェルに接続できませんでした。')
    solid = BRepBuilderAPI_MakeSolid(TopoDS.Shell(shells[0])).Solid()
    if not BRepLib.OrientClosedSolid_s(solid):
        raise ValueError('閉じた翼の実体を構成できませんでした。')
    return solid


def inspect_solid(shape):
    shells = list(subshapes(shape, TopAbs_SHELL))
    if (len(list(subshapes(shape, TopAbs_SOLID))) != 1 or len(shells) != 1
            or not BRep_Tool.IsClosed_s(TopoDS.Shell(shells[0])) or not BRepCheck_Analyzer(shape).IsValid()):
        raise ValueError('一つの正常な閉ソリッドとして検証できませんでした。')
    checker = BRepAlgoAPI_Check()
    checker.SetData(shape, False, True)
    checker.Perform()
    if not checker.IsValid():
        raise ValueError('CADソリッドの自己干渉検査で不合格になりました。')
    tolerance = max(BRep_Tool.Tolerance_s(TopoDS.Edge(edge)) for edge in subshapes(shape, TopAbs_EDGE))
    if tolerance > TOLERANCE_MM * 2:
        raise ValueError('CADの境界許容差が上限を超えました。')
    props = GProp_GProps()
    error = BRepGProp.VolumePropertiesGK_s(shape, props, 1e-9, True, True)
    volume = props.Mass()
    if not math.isfinite(error) or not 0 <= error <= 1e-5 or not math.isfinite(volume) or volume <= 0:
        raise ValueError('翼の体積を安定して評価できませんでした。')
    box = Bnd_Box()
    BRepBndLib.AddOptimal_s(shape, box, False, False)
    lower, upper = box.CornerMin(), box.CornerMax()
    return volume, (lower.X(), lower.Y(), lower.Z(), upper.X(), upper.Y(), upper.Z())


def write_verified_step(payload, path):
    spans = np.array(payload['spans'])
    points_mm = np.array(payload['points_mm'], dtype=float)
    solid = solid_from_sections(spans, points_mm)
    volume, bounds = inspect_solid(solid)
    writer = STEPControl_Writer()
    Interface_Static.SetCVal_s('write.step.unit', 'MM')
    if writer.Transfer(solid, STEPControl_ManifoldSolidBrep) != IFSelect_RetDone or writer.Write(str(path)) != IFSelect_RetDone:
        raise ValueError('STEPファイルの書き出しに失敗しました。')

    reader = STEPControl_Reader()
    if reader.ReadFile(str(path)) != IFSelect_RetDone:
        raise ValueError('書き出したSTEPを再読込できませんでした。')
    length = Sequence_TCollection_AsciiString()
    reader.FileUnits(length, Sequence_TCollection_AsciiString(), Sequence_TCollection_AsciiString())
    if length.Length() != 1 or length.First().ToCString().lower() != 'millimetre':
        raise ValueError('STEPの長さ単位をmmとして確認できませんでした。')
    if reader.TransferRoots() != 1:
        raise ValueError('STEP再読込で一つの翼を取得できませんでした。')
    imported_volume, imported_bounds = inspect_solid(reader.OneShape())
    if (not math.isclose(volume, imported_volume, rel_tol=1e-5, abs_tol=1e-5)
            or any(abs(a - b) > TOLERANCE_MM * 10 for a, b in zip(bounds, imported_bounds, strict=True))):
        raise ValueError('STEP再読込後の体積または外接寸法が許容差を超えました。')


if __name__ == '__main__':
    job = Path(sys.argv[1])
    try:
        write_verified_step(json.loads((job/'blade.json').read_bytes()), job/'blade.step')
    except ValueError as exc:
        (job/'error.txt').write_text(str(exc), encoding='utf-8')
        sys.exit(2)

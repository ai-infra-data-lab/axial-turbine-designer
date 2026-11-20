"""Read-only meridional jets in (axial_m, radius_m); API version 1.

Parameters are metres, but axial position and meridional distance remain
distinct. Native adapters supply the evaluation law; no curve fitting occurs.
"""
import bisect
import math
from dataclasses import dataclass

API_VERSION = 1


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError('Expected a finite real number.')
    return float(value)


@dataclass(frozen=True)
class Jet:
    parameter: float
    side: str | None
    element_id: str
    position_m: tuple
    first: tuple
    second_per_m: tuple
    tangent: tuple | None
    signed_curvature_per_m: float | None


class MeridionalEvaluator:
    """Piecewise evaluator with explicit one-sided jets at interior knots.

callback(index, local_parameter_m) -> (position, first, second).
Derivatives use the declared parameter, NOT an assumed arc length.
The signed curvature is positive when the axial tangent turns toward +radius.
"""
    def __init__(self, *, curve_id, source_hash, parameter_kind, knots_m,
                 element_ids, curve_kinds, callback):
        if not isinstance(curve_id, str) or not curve_id:
            raise ValueError('A native curve identity is required.')
        if not isinstance(source_hash, str) or len(source_hash) != 64 or any(c not in '0123456789abcdef' for c in source_hash):
            raise ValueError('A source snapshot SHA-256 is required.')
        if parameter_kind not in ('axial_position_m', 'meridional_distance_m'):
            raise ValueError('Unknown parameter meaning.')
        knots = tuple(_number(v) for v in knots_m)
        ids = tuple(element_ids)
        kinds = tuple(curve_kinds)
        if len(knots) < 2 or any(b <= a for a, b in zip(knots, knots[1:])):
            raise ValueError('Strictly increasing parameter knots are required.')
        if any(not isinstance(v, str) or not v for v in ids+kinds) or not callable(callback):
            raise ValueError('Invalid element metadata or evaluator.')
        if len(ids) != len(knots)-1 or len(kinds) != len(ids) or len(set(ids)) != len(ids):
            raise ValueError('One unique element identity and kind per interval is required.')
        self.curve_id, self.source_hash = curve_id, source_hash
        self.parameter_kind, self.knots_m = parameter_kind, knots
        self.element_ids, self.curve_kinds = ids, kinds
        self._callback = callback

    def jet(self, parameter, side=None):
        q = _number(parameter)
        if side not in (None, 'left', 'right'):
            raise ValueError('side must be left or right.')
        if not self.knots_m[0] <= q <= self.knots_m[-1]:
            raise ValueError('Parameter outside curve domain; extrapolation is disabled.')
        if q in self.knots_m[1:-1] and side is None:
            raise ValueError('Choose left or right at an interior knot.')
        if (q == self.knots_m[0] and side == 'left') or (q == self.knots_m[-1] and side == 'right'):
            raise ValueError('The requested side is outside the curve domain.')
        search = bisect.bisect_left if side == 'left' else bisect.bisect_right
        i = max(0, min(len(self.element_ids)-1, search(self.knots_m, q)-1))
        vectors = tuple(tuple(_number(v) for v in row) for row in self._callback(i, q-self.knots_m[i]))
        if len(vectors) != 3 or any(len(row) != 2 for row in vectors) or vectors[0][1] <= 0:
            raise ValueError('A jet needs three 2D vectors and positive physical radius.')
        p, d, dd = vectors
        speed = math.hypot(*d)
        if not math.isfinite(speed):
            raise ValueError('Non-finite parameter speed.')
        tangent = tuple(v/speed for v in d) if speed else None
        try:
            curvature = (d[0]*dd[1]-d[1]*dd[0])/speed**3 if speed else None
        except (OverflowError, ZeroDivisionError) as exc:
            raise ValueError('Parameter speed cannot be represented for curvature evaluation.') from exc
        if curvature is not None and not math.isfinite(curvature):
            raise ValueError('Non-finite curvature.')
        return Jet(q, side, self.element_ids[i], p, d, dd, tangent, curvature)

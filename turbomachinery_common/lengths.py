"""Geometric distance along a native evaluator; no axial/arc-length conflation.

Adaptive Simpson errors are numerical estimates, not certified bounds.
Every native interval is integrated separately with one-sided endpoint jets.
"""
import bisect
import math
from dataclasses import dataclass
from .curves import MeridionalEvaluator, _number

API_VERSION = 1


class ConvergenceError(ValueError):
    """The requested numerical accuracy could not be established."""


@dataclass(frozen=True)
class DistanceResult:
    value_m: float
    estimated_error_m: float
    evaluations: int
    method: str = 'adaptive_simpson_one_sided_v1'


@dataclass(frozen=True)
class ParameterResult:
    parameter: float
    distance_residual_m: float
    estimated_distance_error_m: float
    iterations: int


class ArcLengthMap:
    """Read-only distance/parameter conversion, measured from the first knot.

    absolute_tolerance_m is the total quadrature error-estimate budget.
    No fitting, extrapolation, or changes to the original generator occur.
    Limits apply per integral; an inverse is additionally iteration-limited.
    """
    def __init__(self, curve, *, absolute_tolerance_m=1e-10,
                 max_depth=20, max_evaluations=20000):
        if not isinstance(curve, MeridionalEvaluator):
            raise ValueError('A native meridional evaluator is required.')
        tolerance = _number(absolute_tolerance_m)
        if tolerance <= 0:
            raise ValueError('The absolute tolerance must be positive metres.')
        for value, lower, upper in ((max_depth, 1, 30), (max_evaluations, 5, 1000000)):
            if type(value) is not int or not lower <= value <= upper:
                raise ValueError('Invalid integration resource limit.')
        self._curve = curve
        self.curve_id, self.source_hash = curve.curve_id, curve.source_hash
        self.parameter_kind = curve.parameter_kind
        self.knots_m = tuple(curve.knots_m)
        self.absolute_tolerance_m = tolerance
        self._budget = tolerance/(len(self.knots_m)-1)
        if self._budget == 0:
            raise ConvergenceError('Tolerance cannot be represented per interval.')
        self._max_depth, self._max_evaluations = max_depth, max_evaluations
        values, errors, evaluations = [0.], [0.], 0
        for a, b in zip(self.knots_m, self.knots_m[1:]):
            result = self._integral(a, b)
            total = values[-1]+result.value_m
            if not math.isfinite(total) or total <= values[-1]:
                raise ConvergenceError('Distance knots must be strictly increasing and finite.')
            values.append(total)
            errors.append(errors[-1]+result.estimated_error_m)
            evaluations += result.evaluations
        self.distance_knots_m = tuple(values)
        self._errors = tuple(errors)
        self.total = DistanceResult(values[-1], errors[-1], evaluations)

    def _integral(self, a, b):
        calls = 0

        def speed(q):
            nonlocal calls
            calls += 1
            if calls > self._max_evaluations:
                raise ConvergenceError('Quadrature evaluation limit exceeded.')
            jet = self._curve.jet(q, 'right' if q == a else 'left' if q == b else None)
            value = math.hypot(*jet.first)
            if not math.isfinite(value) or value <= 0:
                raise ConvergenceError('A finite positive parameter speed is required.')
            return value

        def simpson(x, y, fx, fm, fy):
            value = (y-x)*(fx+4*fm+fy)/6
            if not math.isfinite(value):
                raise ConvergenceError('Non-finite distance integral.')
            return value

        def refine(x, y, fx, fm, fy, whole, budget, depth):
            mid = x+(y-x)/2
            p, q = x+(mid-x)/2, mid+(y-mid)/2
            if not x < p < mid < q < y:
                raise ConvergenceError('Parameter resolution exhausted.')
            fp, fq = speed(p), speed(q)
            left = simpson(x, mid, fx, fp, fm)
            right = simpson(mid, y, fm, fq, fy)
            delta = left+right-whole
            error = abs(delta)/15
            if error <= budget:
                return left+right+delta/15, error
            if depth == 0:
                raise ConvergenceError('Quadrature depth limit exceeded; increase limits or relax tolerance.')
            lv, le = refine(x, mid, fx, fp, fm, left, budget/2, depth-1)
            rv, re = refine(mid, y, fm, fq, fy, right, budget/2, depth-1)
            return lv+rv, le+re

        mid = a+(b-a)/2
        fa, fm, fb = speed(a), speed(mid), speed(b)
        value, error = refine(a, b, fa, fm, fb, simpson(a, b, fa, fm, fb), self._budget, self._max_depth)
        if not math.isfinite(value) or value <= 0 or not math.isfinite(error):
            raise ConvergenceError('Invalid distance integral.')
        return DistanceResult(value, error, calls)

    def distance_at(self, parameter):
        q = _number(parameter)
        if not self.knots_m[0] <= q <= self.knots_m[-1]:
            raise ValueError('Parameter outside curve domain; extrapolation is disabled.')
        i = bisect.bisect_left(self.knots_m, q)
        if i < len(self.knots_m) and q == self.knots_m[i]:
            return DistanceResult(self.distance_knots_m[i], self._errors[i], 0)
        i -= 1
        partial = self._integral(self.knots_m[i], q)
        return DistanceResult(self.distance_knots_m[i]+partial.value_m,
                              self._errors[i]+partial.estimated_error_m, partial.evaluations)

    def parameter_at(self, distance_m, *, distance_tolerance_m=1e-8, max_iterations=80):
        target, tolerance = _number(distance_m), _number(distance_tolerance_m)
        if tolerance <= 0 or type(max_iterations) is not int or not 1 <= max_iterations <= 200:
            raise ValueError('Invalid inverse tolerance or iteration limit.')
        if not 0 <= target <= self.total.value_m:
            raise ValueError('Distance outside curve domain; extrapolation is disabled.')
        i = min(len(self.knots_m)-2, max(0, bisect.bisect_right(self.distance_knots_m, target)-1))
        # Preserve exact knots whenever their distance residual meets the budget.
        for k in (i, i+1):
            residual = self.distance_knots_m[k]-target
            error = abs(residual)+self._errors[k]
            if error <= tolerance:
                return ParameterResult(self.knots_m[k], residual, error, 0)
        lo, hi = self.knots_m[i], self.knots_m[i+1]
        for iteration in range(1, max_iterations+1):
            q = lo+(hi-lo)/2
            if q == lo or q == hi:
                raise ConvergenceError('Inverse parameter resolution exhausted.')
            result = self.distance_at(q)
            residual = result.value_m-target
            error = abs(residual)+result.estimated_error_m
            if error <= tolerance:
                return ParameterResult(q, residual, error, iteration)
            if abs(residual) <= result.estimated_error_m:
                raise ConvergenceError('Inverse requires a tighter quadrature tolerance.')
            if residual < 0:
                lo = q
            else:
                hi = q
        raise ConvergenceError('Inverse iteration limit exceeded.')

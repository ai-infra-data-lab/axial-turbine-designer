"""Read-only native PCHIP/linear wall adapter; no design migration."""
from core import validate, digest
from meridional import Curve
from turbomachinery_common.curves import MeridionalEvaluator
from turbomachinery_common.lengths import ArcLengthMap


def inspect_wall(raw, wall='hub', **query):
    from turbomachinery_common.inspection import inspect_curve
    return {**inspect_curve(wall_evaluator(raw, wall), **query), 'wall': wall}


def wall_length_map(raw, wall='hub', **options):
    """Convert absolute axial position to distance from the native wall start."""
    return ArcLengthMap(wall_evaluator(raw, wall), **options)


def wall_evaluator(raw, wall='hub'):
    if wall not in ('hub', 'casing'):
        raise ValueError('Expected hub or casing.')
    d = validate(raw)
    if not d['meridional']['enabled']:
        raise ValueError('Enable the design meridional walls before evaluation.')
    m = d['meridional']
    curve = Curve(m[wall], m['interpolation'])

    def evaluate(i, t):
        # Use the native coefficients on the explicitly selected interval.
        # Evaluating x via jet() would lose the side through rounding x_i+t.
        a, b, c, e = curve.coefficients[i]
        return ((curve.x[i]+t, a+b*t+c*t*t+e*t**3),
                (1., b+2*c*t+3*e*t*t), (0., 2*c+6*e*t))

    return MeridionalEvaluator(
        curve_id=wall, source_hash=digest(d), parameter_kind='axial_position_m',
        knots_m=curve.x, element_ids=[f'{wall}:interval:{i}' for i in range(len(curve.coefficients))],
        curve_kinds=[m['interpolation']]*len(curve.coefficients), callback=evaluate)

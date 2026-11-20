"""Shared read-only, SI report for native meridional inspection screens."""
from dataclasses import asdict
from .lengths import ArcLengthMap


def inspect_curve(curve, *, mode='parameter', value=None, side=None):
    if mode not in ('parameter', 'distance'):
        raise ValueError('Unknown query mode; choose parameter or distance.')
    mapping = ArcLengthMap(curve)
    inverse = None
    if mode == 'distance':
        inverse = mapping.parameter_at(0. if value is None else value)
        q = inverse.parameter
    else:
        q = curve.knots_m[0] if value is None else value
    jet = curve.jet(q, side)
    return {'format': 'common-meridional-inspection', 'version': 1,
            'curve_id': curve.curve_id, 'source_hash': curve.source_hash,
            'parameter_kind': curve.parameter_kind,
            'parameter_domain_m': [curve.knots_m[0], curve.knots_m[-1]],
            'parameter_knots_m': list(curve.knots_m),
            'distance_knots_m': list(mapping.distance_knots_m),
            'curve_kinds': list(curve.curve_kinds),
            'jet': asdict(jet), 'distance': asdict(mapping.distance_at(q)),
            'total': asdict(mapping.total), 'inverse': asdict(inverse) if inverse else None}

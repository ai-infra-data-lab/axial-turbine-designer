import copy
import unittest
from core import new_design, validate
from meridional import Curve
from common_meridional import wall_evaluator, wall_length_map


class CommonMeridionalTests(unittest.TestCase):
    def test_wall_distance_map_uses_axial_position_not_distance(self):
        import math
        d = self.design('linear')
        before = copy.deepcopy(d)
        m = wall_length_map(d)
        expected = math.hypot(.3, .01)+math.hypot(.4, -.005)
        self.assertAlmostEqual(m.total.value_m, expected, places=14)
        self.assertEqual(m.parameter_kind, 'axial_position_m')
        self.assertEqual(m.parameter_at(0.).parameter, -.2)
        for x in (-.1, .1, .4):
            self.assertAlmostEqual(m.parameter_at(m.distance_at(x).value_m).parameter, x, places=7)
        self.assertEqual(d, before)

    def test_pchip_distance_against_independent_refined_polyline(self):
        import math
        d = self.design()
        m = wall_length_map(d, 'casing')
        native = Curve(d['meridional']['casing'])
        xs = [-.2+.7*i/20000 for i in range(20001)]
        radii = [native.jet(x)[0] for x in xs]
        polyline = sum(math.hypot(b-a, rb-ra) for a,b,ra,rb in zip(xs,xs[1:],radii,radii[1:]))
        self.assertLess(abs(m.total.value_m-polyline), 2e-10)
        self.assertLessEqual(m.total.estimated_error_m, 1e-10)

    def design(self, mode='pchip'):
        d = new_design()
        d['meridional']['enabled'] = True
        d['meridional']['interpolation'] = mode
        d['meridional']['hub'] = [[-.2, .2], [.1, .21], [.5, .205]]
        d['meridional']['casing'] = [[-.2, .4], [.1, .42], [.5, .41]]
        return validate(d)

    def test_native_jets_both_walls_and_modes(self):
        for mode in ('linear', 'pchip'):
            d = self.design(mode)
            before = copy.deepcopy(d)
            for wall in ('hub', 'casing'):
                c = wall_evaluator(d, wall)
                native = Curve(d['meridional'][wall], mode)
                self.assertEqual(c.parameter_kind, 'axial_position_m')
                for x, side in [(-.2, 'right'), (0., None), (.1, 'left'), (.1, 'right'), (.3, None), (.5, 'left')]:
                    j = c.jet(x, side)
                    r, first, second, _ = native.jet(x, left=side == 'left')
                    for a, b in [(j.position_m[0], x), (j.position_m[1], r),
                                 (j.first[1], first), (j.second_per_m[1], second)]:
                        self.assertAlmostEqual(a, b, places=12)
            self.assertEqual(d, before)

    def test_corner_and_snapshot_detachment(self):
        d = self.design('linear')
        c = wall_evaluator(d)
        left, right = c.jet(.1, 'left'), c.jet(.1, 'right')
        for a, b in zip(left.position_m, right.position_m):
            self.assertAlmostEqual(a, b, places=14)
        self.assertNotEqual(left.tangent, right.tangent)
        with self.assertRaises(ValueError): c.jet(.1)
        d['meridional']['hub'][0][1] = .3
        self.assertEqual(c.jet(-.2).position_m[1], .2)

    def test_disabled_and_invalid_wall(self):
        with self.assertRaises(ValueError): wall_evaluator(new_design())
        with self.assertRaises(ValueError): wall_evaluator(self.design(), 'tip')


if __name__ == '__main__': unittest.main()

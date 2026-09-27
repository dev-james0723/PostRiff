import math
import unittest

from postriff_phase2.growth import calibration as C


class Kappa(unittest.TestCase):
    def test_perfect_and_chance(self):
        self.assertAlmostEqual(C.quadratic_weighted_kappa([0, 1, 2, 3], [0, 1, 2, 3], 4), 1.0)
        self.assertIsNone(C.quadratic_weighted_kappa([2, 2, 2], [2, 2, 2], 4))
        reversed_ = C.quadratic_weighted_kappa([0, 1, 2, 3], [3, 2, 1, 0], 4)
        self.assertLess(reversed_, 0)

    def test_known_value(self):
        # Hand-computed: one step disagreement on one of four items.
        value = C.quadratic_weighted_kappa([0, 1, 2, 3], [0, 1, 2, 2], 4)
        self.assertTrue(0.8 < value < 1.0)

    def test_rejects_bad_input(self):
        for a, b in (([], []), ([0], [0, 1]), ([4], [0]), ([True], [0]), ([0.5], [0])):
            with self.assertRaises(ValueError):
                C.quadratic_weighted_kappa(a, b, 4)


class ECE(unittest.TestCase):
    def test_perfectly_calibrated(self):
        probs = [0.25] * 4 + [0.75] * 4
        outcomes = [1, 0, 0, 0, 1, 1, 1, 0]
        self.assertAlmostEqual(C.expected_calibration_error(probs, outcomes), 0.0)

    def test_overconfident(self):
        self.assertAlmostEqual(C.expected_calibration_error([0.99] * 4, [1, 0, 1, 0]), 0.49, places=6)

    def test_rejects(self):
        for p, o in (([], []), ([1.2], [1]), ([math.nan], [1]), ([0.5], [2])):
            with self.assertRaises(ValueError):
                C.expected_calibration_error(p, o)


class Isotonic(unittest.TestCase):
    def test_monotone_and_applies(self):
        cal = C.isotonic_fit([0.1, 0.2, 0.3, 0.4, 0.9, 0.95], [0, 1, 0, 1, 1, 1])
        self.assertEqual(cal["y"], sorted(cal["y"]))
        self.assertLessEqual(C.isotonic_apply(cal, 0.05), C.isotonic_apply(cal, 0.97))
        self.assertEqual(C.isotonic_apply(cal, 0.0), cal["y"][0])
        self.assertEqual(C.isotonic_apply(cal, 1.0), cal["y"][-1])

    def test_overconfident_ties_are_pulled_down(self):
        cal = C.isotonic_fit([0.99] * 10 + [0.5] * 4, [1] * 6 + [0] * 4 + [0, 0, 1, 0])
        self.assertAlmostEqual(C.isotonic_apply(cal, 0.99), 0.6)

    def test_rejects_empty_map(self):
        with self.assertRaises(ValueError):
            C.isotonic_apply({"x": [], "y": []}, 0.5)


class Other(unittest.TestCase):
    def test_spearman(self):
        self.assertAlmostEqual(C.spearman([1, 2, 3, 4], [10, 20, 30, 40]), 1.0)
        self.assertAlmostEqual(C.spearman([1, 2, 3, 4], [4, 3, 2, 1]), -1.0)
        self.assertIsNone(C.spearman([1, 1, 1], [1, 2, 3]))

    def test_ridge_recovers_line(self):
        rows = [[x] for x in range(10)]
        coef = C.ridge_fit(rows, [2 + 3 * x for x in range(10)], alpha=1e-9)
        self.assertAlmostEqual(coef[0], 2, places=4)
        self.assertAlmostEqual(coef[1], 3, places=4)

    def test_levels_and_threshold_fit(self):
        self.assertEqual([C.to_level(s, [0.35, 0.55, 0.75]) for s in (0.1, 0.4, 0.6, 0.9)], [0, 1, 2, 3])
        scores = [0.1, 0.15, 0.3, 0.42, 0.5, 0.62, 0.7, 0.85, 0.9]
        labels = [0, 0, 0, 1, 1, 2, 2, 3, 3]
        fit = C.fit_thresholds(scores, labels, 4)
        self.assertEqual(fit["thresholds"], sorted(fit["thresholds"]))
        self.assertGreater(fit["kappa"], 0.95)


if __name__ == "__main__":
    unittest.main()

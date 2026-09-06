import unittest

from tools.tracking_baseline import build_analysis


class BaselineMetricTests(unittest.TestCase):
    def test_low_separation_does_not_recommend_gain(self):
        def stats(mean):
            return {"mean": mean, "std": 0.2, "p05": mean - 0.2, "p95": mean + 0.2}

        phases = {}
        for name, value in (("center_up", 0.0), ("eyes_up", -0.2), ("center_down", 0.0), ("eyes_down", 0.2)):
            phases[name] = {"eyes": {"eye_33_133": {"x": stats(0.0), "y": stats(value)}, "eye_362_263": {"x": stats(0.0), "y": stats(value)}}}
        analysis = build_analysis(phases)
        self.assertIsNone(analysis["measured_recommended_down_gain"])

    def test_known_separation_returns_known_gain(self):
        def stats(mean, spread=0.05):
            return {"mean": mean, "std": spread, "p05": mean - spread, "p95": mean + spread}

        phases = {}
        for name, value in (("center_up", 0.0), ("eyes_up", -0.6), ("center_down", 0.0), ("eyes_down", 0.3)):
            phases[name] = {"eyes": {eye: {"x": stats(0.0), "y": stats(value)} for eye in ("eye_33_133", "eye_362_263")}}
        analysis = build_analysis(phases)
        self.assertAlmostEqual(analysis["measured_recommended_down_gain"], 2.0)


if __name__ == "__main__":
    unittest.main()

import unittest

from tools.compare_vertical_candidates import compare_candidates


def _row(label: str, i: int, current: float, raw: float, eyelid: float, orbital: float) -> dict:
    return {
        "frame_index": i,
        "elapsed_s": i / 30.0,
        "protocol_label": label,
        "face_detected": True,
        "valid": True,
        "left_eye_quality": 0.8,
        "right_eye_quality": 0.8,
        "left_h": 0.0,
        "right_h": 0.0,
        "left_v_postbaseline": current,
        "right_v_postbaseline": current,
        "left_v_raw_px": raw,
        "right_v_raw_px": raw,
        "left_v_eyelid_relative": eyelid,
        "right_v_eyelid_relative": eyelid,
        "left_v_orbital_relative": orbital,
        "right_v_orbital_relative": orbital,
        "left_openness": 0.3,
        "right_openness": 0.3,
    }


class VerticalCandidateComparisonTests(unittest.TestCase):
    def test_ranks_candidate_with_high_vertical_range_and_low_leakage(self):
        rows = []
        for i, v in enumerate([-0.01, 0.0, 0.01, 0.0]):
            rows.append(_row("center_hold", i, v, v * 30.0, v, v * 2.0))
        for i, v in enumerate([-0.6, -0.2, 0.2, 0.6], start=10):
            row = _row("vertical_sweep", i, v, v * 20.0, v * 0.2, v * 0.8)
            row["left_h"] = 0.05
            row["right_h"] = 0.05
            rows.append(row)
        for i, h in enumerate([-1.0, 1.0], start=20):
            row = _row("horizontal_sweep", i, 0.02, h * 12.0, 0.01, h * 0.8)
            row["left_h"] = h
            row["right_h"] = h
            rows.append(row)

        report = compare_candidates(rows)

        self.assertIn("current", report["candidates"])
        self.assertGreater(report["candidates"]["current"]["vertical_range_mean"], 1.0)
        self.assertLess(report["candidates"]["current"]["horizontal_leakage_ratio"], 0.1)
        self.assertEqual(report["best_candidate"], "current")


if __name__ == "__main__":
    unittest.main()

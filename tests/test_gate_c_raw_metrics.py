import json
import tempfile
import unittest
from pathlib import Path

from tools.analyze_raw_signals import analyze_records, write_analysis_outputs


def _base(label: str, i: int) -> dict:
    return {
        "frame_index": i,
        "elapsed_s": i / 30.0,
        "protocol_label": label,
        "face_detected": True,
        "valid": True,
        "left_eye_quality": 0.8,
        "right_eye_quality": 0.8,
        "confidence": 0.8,
        "left_h": 0.0,
        "right_h": 0.0,
        "left_v_postbaseline": 0.0,
        "right_v_postbaseline": 0.0,
        "left_openness": 0.3,
        "right_openness": 0.3,
        "left_min_clearance_y": 0.1,
        "right_min_clearance_y": 0.1,
        "head_pose_y": 0.0,
        "pitch_deg": 0.0,
        "condition_id": "test",
    }


class GateCRawMetricsTests(unittest.TestCase):
    def test_analyzes_raw_snr_leakage_agreement_and_head_contamination(self):
        records = []
        for i, value in enumerate([-0.01, 0.0, 0.01, 0.0]):
            row = _base("center_hold", i)
            row["left_v_postbaseline"] = value
            row["right_v_postbaseline"] = value + 0.005
            records.append(row)
        for j, value in enumerate([-1.0, -0.3, 0.3, 1.0], start=10):
            row = _base("horizontal_sweep", j)
            row["left_h"] = value
            row["right_h"] = value
            row["left_v_postbaseline"] = 0.05
            row["right_v_postbaseline"] = 0.05
            records.append(row)
        for j, value in enumerate([-0.8, -0.2, 0.2, 0.8], start=20):
            row = _base("vertical_sweep", j)
            row["left_v_postbaseline"] = value
            row["right_v_postbaseline"] = value + 0.01
            row["left_h"] = 0.08
            row["right_h"] = 0.08
            records.append(row)
        for j, value in enumerate([-0.3, -0.1, 0.1, 0.3], start=30):
            row = _base("head_motion", j)
            row["left_v_postbaseline"] = value
            row["right_v_postbaseline"] = value
            row["pitch_deg"] = value * 10.0
            records.append(row)

        analysis = analyze_records(records)

        self.assertEqual(analysis["overall"]["total_records"], 16)
        self.assertEqual(analysis["overall"]["included_records"], 16)
        self.assertAlmostEqual(
            analysis["segments"]["vertical_sweep"]["left_v_primary_range"], 1.6
        )
        self.assertAlmostEqual(
            analysis["segments"]["vertical_sweep"]["vertical_cross_axis_leakage_ratio"],
            0.0,
        )
        self.assertGreater(
            analysis["segments"]["vertical_sweep"]["left_v_snr_vs_center"], 50.0
        )
        self.assertAlmostEqual(
            analysis["segments"]["head_motion"]["left_v_pitch_corr"], 1.0
        )
        self.assertAlmostEqual(
            analysis["segments"]["vertical_sweep"]["left_right_v_disagreement_p95"],
            0.01,
        )

    def test_writes_markdown_and_csv_outputs(self):
        records = [_base("center_hold", 0), _base("center_hold", 1)]
        analysis = analyze_records(records)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            outputs = write_analysis_outputs(analysis, root / "report.md", root / "metrics.csv")

            self.assertTrue(outputs["report_path"].exists())
            self.assertTrue(outputs["csv_path"].exists())
            self.assertIn("# Raw Signal Analysis Report", outputs["report_path"].read_text())
            rows = outputs["csv_path"].read_text().splitlines()
            self.assertTrue(rows[0].startswith("segment,"))
            self.assertIn("center_hold", rows[1])


if __name__ == "__main__":
    unittest.main()

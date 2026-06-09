import csv
import json
import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

from tools.export_eye_crops import (
    compare_annotations,
    export_eye_crops_from_records,
    write_annotation_template,
)


def _record() -> dict:
    return {
        "frame_index": 42,
        "elapsed_s": 1.4,
        "protocol_label": "center_hold",
        "condition_id": "controlled_no_glasses",
        "condition_glasses": "none",
        "condition_lighting": "normal",
        "left_iris_center": [50, 40],
        "left_iris_points": [[48, 40], [50, 38], [52, 40], [50, 42]],
        "left_corners": [[30, 40], [70, 40]],
        "left_top": [50, 30],
        "left_bottom": [50, 50],
        "left_width": 40.0,
        "left_iris_radius": 2.0,
        "right_iris_center": [130, 40],
        "right_iris_points": [[128, 40], [130, 38], [132, 40], [130, 42]],
        "right_corners": [[110, 40], [150, 40]],
        "right_top": [130, 30],
        "right_bottom": [130, 50],
        "right_width": 40.0,
        "right_iris_radius": 2.0,
    }


class GateB2CropExportTests(unittest.TestCase):
    def test_exports_eye_crops_and_manifest_for_manual_annotation(self):
        frame = np.full((90, 180, 3), 120, dtype=np.uint8)
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)

            manifest_path = export_eye_crops_from_records(
                records=[_record()],
                frames={42: frame},
                output_dir=output_dir,
                crop_padding=12,
            )

            rows = [json.loads(line) for line in manifest_path.read_text().splitlines()]
            self.assertEqual(len(rows), 2)
            left = rows[0]
            self.assertEqual(left["frame_index"], 42)
            self.assertEqual(left["eye"], "left")
            self.assertEqual(left["protocol_label"], "center_hold")
            self.assertEqual(left["condition_id"], "controlled_no_glasses")
            self.assertEqual(left["mediapipe_iris_center_crop"], [32, 22])
            self.assertTrue((output_dir / left["crop_path"]).exists())
            self.assertTrue((output_dir / left["overlay_path"]).exists())

    def test_annotation_template_and_comparison_report(self):
        manifest_row = {
            "frame_index": 42,
            "eye": "left",
            "crop_path": "crops/frame_000042_left.png",
            "mediapipe_iris_center_crop": [32, 22],
            "iris_radius": 2.0,
            "eye_width": 40.0,
            "protocol_label": "center_hold",
            "condition_id": "controlled_no_glasses",
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path = root / "manifest.jsonl"
            manifest_path.write_text(json.dumps(manifest_row) + "\n", encoding="utf-8")

            template_path = write_annotation_template(manifest_path, root / "annotations.csv")
            with template_path.open(newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(rows[0]["manual_center_x"], "")
            self.assertEqual(rows[0]["manual_center_y"], "")

            rows[0]["manual_center_x"] = "35"
            rows[0]["manual_center_y"] = "26"
            with template_path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=rows[0].keys())
                writer.writeheader()
                writer.writerows(rows)

            report = compare_annotations(manifest_path, template_path)
            self.assertEqual(report["count"], 1)
            self.assertAlmostEqual(report["median_error_px"], 5.0)
            self.assertAlmostEqual(report["median_error_by_iris_radius"], 2.5)
            self.assertAlmostEqual(report["median_error_by_eye_width"], 0.125)


if __name__ == "__main__":
    unittest.main()

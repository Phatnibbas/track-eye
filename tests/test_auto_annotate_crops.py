import csv
import json
import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

from tools.auto_annotate_crops import auto_annotate_manifest
from tools.export_eye_crops import compare_annotations


class AutoAnnotateCropsTests(unittest.TestCase):
    def test_auto_annotates_dark_blob_center_in_crop(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            crops = root / "crops"
            crops.mkdir()
            image = np.full((80, 100, 3), 180, dtype=np.uint8)
            cv2.circle(image, (42, 37), 10, (20, 20, 20), -1)
            cv2.imwrite(str(crops / "eye.png"), image)
            manifest = root / "manifest.jsonl"
            manifest.write_text(
                json.dumps(
                    {
                        "frame_index": 1,
                        "eye": "left",
                        "protocol_label": "center_hold",
                        "condition_id": "test",
                        "crop_path": "crops/eye.png",
                        "overlay_path": "crops/eye.png",
                        "mediapipe_iris_center_crop": [40, 35],
                        "iris_radius": 10.0,
                        "eye_width": 50.0,
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            annotations = auto_annotate_manifest(manifest, root / "auto_annotations.csv", root)

            with annotations.open(encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(rows[0]["usable"], "1")
            self.assertAlmostEqual(float(rows[0]["manual_center_x"]), 42, delta=2.0)
            self.assertAlmostEqual(float(rows[0]["manual_center_y"]), 37, delta=2.0)

            report = compare_annotations(manifest, annotations)
            self.assertEqual(report["count"], 1)
            self.assertLess(report["median_error_px"], 5.0)


if __name__ == "__main__":
    unittest.main()

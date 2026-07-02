"""Automatically pseudo-annotate exported eye crops.

This is a diagnostic pseudo-labeler, not human ground truth. It estimates the
dark pupil/iris blob center in each crop to compare against MediaPipe iris
center and flag likely bias/failure cases.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
from typing import Any

import cv2
import numpy as np

try:
    from export_eye_crops import compare_annotations
except ModuleNotFoundError:  # imported as tools.auto_annotate_crops in tests
    from tools.export_eye_crops import compare_annotations


FIELDNAMES = [
    "frame_index",
    "eye",
    "protocol_label",
    "condition_id",
    "crop_path",
    "overlay_path",
    "mediapipe_center_x",
    "mediapipe_center_y",
    "manual_center_x",
    "manual_center_y",
    "usable",
    "notes",
]


def auto_annotate_manifest(
    manifest_path: Path, output_csv: Path, root_dir: Path | None = None
) -> Path:
    root = root_dir or manifest_path.parent
    rows = [
        json.loads(line)
        for line in manifest_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    with output_csv.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDNAMES)
        writer.writeheader()
        for row in rows:
            center = row["mediapipe_iris_center_crop"]
            crop_path = root / row["crop_path"]
            image = cv2.imread(str(crop_path), cv2.IMREAD_COLOR)
            auto = _estimate_dark_blob_center(
                image,
                mp_center=(float(center[0]), float(center[1])),
                iris_radius=float(row.get("iris_radius") or 0.0),
            )
            usable = auto is not None
            writer.writerow(
                {
                    "frame_index": row["frame_index"],
                    "eye": row["eye"],
                    "protocol_label": row.get("protocol_label", ""),
                    "condition_id": row.get("condition_id", ""),
                    "crop_path": row["crop_path"],
                    "overlay_path": row.get("overlay_path", ""),
                    "mediapipe_center_x": center[0],
                    "mediapipe_center_y": center[1],
                    "manual_center_x": "" if auto is None else f"{auto[0]:.3f}",
                    "manual_center_y": "" if auto is None else f"{auto[1]:.3f}",
                    "usable": "1" if usable else "0",
                    "notes": "auto_dark_blob" if usable else "auto_failed",
                }
            )
    return output_csv


def auto_annotate_tree(root: Path) -> list[dict[str, Any]]:
    results = []
    for manifest_path in sorted(root.glob("*/manifest.jsonl")):
        output_csv = manifest_path.parent / "auto_annotations.csv"
        auto_annotate_manifest(manifest_path, output_csv, manifest_path.parent)
        report = compare_annotations(manifest_path, output_csv)
        report["session"] = manifest_path.parent.name
        results.append(report)
    return results


def _estimate_dark_blob_center(
    image: np.ndarray | None, mp_center: tuple[float, float], iris_radius: float
) -> tuple[float, float] | None:
    if image is None or image.size == 0:
        return None
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (5, 5), 0)
    h, w = gray.shape[:2]
    cx, cy = mp_center
    radius = max(float(iris_radius), min(w, h) * 0.08, 4.0)
    roi_radius = int(max(radius * 3.0, 18.0))
    x1 = max(0, int(round(cx - roi_radius)))
    y1 = max(0, int(round(cy - roi_radius)))
    x2 = min(w, int(round(cx + roi_radius)))
    y2 = min(h, int(round(cy + roi_radius)))
    roi = gray[y1:y2, x1:x2]
    if roi.size == 0:
        return None

    threshold = min(float(np.percentile(roi, 35)), float(np.mean(roi) - (0.25 * np.std(roi))))
    mask = (roi <= threshold).astype(np.uint8) * 255
    kernel = np.ones((3, 3), dtype=np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None

    best = None
    best_score = -1e18
    expected_area = math.pi * radius * radius
    for contour in contours:
        area = float(cv2.contourArea(contour))
        if area < max(8.0, expected_area * 0.05):
            continue
        moments = cv2.moments(contour)
        if abs(moments["m00"]) <= 1e-9:
            continue
        local_x = float(moments["m10"] / moments["m00"])
        local_y = float(moments["m01"] / moments["m00"])
        global_x = x1 + local_x
        global_y = y1 + local_y
        dist = math.hypot(global_x - cx, global_y - cy)
        perimeter = float(cv2.arcLength(contour, True))
        circularity = (4.0 * math.pi * area / (perimeter * perimeter)) if perimeter > 1e-6 else 0.0
        area_score = -abs(math.log(max(area, 1e-6) / max(expected_area, 1e-6)))
        score = (2.0 * circularity) + area_score - (dist / max(radius * 2.0, 1e-6))
        if score > best_score:
            best_score = score
            best = (global_x, global_y)
    return best


def _write_summary(results: list[dict[str, Any]], path: Path) -> None:
    lines = ["# Auto Annotation Summary", "", "Pseudo-label method: dark blob detection in crop ROI. Not human ground truth.", ""]
    for row in results:
        lines.append(f"## {row['session']}")
        lines.append(f"- count: {row['count']}")
        lines.append(f"- median_error_px: {row['median_error_px']:.3f}")
        lines.append(f"- p95_error_px: {row['p95_error_px']:.3f}")
        lines.append(f"- median_error_by_iris_radius: {row['median_error_by_iris_radius']:.3f}")
        lines.append(f"- median_error_by_eye_width: {row['median_error_by_eye_width']:.3f}")
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Auto pseudo-annotate manual crop exports")
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--summary", type=Path, default=None)
    args = parser.parse_args()
    results = auto_annotate_tree(args.root)
    if args.summary is not None:
        _write_summary(results, args.summary)
    print({"sessions": len(results), "summary": None if args.summary is None else str(args.summary)})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Export eye crops for manual iris/pupil annotation.

Gate B2 scaffold: this module creates reviewable crop images and a manifest
from Gate A2 JSONL records. It does not change runtime tracking behavior.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
from statistics import median
from typing import Any

import cv2
import numpy as np


SIDES = ("left", "right")


def export_eye_crops_from_records(
    records: list[dict[str, Any]],
    frames: dict[int, np.ndarray],
    output_dir: Path,
    crop_padding: int = 24,
) -> Path:
    """Export raw and overlay crops, returning a JSONL manifest path."""

    output_dir.mkdir(parents=True, exist_ok=True)
    crops_dir = output_dir / "crops"
    overlays_dir = output_dir / "overlays"
    crops_dir.mkdir(parents=True, exist_ok=True)
    overlays_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = output_dir / "manifest.jsonl"

    rows: list[dict[str, Any]] = []
    for record in records:
        frame_index = int(record["frame_index"])
        frame = frames.get(frame_index)
        if frame is None:
            continue
        for side in SIDES:
            crop_info = _build_crop(frame, record, side, crop_padding)
            if crop_info is None:
                continue
            crop, overlay, box = crop_info
            crop_name = f"frame_{frame_index:06d}_{side}.png"
            overlay_name = f"frame_{frame_index:06d}_{side}_overlay.png"
            crop_path = crops_dir / crop_name
            overlay_path = overlays_dir / overlay_name
            cv2.imwrite(str(crop_path), crop)
            cv2.imwrite(str(overlay_path), overlay)

            center = record[f"{side}_iris_center"]
            rows.append(
                {
                    "frame_index": frame_index,
                    "elapsed_s": record.get("elapsed_s"),
                    "eye": side,
                    "protocol_label": record.get("protocol_label"),
                    "condition_id": record.get("condition_id", "unspecified"),
                    "condition_glasses": record.get("condition_glasses", "unspecified"),
                    "condition_lighting": record.get("condition_lighting", "unspecified"),
                    "crop_path": str(crop_path.relative_to(output_dir)).replace("\\", "/"),
                    "overlay_path": str(overlay_path.relative_to(output_dir)).replace("\\", "/"),
                    "crop_box_xyxy": list(box),
                    "mediapipe_iris_center_px": [int(center[0]), int(center[1])],
                    "mediapipe_iris_center_crop": [
                        int(center[0] - box[0]),
                        int(center[1] - box[1]),
                    ],
                    "iris_radius": record.get(f"{side}_iris_radius"),
                    "eye_width": record.get(f"{side}_width"),
                }
            )

    with manifest_path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=True) + "\n")
    return manifest_path


def write_annotation_template(manifest_path: Path, output_csv: Path) -> Path:
    """Create an annotation CSV template from a crop manifest."""

    output_csv.parent.mkdir(parents=True, exist_ok=True)
    rows = [json.loads(line) for line in manifest_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    fieldnames = [
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
    with output_csv.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            center = row["mediapipe_iris_center_crop"]
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
                    "manual_center_x": "",
                    "manual_center_y": "",
                    "usable": "1",
                    "notes": "",
                }
            )
    return output_csv


def compare_annotations(manifest_path: Path, annotations_csv: Path) -> dict[str, float | int]:
    """Compare manual crop-space centers with MediaPipe crop-space centers."""

    manifest = {
        (int(row["frame_index"]), row["eye"]): row
        for row in (
            json.loads(line)
            for line in manifest_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        )
    }
    errors: list[float] = []
    by_radius: list[float] = []
    by_width: list[float] = []
    with annotations_csv.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if row.get("usable", "1").strip() in {"0", "false", "False"}:
                continue
            if not row.get("manual_center_x") or not row.get("manual_center_y"):
                continue
            key = (int(row["frame_index"]), row["eye"])
            item = manifest[key]
            mp_x, mp_y = item["mediapipe_iris_center_crop"]
            dx = float(row["manual_center_x"]) - float(mp_x)
            dy = float(row["manual_center_y"]) - float(mp_y)
            err = math.hypot(dx, dy)
            errors.append(err)
            radius = float(item.get("iris_radius") or 0.0)
            width = float(item.get("eye_width") or 0.0)
            if radius > 1e-6:
                by_radius.append(err / radius)
            if width > 1e-6:
                by_width.append(err / width)
    return {
        "count": len(errors),
        "median_error_px": float(median(errors)) if errors else 0.0,
        "p95_error_px": _percentile(errors, 95.0),
        "median_error_by_iris_radius": float(median(by_radius)) if by_radius else 0.0,
        "median_error_by_eye_width": float(median(by_width)) if by_width else 0.0,
    }


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def load_video_frames(video_path: Path, frame_indices: set[int], mirror: bool = True) -> dict[int, np.ndarray]:
    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        raise RuntimeError(f"Could not open video: {video_path}")
    frames: dict[int, np.ndarray] = {}
    wanted = sorted(frame_indices)
    for frame_index in wanted:
        capture.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
        ok, frame = capture.read()
        if not ok:
            continue
        frames[frame_index] = cv2.flip(frame, 1) if mirror else frame
    capture.release()
    return frames


def _build_crop(
    frame: np.ndarray, record: dict[str, Any], side: str, padding: int
) -> tuple[np.ndarray, np.ndarray, tuple[int, int, int, int]] | None:
    points = []
    for key in ("iris_center", "top", "bottom"):
        value = record.get(f"{side}_{key}")
        if value is not None:
            points.append(value)
    points.extend(record.get(f"{side}_iris_points") or [])
    points.extend(record.get(f"{side}_corners") or [])
    if not points:
        return None
    arr = np.asarray(points, dtype=np.float64)
    height, width = frame.shape[:2]
    x1 = max(0, int(np.floor(np.min(arr[:, 0]) - padding)))
    y1 = max(0, int(np.floor(np.min(arr[:, 1]) - padding)))
    x2 = min(width, int(np.ceil(np.max(arr[:, 0]) + padding)))
    y2 = min(height, int(np.ceil(np.max(arr[:, 1]) + padding)))
    if x2 <= x1 or y2 <= y1:
        return None
    crop = frame[y1:y2, x1:x2].copy()
    overlay = crop.copy()
    _draw_overlay(overlay, record, side, x_offset=x1, y_offset=y1)
    return crop, overlay, (x1, y1, x2, y2)


def _draw_overlay(
    crop: np.ndarray, record: dict[str, Any], side: str, x_offset: int, y_offset: int
) -> None:
    def pt(value: list[int]) -> tuple[int, int]:
        return int(value[0] - x_offset), int(value[1] - y_offset)

    for point in record.get(f"{side}_iris_points") or []:
        cv2.circle(crop, pt(point), 2, (0, 255, 255), -1)
    center = record.get(f"{side}_iris_center")
    if center is not None:
        cv2.circle(crop, pt(center), 4, (0, 0, 255), 1)
    for point in record.get(f"{side}_corners") or []:
        cv2.circle(crop, pt(point), 3, (255, 0, 0), -1)
    for key, color in (("top", (0, 255, 0)), ("bottom", (255, 0, 255))):
        value = record.get(f"{side}_{key}")
        if value is not None:
            cv2.circle(crop, pt(value), 3, color, -1)


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    return float(np.percentile(np.asarray(values, dtype=np.float64), percentile))


def main() -> int:
    parser = argparse.ArgumentParser(description="Export eye crops for manual annotation")
    parser.add_argument("--log", type=Path, required=True)
    parser.add_argument("--video", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--max-records", type=int, default=120)
    parser.add_argument("--crop-padding", type=int, default=24)
    parser.add_argument("--no-mirror", action="store_true")
    args = parser.parse_args()

    records = load_jsonl(args.log)[: max(0, args.max_records)]
    frames = load_video_frames(
        args.video,
        {int(record["frame_index"]) for record in records},
        mirror=not args.no_mirror,
    )
    manifest_path = export_eye_crops_from_records(
        records=records,
        frames=frames,
        output_dir=args.output_dir,
        crop_padding=args.crop_padding,
    )
    annotations_path = write_annotation_template(
        manifest_path, args.output_dir / "annotations_template.csv"
    )
    print(f"manifest={manifest_path}")
    print(f"annotations_template={annotations_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

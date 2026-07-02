"""Analyze Gate A2 raw per-eye observation signals.

Gate C scaffold: computes objective metrics from logged raw/per-eye channels.
It does not claim gaze accuracy; it only summarizes logged signal behavior.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np


SEGMENT_ORDER = [
    "center_hold",
    "horizontal_sweep",
    "vertical_sweep",
    "head_motion",
    "blink_degrade",
]


def analyze_records(records: list[dict[str, Any]]) -> dict[str, Any]:
    included = [record for record in records if _include_record(record)]
    center = [record for record in included if record.get("protocol_label") == "center_hold"]
    center_noise = {
        "left_h": _robust_noise([_f(r, "left_h") for r in center]),
        "right_h": _robust_noise([_f(r, "right_h") for r in center]),
        "left_v_postbaseline": _robust_noise([_f(r, "left_v_postbaseline") for r in center]),
        "right_v_postbaseline": _robust_noise([_f(r, "right_v_postbaseline") for r in center]),
    }

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in included:
        grouped[str(record.get("protocol_label", "none"))].append(record)

    segments = {}
    for label in sorted(grouped.keys(), key=_segment_sort_key):
        segments[label] = _segment_metrics(label, grouped[label], center_noise)

    return {
        "overall": {
            "total_records": len(records),
            "included_records": len(included),
            "excluded_records": len(records) - len(included),
            "excluded_ratio": (len(records) - len(included)) / max(len(records), 1),
        },
        "center_noise": center_noise,
        "segments": segments,
    }


def write_analysis_outputs(
    analysis: dict[str, Any], report_path: Path, csv_path: Path
) -> dict[str, Path]:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    _write_markdown_report(analysis, report_path)
    _write_csv_metrics(analysis, csv_path)
    return {"report_path": report_path, "csv_path": csv_path}


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _segment_metrics(
    label: str, records: list[dict[str, Any]], center_noise: dict[str, float]
) -> dict[str, float | int | str]:
    left_h = [_f(r, "left_h") for r in records]
    right_h = [_f(r, "right_h") for r in records]
    left_v = [_f(r, "left_v_postbaseline") for r in records]
    right_v = [_f(r, "right_v_postbaseline") for r in records]
    left_open = [_f(r, "left_openness") for r in records]
    right_open = [_f(r, "right_openness") for r in records]

    metrics: dict[str, float | int | str] = {
        "label": label,
        "frame_count": len(records),
        "left_h_range": _ptp(left_h),
        "right_h_range": _ptp(right_h),
        "left_v_range": _ptp(left_v),
        "right_v_range": _ptp(right_v),
        "left_right_h_corr": _corr(left_h, right_h),
        "left_right_v_corr": _corr(left_v, right_v),
        "left_right_v_disagreement_median": _median_abs_diff(left_v, right_v),
        "left_right_v_disagreement_p95": _percentile_abs_diff(left_v, right_v, 95.0),
        "mean_confidence": _mean([_f(r, "confidence") for r in records]),
        "valid_ratio": _mean([1.0 if r.get("valid") else 0.0 for r in records]),
    }

    metrics["left_h_snr_vs_center"] = metrics["left_h_range"] / max(center_noise["left_h"], 1e-6)
    metrics["right_h_snr_vs_center"] = metrics["right_h_range"] / max(center_noise["right_h"], 1e-6)
    metrics["left_v_snr_vs_center"] = metrics["left_v_range"] / max(center_noise["left_v_postbaseline"], 1e-6)
    metrics["right_v_snr_vs_center"] = metrics["right_v_range"] / max(center_noise["right_v_postbaseline"], 1e-6)

    if label == "horizontal_sweep":
        primary = max(float(metrics["left_h_range"]), float(metrics["right_h_range"]), 1e-6)
        cross = max(float(metrics["left_v_range"]), float(metrics["right_v_range"]))
        metrics["horizontal_cross_axis_leakage_ratio"] = cross / primary
        metrics["left_h_monotonic_abs_rho"] = _split_abs_spearman(records, "left_h")
        metrics["right_h_monotonic_abs_rho"] = _split_abs_spearman(records, "right_h")
    if label == "vertical_sweep":
        primary = max(float(metrics["left_v_range"]), float(metrics["right_v_range"]), 1e-6)
        cross = max(float(metrics["left_h_range"]), float(metrics["right_h_range"]))
        metrics["vertical_cross_axis_leakage_ratio"] = cross / primary
        metrics["left_v_primary_range"] = metrics["left_v_range"]
        metrics["right_v_primary_range"] = metrics["right_v_range"]
        metrics["left_v_monotonic_abs_rho"] = _split_abs_spearman(records, "left_v_postbaseline")
        metrics["right_v_monotonic_abs_rho"] = _split_abs_spearman(records, "right_v_postbaseline")
    if label == "head_motion":
        pitch = [_f(r, "pitch_deg") for r in records]
        head_y = [_f(r, "head_pose_y") for r in records]
        metrics["left_v_pitch_corr"] = _corr(left_v, pitch)
        metrics["right_v_pitch_corr"] = _corr(right_v, pitch)
        metrics["left_v_head_pose_y_corr"] = _corr(left_v, head_y)
        metrics["right_v_head_pose_y_corr"] = _corr(right_v, head_y)
    if label in {"center_hold", "blink_degrade", "eyelid_openness"}:
        metrics["left_v_openness_corr"] = _corr(left_v, left_open)
        metrics["right_v_openness_corr"] = _corr(right_v, right_open)
    return metrics


def _include_record(record: dict[str, Any]) -> bool:
    return bool(record.get("face_detected")) and bool(record.get("valid")) and record.get("left_eye_quality") is not None and record.get("right_eye_quality") is not None


def _f(record: dict[str, Any], key: str) -> float:
    value = record.get(key)
    return float(value) if value is not None else float("nan")


def _ptp(values: list[float]) -> float:
    arr = _finite(values)
    return float(np.ptp(arr)) if arr.size else 0.0


def _mean(values: list[float]) -> float:
    arr = _finite(values)
    return float(np.mean(arr)) if arr.size else 0.0


def _robust_noise(values: list[float]) -> float:
    arr = _finite(values)
    if arr.size == 0:
        return 0.0
    std = float(np.std(arr))
    mad = float(np.median(np.abs(arr - np.median(arr))) * 1.4826)
    return max(std, mad, 1e-6)


def _corr(a: list[float], b: list[float]) -> float:
    aa = np.asarray(a, dtype=np.float64)
    bb = np.asarray(b, dtype=np.float64)
    mask = np.isfinite(aa) & np.isfinite(bb)
    if np.sum(mask) < 2:
        return 0.0
    aa = aa[mask]
    bb = bb[mask]
    if float(np.std(aa)) <= 1e-12 or float(np.std(bb)) <= 1e-12:
        return 0.0
    return float(np.corrcoef(aa, bb)[0, 1])


def _split_abs_spearman(records: list[dict[str, Any]], key: str) -> float:
    if len(records) < 4:
        return 0.0
    ordered = sorted(records, key=lambda row: float(row.get("elapsed_s", 0.0)))
    mid = len(ordered) // 2
    values = []
    for chunk in (ordered[:mid], ordered[mid:]):
        y = [_f(row, key) for row in chunk]
        x = list(range(len(y)))
        values.append(abs(_corr(_rank(x), _rank(y))))
    return float(np.mean(values)) if values else 0.0


def _rank(values: list[float]) -> list[float]:
    arr = np.asarray(values, dtype=np.float64)
    order = np.argsort(arr)
    ranks = np.empty_like(arr, dtype=np.float64)
    ranks[order] = np.arange(len(arr), dtype=np.float64)
    return ranks.tolist()


def _median_abs_diff(a: list[float], b: list[float]) -> float:
    diffs = _abs_diff(a, b)
    return float(np.median(diffs)) if diffs.size else 0.0


def _percentile_abs_diff(a: list[float], b: list[float], percentile: float) -> float:
    diffs = _abs_diff(a, b)
    return float(np.percentile(diffs, percentile)) if diffs.size else 0.0


def _abs_diff(a: list[float], b: list[float]) -> np.ndarray:
    aa = np.asarray(a, dtype=np.float64)
    bb = np.asarray(b, dtype=np.float64)
    mask = np.isfinite(aa) & np.isfinite(bb)
    return np.abs(aa[mask] - bb[mask])


def _finite(values: list[float]) -> np.ndarray:
    arr = np.asarray(values, dtype=np.float64)
    return arr[np.isfinite(arr)]


def _segment_sort_key(label: str) -> tuple[int, str]:
    return (SEGMENT_ORDER.index(label) if label in SEGMENT_ORDER else len(SEGMENT_ORDER), label)


def _write_markdown_report(analysis: dict[str, Any], path: Path) -> None:
    lines = ["# Raw Signal Analysis Report", ""]
    overall = analysis["overall"]
    lines.append(f"- Total records: {overall['total_records']}")
    lines.append(f"- Included records: {overall['included_records']}")
    lines.append(f"- Excluded ratio: {overall['excluded_ratio']:.3f}")
    lines.append("")
    lines.append("## Segments")
    lines.append("")
    for label, metrics in analysis["segments"].items():
        lines.append(f"### {label}")
        lines.append("")
        for key, value in metrics.items():
            if key == "label":
                continue
            if isinstance(value, float):
                lines.append(f"- {key}: {value:.6f}")
            else:
                lines.append(f"- {key}: {value}")
        lines.append("")
    path.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")


def _write_csv_metrics(analysis: dict[str, Any], path: Path) -> None:
    rows = []
    keys = {"segment"}
    for label, metrics in analysis["segments"].items():
        row = {"segment": label, **{k: v for k, v in metrics.items() if k != "label"}}
        rows.append(row)
        keys.update(row.keys())
    fieldnames = ["segment", *sorted(k for k in keys if k != "segment")]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description="Analyze Gate A2 raw signal JSONL")
    parser.add_argument("--log", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--csv", type=Path, required=True)
    args = parser.parse_args()
    analysis = analyze_records(load_jsonl(args.log))
    outputs = write_analysis_outputs(analysis, args.report, args.csv)
    print(f"report={outputs['report_path']}")
    print(f"csv={outputs['csv_path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

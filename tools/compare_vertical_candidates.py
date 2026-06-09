"""Offline comparison of logged vertical feature candidates."""

from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np


CANDIDATES = {
    "current": ("left_v_postbaseline", "right_v_postbaseline"),
    "raw_px": ("left_v_raw_px", "right_v_raw_px"),
    "eyelid_relative": ("left_v_eyelid_relative", "right_v_eyelid_relative"),
    "orbital_relative": ("left_v_orbital_relative", "right_v_orbital_relative"),
}


def compare_candidates(records: list[dict[str, Any]]) -> dict[str, Any]:
    included = [r for r in records if _include(r)]
    by_label = defaultdict(list)
    for row in included:
        by_label[str(row.get("protocol_label", "none"))].append(row)

    results = {}
    for name, (left_key, right_key) in CANDIDATES.items():
        results[name] = _candidate_metrics(name, left_key, right_key, by_label)

    best = max(results, key=lambda key: float(results[key]["score"]))
    return {"best_candidate": best, "candidates": results}


def compare_files(paths: list[Path]) -> list[dict[str, Any]]:
    rows = []
    for path in paths:
        records = _load_jsonl(path)
        first = records[0] if records else {}
        report = compare_candidates(records)
        for candidate, metrics in report["candidates"].items():
            rows.append(
                {
                    "session": path.stem,
                    "condition_id": first.get("condition_id", "unspecified"),
                    "glasses": first.get("condition_glasses", "unspecified"),
                    "candidate": candidate,
                    "best_candidate": report["best_candidate"],
                    **metrics,
                }
            )
    return rows


def write_outputs(rows: list[dict[str, Any]], csv_path: Path, report_path: Path) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows[0].keys()) if rows else []
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    report_path.write_text(_markdown(rows), encoding="utf-8")


def _candidate_metrics(name: str, left_key: str, right_key: str, by_label: dict[str, list[dict[str, Any]]]) -> dict[str, float | str]:
    center = by_label.get("center_hold", [])
    vertical = by_label.get("vertical_sweep", [])
    horizontal = by_label.get("horizontal_sweep", [])
    head = by_label.get("head_motion", [])
    blink = by_label.get("blink_degrade", [])

    center_noise = _mean_pair_noise(center, left_key, right_key)
    vertical_range = _mean_pair_range(vertical, left_key, right_key)
    horizontal_leak = _mean_pair_range(horizontal, left_key, right_key)
    head_range = _mean_pair_range(head, left_key, right_key)
    blink_range = _mean_pair_range(blink, left_key, right_key)
    disagreement_p95 = _pair_disagreement_p95(vertical, left_key, right_key)
    vertical_snr = vertical_range / max(center_noise, 1e-6)
    horizontal_leakage_ratio = horizontal_leak / max(vertical_range, 1e-6)
    head_leakage_ratio = head_range / max(vertical_range, 1e-6)
    score = vertical_snr / (1.0 + horizontal_leakage_ratio + head_leakage_ratio + disagreement_p95)

    return {
        "candidate": name,
        "center_noise_mean": center_noise,
        "vertical_range_mean": vertical_range,
        "vertical_snr_mean": vertical_snr,
        "horizontal_leakage_ratio": horizontal_leakage_ratio,
        "head_leakage_ratio": head_leakage_ratio,
        "blink_range_mean": blink_range,
        "vertical_disagreement_p95": disagreement_p95,
        "score": score,
    }


def _include(row: dict[str, Any]) -> bool:
    return bool(row.get("face_detected")) and bool(row.get("valid")) and row.get("left_eye_quality") is not None and row.get("right_eye_quality") is not None


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _values(rows: list[dict[str, Any]], key: str) -> np.ndarray:
    return np.asarray([float(row.get(key) or 0.0) for row in rows], dtype=np.float64)


def _mean_pair_range(rows: list[dict[str, Any]], left_key: str, right_key: str) -> float:
    if not rows:
        return 0.0
    return float((_range(_values(rows, left_key)) + _range(_values(rows, right_key))) * 0.5)


def _mean_pair_noise(rows: list[dict[str, Any]], left_key: str, right_key: str) -> float:
    if not rows:
        return 1e-6
    return float((_noise(_values(rows, left_key)) + _noise(_values(rows, right_key))) * 0.5)


def _pair_disagreement_p95(rows: list[dict[str, Any]], left_key: str, right_key: str) -> float:
    if not rows:
        return 0.0
    diff = np.abs(_values(rows, left_key) - _values(rows, right_key))
    return float(np.percentile(diff, 95.0)) if diff.size else 0.0


def _range(values: np.ndarray) -> float:
    return float(np.ptp(values)) if values.size else 0.0


def _noise(values: np.ndarray) -> float:
    if values.size == 0:
        return 1e-6
    std = float(np.std(values))
    mad = float(np.median(np.abs(values - np.median(values))) * 1.4826)
    return max(std, mad, 1e-6)


def _markdown(rows: list[dict[str, Any]]) -> str:
    lines = ["# Vertical Candidate Comparison", "", "Score = vertical_snr / (1 + horizontal_leakage + head_leakage + vertical_disagreement_p95).", ""]
    by_session = defaultdict(list)
    for row in rows:
        by_session[str(row["session"])].append(row)
    for session, items in by_session.items():
        lines.append(f"## {session}")
        best = items[0]["best_candidate"]
        lines.append(f"- best_candidate: {best}")
        for item in sorted(items, key=lambda r: float(r["score"]), reverse=True):
            lines.append(
                f"- {item['candidate']}: score={float(item['score']):.3f}, "
                f"snr={float(item['vertical_snr_mean']):.3f}, "
                f"v_range={float(item['vertical_range_mean']):.3f}, "
                f"h_leak={float(item['horizontal_leakage_ratio']):.3f}, "
                f"head_leak={float(item['head_leakage_ratio']):.3f}, "
                f"disagree95={float(item['vertical_disagreement_p95']):.3f}"
            )
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare logged vertical candidates")
    parser.add_argument("--root", type=Path, default=Path("benchmark_data"))
    parser.add_argument("--pattern", default="session_20260427_*.jsonl")
    parser.add_argument("--csv", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    rows = compare_files(sorted(args.root.glob(args.pattern)))
    write_outputs(rows, args.csv, args.report)
    print({"rows": len(rows), "csv": str(args.csv), "report": str(args.report)})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

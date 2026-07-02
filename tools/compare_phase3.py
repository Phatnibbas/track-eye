#!/usr/bin/env python3
"""Compare two benchmark summary markdown files for Phase 3 gate checks."""

import argparse
import re
import sys
from pathlib import Path


def parse_summary(path: Path) -> dict:
    """Parse a markdown summary file and extract metrics."""
    content = path.read_text(encoding="utf-8")

    metrics = {}

    # Extract FPS p50 from header (e.g., "FPS p50/p95: 18.33 / 19.09")
    fps_match = re.search(r"FPS p50/p95:\s*([\d.]+)\s*/", content)
    if fps_match:
        metrics["fps_p50"] = float(fps_match.group(1))
    else:
        metrics["fps_p50"] = None

    # Extract segment metrics
    # Pattern for center_hold: "Center jitter: 0.016"
    center_jitters = re.findall(
        r"center_hold.*?Center jitter:\s*([\d.]+)", content, re.DOTALL | re.IGNORECASE
    )
    if center_jitters:
        metrics["center_hold"] = sum(float(x) for x in center_jitters) / len(
            center_jitters
        )
    else:
        metrics["center_hold"] = None

    # Pattern for vertical_sweep: "Cross-axis leakage: 0.037" and "Y std/range: 0.423 / 0.977"
    vertical = {}
    leak_match = re.search(
        r"vertical_sweep.*?Cross-axis leakage:\s*([\d.]+)",
        content,
        re.DOTALL | re.IGNORECASE,
    )
    if leak_match:
        vertical["leakage"] = float(leak_match.group(1))
    y_std_match = re.search(
        r"vertical_sweep.*?Y std/range:\s*([\d.]+)\s*/",
        content,
        re.DOTALL | re.IGNORECASE,
    )
    if y_std_match:
        vertical["y_std"] = float(y_std_match.group(1))
    metrics["vertical_sweep"] = vertical if vertical else None

    # Pattern for diagonal_sweep: "X std/range: 0.487 / 1.412" and "Y std/range: 0.244 / 0.920"
    diagonal = {}
    x_std_match = re.search(
        r"diagonal_sweep.*?X std/range:\s*([\d.]+)\s*/",
        content,
        re.DOTALL | re.IGNORECASE,
    )
    if x_std_match:
        diagonal["x_std"] = float(x_std_match.group(1))
    y_std_match = re.search(
        r"diagonal_sweep.*?Y std/range:\s*([\d.]+)\s*/",
        content,
        re.DOTALL | re.IGNORECASE,
    )
    if y_std_match:
        diagonal["y_std"] = float(y_std_match.group(1))
    metrics["diagonal_sweep"] = diagonal if diagonal else None

    # Pattern for blink_degrade: "Y std/range: 0.073 / 0.328" (y std and y range)
    blink = {}
    y_std_range_match = re.search(
        r"blink_degrade.*?Y std/range:\s*([\d.]+)\s*/\s*([\d.]+)",
        content,
        re.DOTALL | re.IGNORECASE,
    )
    if y_std_range_match:
        blink["y_std"] = float(y_std_range_match.group(1))
        blink["y_range"] = float(y_std_range_match.group(2))
    metrics["blink_degrade"] = blink if blink else None

    return metrics


def compute_improvement(baseline: float, candidate: float) -> float:
    """Compute % improvement (positive = improvement, lower is better)."""
    if baseline == 0:
        return 0.0
    return ((baseline - candidate) / baseline) * 100


def main():
    parser = argparse.ArgumentParser(
        description="Compare benchmark summaries for Phase 3 gates"
    )
    parser.add_argument(
        "--baseline", required=True, help="Path to baseline summary markdown"
    )
    parser.add_argument(
        "--candidate", required=True, help="Path to candidate summary markdown"
    )
    args = parser.parse_args()

    baseline_path = Path(args.baseline)
    candidate_path = Path(args.candidate)

    if not baseline_path.exists():
        print(f"ERROR: Baseline file not found: {baseline_path}", file=sys.stderr)
        sys.exit(1)
    if not candidate_path.exists():
        print(f"ERROR: Candidate file not found: {candidate_path}", file=sys.stderr)
        sys.exit(1)

    baseline = parse_summary(baseline_path)
    candidate = parse_summary(candidate_path)

    # Check for missing required metrics
    errors = []
    if baseline.get("fps_p50") is None or candidate.get("fps_p50") is None:
        errors.append("FPS p50 missing from one or both files")
    if baseline.get("center_hold") is None or candidate.get("center_hold") is None:
        errors.append("center_hold missing from one or both files")
    if not baseline.get("vertical_sweep") or not candidate.get("vertical_sweep"):
        errors.append("vertical_sweep missing from one or both files")
    if not baseline.get("diagonal_sweep") or not candidate.get("diagonal_sweep"):
        errors.append("diagonal_sweep missing from one or both files")
    if not baseline.get("blink_degrade") or not candidate.get("blink_degrade"):
        errors.append("blink_degrade missing from one or both files")

    if errors:
        for err in errors:
            print(f"WARNING: {err}", file=sys.stderr)
        print("FAIL: Missing required segments", file=sys.stderr)
        sys.exit(1)

    # Compute improvements
    results = {}

    # Diagonal behavior: avg of x_std and y_std improvements (lower is better)
    diag_baseline_avg = (
        baseline["diagonal_sweep"]["x_std"] + baseline["diagonal_sweep"]["y_std"]
    ) / 2
    diag_candidate_avg = (
        candidate["diagonal_sweep"]["x_std"] + candidate["diagonal_sweep"]["y_std"]
    ) / 2
    results["diagonal_improvement"] = compute_improvement(
        diag_baseline_avg, diag_candidate_avg
    )

    # Vertical post-calibration: avg of leakage and y_std improvements (lower is better)
    vert_baseline_avg = (
        baseline["vertical_sweep"]["leakage"] + baseline["vertical_sweep"]["y_std"]
    ) / 2
    vert_candidate_avg = (
        candidate["vertical_sweep"]["leakage"] + candidate["vertical_sweep"]["y_std"]
    ) / 2
    results["vertical_improvement"] = compute_improvement(
        vert_baseline_avg, vert_candidate_avg
    )

    # FPS drop (higher fps is better, so drop = baseline - candidate)
    if baseline["fps_p50"] > 0:
        fps_drop = (
            (baseline["fps_p50"] - candidate["fps_p50"]) / baseline["fps_p50"]
        ) * 100
    else:
        fps_drop = 0
    results["fps_drop"] = fps_drop

    # Determine pass/fail
    diagonal_pass = results["diagonal_improvement"] >= 15.0
    vertical_pass = results["vertical_improvement"] >= 15.0
    fps_pass = results["fps_drop"] <= 5.0

    # Print report
    print("=" * 60)
    print("Phase 3 Gate Check Report")
    print("=" * 60)
    print(f"Baseline:  {baseline_path}")
    print(f"Candidate: {candidate_path}")
    print()

    print("Raw Values:")
    print(
        f"  FPS p50:      baseline={baseline['fps_p50']:.2f}, candidate={candidate['fps_p50']:.2f}"
    )
    print(
        f"  Center hold:  baseline={baseline['center_hold']:.4f}, candidate={candidate['center_hold']:.4f}"
    )
    print(
        f"  Vertical:     leakage baseline={baseline['vertical_sweep']['leakage']:.4f}, candidate={candidate['vertical_sweep']['leakage']:.4f}"
    )
    print(
        f"                y_std   baseline={baseline['vertical_sweep']['y_std']:.4f}, candidate={candidate['vertical_sweep']['y_std']:.4f}"
    )
    print(
        f"  Diagonal:     x_std   baseline={baseline['diagonal_sweep']['x_std']:.4f}, candidate={candidate['diagonal_sweep']['x_std']:.4f}"
    )
    print(
        f"                y_std   baseline={baseline['diagonal_sweep']['y_std']:.4f}, candidate={candidate['diagonal_sweep']['y_std']:.4f}"
    )
    print(
        f"  Blink degrade: y_std  baseline={baseline['blink_degrade']['y_std']:.4f}, candidate={candidate['blink_degrade']['y_std']:.4f}"
    )
    print(
        f"                y_range baseline={baseline['blink_degrade']['y_range']:.4f}, candidate={candidate['blink_degrade']['y_range']:.4f}"
    )
    print()

    print("Improvements (lower is better):")
    print(
        f"  Diagonal avg (x_std+y_std)/2: {results['diagonal_improvement']:.2f}% {'PASS' if diagonal_pass else 'FAIL'} (threshold: >= 15%)"
    )
    print(
        f"  Vertical avg (leakage+y_std)/2: {results['vertical_improvement']:.2f}% {'PASS' if vertical_pass else 'FAIL'} (threshold: >= 15%)"
    )
    print(
        f"  FPS drop: {results['fps_drop']:.2f}% {'PASS' if fps_pass else 'FAIL'} (threshold: <= 5%)"
    )
    print()

    all_pass = diagonal_pass and vertical_pass and fps_pass
    print("=" * 60)
    print(f"OVERALL: {'PASS' if all_pass else 'FAIL'}")
    print("=" * 60)

    sys.exit(0 if all_pass else 1)


if __name__ == "__main__":
    main()

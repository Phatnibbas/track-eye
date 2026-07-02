"""Generate aggregate Problem A report and prioritized annotation subset."""

from __future__ import annotations

import argparse
import csv
import json
import shutil
from collections import defaultdict
from pathlib import Path
from typing import Any

from export_eye_crops import (
    export_eye_crops_from_records,
    load_video_frames,
    write_annotation_template,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate Problem A batch report")
    parser.add_argument("--root", type=Path, default=Path("benchmark_data"))
    parser.add_argument("--pattern", default="session_20260427_*.jsonl")
    parser.add_argument("--annotation-root", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--csv", type=Path, required=True)
    args = parser.parse_args()

    files = sorted(args.root.glob(args.pattern))
    if not files:
        raise RuntimeError(f"No files matched: {args.root / args.pattern}")

    if args.annotation_root.exists():
        shutil.rmtree(args.annotation_root)
    args.annotation_root.mkdir(parents=True, exist_ok=True)

    rows: list[dict[str, Any]] = []
    selected_total = 0
    for path in files:
        records = _load_jsonl(path)
        first = records[0]
        metrics = _load_metrics(path.with_suffix(".gate_c_metrics.csv"))
        row = _session_row(path.stem, first, records, metrics)
        rows.append(row)

        selected = _select_annotation_records(records)
        frames = load_video_frames(
            path.with_suffix(".mp4"),
            {int(record["frame_index"]) for record in selected},
            mirror=True,
        )
        session_out = args.annotation_root / path.stem
        manifest = export_eye_crops_from_records(selected, frames, session_out, crop_padding=24)
        write_annotation_template(manifest, session_out / "annotations_template.csv")
        selected_total += len(selected)

    _write_report(args.report, rows, args.annotation_root, selected_total)
    _write_csv(args.csv, rows)
    print(
        {
            "report": str(args.report),
            "metrics_csv": str(args.csv),
            "sessions": len(rows),
            "selected_records": selected_total,
            "annotation_root": str(args.annotation_root),
        }
    )
    return 0


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _load_metrics(path: Path) -> dict[str, dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return {row["segment"]: row for row in csv.DictReader(handle)}


def _session_row(
    session: str, first: dict[str, Any], records: list[dict[str, Any]], metrics: dict[str, dict[str, str]]
) -> dict[str, Any]:
    return {
        "session": session,
        "condition_id": first.get("condition_id"),
        "glasses": first.get("condition_glasses"),
        "records": len(records),
        "included_ratio": _included_ratio(records),
        "h_left_range": _metric(metrics, "horizontal_sweep", "left_h_range"),
        "h_right_range": _metric(metrics, "horizontal_sweep", "right_h_range"),
        "h_leak": _metric(metrics, "horizontal_sweep", "horizontal_cross_axis_leakage_ratio"),
        "v_left_range": _metric(metrics, "vertical_sweep", "left_v_range"),
        "v_right_range": _metric(metrics, "vertical_sweep", "right_v_range"),
        "v_leak": _metric(metrics, "vertical_sweep", "vertical_cross_axis_leakage_ratio"),
        "v_disagree_p95": _metric(metrics, "vertical_sweep", "left_right_v_disagreement_p95"),
        "head_left_v_range": _metric(metrics, "head_motion", "left_v_range"),
        "head_right_v_range": _metric(metrics, "head_motion", "right_v_range"),
        "blink_conf": _metric(metrics, "blink_degrade", "mean_confidence"),
    }


def _metric(metrics: dict[str, dict[str, str]], segment: str, key: str) -> float:
    try:
        return float(metrics.get(segment, {}).get(key, 0.0) or 0.0)
    except ValueError:
        return 0.0


def _included_ratio(records: list[dict[str, Any]]) -> float:
    included = [
        record
        for record in records
        if record.get("face_detected")
        and record.get("valid")
        and record.get("left_eye_quality") is not None
        and record.get("right_eye_quality") is not None
    ]
    return len(included) / max(len(records), 1)


def _select_annotation_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    included = [
        record
        for record in records
        if record.get("face_detected")
        and record.get("valid")
        and record.get("left_eye_quality") is not None
        and record.get("right_eye_quality") is not None
    ]
    chosen: list[dict[str, Any]] = []

    def add(label: str, count: int, score_key) -> None:
        candidates = [record for record in included if record.get("protocol_label") == label]
        for record in sorted(candidates, key=score_key, reverse=True)[:count]:
            if record not in chosen:
                chosen.append(record)

    add(
        "vertical_sweep",
        5,
        lambda r: max(abs(r.get("left_v_postbaseline") or 0.0), abs(r.get("right_v_postbaseline") or 0.0)),
    )
    add(
        "head_motion",
        4,
        lambda r: max(
            abs(r.get("left_v_postbaseline") or 0.0),
            abs(r.get("right_v_postbaseline") or 0.0),
            abs(r.get("left_h") or 0.0),
            abs(r.get("right_h") or 0.0),
        ),
    )
    add(
        "blink_degrade",
        4,
        lambda r: (1.0 - float(r.get("confidence") or 0.0))
        + abs((r.get("left_v_postbaseline") or 0.0) - (r.get("right_v_postbaseline") or 0.0)),
    )
    add(
        "horizontal_sweep",
        3,
        lambda r: max(abs(r.get("left_h") or 0.0), abs(r.get("right_h") or 0.0)),
    )
    add(
        "center_hold",
        2,
        lambda r: abs((r.get("left_v_postbaseline") or 0.0) - (r.get("right_v_postbaseline") or 0.0)),
    )
    return chosen


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def _write_report(path: Path, rows: list[dict[str, Any]], annotation_root: Path, selected_total: int) -> None:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[str(row["glasses"])].append(row)

    lines = [
        "# Problem A Batch Report — 2026-04-27",
        "",
        "## Scope",
        "",
        "Six user-recorded sessions: 3 no-glasses, 3 glasses. Metrics are raw-signal diagnostics, not gaze accuracy claims.",
        "",
        "## Per-session metrics",
        "",
    ]
    for row in rows:
        lines.append(f"### {row['condition_id']} ({row['glasses']})")
        lines.append(f"- records: {row['records']} | included ratio: {row['included_ratio']:.3f}")
        lines.append(
            f"- horizontal range L/R: {row['h_left_range']:.3f} / {row['h_right_range']:.3f}; leakage: {row['h_leak']:.3f}"
        )
        lines.append(
            f"- vertical range L/R: {row['v_left_range']:.3f} / {row['v_right_range']:.3f}; leakage: {row['v_leak']:.3f}; disagreement p95: {row['v_disagree_p95']:.3f}"
        )
        lines.append(
            f"- head-motion vertical range L/R: {row['head_left_v_range']:.3f} / {row['head_right_v_range']:.3f}; blink mean confidence: {row['blink_conf']:.3f}"
        )
        lines.append("")

    lines.extend(["## Aggregate by glasses condition", ""])
    for group, values in groups.items():
        lines.append(f"### {group}")
        for key in [
            "h_left_range",
            "h_right_range",
            "h_leak",
            "v_left_range",
            "v_right_range",
            "v_leak",
            "v_disagree_p95",
            "head_left_v_range",
            "head_right_v_range",
            "blink_conf",
        ]:
            lines.append(f"- {key}: {_mean(values, key):.3f}")
        lines.append("")

    lines.extend(
        [
            "## Interpretation guardrails",
            "",
            "- These metrics support that raw movement is observable, especially horizontal and no-glasses vertical.",
            "- Glasses reduce vertical amplitude and increase vertical-sweep leakage/head-motion sensitivity in this batch.",
            "- Manual annotation is still required before claiming MediaPipe center accuracy or confidence-vs-error calibration.",
            "",
            "## Priority annotation subset",
            "",
            f"- Selected records: {selected_total}",
            f"- Crop folder: `{annotation_root.as_posix()}`",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _mean(rows: list[dict[str, Any]], key: str) -> float:
    return sum(float(row[key]) for row in rows) / max(len(rows), 1)


if __name__ == "__main__":
    raise SystemExit(main())

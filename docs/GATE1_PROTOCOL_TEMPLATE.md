# Gate 1 — Validation Readiness and Execution Framework

Status: **FRAMEWORK DEFINED; ACCEPTANCE COLLECTION BLOCKED**

This document is the execution contract for Gate 1. It does not approve any
tracking source, mapping, timing, detector, product threshold, emission path,
transport, or rig behavior.

## 1. Audit finding — 2026-09-23

The capture mechanism runs, but the deployed system is not ready to collect
acceptance data:

- systemd does not pass `--validation-token`, so validation endpoints are
  intentionally disabled;
- the source checks a token in the JSON body; it is not an HTTP bearer token;
- missing `scenario`, `lighting_condition`, `consent_ref`, and
  `participant_split` currently become `"unlabeled"` instead of being rejected;
- `exposure` is caller-supplied metadata, not camera-control readback;
- the manifest has no opaque participant ID or visit/episode ID, so
  participant-level split leakage cannot be audited;
- `cleanup` keeps the newest five sessions; it does not implement automatic
  deletion after derived artifacts are accepted;
- JPEGs are mirrored pre-render frames, not lossless sensor frames.

Therefore existing tooling is suitable for explicit smoke capture only.
No captured session counts toward Gate 1 or later acceptance until the
preflight requirements below are implemented and verified.

## 2. Required capture identity

Every acceptance session must contain:

| Field | Contract |
|---|---|
| `protocol_version` | Frozen validation protocol identifier |
| `participant_id` | Opaque consented code; no name or recognition feature |
| `visit_id` | Unique episode code; one uninterrupted visit |
| `participant_split` | Exactly `tuning` or `heldout`; assigned before capture |
| `scenario_id` | Stable ID generated from the scenario axes below |
| `consent_ref` | Opaque reference to the consent record |
| `lighting_condition` | Controlled label plus measured value where available |
| `exposure` | Camera-control readback, not an operator guess |
| code/model/config/calibration checksums | Exact runtime identity |
| camera negotiation and mirror state | Exact capture path |
| start/end timestamps and frame count | Episode boundaries |

One `participant_id` must appear in only one split. A participant may have
multiple `visit_id` values in that same split. The software must reject missing,
empty, unknown, or contradictory fields before creating a session directory.

## 3. Scenario registry

Build `scenario_id` from explicit axes; do not encode meaning in free text.

| Axis | Initial values |
|---|---|
| occupancy | `empty`, `single`, `multiple`, `handoff` |
| posture | `seated`, `standing` |
| distance | `near`, `mid`, `two-meter` |
| motion | `still`, `eyes-only`, `yaw-left`, `yaw-right`, `pitch-up`, `pitch-down`, `translate`, `entry`, `exit`, `facing-away` |
| lighting | `normal`, `dim`, `backlit`, `screen-changing`, `glare` |
| occlusion | `none`, `one-eye`, `partial-face`, `glasses`, `sunglasses`, `mask`, `hat` |

Not every Cartesian combination is required. The collection plan must list the
chosen combinations before capture and explain omitted strata. Never infer
sensitive attributes from images.

## 4. Split and freeze rules

1. Assign the opaque participant to `tuning` or `heldout` before capture.
2. Use only `tuning` episodes to fit quality gates, source mappings, detector
   thresholds, and selector timing.
3. Freeze code, model, config, calibration, metric definitions, and checksums.
4. Run `heldout` episodes without retuning.
5. A held-out failure returns work to tuning and requires a new frozen version;
   the failed held-out data must not silently become tuning data.
6. Use visit episodes as the statistical unit, not correlated frames.

## 5. Metric definitions

Numerical limits are owner decisions and remain **TBD**. Freeze each limit and
its confidence target before the held-out run.

| Metric | Definition |
|---|---|
| visitor-present coverage | Fraction of labeled visitor-present time with a responsive non-`INVALID` target |
| first-motion latency | Visitor entry/motion label to first target motion from that visitor |
| maximum frozen interval | Longest interval target remains unchanged while the selected visitor is labeled moving |
| still jitter | Target variation during a labeled still interval, by source and axis |
| transition step | Target discontinuity at a source change |
| false activation | Non-`INVALID` target time during labeled empty-scene intervals |
| source flap rate | Source changes per minute excluding labeled entry/exit transitions |
| production FPS | Per-episode processing distribution with every configured shadow stage active |

Report per condition and worst condition. A global average cannot hide a failed
distance, lighting, occlusion, occupancy, or participant stratum.

## 6. Privacy and retention

- Capture only after consent and explicit start.
- Store `consent_ref` and opaque IDs; never names or face-recognition features.
- Run only on an isolated/trusted network.
- Keep JPEGs only until derived rows and summaries are accepted.
- Record deletion as an auditable event; do not equate keep-five rotation with
  consent withdrawal or accepted-artifact deletion.
- Keep normal production free of image storage.

## 7. Implementation queue

Complete in this order:

1. make required metadata strict and add opaque participant/visit IDs;
2. read actual camera exposure/control values into the manifest;
3. configure an operational validation token without storing it in Git;
4. add focused contract tests for rejection, split values, and manifest fields;
5. smoke one short session, inspect artifacts, then delete it;
6. freeze metric limits and confidence/sample-count targets;
7. approve a collection matrix; only then begin tuning captures.

## 8. Gate 1 exit criteria

Gate 1 passes only when:

- every required manifest field is machine-validated;
- camera controls are measured;
- participant and visit identity support leakage checks;
- auth is configured and verified on the live service;
- consent, access, retention, and specific-session deletion are operational;
- scenario registry, split assignment, metrics, numerical limits, confidence
  target, and collection matrix are frozen;
- a smoke session produces complete artifacts and is deliberately deleted;
- local and Pi source checksums match and emission remains disabled.

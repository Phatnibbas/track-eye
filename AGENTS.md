# Track Eye Agent Context

## Current ROI acquisition deployment — 2026-10-17

Production is `b8387c0` plus diagnostic UI and the native-ROI acquisition change.
One full-range detection now precedes one FaceMesh call: cold/lost tracking uses
a selected 1.8× padded crop; healthy ROI follows accepted mesh bounds. All
landmarks return to original pixels before unchanged aperture-v1 measurement.
The 0.6s retained reference is geometric association, not person identity.
FACE fallback remains independent; no visitor/YOLOX pipeline, threshold/model,
mapping/calibration-unit, head-sign, body or sender-policy change.
Web distinguishes pre-EMA, raw-after-EMA and tuned output. Geometry is not
calibrated pupil reliability. Controlled photographic replay improves cold
acquisition, not measured2m/low-light/multiple-visitor acceptance.
Camera PID136647 and sender PID146887 active; calibration clean, gain
3.9/3/3.45/3.7, limit1.0, two neutrals, saved SHA/pin2f797a4c….
Existing sender policy issued one acknowledged bounded CLEAR after a startup
FAULT rejection; no HOME/reset/flash. New final sender session had no rejection
or CLEAR. Read `docs/PI5_DEPLOYED_STATE.md` and fresh state before operating.

## Historical E2E restoration authority — 2026-10-17

Owner requested rollback to synchronized pre-upgrade `b8387c0`, then explicitly
authorized CLEAR and restoring the old camera→sender→master→Delta operation.
Runtime source remains the baseline; no visitor/YOLOX upgrade is active.
Current verification, active services and recovery evidence:
`docs/PI5_DEPLOYED_STATE.md`. The simpler pipeline in `PROJECT_FRAMEWORK.md`
is still design only.

Camera and sender are separate unique device owners. Master was recovered from
confirmed REPL using loaded RAM definitions, with auto-home, auto-rehome and
restored-target replay disabled; flash was not changed. One explicit CLEAR
received OK CLEAR and six fresh ONLINE/IDLE/homed/error-free node states.
The old sender is running again; only its calibration pin was updated.
Its owner-test readiness policy and bounded CLEAR remain as before, not a new
fail-closed installation profile. No HOME/reset/flash was performed.

Saved calibration/data remain Pi-owned. Live UI tuning may be dirty and differ
from disk; inspect and preserve it before any camera restart, never overwrite
it from a dated profile. Read current state before motion/recovery. RAM safety
overrides do not survive master reset; do not infer safe reboot from this run.

Owner instructions in the active session govern the requested operation.
Historical checkpoint restrictions and numerical values below are dated
records, not standing execution bans. SSH to `pi5` when the task requires it;
report mutations and verify health. Exactly one owner per camera/serial device.

## 2026-10-08 Pi5/Delta protocol checkpoint (project context)

For Delta integration work, first read `docs/PROJECT_CONTEXT.md` and
`docs/HANDOFF_CURRENT.md`, then `docs/PI5_MASTER_DATA_CONTRACT.md` and
`docs/PI5_MASTER_PROTOCOL_AUDIT_2026-10-08.md`. This is curated project context,
not permission to execute proposed next steps or change production behavior.

Owner temporarily accepted matching text semantics and bounded session evidence:
3000/3000 IK queries at ~10 Hz, plus 50/50 across 5 fd-reopen sessions. Do not
claim physical cable reconnect/reset/24-7 reliability or live motor delivery.
The existing Delta master accepts ASCII `look az tilt twist ms` (newline) at
115200, not the tracking package's binary EyeTargetFrame. The codec contract
remains separate; no binary decoder or effective fallback emission was added.

Prototype/evidence stays in `/home/pi5/track-eye-integration-audit-20261008/`.
Production `track_eye.app`, calibration and fallback settings are unchanged.
Display-left is the owner-selected prototype route; trial mapping is explicit
config, not rig calibration. Never auto-clear/home, bypass readiness, flash
firmware, replay stale targets or promote shadow output by implication.

The September framework below remains the production/fallback baseline;
October docs record a scoped independent protocol investigation, not rollout.

## Mandatory read order

Before changing behavior or deployment:

1. `docs/PROJECT_FRAMEWORK.md` — current product invariant, architecture, contracts, evidence, and change protocol.
2. `docs/PI5_DEPLOYED_STATE.md` — live host, service, calibration, artifacts, and operational checks.
3. Relevant source sections and tests.
4. Live Pi files/state affected by the task via `ssh pi5`.
5. `docs/OPEN_RESEARCH_PROTOCOL_FALLBACK.md` — accepted output contract and priority, deployed shadow implementation, and open behavioral/transport/rig gates.

The transport-independent Pi5→ESP32 payload and fallback priority were accepted on 2026-09-16. The codec, candidate pipeline, time-based selector, status diagnostics, and validation capture are deployed in shadow mode. This is not effective fallback output: `track_eye.app` does not call the encoder or transmit decisions, and configuration rejects `emission_enabled=true`.

Current validation and rollout scope is **pupil, head, and face only**. Body/person fallback remains implemented as diagnostics but is deferred and must stay `body_enabled=false`. Exact pupil-quality gates, head axes/sign/range, face mapping, transitions, multi-person behavior, transport/framing, watchdog, and mechanics remain open. Do not overclaim behavior at 2 m, in low light, or with multiple visitors.


`docs/PIVOT_PUPIL_MIRROR_2026-07-02.md` is historical. Its correction from gaze estimation to pupil mirroring remains valid; its proposed work and file inventory are stale.

## Core product invariants

Keep the artwork responsive while a visitor is detected. Prefer two independent **eye-in-head pupil motions** when reliable; otherwise emit explicitly labeled head-orientation, then face-position motion, which may be shared by both artwork eyes. Active priority is `PUPIL -> HEAD -> FACE -> HELD -> INVALID`. Body/person fallback is outside the current rollout scope and remains disabled. Normal pupil mode is not screen gaze, world-space gaze, or a fused binocular vector; its head-motion robustness and vertical separability must be measured, not assumed.

## Source of truth

- User-stated installation behavior is authoritative intent.
- Live Pi state is authoritative for what is deployed and calibrated.
- This Git repository is authoritative for the next source change.
- Tests and baseline artifacts provide narrower evidence; they do not override product intent.
- `/home/pi5/track-eye` is not a Git checkout. Validate deployment with explicit checksums.

## Canonical runtime

```text
Camera -> mirror -> one pre-render frame
  |-> full-range face detection -> selected cold/lost ROI -> EyeTracker
  |     `-> OutputTuner -> production OutputTrackingResult
  |-> pupil/head/face/body observations -> FallbackSelector -> shadow decision
  `-> explicit ValidationSession capture
production OutputTrackingResult -> renderer -> FrameHub -> WebUIServer
```

Fallback decisions remain diagnostics only. Pupil observations entering the selector use calibrated output coordinates; raw geometry remains diagnostic. Head/face/body mappings are uncalibrated.

Systemd runs `/home/pi5/track-eye/.venv/bin/python -u -m track_eye.app` from `/home/pi5/track-eye`. The canonical production code is the `track_eye/` package. Root-level Pi files such as `rendering.py`, `web.py`, and `tracking_baseline.py` are legacy leftovers and are not the systemd runtime.

Servo/UDP code remains outside `track_eye.app`. Do not integrate `servo_link.py` without explicit scope.

## Non-negotiable contracts

- `TrackingResult` remains raw and unscaled.
- `face_detected == False` implies `eyes is None`; never publish stale eye values.
- Neutral offsets, directional gains, and soft limiting exist only in `OutputTrackingResult`.
- Rendering never changes tracking semantics.
- The accepted Pi5→ESP32 payload carries only final normalized desired positions plus per-eye state and freshness metadata; current `left_slot`/`right_slot` are processed-image/display channels, not anatomical labels; mechanical and servo units remain outside it.
- Shadow decisions must not replace production output or reach hardware until the documented behavioral and rig gates pass.
- Validation capture stores participant JPEGs. Controls require a JSON-body token when configured; the deployed unit has no token and leaves them disabled. Use only on a trusted network and delete artifacts deliberately.
- Exactly one production process owns the camera.
- `FrameHub` remains bounded to the latest JPEG; clients may skip frames by sequence.
- `/healthz` measures capture freshness, not face presence.
- Preserve Pi-owned `output-calibration.json` and `benchmark_data/` during ordinary source sync.
- Do not run standalone baseline while the production service owns the camera.

## Current deployed facts

Revalidated on 2026-09-23:

- service active and enabled, health 200, one app process/camera owner;
- UGREEN by-id camera, MJPG 1280×720 at 30 fps;
- recent full-shadow empty-scene validation reported 15.03–16.87 fps, median 16.21 fps;
- Python 3.11.15, MediaPipe 0.10.14, OpenCV 4.13.0, NumPy 2.4.6, protobuf 4.25.9;
- pinned Face Landmarker SHA-256 `64184e229b263107bc2b804c6625db1341ff2bb731874b0bcc2fe6544e0bc9ff`;
- fallback config checksum `33c86e3c36ab90f7`, emission disabled, calibration false, body selection disabled;
- 47 tests pass locally and on the Pi; initial acquisition now obeys per-source `promote_s`;
- `validation_data/` is empty and validation controls return 400 while no token is configured;
- persisted output gain remains `4.0/4.0`, `3.5/3.45`, soft limit `1.5`, with two saved neutrals.

These live values are not code defaults. Never overwrite them implicitly.

## Evidence status

The latest inspected baseline achieved 100% face/iris tracking and zero read failures, but did not fully validate two-eye direction quality: eye `362_263` had minimum horizontal separation `0.55`, so normalized head drift for that eye was gated out. The artifact predates the current output-tuning report schema and does not justify the current persisted gain by itself.

## Verification and deployment

For a source change:

1. edit locally;
2. run focused tests and a behavioral smoke path;
3. sync only intended files;
4. compare local/Pi checksums;
5. restart only for an intentional deployment;
6. verify service status, startup journal, `/healthz`, `/status.json`, and changed behavior;
7. refresh `docs/PI5_DEPLOYED_STATE.md` when deployed state changes.

Current known seams are listed in `docs/PROJECT_FRAMEWORK.md`; do not silently “fix” them outside task scope.
